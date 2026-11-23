# Databricks notebook source
# MAGIC %md
# MAGIC # 25 · Gold: Real-World Outcomes (Weight and HbA1c)
# MAGIC
# MAGIC **Business question:** *In routine care, how much weight do patients lose on each product, and
# MAGIC how does that differ for patients who stay on treatment?*
# MAGIC
# MAGIC **Method**
# MAGIC - Baseline: closest weight in the 90 days before (up to 7 days after) the first fill
# MAGIC - Follow-up: closest weight to 6 months (150–210 days) and 12 months (330–400 days) after the first fill
# MAGIC - Two views:
# MAGIC   - **All starters** – everyone who started, whether or not they stayed on it (real-world, "intent-to-treat"-like)
# MAGIC   - **Persistent** – still on the first product at that time point
# MAGIC - HbA1c change for patients with type 2 diabetes, same windows
# MAGIC
# MAGIC > Outcome sizes come from simulation parameters and are **not** evidence about any real product.
# MAGIC
# MAGIC **Outputs:** `gold_outcomes_patient`, `gold_outcomes_summary`

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

ep = load_pdf("gold_treatment_episodes")
coh = load_pdf("gold_patient_cohort")
vit = spark.sql("""SELECT v.ptid, v.obs_date, v.weight_kg FROM silver_vitals v
                   JOIN gold_patient_cohort c ON v.ptid = c.ptid AND c.treated
                   WHERE v.weight_kg IS NOT NULL""").toPandas()
a1c = spark.sql("""SELECT h.ptid, h.result_date, h.hba1c_pct FROM silver_hba1c h
                   JOIN gold_patient_cohort c ON h.ptid = c.ptid AND c.treated AND c.has_t2d = 1""").toPandas()

first = ep[ep["episode_seq"] == 1][["ptid", "brand_name", "drug_class", "start_date", "supply_end_date", "followup_end"]].copy()
for c in ["start_date", "supply_end_date", "followup_end"]:
    first[c] = pd.to_datetime(first[c])
vit["obs_date"] = pd.to_datetime(vit["obs_date"])
a1c["result_date"] = pd.to_datetime(a1c["result_date"])

WINDOWS = {"baseline": (-90, 7, 0), "6m": (150, 210, 180), "12m": (330, 400, 365)}   # no spaces: Delta column names


def closest(df, date_col, val_col, lo, hi, target):
    m = df.merge(first[["ptid", "start_date"]], on="ptid")
    m["d"] = (m[date_col] - m["start_date"]).dt.days
    m = m[(m["d"] >= lo) & (m["d"] <= hi)].copy()
    m["dist"] = (m["d"] - target).abs()
    return m.sort_values("dist").drop_duplicates("ptid").set_index("ptid")[val_col]


out = first.set_index("ptid")
for name, (lo, hi, target) in WINDOWS.items():
    out[f"weight_{name}"] = closest(vit, "obs_date", "weight_kg", lo, hi, target)
    out[f"hba1c_{name}"] = closest(a1c, "result_date", "hba1c_pct", lo, hi, target)
out = out.reset_index()

for tp, days in [("6m", 180), ("12m", 365)]:
    out[f"pct_weight_change_{tp}"] = (100 * (out[f"weight_{tp}"] / out["weight_baseline"] - 1)).round(1)
    out[f"hba1c_change_{tp}"] = (out[f"hba1c_{tp}"] - out["hba1c_baseline"]).round(2)
    out[f"persistent_at_{tp}"] = out["supply_end_date"] >= out["start_date"] + pd.Timedelta(days=days)
out = out.merge(coh[["ptid", "payer_at_index", "diabetes_status", "bmi_category", "gender", "age_group"]], on="ptid")
save_pdf(out, "gold_outcomes_patient")

# COMMAND ----------

rows = []
for tp, tp_label in [("6m", "6 months"), ("12m", "12 months")]:
    col = f"pct_weight_change_{tp}"
    for view in ["All starters", "Persistent"]:
        d = out[out[col].notna()]
        if view == "Persistent":
            d = d[d[f"persistent_at_{tp}"]]
        for brand, g in d.groupby("brand_name"):
            if len(g) < 20:
                continue
            a = g[f"hba1c_change_{tp}"].dropna()
            rows.append({"time_point": tp_label, "view": view, "brand_name": brand, "patients": len(g),
                         "mean_pct_weight_change": round(g[col].mean(), 1), "median_pct_weight_change": round(g[col].median(), 1),
                         "pct_lost_5pct_or_more": round(100 * (g[col] <= -5).mean(), 1),
                         "pct_lost_10pct_or_more": round(100 * (g[col] <= -10).mean(), 1),
                         "pct_lost_15pct_or_more": round(100 * (g[col] <= -15).mean(), 1),
                         "t2d_patients_with_hba1c": len(a),
                         "mean_hba1c_change": round(a.mean(), 2) if len(a) >= 20 else np.nan})
summary = pd.DataFrame(rows)
save_pdf(summary, "gold_outcomes_summary")
display(summary[summary["time_point"] == "12 months"].sort_values(["view", "mean_pct_weight_change"]))
