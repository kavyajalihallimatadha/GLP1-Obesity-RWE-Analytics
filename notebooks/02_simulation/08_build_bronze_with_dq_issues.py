# Databricks notebook source
# MAGIC %md
# MAGIC # 08 · Build the Bronze (Raw) Layer with Real-World Data-Quality Problems
# MAGIC
# MAGIC Real claims and EHR extracts are messy. This notebook takes the clean simulated tables and
# MAGIC injects the kinds of problems analysts actually meet, then lands everything as **string columns**
# MAGIC (like a raw file drop) in `bronze_*` tables.
# MAGIC
# MAGIC Every injected problem is counted in `dq_injection_log`, so the Silver layer can prove it found
# MAGIC and fixed them (see notebook 13).
# MAGIC
# MAGIC | Area | Problems injected |
# MAGIC |---|---|
# MAGIC | Patient | gender/race/region spelled many ways, impossible birth years, duplicate rows |
# MAGIC | Enrollment | start/end dates swapped, overlapping spans, mixed date formats, lower-case payer codes |
# MAGIC | Encounters / diagnoses | duplicates, ICD-10 codes with/without dots, lower case, spaces, ICD-9 leftovers, retired code E66.8 used after Oct 2024 |
# MAGIC | Vitals | lb/kg unit spellings, missing units, decimal-shift errors, text in numeric fields, height as 5' 6" |
# MAGIC | Labs | IFCC units without a unit label, "Pending"/"Cancelled" results, "<" and ">" values |
# MAGIC | Pharmacy claims | NDCs in 4 formats (11-digit, hyphenated, 10-digit labeled, lost leading zeros), reversals, days supply 0/999/blank, fills after death, patients missing from the patient table, duplicates |
# MAGIC | Providers | specialty spelled several ways |

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

rng = np.random.default_rng(SEED + 8)
INJ = []


def note(table, issue, n):
    INJ.append({"table_name": table, "issue": issue, "rows_injected": int(n)})
    print(f"{table:<28} {issue:<60} {int(n):>8,}")


def as_strings(df):
    """Land every column as text, the way a raw extract arrives."""
    out = pd.DataFrame(index=df.index)
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            out[c] = s.dt.strftime("%Y-%m-%d").where(s.notna(), None)
        elif pd.api.types.is_bool_dtype(s):
            out[c] = s.map({True: "Y", False: "N"})
        else:
            out[c] = s.astype(object).where(s.notna(), None).map(lambda v: None if v is None else str(v))
    return out


def pick(df, frac, mask=None):
    """Random row labels (optionally among rows where mask is True)."""
    pool = df.index if mask is None else df.index[mask]
    k = int(round(len(pool) * frac))
    return rng.choice(pool, k, replace=False) if k else np.array([], dtype=pool.dtype)


def mix_dates(df, col, frac, table):
    idx = pick(df, frac, df[col].notna())
    half = len(idx) // 2
    d = pd.to_datetime(df.loc[idx, col])
    df.loc[idx[:half], col] = d[:half].dt.strftime("%m/%d/%Y").to_numpy()
    df.loc[idx[half:], col] = d[half:].dt.strftime("%Y%m%d").to_numpy()
    note(table, f"{col}: non-ISO date format (MM/DD/YYYY or YYYYMMDD)", len(idx))


def add_dups(df, frac, table):
    idx = pick(df, frac)
    note(table, "exact duplicate rows", len(idx))
    return pd.concat([df, df.loc[idx]], ignore_index=True)

# COMMAND ----------

# MAGIC %md ## Patient

# COMMAND ----------

p = as_strings(load_pdf("sim_patient"))
idx = pick(p, 0.06)
p.loc[idx, "Gender"] = [rng.choice(["Female", "female", "f", "FEMALE"]) if g == "F" else rng.choice(["Male", "MALE", "m", "male"])
                        for g in p.loc[idx, "Gender"]]
note("bronze_patient", "Gender: non-standard spelling", len(idx))
idx = pick(p, 0.005)
p.loc[idx, "Gender"] = rng.choice(["U", "", None], len(idx))
note("bronze_patient", "Gender: unknown / blank", len(idx))

race_var = {"Caucasian": ["White", "CAUCASIAN", "caucasian "], "African American": ["Black", "African-American", "AFRICAN AMERICAN"],
            "Asian": ["ASIAN", "asian"], "Other/Unknown": ["Unknown", "Other", "other/unknown"]}
idx = pick(p, 0.04)
p.loc[idx, "Race"] = [rng.choice(race_var[r]) for r in p.loc[idx, "Race"]]
note("bronze_patient", "Race: non-standard spelling / synonym", len(idx))

reg_var = {"Northeast": "NORTHEAST", "Midwest": "Mid West", "South": "south ", "West": "WEST"}
idx = pick(p, 0.03)
p.loc[idx, "Region"] = p.loc[idx, "Region"].map(reg_var)
note("bronze_patient", "Region: non-standard spelling", len(idx))

idx = pick(p, 0.004)
p.loc[idx, "Birth_yr"] = rng.choice(["0", "1800", "2031", "", "19xx"], len(idx))
note("bronze_patient", "Birth_yr: impossible / non-numeric", len(idx))

p = add_dups(p, 0.003, "bronze_patient")
save_pdf(p, "bronze_patient")

# COMMAND ----------

# MAGIC %md ## Insurance enrollment

# COMMAND ----------

e = as_strings(load_pdf("sim_member_enrollment"))
idx = pick(e, 0.005)
e.loc[idx, ["Eligeff", "Eligend"]] = e.loc[idx, ["Eligend", "Eligeff"]].to_numpy()
note("bronze_member_enrollment", "Eligeff/Eligend swapped", len(idx))

idx = pick(e, 0.01)
ov = e.loc[idx].copy()
ov["Eligeff"] = (pd.to_datetime(ov["Eligeff"]) + pd.Timedelta(days=45)).dt.strftime("%Y-%m-%d")
ov["Eligend"] = (pd.to_datetime(ov["Eligend"]) + pd.Timedelta(days=45)).dt.strftime("%Y-%m-%d")
e = pd.concat([e, ov], ignore_index=True)
note("bronze_member_enrollment", "overlapping duplicate span (+45 days)", len(idx))

idx = pick(e, 0.02)
e.loc[idx, "Bus"] = e.loc[idx, "Bus"].str.lower()
note("bronze_member_enrollment", "Bus: lower case", len(idx))
mix_dates(e, "Eligeff", 0.08, "bronze_member_enrollment")
mix_dates(e, "Eligend", 0.08, "bronze_member_enrollment")
save_pdf(e, "bronze_member_enrollment")

# COMMAND ----------

# MAGIC %md ## Providers

# COMMAND ----------

pv = load_pdf("sim_provider")
prov_ehr = as_strings(pv.rename(columns={"provid": "ProvId", "specialty": "Specialty", "prim_spec_ind": "Prim_spec_ind",
                                         "taxonomy": "Taxonomy"})[["ProvId", "Specialty", "Prim_spec_ind", "Taxonomy"]])
spec_var = {"Endocrinology": ["ENDOCRINOLOGY", "Endo", "Endocrinology, Diabetes & Metabolism"],
            "Family Medicine": ["Family Practice", "FAMILY MEDICINE", "family med"],
            "Internal Medicine": ["Int Med", "INTERNAL MEDICINE"], "Nurse Practitioner": ["NP", "Nurse practitioner"],
            "Cardiology": ["Cardiovascular Disease", "CARDIOLOGY"], "Gastroenterology": ["GI", "Gastroenterology "],
            "Surgery": ["General Surgery", "SURGERY"]}
idx = pick(prov_ehr, 0.08)
prov_ehr.loc[idx, "Specialty"] = [rng.choice(spec_var[s]) for s in prov_ehr.loc[idx, "Specialty"]]
note("bronze_provider", "Specialty: non-standard spelling", len(idx))
prov_ehr["SourceID"] = "EHR"
save_pdf(prov_ehr, "bronze_provider")

prov_cl = as_strings(pv.rename(columns={"prov_unique": "Prov_Unique", "state": "Prov_State", "prov_type": "Prov_Type",
                                        "taxonomy": "Taxonomy1", "grp_practice": "Grp_Practice", "hosp_affil": "Hosp_Affil"})[
    ["Prov_Unique", "Prov_State", "Prov_Type", "Taxonomy1", "Grp_Practice", "Hosp_Affil"]])
save_pdf(prov_cl, "bronze_claims_provider")

# COMMAND ----------

# MAGIC %md ## Encounters and diagnoses

# COMMAND ----------

en = as_strings(load_pdf("sim_encounter"))
idx = pick(en, 0.02)
en.loc[idx, "Interaction_type"] = en.loc[idx, "Interaction_type"].str.upper()
note("bronze_encounter", "Interaction_type: upper case", len(idx))
mix_dates(en, "Interaction_date", 0.05, "bronze_encounter")
en = add_dups(en, 0.005, "bronze_encounter")
save_pdf(en, "bronze_encounter")

dx = as_strings(load_pdf("sim_diagnosis"))
idx = pick(dx, 0.08)
dx.loc[idx, "Diagnosis_cd"] = dx.loc[idx, "Diagnosis_cd"].str.replace(".", "", regex=False)
note("bronze_diagnosis", "Diagnosis_cd: missing decimal point", len(idx))
idx = pick(dx, 0.03)
dx.loc[idx, "Diagnosis_cd"] = dx.loc[idx, "Diagnosis_cd"].str.lower()
note("bronze_diagnosis", "Diagnosis_cd: lower case", len(idx))
idx = pick(dx, 0.02)
dx.loc[idx, "Diagnosis_cd"] = " " + dx.loc[idx, "Diagnosis_cd"] + "  "
note("bronze_diagnosis", "Diagnosis_cd: leading/trailing spaces", len(idx))

post = pd.to_datetime(dx["Diag_date"], errors="coerce") >= pd.Timestamp("2024-10-01")
obese_new = dx["Diagnosis_cd"].str.strip().str.upper().str.replace(".", "", regex=False).isin(["E66811", "E66812", "E669"])
idx = pick(dx, 0.04, post & obese_new)
dx.loc[idx, "Diagnosis_cd"] = "E66.8"
note("bronze_diagnosis", "E66.8 used after it became non-billable (2024-10-01)", len(idx))

k = int(len(dx) * 0.003)
icd9 = dx.loc[pick(dx, 0.003)].copy()
icd9["Diagnosis_cd"] = rng.choice(["278.00", "278.01", "250.00", "401.9"], len(icd9))
icd9["Diagnosis_cd_type"] = "ICD9"
dx = pd.concat([dx, icd9], ignore_index=True)
note("bronze_diagnosis", "legacy ICD-9 rows", len(icd9))
mix_dates(dx, "Diag_date", 0.05, "bronze_diagnosis")
dx = add_dups(dx, 0.01, "bronze_diagnosis")
save_pdf(dx, "bronze_diagnosis")

save_pdf(as_strings(load_pdf("sim_insurance")), "bronze_insurance")

proc = as_strings(load_pdf("sim_procedure"))
idx = pick(proc, 0.10)
proc.loc[idx, "Proc_code_type"] = rng.choice(["CPT", "cpt4", "HCPCS/CPT"], len(idx))
note("bronze_procedure", "Proc_code_type: inconsistent label", len(idx))
save_pdf(proc, "bronze_procedure")

# COMMAND ----------

# MAGIC %md ## Medical claims

# COMMAND ----------

ms = as_strings(load_pdf("sim_claims_med_services"))
idx = pick(ms, 0.002)
ms.loc[idx, "Std_cost"] = (-pd.to_numeric(ms.loc[idx, "Std_cost"])).astype(str)
note("bronze_claims_med_services", "Std_cost negative (adjustment line)", len(idx))
mix_dates(ms, "Fst_dt", 0.05, "bronze_claims_med_services")
ms = add_dups(ms, 0.007, "bronze_claims_med_services")
save_pdf(ms, "bronze_claims_med_services")

md = as_strings(load_pdf("sim_claims_med_diagnosis"))
idx = pick(md, 0.03, md["Diag"].str.len() > 3)
md.loc[idx, "Diag"] = md.loc[idx, "Diag"].str[:3] + "." + md.loc[idx, "Diag"].str[3:]
note("bronze_claims_med_diagnosis", "Diag: decimal point present (claims normally have none)", len(idx))
idx = pick(md, 0.01)
md.loc[idx, "Diag"] = md.loc[idx, "Diag"].str.lower()
note("bronze_claims_med_diagnosis", "Diag: lower case", len(idx))
md = add_dups(md, 0.005, "bronze_claims_med_diagnosis")
save_pdf(md, "bronze_claims_med_diagnosis")

# COMMAND ----------

# MAGIC %md ## Vital signs

# COMMAND ----------

ob = as_strings(load_pdf("sim_observation"))
wt = ob["Obs_type"] == "WT"
idx = pick(ob, 0.03, wt)
ob.loc[idx, "Obs_unit"] = [rng.choice(["LBS", "lbs", "Lb"]) if u == "lb" else rng.choice(["KG", "kgs", "Kg"]) for u in ob.loc[idx, "Obs_unit"]]
note("bronze_observation", "Obs_unit: non-standard spelling", len(idx))
idx = pick(ob, 0.01, wt)
ob.loc[idx, "Obs_unit"] = None
note("bronze_observation", "Obs_unit: missing for weight", len(idx))

bm = ob["Obs_type"] == "BMI"
idx = pick(ob, 0.003, bm)
ob.loc[idx, "Obs_result"] = (pd.to_numeric(ob.loc[idx, "Obs_result"]) * 10).round(1).astype(str)
note("bronze_observation", "BMI: decimal shift (x10)", len(idx))
idx = pick(ob, 0.002, wt)
ob.loc[idx, "Obs_result"] = (pd.to_numeric(ob.loc[idx, "Obs_result"]) / 10).round(1).astype(str)
note("bronze_observation", "Weight: decimal shift (/10)", len(idx))
idx = pick(ob, 0.002)
ob.loc[idx, "Obs_result"] = rng.choice(["refused", "see note", "", "N/A"], len(idx))
note("bronze_observation", "Obs_result: text in numeric field", len(idx))

ht = (ob["Obs_type"] == "HT") & pd.to_numeric(ob["Obs_result"], errors="coerce").notna()
idx = pick(ob, 0.02, ht)
inches = [float(v) if u == "in" else float(v) / 2.54 for v, u in zip(ob.loc[idx, "Obs_result"], ob.loc[idx, "Obs_unit"])]
ob.loc[idx, "Obs_result"] = [f"{int(x // 12)}' {int(round(x % 12))}\"" for x in inches]
ob.loc[idx, "Obs_unit"] = "ft/in"
note("bronze_observation", "Height recorded as feet-inches text", len(idx))
mix_dates(ob, "Obs_date", 0.03, "bronze_observation")
ob = add_dups(ob, 0.01, "bronze_observation")
save_pdf(ob, "bronze_observation")

# COMMAND ----------

# MAGIC %md ## Labs

# COMMAND ----------

lb = as_strings(load_pdf("sim_lab"))
ifcc = lb["Result_unit"] == "mmol/mol"
idx = pick(lb, 0.15, ifcc)
lb.loc[idx, "Result_unit"] = None
note("bronze_lab", "Result_unit missing (IFCC mmol/mol value)", len(idx))
idx = pick(lb, 0.005)
lb.loc[idx, "Test_result"] = rng.choice(["Pending", "CANCELLED", "Specimen hemolyzed"], len(idx))
note("bronze_lab", "Test_result: not a result (pending/cancelled)", len(idx))
idx = pick(lb, 0.002, lb["Result_unit"] == "%")
lb.loc[idx, "Test_result"] = rng.choice(["<4.0", ">14.0"], len(idx))
note("bronze_lab", "Test_result: censored value with < or >", len(idx))
mix_dates(lb, "Result_date", 0.04, "bronze_lab")
lb = add_dups(lb, 0.005, "bronze_lab")
save_pdf(lb, "bronze_lab")

# COMMAND ----------

# MAGIC %md ## Pharmacy claims

# COMMAND ----------

rx = as_strings(load_pdf("sim_claims_rx"))
paid = rx["Transaction_Type"] == "PAID"
n11 = rx["Ndc"]

idx = pick(rx, 0.10)
rx.loc[idx, "Ndc"] = n11[idx].str[:5] + "-" + n11[idx].str[5:9] + "-" + n11[idx].str[9:]
note("bronze_claims_rx", "Ndc: 11-digit with hyphens (5-4-2)", len(idx))

ref = load_pdf("ref_ndc").set_index("ndc11")["ndc_labeled"]
rest = ~rx.index.isin(idx)
idx2 = pick(rx, 0.05, rest)
rx.loc[idx2, "Ndc"] = ref.reindex(n11[idx2]).to_numpy()
note("bronze_claims_rx", "Ndc: 10-digit FDA labeled format", len(idx2))

rest = rest & ~rx.index.isin(idx2)
idx3 = pick(rx, 0.03, rest)
rx.loc[idx3, "Ndc"] = n11[idx3].str.lstrip("0")
note("bronze_claims_rx", "Ndc: leading zeros lost (numeric cast)", len(idx3))

rest = rest & ~rx.index.isin(idx3)
idx4 = pick(rx, 0.01, rest)
rx.loc[idx4, "Ndc"] = " " + n11[idx4] + " "
note("bronze_claims_rx", "Ndc: padded with spaces", len(idx4))

idx = pick(rx, 0.05)
rx.loc[idx, "Brnd_nm"] = rx.loc[idx, "Brnd_nm"].str.title() + rng.choice(["", " "], len(idx))
note("bronze_claims_rx", "Brnd_nm: mixed case / trailing space", len(idx))

idx = pick(rx, 0.005, paid)
rx.loc[idx, "Days_Sup"] = "0"
note("bronze_claims_rx", "Days_Sup = 0", len(idx))
idx = pick(rx, 0.003, paid & (rx["Days_Sup"] != "0"))
rx.loc[idx, "Days_Sup"] = "999"
note("bronze_claims_rx", "Days_Sup = 999", len(idx))
idx = pick(rx, 0.002, paid & ~rx["Days_Sup"].isin(["0", "999"]))
rx.loc[idx, "Days_Sup"] = None
note("bronze_claims_rx", "Days_Sup missing", len(idx))

# reversals: a paid claim is later reversed (same Clmid, negative quantity and cost)
idx = pick(rx, 0.02, paid)
rev = rx.loc[idx].copy()
rev["Transaction_Type"] = "REVERSAL"
rev["Quantity"] = (-pd.to_numeric(rev["Quantity"])).astype(str)
rev["Std_Cost"] = (-pd.to_numeric(rev["Std_Cost"])).astype(str)
rev["Fill_dt"] = (pd.to_datetime(rev["Fill_dt"]) + pd.to_timedelta(rng.integers(1, 6, len(rev)), unit="D")).dt.strftime("%Y-%m-%d")
note("bronze_claims_rx", "reversal rows (paid claim later reversed)", len(rev))

# fills after death
pt = load_pdf("sim_patient")
dead = pt[pt["Date_of_death"].notna()][["PtId", "Date_of_death"]]
dead_fills = rx[paid].merge(dead, left_on="PTID", right_on="PtId")
last = dead_fills.sort_values("Fill_dt").groupby("PTID").tail(1)
last = last.sample(frac=0.6, random_state=SEED) if len(last) else last
after = last[rx.columns].copy()
dod = pd.to_datetime(last["Date_of_death"], format="%Y%m") + pd.offsets.MonthEnd(0)
after["Fill_dt"] = (dod + pd.to_timedelta(rng.integers(20, 90, len(after)), unit="D")).dt.strftime("%Y-%m-%d").to_numpy()
after["Clmid"] = [f"RXD{7900000000 + i}" for i in range(len(after))]
note("bronze_claims_rx", "fill dated after the patient's death", len(after))

# patients not present in the patient table
orphan = rx.loc[pick(rx, 0.002, paid)].copy()
orphan["PTID"] = [f"PT9{rng.integers(10**8, 10**9 - 1)}" for _ in range(len(orphan))]
orphan["Clmid"] = [f"RXO{7800000000 + i}" for i in range(len(orphan))]
note("bronze_claims_rx", "PTID not found in patient table", len(orphan))

rx = pd.concat([rx, rev, after, orphan], ignore_index=True)
mix_dates(rx, "Fill_dt", 0.05, "bronze_claims_rx")
rx = add_dups(rx, 0.01, "bronze_claims_rx")
save_pdf(rx, "bronze_claims_rx")

# COMMAND ----------

# MAGIC %md ## Prescriptions written (EHR)

# COMMAND ----------

rw = as_strings(load_pdf("sim_rx_written"))
idx = pick(rw, 0.03)
rw.loc[idx, "NDC"] = None
note("bronze_rx_written", "NDC missing (drug name only)", len(idx))
idx = pick(rw, 0.03)
rw.loc[idx, "Drug_name"] = rw.loc[idx, "Drug_name"].str.lower()
note("bronze_rx_written", "Drug_name: lower case", len(idx))
mix_dates(rw, "RX_date", 0.05, "bronze_rx_written")
save_pdf(rw, "bronze_rx_written")

# COMMAND ----------

save_pdf(pd.DataFrame(INJ), "dq_injection_log")
display(pd.DataFrame(INJ))
