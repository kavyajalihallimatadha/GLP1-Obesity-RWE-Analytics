# Databricks notebook source
# MAGIC %md
# MAGIC # 22 · Gold: Persistence and Adherence
# MAGIC
# MAGIC **Business questions:** *How long do patients stay on their first treatment? Do they take it as
# MAGIC prescribed?*
# MAGIC
# MAGIC **Persistence (Kaplan-Meier)**
# MAGIC - Starts at the first fill of the first product after index
# MAGIC - The patient "stops" (event) when the supply runs out and no refill comes within 60 days
# MAGIC - Patients still on treatment at the end of follow-up are **censored** (they count while observed)
# MAGIC - Curves by product, payer, diabetes status and start year
# MAGIC
# MAGIC **Adherence (Proportion of Days Covered, PDC)**
# MAGIC - Window: 365 days from the first fill; only patients with 365+ days of follow-up
# MAGIC - Days covered by fills of the first product; overlapping supply is shifted forward
# MAGIC - Adherent = PDC ≥ 0.80 (the common quality-measure threshold)
# MAGIC
# MAGIC **Outputs:** `gold_persistence_curve`, `gold_persistence_summary`, `gold_adherence`

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

ep = load_pdf("gold_treatment_episodes")
coh = load_pdf("gold_patient_cohort")
fills = load_pdf("work_cohort_fills")
for c in ["start_date", "supply_end_date", "followup_end"]:
    ep[c] = pd.to_datetime(ep[c])
fills["fill_date"] = pd.to_datetime(fills["fill_date"])

first = ep[ep["episode_seq"] == 1].copy()
first["event"] = first["discontinued"].astype(bool)
first["time"] = np.where(first["event"], (first["supply_end_date"] - first["start_date"]).dt.days,
                         (first["followup_end"] - first["start_date"]).dt.days).clip(min=1)
first = first.merge(coh[["ptid", "payer_at_index", "diabetes_status", "race", "ethnicity", "age_group", "gender"]], on="ptid")
first["start_year"] = first["start_date"].dt.year.astype(str)
print(f"patients with a first treatment episode: {len(first):,}")

# COMMAND ----------

# MAGIC %md ## Kaplan-Meier persistence curves

# COMMAND ----------

def kaplan_meier(time, event, grid):
    """Survival probability at each day in grid, plus number at risk."""
    t = np.asarray(time); e = np.asarray(event).astype(bool)
    order = np.argsort(t)
    t, e = t[order], e[order]
    uniq = np.unique(t[e])
    surv, s = {}, 1.0
    for u in uniq:
        at_risk = np.sum(t >= u)
        d = np.sum((t == u) & e)
        s *= (1 - d / at_risk)
        surv[u] = s
    keys = np.array(sorted(surv))
    out = []
    for g in grid:
        k = keys[keys <= g]
        out.append((g, surv[k[-1]] if len(k) else 1.0, int(np.sum(t >= g))))
    return out


GRID = list(range(0, 361, 15)) + [365]
groups = [("Overall", None), ("Product", "brand_name"), ("Payer", "payer_at_index"),
          ("Diabetes status", "diabetes_status"), ("Start year", "start_year")]
curve_rows, summ_rows = [], []
for gtype, col in groups:
    parts = [("All patients", first)] if col is None else list(first.groupby(col))
    for gval, d in parts:
        if len(d) < 30:
            continue
        km = kaplan_meier(d["time"], d["event"], GRID)
        for day, s, n_risk in km:
            curve_rows.append({"group_type": gtype, "group_value": gval, "day": day,
                               "pct_persistent": round(100 * s, 1), "n_at_risk": n_risk})
        surv = dict((day, s) for day, s, _ in km)
        median = next((day for day, s, _ in km if s <= 0.5), None)
        summ_rows.append({"group_type": gtype, "group_value": gval, "patients": len(d),
                          "pct_persistent_90d": round(100 * surv[90], 1), "pct_persistent_180d": round(100 * surv[180], 1),
                          "pct_persistent_365d": round(100 * surv[365], 1),
                          "median_days_persistent": median if median is not None else ">365"})
curve = pd.DataFrame(curve_rows)
summary = pd.DataFrame(summ_rows)
summary["median_days_persistent"] = summary["median_days_persistent"].astype(str)
save_pdf(curve, "gold_persistence_curve")
save_pdf(summary, "gold_persistence_summary")
display(summary[summary["group_type"] == "Product"].sort_values("pct_persistent_365d", ascending=False))

# COMMAND ----------

# MAGIC %md ## Adherence (PDC) in the first 365 days

# COMMAND ----------

elig = first[(first["followup_end"] - first["start_date"]).dt.days >= PDC_WINDOW_DAYS - 1]
f = fills.merge(elig[["ptid", "product_key", "start_date"]], on=["ptid", "product_key"])
f = f[(f["fill_date"] >= f["start_date"]) & (f["fill_date"] < f["start_date"] + pd.Timedelta(days=PDC_WINDOW_DAYS))]
f = f.sort_values(["ptid", "fill_date"])

pdc_rows = []
for pt, g in f.groupby("ptid"):
    start = g["start_date"].iloc[0]
    covered = np.zeros(PDC_WINDOW_DAYS, dtype=bool)
    next_free = 0
    for fd, ds in zip(g["fill_date"], g["days_supply"]):
        s = max((fd - start).days, next_free)            # shift overlapping supply forward
        e = min(s + int(ds), PDC_WINDOW_DAYS)
        if s < PDC_WINDOW_DAYS:
            covered[s:e] = True
        next_free = max(next_free, s + int(ds))
    pdc_rows.append({"ptid": pt, "pdc": covered.mean(), "fills_in_window": len(g)})
pdc = pd.DataFrame(pdc_rows).merge(elig[["ptid", "brand_name", "molecule", "drug_class", "payer_at_index",
                                         "diabetes_status", "race", "ethnicity", "age_group", "gender", "start_year"]], on="ptid")
pdc["pdc"] = pdc["pdc"].round(3)
pdc["adherent"] = pdc["pdc"] >= PDC_ADHERENT
pdc["pdc_band"] = pd.cut(pdc["pdc"], [-0.01, 0.2, 0.4, 0.6, 0.8, 1.0], labels=["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"]).astype(str)
save_pdf(pdc, "gold_adherence")
display(pdc.groupby("brand_name").agg(patients=("ptid", "count"), mean_pdc=("pdc", "mean"),
                                      pct_adherent=("adherent", "mean")).round(3))
