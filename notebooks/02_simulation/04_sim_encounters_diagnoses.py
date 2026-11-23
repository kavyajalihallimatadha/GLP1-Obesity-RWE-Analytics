# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Simulate Encounters, Diagnoses and Medical Claims
# MAGIC
# MAGIC **EHR side**
# MAGIC - `sim_encounter` – office, telehealth, emergency and inpatient encounters (telehealth jumps in 2020)
# MAGIC - `sim_diagnosis` – ICD-10-CM codes with EHR diagnosis status ("Diagnosis of", "History of", "Possible diagnosis of")
# MAGIC - `sim_insurance` – payer recorded at the encounter
# MAGIC
# MAGIC **Claims side**
# MAGIC - `sim_claims_med_services` – professional / facility claim lines (CPT, place of service, cost)
# MAGIC - `sim_claims_med_diagnosis` – claim diagnosis codes (stored **without** the decimal point, like real claims)
# MAGIC
# MAGIC **Realistic coding behaviour built in**
# MAGIC - Obesity code choice depends on obesity class and date; the new class codes (E66.811–E66.813)
# MAGIC   only appear from 2024-10-01 and adoption ramps up over months (old codes keep being used)
# MAGIC - E66.8 stops being used after 2024-09-30; CKD stage 3 moves from N18.3 to N18.30 on 2020-10-01
# MAGIC - BMI Z-codes appear mainly around the time obesity is first documented
# MAGIC - Claims exist only while the patient is enrolled; some claims come from providers outside the EHR network

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

rng = np.random.default_rng(SEED + 4)
truth = load_pdf("sim_patient_truth")
prov = load_pdf("sim_provider")
enroll = load_pdf("sim_member_enrollment")
N = len(truth)

# COMMAND ----------

# MAGIC %md ## EHR encounters

# COMMAND ----------

ehr_days = np.maximum((truth["ehr_end"] - truth["ehr_start"]).dt.days.to_numpy(), 30)
rate = 2.6 + 1.2 * truth["t2d"].to_numpy() + 0.6 * (truth["bmi_class"] == "C3").to_numpy()
n_extra = rng.poisson(rate * ehr_days / 365.25)
n_enc = n_extra + 1                                      # +1 = the encounter where obesity is first documented

pi = np.repeat(np.arange(N), n_enc)
is_index = np.zeros(len(pi), dtype=bool)
first_pos = np.r_[0, np.cumsum(n_enc)[:-1]]
is_index[first_pos] = True

offs = (rng.random(len(pi)) * ehr_days[pi]).astype(int)
enc_date = truth["ehr_start"].to_numpy()[pi] + offs.astype("timedelta64[D]")
enc_date[is_index] = truth["first_obesity_date"].to_numpy()[pi[is_index]]
enc_date = pd.to_datetime(enc_date).normalize()

enc = pd.DataFrame({"pi": pi, "enc_date": enc_date, "is_index": is_index})
enc["PtId"] = truth["ptid"].to_numpy()[pi]

# encounter type: telehealth share depends on period
d = enc["enc_date"]
tele_p = np.select([d < "2020-03-01", d < "2021-01-01", d < "2022-01-01"], [0.02, 0.35, 0.18], 0.12)
u = rng.random(len(enc))
enc["Interaction_type"] = np.select(
    [u < 0.04, u < 0.06, u < 0.06 + tele_p],
    ["Emergency patient", "Inpatient", "Telehealth"], "Office or clinic patient")
enc.loc[enc["is_index"] & enc["Interaction_type"].isin(["Emergency patient", "Inpatient"]), "Interaction_type"] = "Office or clinic patient"

# provider: PCP 70%, otherwise a random provider in the patient's region (endocrinology more likely for T2D)
enc["provid"] = truth["pcp"].to_numpy()[pi]
other = rng.random(len(enc)) >= 0.70
reg = truth["region"].to_numpy()[pi]
t2d_e = truth["t2d"].to_numpy()[pi]
for r in prov["region"].unique():
    pool_all = prov.loc[prov["region"] == r, "provid"].to_numpy()
    pool_endo = prov.loc[(prov["region"] == r) & (prov["specialty"] == "Endocrinology"), "provid"].to_numpy()
    m = other & (reg == r)
    pick = rng.choice(pool_all, m.sum())
    endo_pick = (rng.random(m.sum()) < 0.35) & t2d_e[m]
    pick[endo_pick] = rng.choice(pool_endo, endo_pick.sum())
    enc.loc[m, "provid"] = pick

enc = enc.sort_values(["pi", "enc_date"]).reset_index(drop=True)
enc["EncId"] = [f"EN{4000000000 + i}" for i in range(len(enc))]
enc["VisitId"] = [f"VS{7000000000 + i}" for i in range(len(enc))]
enc["Interaction_time"] = [f"{h:02d}:{m:02d}" for h, m in zip(rng.integers(7, 19, len(enc)), rng.integers(0, 60, len(enc)))]
enc["Academic_community_flag"] = np.where(rng.random(len(enc)) < 0.3, "Academic", "Community")
print(f"EHR encounters: {len(enc):,}")

# COMMAND ----------

# MAGIC %md ## EHR diagnoses

# COMMAND ----------

t = truth
E = enc
P = E["pi"].to_numpy()
date = E["enc_date"]
n = len(E)
fod = t["first_obesity_date"].to_numpy()[P]
after_onset = date.to_numpy() >= fod
klass = t["bmi_class"].to_numpy()[P]
NEW_CODES = pd.Timestamp("2024-10-01")


def obesity_code(klass, date, u1, u2):
    """Code a clinician would choose, given obesity class and date."""
    date = pd.Series(pd.to_datetime(date)).reset_index(drop=True)
    months = ((date - NEW_CODES).dt.days / 30.44).clip(lower=0).to_numpy()
    new_era = (date >= NEW_CODES).to_numpy()
    p_new = np.clip(0.30 + 0.06 * months, 0, 0.85)
    use_new = new_era & (u1 < p_new)
    old_c3 = np.where(u2 < 0.70, "E66.01", "E66.9")
    old_other_pre = np.select([u2 < 0.75, u2 < 0.90], ["E66.9", "E66.09"], "E66.8")
    old_other_post = np.where(u2 < 0.85, "E66.9", "E66.09")
    old_other = np.where(new_era, old_other_post, old_other_pre)
    old = np.where(klass == "C3", old_c3, old_other)
    new = np.select([klass == "C1", klass == "C2"], ["E66.811", "E66.812"], "E66.813")
    code = np.where(use_new, new, old)
    return np.where(klass == "OW", "E66.3", code)


dx_parts = []


def add_dx(mask, codes, status_p=(0.90, 0.06, 0.04)):
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return
    codes = np.asarray(codes)
    codes = codes[idx] if codes.shape and len(codes) == n else np.repeat(codes, len(idx))
    status = rng.choice(["Diagnosis of", "History of", "Possible diagnosis of"], len(idx), p=list(status_p))
    dx_parts.append(pd.DataFrame({"row": idx, "Diagnosis_cd": codes, "Diagnosis_status": status}))


coded_patient = ~t["undercoded"].to_numpy()[P]
ob_mask = after_onset & coded_patient & (E["is_index"].to_numpy() | (rng.random(n) < 0.45))
ob_codes = obesity_code(klass, date, rng.random(n), rng.random(n))
add_dx(ob_mask, ob_codes, (0.97, 0.02, 0.01))

# BMI Z-codes around first documentation
bmi0 = t["bmi0"].to_numpy()[P]
z_code = np.select(
    [bmi0 < 40, bmi0 < 45, bmi0 < 50, bmi0 < 60, bmi0 < 70],
    [np.char.add("Z68.", np.floor(bmi0).astype(int).astype(str)), "Z68.41", "Z68.42", "Z68.43", "Z68.44"],
    "Z68.45")
near_onset = (date.to_numpy() - fod) <= np.timedelta64(180, "D")
add_dx(ob_mask & near_onset & (rng.random(n) < 0.55), z_code, (1.0, 0.0, 0.0))

# comorbidities
r = lambda: rng.random(n)
uu = r()
t2d_code = np.select([uu < 0.60, uu < 0.85], ["E11.9", "E11.65"], "E11.22")
t2d_code = np.where((t2d_code == "E11.22") & ~t["ckd"].to_numpy()[P], "E11.9", t2d_code)
add_dx(t["t2d"].to_numpy()[P] & (r() < 0.70), t2d_code)
add_dx(t["t1d"].to_numpy()[P] & (r() < 0.70), "E10.9")
add_dx(t["htn"].to_numpy()[P] & (r() < 0.50), "I10")
add_dx(t["dyslip"].to_numpy()[P] & (r() < 0.40), "E78.5")
add_dx(t["osa"].to_numpy()[P] & (r() < 0.30), "G47.33")
add_dx(t["ascvd"].to_numpy()[P] & (r() < 0.40), "I25.10")
add_dx(t["mash"].to_numpy()[P] & (r() < 0.25), "K75.81")
ckd_code = np.where(date < "2020-10-01", "N18.3", "N18.30")
add_dx(t["ckd"].to_numpy()[P] & (r() < 0.35), ckd_code)

ps = t["preg_start"].to_numpy()[P]
in_preg = (~pd.isna(ps)) & (date.to_numpy() >= ps) & (date.to_numpy() <= ps + np.timedelta64(280, "D"))
add_dx(in_preg & (r() < 0.80), "Z33.1", (1.0, 0.0, 0.0))

# rule-out noise: "possible" diabetes in patients who do not have it
add_dx(~t["t2d"].to_numpy()[P] & (r() < 0.01), "E11.9", (0.0, 0.0, 1.0))

dx = pd.concat(dx_parts, ignore_index=True)
dx = dx.merge(E[["EncId", "PtId", "enc_date"]], left_on="row", right_index=True).drop(columns="row")
dx = dx.sort_values(["EncId"]).reset_index(drop=True)
dx["Primary_diagnosis"] = np.where(dx.groupby("EncId").cumcount() == 0, "1", "0")
dx["Diag_date"] = dx["enc_date"]
dx["Diag_time"] = None
dx["Diagnosis_cd_type"] = "ICD10"
dx["POA"] = None
dx["Admitting_diagnosis"] = "0"
dx["Discharge_diagnosis"] = "0"
dx["Problem_list"] = np.where(rng.random(len(dx)) < 0.15, "Y", "N")
dx["SourceID"] = "EHR"
sim_diagnosis = dx[["PtId", "EncId", "Diag_date", "Diag_time", "Diagnosis_cd", "Diagnosis_cd_type",
                    "Diagnosis_status", "POA", "Admitting_diagnosis", "Discharge_diagnosis",
                    "Primary_diagnosis", "Problem_list", "SourceID"]]
print(f"EHR diagnoses: {len(sim_diagnosis):,}")

# COMMAND ----------

# MAGIC %md ## Match encounters to insurance spans

# COMMAND ----------

def attach_span(df, date_col):
    """For each row, find the enrollment span that covers the date (if any)."""
    m = df[["PtId", date_col]].reset_index().merge(
        enroll[["PTID", "Pat_planid", "Bus", "Eligeff", "Eligend"]], left_on="PtId", right_on="PTID", how="inner")
    m = m[(m[date_col] >= m["Eligeff"]) & (m[date_col] <= m["Eligend"])]
    m = m.drop_duplicates("index").set_index("index")
    return df.join(m[["Pat_planid", "Bus"]])


E = attach_span(E, "enc_date")
print(f"encounters inside an enrollment span: {E['Bus'].notna().mean():.1%}")

# EHR insurance table (payer captured at about half of encounters)
ins_map = {"COM": "Commercial", "MCR": "Medicare", "MCD": "Medicaid"}
ins = E[rng.random(len(E)) < 0.5][["PtId", "EncId", "enc_date", "Interaction_time", "Bus"]].copy()
ins["Ins_type"] = ins["Bus"].map(ins_map)
ins.loc[ins["Ins_type"].isna(), "Ins_type"] = rng.choice(["Uninsured", "Other Payor", "Unknown"],
                                                         ins["Ins_type"].isna().sum(), p=[0.35, 0.30, 0.35])
sim_insurance = ins.rename(columns={"enc_date": "Insurance_date", "Interaction_time": "Insurance_time"})[
    ["PtId", "EncId", "Insurance_date", "Insurance_time", "Ins_type"]]
sim_insurance["SourceID"] = "EHR"

# COMMAND ----------

# MAGIC %md ## Medical claims (from EHR encounters + claims-only encounters)

# COMMAND ----------

prov_idx = prov.set_index("provid")

# 1) EHR encounters that were billed while enrolled
billed = E[E["Bus"].notna() & (rng.random(len(E)) < 0.90)].copy()
billed["source"] = "EHR_LINKED"

# 2) claims-only encounters (providers outside the EHR network), ~0.8 per enrolled year
sp = enroll.copy()
sp["days"] = (sp["Eligend"] - sp["Eligeff"]).dt.days.clip(lower=1)
k = rng.poisson(0.8 * sp["days"] / 365.25)
rep = sp.loc[sp.index.repeat(k)].reset_index(drop=True)
rep["enc_date"] = rep["Eligeff"] + pd.to_timedelta((rng.random(len(rep)) * rep["days"]).astype(int), unit="D")
rep = rep.rename(columns={"PTID": "PtId"})
pid_to_i = pd.Series(np.arange(N), index=truth["ptid"])
rep["pi"] = pid_to_i.loc[rep["PtId"]].to_numpy()
rep["Interaction_type"] = rng.choice(["Office or clinic patient", "Emergency patient", "Inpatient"],
                                     len(rep), p=[0.88, 0.08, 0.04])
reg = truth["region"].to_numpy()[rep["pi"]]
rep["provid"] = None
for rr in prov["region"].unique():
    m = reg == rr
    rep.loc[m, "provid"] = rng.choice(prov.loc[prov["region"] == rr, "provid"].to_numpy(), m.sum())
rep["EncId"] = None
rep["source"] = "CLAIMS_ONLY"

cl = pd.concat([billed[["pi", "PtId", "enc_date", "Interaction_type", "provid", "EncId", "Pat_planid", "Bus", "source"]],
                rep[["pi", "PtId", "enc_date", "Interaction_type", "provid", "EncId", "Pat_planid", "Bus", "source"]]],
               ignore_index=True)
cl = cl.sort_values(["PtId", "enc_date"]).reset_index(drop=True)
cl["Clmid"] = [f"CM{5000000000 + i}" for i in range(len(cl))]

ty = cl["Interaction_type"]
uu = rng.random(len(cl))
office_cpt = np.select([uu < 0.05, uu < 0.60], ["99203", "99213"], "99214")
cl["Proc_cd"] = np.select([ty == "Emergency patient", ty == "Inpatient"], ["99284", "99223"], office_cpt)
cl["Pos"] = np.select([ty == "Telehealth", ty == "Emergency patient", ty == "Inpatient"], ["02", "23", "21"], "11")
los = np.where(ty == "Inpatient", rng.integers(2, 7, len(cl)), 0)
cl["Fst_dt"] = cl["enc_date"]
cl["Lst_dt"] = cl["enc_date"] + pd.to_timedelta(los, unit="D")
base_cost = np.select([ty == "Emergency patient", ty == "Inpatient"],
                      [rng.uniform(600, 1500, len(cl)), rng.uniform(8000, 20000, len(cl))],
                      rng.uniform(90, 170, len(cl)))
cl["Std_cost"] = base_cost.round(2)
cl["Std_cost_yr"] = cl["Fst_dt"].dt.year
cl["Prov_Unique"] = prov_idx.loc[cl["provid"], "prov_unique"].to_numpy()
cl["Paid_Status"] = np.where(rng.random(len(cl)) < 0.97, "P", "D")
cl["Clmseq"] = "001"
cl["Bill_type"] = None
cl["Units"] = 1
cl["Tos_cd"] = np.select([ty == "Inpatient", ty == "Emergency patient"], ["FAC_IP.ROOM", "FAC_OP.ER"], "PROF.OFFICE")

sim_claims_med_services = cl[["PtId", "Pat_planid", "Clmid", "Clmseq", "Fst_dt", "Lst_dt", "Proc_cd", "Pos",
                              "Prov_Unique", "Std_cost", "Std_cost_yr", "Paid_Status", "Units", "Tos_cd",
                              "Bill_type"]].rename(columns={"PtId": "PTID"})
print(f"medical claims: {len(cl):,}  ({(cl['source'] == 'CLAIMS_ONLY').mean():.0%} claims-only)")

# COMMAND ----------

# MAGIC %md ## Claim diagnosis codes

# COMMAND ----------

# EHR-linked claims carry the confirmed EHR diagnoses of that encounter
linked = cl[cl["source"] == "EHR_LINKED"][["Clmid", "EncId", "PtId", "Pat_planid", "Fst_dt"]]
confirmed = dx[dx["Diagnosis_status"] == "Diagnosis of"][["EncId", "Diagnosis_cd"]]
cdx1 = linked.merge(confirmed, on="EncId")

# claims-only encounters: draw codes from the patient's true conditions
co = cl[cl["source"] == "CLAIMS_ONLY"].reset_index(drop=True)
Pc = co["pi"].to_numpy()
m = len(co)
parts = []
ob_ok = (co["Fst_dt"].to_numpy() >= truth["first_obesity_date"].to_numpy()[Pc]) & ~truth["undercoded"].to_numpy()[Pc]
codes = obesity_code(truth["bmi_class"].to_numpy()[Pc], co["Fst_dt"], rng.random(m), rng.random(m))
sel = ob_ok & (rng.random(m) < 0.35)
parts.append(pd.DataFrame({"i": np.flatnonzero(sel), "Diagnosis_cd": codes[sel]}))
for flag, code, p in [("t2d", "E11.9", 0.6), ("htn", "I10", 0.45), ("dyslip", "E78.5", 0.35),
                      ("osa", "G47.33", 0.3), ("ascvd", "I25.10", 0.4), ("t1d", "E10.9", 0.6)]:
    s = truth[flag].to_numpy()[Pc] & (rng.random(m) < p)
    parts.append(pd.DataFrame({"i": np.flatnonzero(s), "Diagnosis_cd": code}))
cdx2 = pd.concat(parts, ignore_index=True).merge(co[["Clmid", "PtId", "Pat_planid", "Fst_dt"]], left_on="i", right_index=True)
# a claim needs at least one diagnosis: give empty ones a general exam code
no_dx = co.loc[~co.index.isin(cdx2["i"]), ["Clmid", "PtId", "Pat_planid", "Fst_dt"]].copy()
no_dx["Diagnosis_cd"] = "Z00.00"
cdx = pd.concat([cdx1.drop(columns="EncId"), cdx2.drop(columns="i"), no_dx], ignore_index=True)

cdx = cdx.sort_values(["Clmid"]).reset_index(drop=True)
cdx["Diag_Position"] = cdx.groupby("Clmid").cumcount() + 1
cdx["Diag"] = cdx["Diagnosis_cd"].str.replace(".", "", regex=False)    # claims store codes without the dot
cdx["ICD_Flag"] = "10"
cdx["POA"] = None
sim_claims_med_diagnosis = cdx.rename(columns={"PtId": "PTID", "Fst_dt": "FST_DT"})[
    ["PTID", "Pat_planid", "Clmid", "Diag", "Diag_Position", "ICD_Flag", "POA", "FST_DT"]]
print(f"claim diagnosis rows: {len(sim_claims_med_diagnosis):,}")

# COMMAND ----------

# MAGIC %md ## Save

# COMMAND ----------

sim_encounter = E[["PtId", "VisitId", "EncId", "Interaction_type", "enc_date", "Interaction_time",
                   "Academic_community_flag", "provid"]].rename(columns={"enc_date": "Interaction_date"})
sim_encounter["SourceID"] = "EHR"

save_pdf(sim_encounter, "sim_encounter")
save_pdf(sim_diagnosis, "sim_diagnosis")
save_pdf(sim_insurance, "sim_insurance")
save_pdf(sim_claims_med_services, "sim_claims_med_services")
save_pdf(sim_claims_med_diagnosis, "sim_claims_med_diagnosis")
