# Databricks notebook source
# MAGIC %md
# MAGIC # 07 · Simulate Vital Signs (Weight, BMI, Height) and HbA1c Labs
# MAGIC
# MAGIC Each patient's weight follows a simulated path:
# MAGIC - slow weight gain over time without treatment
# MAGIC - weight loss while on treatment, approaching a product-specific maximum over several months
# MAGIC   (patients differ in how well they respond, and some do not respond)
# MAGIC - partial weight regain after stopping treatment
# MAGIC - a large, lasting drop after bariatric surgery
# MAGIC
# MAGIC HbA1c (type 2 diabetes patients) follows the same idea. About 8% of HbA1c results are reported in
# MAGIC IFCC units (mmol/mol, LOINC 59261-8) instead of US NGSP % (LOINC 4548-4).
# MAGIC
# MAGIC **Outputs:** `sim_observation` (EHR Observations), `sim_lab` (EHR Lab)
# MAGIC
# MAGIC > Treatment effect sizes are illustrative simulation parameters, **not clinical evidence**.

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

rng = np.random.default_rng(SEED + 7)
truth = load_pdf("sim_patient_truth").set_index("ptid")
enc = load_pdf("sim_encounter")
fills = load_pdf("sim_rx_fill_truth")
surg = load_pdf("sim_surgery_truth").set_index("ptid")["surgery_date"]

MAX_LOSS = {"ZEPBOUND": .18, "MOUNJARO": .13, "WEGOVY": .13, "OZEMPIC": .08, "RYBELSUS": .04, "TRULICITY": .03,
            "VICTOZA": .03, "SAXENDA": .06, "LIRA_GEN_T2D": .03, "LIRA_GEN_WM": .06, "QSYMIA": .07, "CONTRAVE": .05}
A1C_DROP = {"ZEPBOUND": 1.8, "MOUNJARO": 1.8, "WEGOVY": 1.4, "OZEMPIC": 1.4, "RYBELSUS": 1.1, "TRULICITY": 1.2,
            "VICTOZA": 1.0, "SAXENDA": 1.0, "LIRA_GEN_T2D": 1.0, "LIRA_GEN_WM": 1.0, "QSYMIA": .2, "CONTRAVE": .2}
TAU_ON, TAU_OFF, KEEP = 110.0, 200.0, 0.35        # days to effect, days to regain, share of loss kept
TAU_A1C = 70.0

ep = fills.groupby(["ptid", "episode_id", "product_key"]).agg(
    start=("fill_date", "min"), last=("fill_date", "max"), ds=("days_supply", "max")).reset_index()
ep["end"] = ep["last"] + pd.to_timedelta(ep["ds"], unit="D")
ep = ep.sort_values(["ptid", "start"])
episodes = {k: g[["start", "end", "product_key"]].to_numpy() for k, g in ep.groupby("ptid")}


def effect_path(dates, eps, max_effect, tau_on, tau_off, keep):
    """Fraction of effect at each date, given chronological treatment episodes."""
    days = dates.astype("datetime64[D]").astype(np.int64)
    out = np.zeros(len(days))
    level, t_prev = 0.0, None
    for st, en, pk in eps:
        s = np.datetime64(st, "D").astype(np.int64); e = np.datetime64(en, "D").astype(np.int64)
        E = max_effect[pk]
        if t_prev is not None:                         # off-treatment decay before this episode
            off = (days > t_prev) & (days < s)
            out[off] = level_end * (keep + (1 - keep) * np.exp(-(days[off] - t_prev) / tau_off))
            level = level_end * (keep + (1 - keep) * np.exp(-(s - t_prev) / tau_off))
        on = (days >= s) & (days <= e)
        out[on] = E - (E - level) * np.exp(-(days[on] - s) / tau_on)
        level_end = E - (E - level) * np.exp(-(e - s) / tau_on)
        t_prev = e
    if t_prev is not None:
        after = days > t_prev
        out[after] = level_end * (keep + (1 - keep) * np.exp(-(days[after] - t_prev) / tau_off))
    return out

# COMMAND ----------

# MAGIC %md ## Weight, BMI and height observations

# COMMAND ----------

p_meas = enc["Interaction_type"].map({"Office or clinic patient": .70, "Inpatient": .70,
                                      "Telehealth": .30, "Emergency patient": .20}).to_numpy()
obs_enc = enc[rng.random(len(enc)) < p_meas][["PtId", "EncId", "Interaction_date", "Interaction_time"]]
obs_enc = obs_enc.sort_values(["PtId", "Interaction_date"])

resp = pd.Series(np.clip(rng.normal(1.0, 0.35, len(truth)), 0, 2), index=truth.index)   # responder variability
a1c0 = pd.Series(np.clip(rng.normal(8.1, 1.0, len(truth)), 6.5, 12.5), index=truth.index)

w_rows = []
for pt, g in obs_enc.groupby("PtId", sort=False):
    t = truth.loc[pt]
    dates = g["Interaction_date"].to_numpy()
    h = t["height_cm"] / 100
    w0 = t["bmi0"] * h * h
    yrs = (dates - np.datetime64(t["first_obesity_date"])).astype("timedelta64[D]").astype(float) / 365.25
    drift = 1 + 0.004 * yrs
    eps = episodes.get(pt, [])
    loss = effect_path(dates, eps, {k: v * resp[pt] for k, v in MAX_LOSS.items()}, TAU_ON, TAU_OFF, KEEP) if len(eps) else 0
    s_loss = 0
    if pt in surg.index:
        dd = (dates - np.datetime64(surg[pt])).astype("timedelta64[D]").astype(float)
        s_loss = np.where(dd > 0, 0.27 * (1 - np.exp(-dd / 120)), 0)
    w = w0 * drift * (1 - loss) * (1 - s_loss) + rng.normal(0, 1.2, len(dates))
    w_rows.append(pd.DataFrame({"PtId": pt, "EncId": g["EncId"].to_numpy(), "date": dates,
                                "time": g["Interaction_time"].to_numpy(), "wt_kg": w, "ht_cm": t["height_cm"]}))
W = pd.concat(w_rows, ignore_index=True)
W["bmi"] = (W["wt_kg"] / (W["ht_cm"] / 100) ** 2).round(1)

lb = rng.random(len(W)) < 0.60
wt = pd.DataFrame({"PtId": W["PtId"], "EncId": W["EncId"], "Obs_type": "WT", "Obs_date": W["date"], "Obs_time": W["time"],
                   "Obs_result": np.where(lb, (W["wt_kg"] * 2.20462).round(1), W["wt_kg"].round(1)).astype(str),
                   "Obs_unit": np.where(lb, "lb", "kg")})
bmi_keep = rng.random(len(W)) < 0.85
bmi = pd.DataFrame({"PtId": W["PtId"], "EncId": W["EncId"], "Obs_type": "BMI", "Obs_date": W["date"],
                    "Obs_time": W["time"], "Obs_result": W["bmi"].astype(str), "Obs_unit": "kg/m2"})[bmi_keep]
first = W.drop_duplicates("PtId")
cm = rng.random(len(first)) < 0.5
ht = pd.DataFrame({"PtId": first["PtId"], "EncId": first["EncId"], "Obs_type": "HT", "Obs_date": first["date"],
                   "Obs_time": first["time"],
                   "Obs_result": np.where(cm, first["ht_cm"].round(1), (first["ht_cm"] / 2.54).round(1)).astype(str),
                   "Obs_unit": np.where(cm, "cm", "in")})
obs = pd.concat([wt, bmi, ht], ignore_index=True)
obs["NLP"] = "N"
obs["Result_date"] = obs["Obs_date"]
obs["Evaluated_for_range"] = None
obs["Value_within_range"] = None
obs["SourceID"] = "EHR"
print(f"observations: {len(obs):,}")
display(obs["Obs_type"].value_counts())

# COMMAND ----------

# MAGIC %md ## HbA1c labs

# COMMAND ----------

lab_enc = enc.merge(truth[["t2d"]], left_on="PtId", right_index=True)
p_lab = np.where(lab_enc["t2d"], 0.35, 0.06) * (lab_enc["Interaction_type"] != "Emergency patient")
lab_enc = lab_enc[rng.random(len(lab_enc)) < p_lab]

l_rows = []
for pt, g in lab_enc.groupby("PtId", sort=False):
    dates = g["Interaction_date"].to_numpy()
    if truth.loc[pt, "t2d"]:
        eps = episodes.get(pt, [])
        drop = effect_path(dates, eps, {k: v * resp[pt] for k, v in A1C_DROP.items()}, TAU_A1C, 150.0, 0.1) if len(eps) else 0
        yrs = (dates - np.datetime64(truth.loc[pt, "first_obesity_date"])).astype("timedelta64[D]").astype(float) / 365.25
        val = a1c0[pt] + 0.1 * yrs - drop + rng.normal(0, 0.25, len(dates))
    else:
        val = rng.normal(5.6, 0.3, len(dates))
    l_rows.append(pd.DataFrame({"PtId": pt, "EncId": g["EncId"].to_numpy(), "date": dates, "ngsp": np.clip(val, 4.2, 15)}))
L = pd.concat(l_rows, ignore_index=True)
ifcc = rng.random(len(L)) < 0.08
L["Test_result"] = np.where(ifcc, ((L["ngsp"] - 2.152) / 0.09148).round(0), L["ngsp"].round(1)).astype(str)
L["Result_unit"] = np.where(ifcc, "mmol/mol", "%")
L["Loinc"] = np.where(ifcc, "59261-8", "4548-4")
L["Test_name"] = np.where(ifcc, "HbA1c (IFCC)", "Hemoglobin A1c")
L["Normal_range"] = np.where(ifcc, "20-38", "4.0-5.6")
L["Relative_indicator"] = np.where(L["ngsp"] > 5.6, "H", "N")
collect_lag = pd.to_timedelta(rng.integers(0, 2, len(L)), unit="D")
lab = pd.DataFrame({
    "PtId": L["PtId"], "EncId": L["EncId"], "Test_name": L["Test_name"], "Test_type": "Lab", "Loinc": L["Loinc"],
    "Order_date": L["date"], "Order_time": "09:00", "Collected_date": L["date"] + collect_lag, "Collected_time": "10:15",
    "Result_date": L["date"] + collect_lag + pd.to_timedelta(rng.integers(0, 3, len(L)), unit="D"),
    "Result_time": "16:40", "Test_result": L["Test_result"], "Relative_indicator": L["Relative_indicator"],
    "Result_unit": L["Result_unit"], "Normal_range": L["Normal_range"], "Evaluated_for_range": "Y",
    "Value_within_range": np.where(L["Relative_indicator"] == "N", "Y", "N"), "SourceID": "EHR",
})
print(f"HbA1c results: {len(lab):,}")

# COMMAND ----------

save_pdf(obs, "sim_observation")
save_pdf(lab, "sim_lab")
