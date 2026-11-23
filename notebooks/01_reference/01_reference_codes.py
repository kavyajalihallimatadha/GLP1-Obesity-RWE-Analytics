# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Reference Code Lists
# MAGIC
# MAGIC Builds the code lists the whole project depends on. Every code here was checked against a public
# MAGIC source (FDA labels / DailyMed, CDC, AMA CPT references, LOINC). Sources are listed in
# MAGIC `docs/verified_reference.md`.
# MAGIC
# MAGIC | Table | What it holds |
# MAGIC |---|---|
# MAGIC | `ref_product` | One row per drug product (brand/generic, molecule, class, approval/availability dates) |
# MAGIC | `ref_ndc` | NDC codes by product and dose step (10-digit labeled + 11-digit billing format) |
# MAGIC | `ref_icd10` | Diagnosis codes used for cohort building and comorbidities |
# MAGIC | `ref_procedure` | CPT codes (bariatric surgery, office visits) |
# MAGIC | `ref_loinc` | Lab / vital-sign codes |
# MAGIC | `ref_geography` | Census region → division → state |
# MAGIC | `ref_market_events` | Drug shortages and coverage changes used to shape the simulation |
# MAGIC | `ref_specialty` | Provider specialties with NUCC taxonomy codes |

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

# MAGIC %md ## Products

# COMMAND ----------

# avail_date = first date a fill can appear in the simulation (approval month + ~1 month;
# exact day used where the source gives it). Products approved before 2018 only need the
# year to be right, because the study window starts in 2018.
ref_product = pd.DataFrame([
    # product_key, brand, generic, manufacturer, molecule, drug_class, route, indication, approval_date, avail_date, is_generic, days_supply
    ("VICTOZA",   "Victoza",   "liraglutide",             "Novo Nordisk", "liraglutide",  "GLP-1 RA",       "SC",   "T2D",     "2010-01-25", "2010-01-25", "N", 30),
    ("SAXENDA",   "Saxenda",   "liraglutide",             "Novo Nordisk", "liraglutide",  "GLP-1 RA",       "SC",   "Obesity", "2014-12-01", "2014-12-31", "N", 30),
    ("TRULICITY", "Trulicity", "dulaglutide",             "Eli Lilly",    "dulaglutide",  "GLP-1 RA",       "SC",   "T2D",     "2014-09-01", "2014-10-01", "N", 28),
    ("OZEMPIC",   "Ozempic",   "semaglutide",             "Novo Nordisk", "semaglutide",  "GLP-1 RA",       "SC",   "T2D",     "2017-12-05", "2018-01-05", "N", 28),
    ("RYBELSUS",  "Rybelsus",  "semaglutide",             "Novo Nordisk", "semaglutide",  "GLP-1 RA",       "Oral", "T2D",     "2019-09-01", "2019-10-01", "N", 30),
    ("WEGOVY",    "Wegovy",    "semaglutide",             "Novo Nordisk", "semaglutide",  "GLP-1 RA",       "SC",   "Obesity", "2021-06-04", "2021-06-05", "N", 28),
    ("MOUNJARO",  "Mounjaro",  "tirzepatide",             "Eli Lilly",    "tirzepatide",  "GIP/GLP-1 RA",   "SC",   "T2D",     "2022-05-01", "2022-06-01", "N", 28),
    ("ZEPBOUND",  "Zepbound",  "tirzepatide",             "Eli Lilly",    "tirzepatide",  "GIP/GLP-1 RA",   "SC",   "Obesity", "2023-11-01", "2023-12-01", "N", 28),
    ("LIRA_GEN_T2D", "Liraglutide (generic Victoza)", "liraglutide", "Teva / Hikma", "liraglutide", "GLP-1 RA", "SC", "T2D",   "2024-06-25", "2024-06-25", "Y", 30),
    ("LIRA_GEN_WM",  "Liraglutide (generic Saxenda)", "liraglutide", "Teva",         "liraglutide", "GLP-1 RA", "SC", "Obesity", "2025-08-01", "2025-09-01", "Y", 30),
    ("QSYMIA",    "Qsymia",    "phentermine/topiramate ER", "Vivus",      "phentermine/topiramate", "Non-GLP-1 AOM", "Oral", "Obesity", "2012-07-01", "2012-09-01", "N", 30),
    ("CONTRAVE",  "Contrave",  "naltrexone/bupropion ER",   "Nalpropion", "naltrexone/bupropion",   "Non-GLP-1 AOM", "Oral", "Obesity", "2014-09-01", "2014-10-01", "N", 30),
], columns=["product_key", "brand_name", "generic_name", "manufacturer", "molecule", "drug_class",
            "route", "indication_group", "approval_date", "avail_date", "is_generic", "days_supply"])
for c in ["approval_date", "avail_date"]:
    ref_product[c] = pd.to_datetime(ref_product[c])
save_pdf(ref_product, "ref_product")
display(ref_product)

# COMMAND ----------

# MAGIC %md ## NDC codes (dose step = position in the label's dose-escalation schedule)

# COMMAND ----------

ndc_rows = [
    # product_key, dose_step, strength, labeled_ndc (as on FDA label), package_qty, qty_unit
    ("WEGOVY", 1, "0.25 mg/0.5 mL", "0169-4525-14", 4, "pen"),
    ("WEGOVY", 2, "0.5 mg/0.5 mL",  "0169-4505-14", 4, "pen"),
    ("WEGOVY", 3, "1 mg/0.5 mL",    "0169-4501-14", 4, "pen"),
    ("WEGOVY", 4, "1.7 mg/0.75 mL", "0169-4517-14", 4, "pen"),
    ("WEGOVY", 5, "2.4 mg/0.75 mL", "0169-4524-14", 4, "pen"),
    ("ZEPBOUND", 1, "2.5 mg/0.5 mL",  "0002-2506-80", 4, "pen"),
    ("ZEPBOUND", 2, "5 mg/0.5 mL",    "0002-2495-80", 4, "pen"),
    ("ZEPBOUND", 3, "7.5 mg/0.5 mL",  "0002-2484-80", 4, "pen"),
    ("ZEPBOUND", 4, "10 mg/0.5 mL",   "0002-2471-80", 4, "pen"),
    ("ZEPBOUND", 5, "12.5 mg/0.5 mL", "0002-2460-80", 4, "pen"),
    ("ZEPBOUND", 6, "15 mg/0.5 mL",   "0002-2457-80", 4, "pen"),
    ("MOUNJARO", 1, "2.5 mg/0.5 mL",  "0002-1506-80", 4, "pen"),
    ("MOUNJARO", 2, "5 mg/0.5 mL",    "0002-1495-80", 4, "pen"),
    ("MOUNJARO", 3, "7.5 mg/0.5 mL",  "0002-1484-80", 4, "pen"),
    ("MOUNJARO", 4, "10 mg/0.5 mL",   "0002-1471-80", 4, "pen"),
    ("MOUNJARO", 5, "12.5 mg/0.5 mL", "0002-1460-80", 4, "pen"),
    ("MOUNJARO", 6, "15 mg/0.5 mL",   "0002-1457-80", 4, "pen"),
    ("OZEMPIC", 1, "0.25/0.5 mg pen (2 mg/3 mL)", "0169-4181-13", 1, "pen"),
    ("OZEMPIC", 2, "1 mg pen (4 mg/3 mL)",        "0169-4130-13", 1, "pen"),
    ("OZEMPIC", 3, "2 mg pen (8 mg/3 mL)",        "0169-4772-12", 1, "pen"),
    ("RYBELSUS", 1, "3 mg tablet",  "0169-4303-30", 30, "tablet"),
    ("RYBELSUS", 2, "7 mg tablet",  "0169-4307-30", 30, "tablet"),
    ("RYBELSUS", 3, "14 mg tablet", "0169-4314-30", 30, "tablet"),
    ("TRULICITY", 1, "0.75 mg/0.5 mL", "0002-1433-80", 4, "pen"),
    ("TRULICITY", 2, "1.5 mg/0.5 mL",  "0002-1434-80", 4, "pen"),
    ("TRULICITY", 3, "3 mg/0.5 mL",    "0002-2236-80", 4, "pen"),
    ("TRULICITY", 4, "4.5 mg/0.5 mL",  "0002-3182-80", 4, "pen"),
    ("VICTOZA", 1, "18 mg/3 mL, 2-pen pack", "0169-4060-12", 2, "pen"),
    ("VICTOZA", 2, "18 mg/3 mL, 3-pen pack", "0169-4060-13", 3, "pen"),
    ("SAXENDA", 1, "18 mg/3 mL, 5-pen pack", "0169-2800-15", 5, "pen"),
    ("LIRA_GEN_T2D", 1, "18 mg/3 mL, 2-pen pack (authorized generic)", "00480-3667-20", 2, "pen"),
    ("LIRA_GEN_T2D", 2, "18 mg/3 mL, 3-pen pack",                      "0143-9144-03", 3, "pen"),
    ("LIRA_GEN_WM", 1, "18 mg/3 mL, 5-pen pack",                       "00480-7250-46", 5, "pen"),
    ("QSYMIA", 1, "7.5 mg/46 mg capsule", "62541-201-30", 30, "capsule"),
    ("CONTRAVE", 1, "8 mg/90 mg tablet",  "51267-890-99", 120, "tablet"),
]
ref_ndc = pd.DataFrame(ndc_rows, columns=["product_key", "dose_step", "strength", "ndc_labeled",
                                          "package_qty", "qty_unit"])


def to_ndc11(labeled: str) -> str:
    """Convert a labeled NDC (4-4-2, 5-3-2, 5-4-1 or already 5-4-2) to the 11-digit billing format."""
    a, b, c = labeled.split("-")
    return a.zfill(5) + b.zfill(4) + c.zfill(2)


ref_ndc["ndc11"] = ref_ndc["ndc_labeled"].map(to_ndc11)
ref_ndc["max_step"] = ref_ndc.groupby("product_key")["dose_step"].transform("max")
ref_ndc = ref_ndc.merge(ref_product[["product_key", "brand_name", "generic_name", "molecule", "drug_class"]],
                        on="product_key")
assert ref_ndc["ndc11"].str.len().eq(11).all()
assert ref_ndc["ndc11"].is_unique
save_pdf(ref_ndc, "ref_ndc")
display(ref_ndc)

# COMMAND ----------

# MAGIC %md ## ICD-10-CM diagnosis codes

# COMMAND ----------

icd_rows = [
    # code, description, category, valid_from, valid_to
    ("E66.01",  "Morbid (severe) obesity due to excess calories", "OBESITY", None, None),
    ("E66.09",  "Other obesity due to excess calories",            "OBESITY", None, None),
    ("E66.8",   "Other obesity",                                   "OBESITY", None, "2024-09-30"),
    ("E66.9",   "Obesity, unspecified",                            "OBESITY", None, None),
    ("E66.811", "Obesity, class 1",                                "OBESITY", "2024-10-01", None),
    ("E66.812", "Obesity, class 2",                                "OBESITY", "2024-10-01", None),
    ("E66.813", "Obesity, class 3",                                "OBESITY", "2024-10-01", None),
    ("E66.89",  "Other obesity not elsewhere classified",          "OBESITY", "2024-10-01", None),
    ("E66.3",   "Overweight",                                      "OVERWEIGHT", None, None),
    ("E11.9",   "Type 2 diabetes mellitus without complications",  "T2D", None, None),
    ("E11.65",  "Type 2 diabetes mellitus with hyperglycemia",     "T2D", None, None),
    ("E11.22",  "Type 2 diabetes mellitus with diabetic chronic kidney disease", "T2D", None, None),
    ("E10.9",   "Type 1 diabetes mellitus without complications",  "T1D", None, None),
    ("I10",     "Essential (primary) hypertension",                "HTN", None, None),
    ("E78.5",   "Hyperlipidemia, unspecified",                     "DYSLIPIDEMIA", None, None),
    ("G47.33",  "Obstructive sleep apnea (adult) (pediatric)",     "OSA", None, None),
    ("I25.10",  "Atherosclerotic heart disease of native coronary artery without angina pectoris", "ASCVD", None, None),
    ("K75.81",  "Nonalcoholic steatohepatitis (NASH)",             "MASH", None, None),
    ("N18.3",   "Chronic kidney disease, stage 3 (moderate)",      "CKD", None, "2020-09-30"),
    ("N18.30",  "Chronic kidney disease, stage 3 unspecified",     "CKD", "2020-10-01", None),
    ("Z33.1",   "Pregnant state, incidental",                      "PREGNANCY", None, None),
]
# Adult BMI Z-codes (BMI ranges in the code titles)
for v in range(25, 30):
    icd_rows.append((f"Z68.{v}", f"Body mass index [BMI] {v}.0-{v}.9, adult", "BMI", None, None))
for v in range(30, 40):
    icd_rows.append((f"Z68.{v}", f"Body mass index [BMI] {v}.0-{v}.9, adult", "BMI", None, None))
for code, lo, hi in [("Z68.41", 40, 44.9), ("Z68.42", 45, 49.9), ("Z68.43", 50, 59.9),
                     ("Z68.44", 60, 69.9), ("Z68.45", 70, None)]:
    title = f"Body mass index [BMI] {lo}.0-{hi}, adult" if hi else f"Body mass index [BMI] {lo} or greater, adult"
    icd_rows.append((code, title, "BMI", None, None))

ref_icd10 = pd.DataFrame(icd_rows, columns=["icd10_code", "description", "category", "valid_from", "valid_to"])
ref_icd10["icd10_nodot"] = ref_icd10["icd10_code"].str.replace(".", "", regex=False)


def bmi_range(row):
    if row["category"] != "BMI":
        return pd.Series([np.nan, np.nan])
    n = row["icd10_code"]
    table = {"Z68.41": (40, 44.9), "Z68.42": (45, 49.9), "Z68.43": (50, 59.9),
             "Z68.44": (60, 69.9), "Z68.45": (70, 99)}
    if n in table:
        return pd.Series(table[n])
    v = int(n.split(".")[1])
    return pd.Series([v, v + 0.9])


ref_icd10[["bmi_low", "bmi_high"]] = ref_icd10.apply(bmi_range, axis=1)
for c in ["valid_from", "valid_to"]:
    ref_icd10[c] = pd.to_datetime(ref_icd10[c])
save_pdf(ref_icd10, "ref_icd10")

# COMMAND ----------

# MAGIC %md ## Procedures (CPT) and labs (LOINC)

# COMMAND ----------

ref_procedure = pd.DataFrame([
    ("43775", "Laparoscopic sleeve gastrectomy", "BARIATRIC"),
    ("43644", "Laparoscopic gastric bypass with Roux-en-Y gastroenterostomy (limb 150 cm or less)", "BARIATRIC"),
    ("99203", "Office visit, new patient (low complexity)", "EM_OFFICE"),
    ("99213", "Office visit, established patient (low complexity)", "EM_OFFICE"),
    ("99214", "Office visit, established patient (moderate complexity)", "EM_OFFICE"),
    ("99284", "Emergency department visit (high severity)", "EM_ED"),
    ("99223", "Initial hospital inpatient care (high complexity)", "EM_INPATIENT"),
], columns=["proc_code", "description", "category"])
save_pdf(ref_procedure, "ref_procedure")

ref_loinc = pd.DataFrame([
    ("4548-4",  "Hemoglobin A1c/Hemoglobin.total in Blood (NGSP)", "HBA1C", "%"),
    ("59261-8", "Hemoglobin A1c/Hemoglobin.total in Blood (IFCC)", "HBA1C", "mmol/mol"),
    ("39156-5", "Body mass index (BMI) [Ratio]", "BMI", "kg/m2"),
    ("29463-7", "Body weight", "WEIGHT", "kg"),
], columns=["loinc", "description", "measure", "standard_unit"])
save_pdf(ref_loinc, "ref_loinc")

# COMMAND ----------

# MAGIC %md ## Geography (US Census regions and divisions)

# COMMAND ----------

divisions = {
    "Northeast": {"New England": ["CT", "ME", "MA", "NH", "RI", "VT"],
                  "Middle Atlantic": ["NJ", "NY", "PA"]},
    "Midwest": {"East North Central": ["IL", "IN", "MI", "OH", "WI"],
                "West North Central": ["IA", "KS", "MN", "MO", "NE", "ND", "SD"]},
    "South": {"South Atlantic": ["DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV"],
              "East South Central": ["AL", "KY", "MS", "TN"],
              "West South Central": ["AR", "LA", "OK", "TX"]},
    "West": {"Mountain": ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY"],
             "Pacific": ["AK", "CA", "HI", "OR", "WA"]},
}
ref_geography = pd.DataFrame([(r, d, s) for r, ds in divisions.items() for d, ss in ds.items() for s in ss],
                             columns=["region", "division", "state"])
save_pdf(ref_geography, "ref_geography")

# COMMAND ----------

# MAGIC %md ## Market events (verified dates) and provider specialties

# COMMAND ----------

ref_market_events = pd.DataFrame([
    ("SHORTAGE", "WEGOVY",   "Wegovy injection shortage",        "2022-03-01", "2025-02-21"),
    ("SHORTAGE", "OZEMPIC",  "Ozempic injection shortage",       "2022-08-01", "2025-02-21"),
    ("SHORTAGE", "MOUNJARO", "Tirzepatide injection shortage",   "2022-12-15", "2024-10-02"),
    ("SHORTAGE", "ZEPBOUND", "Tirzepatide injection shortage",   "2023-12-01", "2024-10-02"),
    ("COVERAGE", "WEGOVY",   "Medicare Part D may cover Wegovy for CV-risk indication only", "2024-03-08", None),
    ("CODING",   None,       "New ICD-10-CM obesity class codes (E66.811-E66.813)",          "2024-10-01", None),
    ("GENERIC",  "LIRA_GEN_T2D", "First generic GLP-1 (liraglutide, Victoza reference) launched", "2024-06-25", None),
    ("GENERIC",  "LIRA_GEN_WM",  "First generic of Saxenda approved",                           "2025-08-01", None),
], columns=["event_type", "product_key", "description", "start_date", "end_date"])
for c in ["start_date", "end_date"]:
    ref_market_events[c] = pd.to_datetime(ref_market_events[c])
save_pdf(ref_market_events, "ref_market_events")

ref_specialty = pd.DataFrame([
    ("Family Medicine",      "207Q00000X", 0.34),
    ("Internal Medicine",    "207R00000X", 0.30),
    ("Endocrinology",        "207RE0101X", 0.08),
    ("Cardiology",           "207RC0000X", 0.07),
    ("Nurse Practitioner",   "363L00000X", 0.13),
    ("Gastroenterology",     "207RG0100X", 0.04),
    ("Surgery",              "208600000X", 0.04),
], columns=["specialty", "taxonomy", "share"])
save_pdf(ref_specialty, "ref_specialty")
