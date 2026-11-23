# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Simulate Patients and Insurance Enrollment
# MAGIC
# MAGIC Creates 50,000 patients in a linked claims + EHR style, plus their insurance enrollment history.
# MAGIC
# MAGIC **What gets simulated**
# MAGIC - Demographics: birth year, sex, race, ethnicity, census region / division
# MAGIC - Clinical profile (hidden "truth"): height, baseline BMI and obesity class, comorbidities
# MAGIC   (type 2 diabetes, hypertension, dyslipidemia, sleep apnea, heart disease, MASH, CKD)
# MAGIC - When the patient first has obesity documented, and whether their clinicians actually code it
# MAGIC   (obesity is under-coded in real claims, so ~12% of patients only show it through BMI readings)
# MAGIC - Insurance: payer type (Commercial / Medicare / Medicaid), plan product, coverage spans with
# MAGIC   gaps, aging into Medicare at 65, pharmacy coverage flag
# MAGIC - EHR activity window (can extend beyond insurance enrollment), deaths, pregnancies
# MAGIC
# MAGIC **Outputs**
# MAGIC - `sim_patient_truth` – hidden clinical truth used by later generators (never used in analysis)
# MAGIC - `sim_patient` – EHR **Patient** table
# MAGIC - `sim_member_enrollment` – claims **Member Detail** enrollment spans
# MAGIC
# MAGIC > All rates below are simulation parameters, not real-world statistics.

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

rng = np.random.default_rng(SEED + 3)
N = N_PATIENTS
D0 = pd.Timestamp(DATA_START)
DEND = pd.Timestamp(STUDY_END)

geo = load_pdf("ref_geography")
prov = load_pdf("sim_provider")

# COMMAND ----------

# MAGIC %md ## Demographics

# COMMAND ----------

ptid = np.array([f"PT{300000000 + i}" for i in range(N)])

adult = rng.random(N) >= 0.03                       # 3% adolescents -> removed by the age rule later
age_2018 = np.where(adult, np.clip(rng.normal(50, 15, N), 18, 88), rng.integers(12, 18, N)).round().astype(int)
birth_yr = 2018 - age_2018

sex = rng.choice(["F", "M"], N, p=[0.58, 0.42])
race = rng.choice(["Caucasian", "African American", "Asian", "Other/Unknown"], N, p=[0.66, 0.15, 0.05, 0.14])
ethnicity = rng.choice(["Not Hispanic", "Hispanic", "Unknown"], N, p=[0.70, 0.16, 0.14])

region_p = {"South": 0.38, "West": 0.24, "Midwest": 0.21, "Northeast": 0.17}
region = rng.choice(list(region_p), N, p=list(region_p.values()))
state = np.empty(N, dtype=object)
for r in region_p:
    m = region == r
    state[m] = rng.choice(geo.loc[geo["region"] == r, "state"].to_numpy(), m.sum())
division = pd.Series(state).map(geo.set_index("state")["division"]).to_numpy()

# Primary care provider from the same region
pcp = np.empty(N, dtype=object)
pc_specs = ["Family Medicine", "Internal Medicine", "Nurse Practitioner"]
for r in region_p:
    m = region == r
    pool = prov.loc[(prov["region"] == r) & prov["specialty"].isin(pc_specs), "provid"].to_numpy()
    pcp[m] = rng.choice(pool, m.sum())

# COMMAND ----------

# MAGIC %md ## Clinical profile (hidden truth)

# COMMAND ----------

bmi_class = rng.choice(["OW", "C1", "C2", "C3"], N, p=[0.15, 0.38, 0.26, 0.21])
bmi0 = np.select(
    [bmi_class == "OW", bmi_class == "C1", bmi_class == "C2"],
    [rng.uniform(27, 30, N), rng.uniform(30, 35, N), rng.uniform(35, 40, N)],
    default=np.minimum(40 + rng.gamma(2.0, 3.5, N), 70),
).round(1)
height_cm = np.where(sex == "F", rng.normal(162.5, 7, N), rng.normal(176.5, 7.5, N)).round(1)

age50 = age_2018 >= 50
age60 = age_2018 >= 60
age65 = age_2018 >= 65
c2plus = np.isin(bmi_class, ["C2", "C3"])
c3 = bmi_class == "C3"

t1d = rng.random(N) < 0.008
t2d = (~t1d) & (rng.random(N) < 0.22 + 0.08 * c2plus + 0.12 * age50)
htn = rng.random(N) < 0.30 + 0.25 * age50 + 0.08 * c3
dyslip = rng.random(N) < 0.30 + 0.20 * age50
osa = rng.random(N) < 0.07 + 0.08 * (bmi_class == "C2") + 0.15 * c3
ascvd = rng.random(N) < 0.03 + 0.10 * age60 + 0.03 * t2d
mash = rng.random(N) < 0.04 + 0.03 * t2d
ckd = rng.random(N) < 0.03 + 0.06 * t2d + 0.05 * age65

# COMMAND ----------

# MAGIC %md ## Insurance enrollment spans

# COMMAND ----------

def month_start(ts):
    return ts.to_period("M").to_timestamp()


def month_end(ts):
    return ts.to_period("M").to_timestamp(how="end").normalize()


ehr_only = rng.random(N) < 0.05                    # EHR patients with no linked claims enrollment
start_offset = (rng.beta(1.2, 2.0, N) * 3100).astype(int)
enroll_start = pd.to_datetime(D0 + pd.to_timedelta(start_offset, unit="D"))
enroll_dur = (180 + rng.exponential(1500, N)).astype(int)
enroll_end = pd.to_datetime(np.minimum((enroll_start + pd.to_timedelta(enroll_dur, unit="D")).values, DEND.to_datetime64()))
enroll_start = enroll_start.map(month_start)
enroll_end = pd.DatetimeIndex(enroll_end).map(month_end)

pharmacy_cov = np.where(rng.random(N) < 0.92, "Y", "N")

# Deaths (2.5%)
dies = rng.random(N) < 0.025
death_date = pd.Series(pd.NaT, index=range(N))
lo = enroll_start + pd.Timedelta(days=200)
span_days = np.maximum((DEND - lo).days, 30)
death_draw = lo + pd.to_timedelta((rng.random(N) * span_days).astype(int), unit="D")
death_date[dies] = death_draw[dies]
death_date = pd.to_datetime(death_date)
# claims enrollment usually stops at death (80%); 20% keep a stale end date (a real data issue)
stop_at_death = dies & (rng.random(N) < 0.80) & (death_date.values < enroll_end.values)
enroll_end = pd.DatetimeIndex(np.where(stop_at_death, pd.DatetimeIndex(death_date).map(lambda d: month_end(d) if pd.notna(d) else d), enroll_end))

product_by_bus = {
    "COM": (["PPO", "HMO", "POS", "EPO"], [0.45, 0.30, 0.15, 0.10]),
    "MCR": (["MA-HMO", "MA-PPO"], [0.6, 0.4]),
    "MCD": (["HMO"], [1.0]),
}


def pick_bus(age):
    if age >= 65:
        return rng.choice(["MCR", "COM", "MCD"], p=[0.85, 0.12, 0.03])
    return rng.choice(["COM", "MCD", "MCR"], p=[0.72, 0.24, 0.04])


span_rows = []
for i in range(N):
    if ehr_only[i]:
        continue
    s, e = enroll_start[i], enroll_end[i]
    if e <= s:
        continue
    bus = pick_bus(s.year - birth_yr[i])
    segments = [(s, e, bus)]
    # aging into Medicare
    yr65 = birth_yr[i] + 65
    t65 = pd.Timestamp(year=yr65, month=1, day=1) if 1900 < yr65 < 2100 else None
    if bus == "COM" and t65 is not None and s < t65 < e and rng.random() < 0.70:
        segments = [(s, t65 - pd.Timedelta(days=1), "COM"), (t65, e, "MCR")]
    # coverage gap (18% of members): split one segment with a 60-240 day hole
    if rng.random() < 0.18:
        k = rng.integers(len(segments))
        a, b, bb = segments[k]
        if (b - a).days > 400:
            cut = a + pd.Timedelta(days=int(rng.integers(120, (b - a).days - 200)))
            gap = int(rng.integers(60, 240))
            new = [(a, month_end(cut), bb), (month_start(cut + pd.Timedelta(days=gap)), b, bb)]
            segments = segments[:k] + [x for x in new if x[1] > x[0]] + segments[k + 1:]
    fam = f"F{rng.integers(10**7, 10**8)}"
    for a, b, bb in segments:
        prods, pp = product_by_bus[bb]
        span_rows.append({
            "PTID": ptid[i],
            "Pat_planid": f"{bb}{rng.integers(10**6, 10**7)}",
            "Aso": "Y" if (bb == "COM" and rng.random() < 0.55) else "N",
            "Bus": bb,
            "Cdhp": "Y" if (bb == "COM" and rng.random() < 0.25) else "N",
            "Eligeff": a,
            "Eligend": b,
            "Family_Id": fam,
            "Group_nbr": f"G{rng.integers(10**5, 10**6)}" if bb == "COM" else None,
            "Health_Exch": "Y" if (bb == "COM" and rng.random() < 0.06) else "N",
            "Medical_coverage_ind": "Y",
            "Pharmacy_coverage_ind": pharmacy_cov[i],
            "Product": rng.choice(prods, p=pp),
        })
enroll = pd.DataFrame(span_rows)
display(enroll.groupby("Bus").size())

# COMMAND ----------

# MAGIC %md ## EHR activity window, obesity onset, pregnancy

# COMMAND ----------

ehr_start = enroll_start - pd.to_timedelta(rng.integers(0, 365, N), unit="D")
ehr_start = pd.DatetimeIndex(np.maximum(ehr_start.values, D0.to_datetime64()))
ehr_end = enroll_end + pd.to_timedelta(rng.integers(0, 365, N), unit="D")
ehr_end = pd.DatetimeIndex(np.minimum(ehr_end.values, DEND.to_datetime64()))
dd = pd.DatetimeIndex(death_date)
ehr_end = pd.DatetimeIndex(np.where(dd.notna() & (dd < ehr_end), dd, ehr_end))

ehr_days = np.maximum((ehr_end - ehr_start).days.to_numpy(), 60)
first_obesity_date = ehr_start + pd.to_timedelta((30 + rng.beta(1.0, 1.6, N) * (ehr_days - 30)).astype(int), unit="D")
undercoded = rng.random(N) < 0.12   # obesity never coded as a diagnosis; only BMI readings show it

pregnant = (sex == "F") & (age_2018 < 43) & (rng.random(N) < 0.04)
preg_start = ehr_start + pd.to_timedelta((rng.random(N) * ehr_days).astype(int), unit="D")
preg_start = pd.DatetimeIndex(np.where(pregnant, preg_start, pd.NaT))

# COMMAND ----------

# MAGIC %md ## Save tables

# COMMAND ----------

truth = pd.DataFrame({
    "ptid": ptid, "birth_yr": birth_yr, "age_2018": age_2018, "sex": sex, "race": race,
    "ethnicity": ethnicity, "region": region, "division": division, "state": state, "pcp": pcp,
    "height_cm": height_cm, "bmi_class": bmi_class, "bmi0": bmi0,
    "t1d": t1d, "t2d": t2d, "htn": htn, "dyslip": dyslip, "osa": osa, "ascvd": ascvd, "mash": mash, "ckd": ckd,
    "ehr_only": ehr_only, "pharmacy_cov": pharmacy_cov,
    "enroll_start": enroll_start, "enroll_end": enroll_end,
    "ehr_start": ehr_start, "ehr_end": ehr_end,
    "first_obesity_date": first_obesity_date, "undercoded": undercoded,
    "pregnant": pregnant, "preg_start": preg_start, "death_date": death_date,
})
save_pdf(truth, "sim_patient_truth")

sources = [f"S{n:03d}" for n in range(1, 41)]
patient = pd.DataFrame({
    "PtId": ptid,
    "Birth_yr": birth_yr,
    "Gender": sex,
    "Race": race,
    "Ethnicity": ethnicity,
    "Region": region,
    "Division": division,
    "Deceased_indicator": np.where(death_date.notna(), "1", "0"),
    "Date_of_death": pd.DatetimeIndex(death_date).strftime("%Y%m").where(death_date.notna(), None),
    "Provid_pcp": pcp,
    "IDN_indicator": np.where(rng.random(N) < 0.6, "Y", "N"),
    "First_month_active": ehr_start.strftime("%Y%m"),
    "Last_month_active": ehr_end.strftime("%Y%m"),
    "Notes_eligible": np.where(rng.random(N) < 0.7, "Y", "N"),
    "Has_notes": np.where(rng.random(N) < 0.65, "Y", "N"),
    "SourceId": rng.choice(sources, N),
    "Source_data_through": "202512",
    "Integrated": "Y",
    "Market_clarity": np.where(ehr_only, "N", "Y"),
    "Eligibility": np.where(ehr_only, "EHR only", "Claims + EHR"),
})
save_pdf(patient, "sim_patient")
save_pdf(enroll, "sim_member_enrollment")

display(truth[["t2d", "htn", "dyslip", "osa", "ascvd", "mash", "ckd", "t1d"]].mean().round(3))
