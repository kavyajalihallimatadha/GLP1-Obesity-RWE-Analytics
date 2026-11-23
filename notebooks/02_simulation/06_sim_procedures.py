# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · Simulate Bariatric Surgery
# MAGIC
# MAGIC Bariatric surgery is the main non-drug treatment for severe obesity. Published analyses report
# MAGIC that bariatric surgery volumes fell as GLP-1 use rose between 2022 and 2024, so the simulated
# MAGIC yearly surgery rate drops after 2022 and is lower for patients already on a GLP-1.
# MAGIC
# MAGIC - CPT **43775** – laparoscopic sleeve gastrectomy
# MAGIC - CPT **43644** – laparoscopic Roux-en-Y gastric bypass
# MAGIC
# MAGIC **Outputs:** `sim_procedure` (EHR Procedure), surgical encounters appended to `sim_encounter`,
# MAGIC surgical claims appended to `sim_claims_med_services` / `sim_claims_med_diagnosis`,
# MAGIC `sim_surgery_truth` (answer key).
# MAGIC
# MAGIC > Yearly rates are simulation parameters, not real statistics.

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

rng = np.random.default_rng(SEED + 6)
truth = load_pdf("sim_patient_truth")
fills = load_pdf("sim_rx_fill_truth")
enroll = load_pdf("sim_member_enrollment")
prov = load_pdf("sim_provider")

YEARLY_RATE = {2016: .012, 2017: .012, 2018: .012, 2019: .012, 2020: .009, 2021: .012,
               2022: .011, 2023: .009, 2024: .0075, 2025: .007}

# treatment coverage windows (episode start -> last fill + days supply)
ep = fills.groupby(["ptid", "episode_id"]).agg(start=("fill_date", "min"), last=("fill_date", "max"),
                                                ds=("days_supply", "max")).reset_index()
ep["end"] = ep["last"] + pd.to_timedelta(ep["ds"], unit="D")
on_tx = {k: g[["start", "end"]].to_numpy() for k, g in ep.groupby("ptid")}

# COMMAND ----------

eligible = truth[truth["bmi_class"].isin(["C2", "C3"]) & ~truth["pregnant"]]
surg = []
for t in eligible.itertuples():
    s = max(t.ehr_start, t.first_obesity_date)
    for y in range(s.year, t.ehr_end.year + 1):
        a = max(s, pd.Timestamp(year=y, month=1, day=1))
        b = min(t.ehr_end, pd.Timestamp(year=y, month=12, day=31))
        if b <= a:
            continue
        d = a + pd.Timedelta(days=int(rng.integers(0, (b - a).days + 1)))
        rate = YEARLY_RATE[y] * (1.4 if t.bmi_class == "C3" else 1.0)
        if any((st <= d <= en) for st, en in on_tx.get(t.ptid, [])):
            rate *= 0.4
        if rng.random() < rate:
            surg.append((t.ptid, d, "43775" if rng.random() < 0.65 else "43644", t.bmi_class, t.region, t.pcp))
            break
surg = pd.DataFrame(surg, columns=["ptid", "surgery_date", "cpt", "bmi_class", "region", "pcp"])
print(f"bariatric surgeries: {len(surg):,}")
display(surg.groupby(surg["surgery_date"].dt.year).size())

# COMMAND ----------

surgeons = prov[prov["specialty"] == "Surgery"]
surg["provid"] = [rng.choice(surgeons.loc[surgeons["region"] == r, "provid"].to_numpy()) for r in surg["region"]]
surg["EncId"] = [f"ENS{6000000000 + i}" for i in range(len(surg))]
surg["VisitId"] = [f"VSS{8000000000 + i}" for i in range(len(surg))]
surg["setting"] = np.where(rng.random(len(surg)) < 0.6, "Inpatient", "Outpatient")
desc = {"43775": "Laparoscopic sleeve gastrectomy",
        "43644": "Laparoscopic gastric bypass with Roux-en-Y gastroenterostomy"}

sim_procedure = pd.DataFrame({
    "PtId": surg["ptid"], "EncId": surg["EncId"], "Proc_date": surg["surgery_date"],
    "Proc_time": [f"{h:02d}:00" for h in rng.integers(7, 15, len(surg))],
    "Proc_code": surg["cpt"], "Proc_desc": surg["cpt"].map(desc), "Proc_code_type": "CPT4",
    "Provid_perform": surg["provid"], "Provid_order": surg["pcp"], "SourceID": "EHR",
})

new_enc = pd.DataFrame({
    "PtId": surg["ptid"], "VisitId": surg["VisitId"], "EncId": surg["EncId"],
    "Interaction_type": np.where(surg["setting"] == "Inpatient", "Inpatient", "Office or clinic patient"),
    "Interaction_date": surg["surgery_date"], "Interaction_time": "07:30",
    "Academic_community_flag": "Academic", "provid": surg["provid"], "SourceID": "EHR",
})
enc = load_pdf("sim_encounter")
enc = enc[~enc["EncId"].str.startswith("ENS")]           # idempotent re-runs
save_pdf(pd.concat([enc, new_enc], ignore_index=True), "sim_encounter")

# COMMAND ----------

# MAGIC %md ## Surgical claims (only if enrolled on the surgery date)

# COMMAND ----------

m = surg.merge(enroll, left_on="ptid", right_on="PTID")
m = m[(m["surgery_date"] >= m["Eligeff"]) & (m["surgery_date"] <= m["Eligend"])].drop_duplicates("ptid")
prov_unique = prov.set_index("provid")["prov_unique"]
svc = pd.DataFrame({
    "PTID": m["ptid"], "Pat_planid": m["Pat_planid"], "Clmid": [f"CMS{5900000000 + i}" for i in range(len(m))],
    "Clmseq": "001", "Fst_dt": m["surgery_date"],
    "Lst_dt": m["surgery_date"] + pd.to_timedelta(np.where(m["setting"] == "Inpatient", rng.integers(1, 4, len(m)), 0), unit="D"),
    "Proc_cd": m["cpt"], "Pos": np.where(m["setting"] == "Inpatient", "21", "22"),
    "Prov_Unique": prov_unique.loc[m["provid"]].to_numpy(),
    "Std_cost": rng.uniform(15000, 30000, len(m)).round(2), "Std_cost_yr": m["surgery_date"].dt.year,
    "Paid_Status": "P", "Units": 1, "Tos_cd": np.where(m["setting"] == "Inpatient", "FAC_IP.SURG", "FAC_OP.SURG"),
    "Bill_type": None,
})
new_code = m["surgery_date"] >= pd.Timestamp("2024-10-01")
ob = np.where(m["bmi_class"] == "C3", np.where(new_code, "E66813", "E6601"), np.where(new_code, "E66812", "E669"))
cdx = pd.DataFrame({"PTID": svc["PTID"], "Pat_planid": svc["Pat_planid"], "Clmid": svc["Clmid"],
                    "Diag": ob, "Diag_Position": 1, "ICD_Flag": "10", "POA": "Y", "FST_DT": svc["Fst_dt"]})

svc_all = load_pdf("sim_claims_med_services")
svc_all = svc_all[~svc_all["Clmid"].str.startswith("CMS")]
save_pdf(pd.concat([svc_all, svc], ignore_index=True), "sim_claims_med_services")
cdx_all = load_pdf("sim_claims_med_diagnosis")
cdx_all = cdx_all[~cdx_all["Clmid"].str.startswith("CMS")]
save_pdf(pd.concat([cdx_all, cdx], ignore_index=True), "sim_claims_med_diagnosis")

save_pdf(sim_procedure, "sim_procedure")
save_pdf(surg[["ptid", "surgery_date", "cpt"]], "sim_surgery_truth")
