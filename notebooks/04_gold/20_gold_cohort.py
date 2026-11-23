# Databricks notebook source
# MAGIC %md
# MAGIC # 20 · Gold: Study Cohort (Adults with Obesity or Overweight + Comorbidity)
# MAGIC
# MAGIC **Business question:** *Who are the patients eligible for anti-obesity treatment, and what do they look like?*
# MAGIC
# MAGIC **Cohort definition**
# MAGIC
# MAGIC | Step | Rule |
# MAGIC |---|---|
# MAGIC | 1 | Evidence of obesity (obesity ICD-10 code, BMI Z-code ≥ 30, or measured BMI ≥ 30) **or** overweight (E66.3, BMI Z-code 27–29.9, or measured BMI 27–29.9) **with** a weight-related comorbidity in the prior 365 days, between 2018-01-01 and 2025-12-31. The first such date is the **index date**. This mirrors the label eligibility for the newer weight-management drugs (BMI ≥ 30, or ≥ 27 with a weight-related condition). |
# MAGIC | 2 | Age ≥ 18 at index |
# MAGIC | 3 | Linked claims and continuous medical + pharmacy coverage 180 days before and 180 days after index |
# MAGIC | 4 | No type 1 diabetes diagnosis |
# MAGIC | 5 | Not pregnant around index (Z33.1 within ±180 days) |
# MAGIC | 6 | No bariatric surgery before index |
# MAGIC | 7 | **New users only:** no GLP-1 / anti-obesity fill in the 180-day baseline |
# MAGIC
# MAGIC **Outputs:** `gold_cohort_attrition`, `gold_patient_cohort` (one row per cohort patient)

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

# MAGIC %md ## Step 1: qualifying evidence and index date

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW ev_obese AS
SELECT ptid, dx_date AS ev_date,
       CASE WHEN category = 'OBESITY' THEN 'Obesity diagnosis code' ELSE 'BMI Z-code >= 30' END AS ev_src
FROM silver_diagnosis
WHERE dx_status = 'Diagnosis of' AND (category = 'OBESITY' OR (category = 'BMI' AND bmi_low >= 30))
UNION ALL
SELECT ptid, obs_date, 'Measured BMI >= 30' FROM silver_vitals WHERE bmi >= 30
""")

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW ev_overweight AS
SELECT ptid, dx_date AS ev_date FROM silver_diagnosis
WHERE dx_status = 'Diagnosis of' AND (category = 'OVERWEIGHT' OR (category = 'BMI' AND bmi_low >= 27 AND bmi_low < 30))
UNION ALL
SELECT ptid, obs_date FROM silver_vitals WHERE bmi >= 27 AND bmi < 30
""")

spark.sql("""
CREATE OR REPLACE TEMP VIEW comorb AS
SELECT DISTINCT ptid, dx_date, category FROM silver_diagnosis
WHERE dx_status IN ('Diagnosis of', 'History of')
  AND category IN ('T2D', 'HTN', 'DYSLIPIDEMIA', 'OSA', 'ASCVD', 'MASH', 'CKD')
""")

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW index_dates AS
WITH q1 AS (
  SELECT ptid, MIN(ev_date) AS d, min_by(ev_src, ev_date) AS src
  FROM ev_obese WHERE ev_date BETWEEN DATE'{STUDY_START}' AND DATE'{STUDY_END}' GROUP BY ptid),
q2 AS (
  SELECT o.ptid, MIN(o.ev_date) AS d
  FROM ev_overweight o
  JOIN comorb c ON o.ptid = c.ptid AND c.dx_date BETWEEN date_sub(o.ev_date, 365) AND o.ev_date
  WHERE o.ev_date BETWEEN DATE'{STUDY_START}' AND DATE'{STUDY_END}'
  GROUP BY o.ptid)
SELECT COALESCE(q1.ptid, q2.ptid) AS ptid,
       CASE WHEN q2.d IS NULL OR (q1.d IS NOT NULL AND q1.d <= q2.d) THEN q1.d ELSE q2.d END AS index_date,
       CASE WHEN q2.d IS NULL OR (q1.d IS NOT NULL AND q1.d <= q2.d) THEN q1.src
            ELSE 'Overweight + comorbidity' END AS index_source
FROM q1 FULL OUTER JOIN q2 ON q1.ptid = q2.ptid
""")

# COMMAND ----------

# MAGIC %md ## Steps 2–7: inclusion / exclusion flags

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE work_cohort_flags AS
WITH base AS (
  SELECT p.*, i.index_date, i.index_source, year(i.index_date) - p.birth_yr AS age_at_index
  FROM silver_patient p JOIN index_dates i ON p.ptid = i.ptid),
cov AS (
  SELECT b.ptid, MAX(c.cov_end) AS cov_end
  FROM base b JOIN silver_enrollment_continuous c
    ON b.ptid = c.ptid AND c.cov_start <= date_sub(b.index_date, {BASELINE_DAYS})
                        AND c.cov_end >= date_add(b.index_date, {MIN_FOLLOWUP_DAYS})
  GROUP BY b.ptid),
t1d AS (SELECT DISTINCT ptid FROM silver_diagnosis WHERE category = 'T1D' AND dx_status = 'Diagnosis of'),
preg AS (
  SELECT DISTINCT b.ptid FROM base b JOIN silver_diagnosis d
    ON b.ptid = d.ptid AND d.category = 'PREGNANCY' AND d.dx_date BETWEEN date_sub(b.index_date, 180) AND date_add(b.index_date, 180)),
prior_surg AS (
  SELECT DISTINCT b.ptid FROM base b JOIN silver_bariatric_surgery s ON b.ptid = s.ptid AND s.surgery_date < b.index_date),
prior_rx AS (
  SELECT DISTINCT b.ptid FROM base b JOIN silver_rx_fills f
    ON b.ptid = f.ptid AND f.fill_date >= date_sub(b.index_date, {BASELINE_DAYS}) AND f.fill_date < b.index_date)
SELECT b.*,
       cov.cov_end,
       (b.age_at_index >= 18) AS f_adult,
       (b.has_claims AND cov.cov_end IS NOT NULL) AS f_enrolled,
       (t1d.ptid IS NULL) AS f_no_t1d,
       (preg.ptid IS NULL) AS f_not_pregnant,
       (prior_surg.ptid IS NULL) AS f_no_prior_surgery,
       (prior_rx.ptid IS NULL) AS f_new_user
FROM base b
LEFT JOIN cov ON b.ptid = cov.ptid
LEFT JOIN t1d ON b.ptid = t1d.ptid
LEFT JOIN preg ON b.ptid = preg.ptid
LEFT JOIN prior_surg ON b.ptid = prior_surg.ptid
LEFT JOIN prior_rx ON b.ptid = prior_rx.ptid
""")

# COMMAND ----------

# MAGIC %md ## Attrition table

# COMMAND ----------

steps = [
    ("0", "All patients in the data", None),
    ("1", "Obesity, or overweight + comorbidity, 2018-2025 (index date)", "TRUE"),
    ("2", "Age 18+ at index", "f_adult"),
    ("3", "Continuous medical + pharmacy coverage 180 days before and after index", "f_enrolled"),
    ("4", "No type 1 diabetes", "f_no_t1d"),
    ("5", "Not pregnant around index", "f_not_pregnant"),
    ("6", "No bariatric surgery before index", "f_no_prior_surgery"),
    ("7", "New users: no GLP-1 / anti-obesity fill in 180-day baseline", "f_new_user"),
]
rows, cond = [], "TRUE"
prev = spark.table("silver_patient").count()
for k, label, flag in steps:
    if flag is None:
        n = prev
    else:
        cond = f"{cond} AND {flag}"
        n = spark.sql(f"SELECT COUNT(*) AS n FROM work_cohort_flags WHERE {cond}").first()["n"]
    rows.append({"step": int(k), "step_label": label, "patients": int(n), "removed": int(prev - n) if flag else 0})
    prev = n
attrition = pd.DataFrame(rows)
attrition["pct_of_start"] = (attrition["patients"] / attrition["patients"].iloc[0] * 100).round(1)
save_pdf(attrition, "gold_cohort_attrition")
display(attrition)

final_cond = cond

# COMMAND ----------

# MAGIC %md ## Patient-level analytic table

# COMMAND ----------

gold = spark.sql(f"""
WITH c AS (
  SELECT *, LEAST(cov_end, COALESCE(death_date, DATE'{STUDY_END}'), DATE'{STUDY_END}') AS followup_end
  FROM work_cohort_flags WHERE {final_cond}),
payer AS (
  SELECT c.ptid, max_by(s.bus, s.eligeff) AS payer_at_index, max_by(s.plan_product, s.eligeff) AS plan_product
  FROM c JOIN silver_enrollment_spans s ON c.ptid = s.ptid AND c.index_date BETWEEN s.eligeff AND s.eligend
  GROUP BY c.ptid),
bmi AS (
  SELECT c.ptid, min_by(v.bmi, abs(datediff(v.obs_date, c.index_date))) AS baseline_bmi,
         min_by(v.weight_kg, abs(datediff(v.obs_date, c.index_date))) AS baseline_weight_kg
  FROM c JOIN silver_vitals v ON c.ptid = v.ptid
   AND v.obs_date BETWEEN date_sub(c.index_date, 180) AND date_add(c.index_date, 30) AND v.bmi IS NOT NULL
  GROUP BY c.ptid),
cm AS (
  SELECT c.ptid,
         MAX(CASE WHEN m.category = 'T2D' THEN 1 ELSE 0 END) AS has_t2d,
         MAX(CASE WHEN m.category = 'HTN' THEN 1 ELSE 0 END) AS has_hypertension,
         MAX(CASE WHEN m.category = 'DYSLIPIDEMIA' THEN 1 ELSE 0 END) AS has_dyslipidemia,
         MAX(CASE WHEN m.category = 'OSA' THEN 1 ELSE 0 END) AS has_sleep_apnea,
         MAX(CASE WHEN m.category = 'ASCVD' THEN 1 ELSE 0 END) AS has_ascvd,
         MAX(CASE WHEN m.category = 'MASH' THEN 1 ELSE 0 END) AS has_mash,
         MAX(CASE WHEN m.category = 'CKD' THEN 1 ELSE 0 END) AS has_ckd
  FROM c JOIN comorb m ON c.ptid = m.ptid AND m.dx_date BETWEEN date_sub(c.index_date, 365) AND date_add(c.index_date, 30)
  GROUP BY c.ptid),
tx AS (
  SELECT c.ptid, MIN(f.fill_date) AS first_fill_date,
         min_by(f.product_key, f.fill_date) AS first_product_key, min_by(f.brand_name, f.fill_date) AS first_brand,
         min_by(f.molecule, f.fill_date) AS first_molecule, min_by(f.drug_class, f.fill_date) AS first_drug_class,
         min_by(f.indication_group, f.fill_date) AS first_indication_group,
         COUNT(DISTINCT f.product_key) AS n_products_used, COUNT(*) AS n_fills
  FROM c JOIN silver_rx_fills f ON c.ptid = f.ptid AND f.fill_date BETWEEN c.index_date AND c.followup_end
  GROUP BY c.ptid),
surg AS (
  SELECT c.ptid, MIN(s.surgery_date) AS surgery_date
  FROM c JOIN silver_bariatric_surgery s ON c.ptid = s.ptid AND s.surgery_date BETWEEN c.index_date AND c.followup_end
  GROUP BY c.ptid)
SELECT c.ptid, c.index_date, year(c.index_date) AS index_year, c.index_source, c.followup_end,
       datediff(c.followup_end, c.index_date) AS followup_days,
       c.age_at_index,
       CASE WHEN c.age_at_index < 35 THEN '18-34' WHEN c.age_at_index < 50 THEN '35-49'
            WHEN c.age_at_index < 65 THEN '50-64' WHEN c.age_at_index < 75 THEN '65-74' ELSE '75+' END AS age_group,
       c.gender, c.race, c.ethnicity, c.region, c.division,
       COALESCE(payer.payer_at_index, 'UNK') AS payer_code,
       CASE payer.payer_at_index WHEN 'COM' THEN 'Commercial' WHEN 'MCR' THEN 'Medicare' WHEN 'MCD' THEN 'Medicaid'
            ELSE 'Unknown' END AS payer_at_index,
       payer.plan_product,
       ROUND(bmi.baseline_bmi, 1) AS baseline_bmi, ROUND(bmi.baseline_weight_kg, 1) AS baseline_weight_kg,
       CASE WHEN bmi.baseline_bmi IS NULL THEN 'No BMI recorded' WHEN bmi.baseline_bmi < 30 THEN 'Overweight (27-29.9)'
            WHEN bmi.baseline_bmi < 35 THEN 'Class 1 (30-34.9)' WHEN bmi.baseline_bmi < 40 THEN 'Class 2 (35-39.9)'
            ELSE 'Class 3 (40+)' END AS bmi_category,
       COALESCE(cm.has_t2d, 0) AS has_t2d, COALESCE(cm.has_hypertension, 0) AS has_hypertension,
       COALESCE(cm.has_dyslipidemia, 0) AS has_dyslipidemia, COALESCE(cm.has_sleep_apnea, 0) AS has_sleep_apnea,
       COALESCE(cm.has_ascvd, 0) AS has_ascvd, COALESCE(cm.has_mash, 0) AS has_mash, COALESCE(cm.has_ckd, 0) AS has_ckd,
       COALESCE(cm.has_t2d + cm.has_hypertension + cm.has_dyslipidemia + cm.has_sleep_apnea + cm.has_ascvd
                + cm.has_mash + cm.has_ckd, 0) AS n_comorbidities,
       CASE WHEN COALESCE(cm.has_t2d, 0) = 1 THEN 'Type 2 diabetes' ELSE 'No type 2 diabetes' END AS diabetes_status,
       (tx.ptid IS NOT NULL) AS treated,
       tx.first_fill_date, datediff(tx.first_fill_date, c.index_date) AS days_to_treatment,
       tx.first_product_key, tx.first_brand, tx.first_molecule, tx.first_drug_class, tx.first_indication_group,
       COALESCE(tx.n_products_used, 0) AS n_products_used, COALESCE(tx.n_fills, 0) AS n_fills,
       (datediff(c.followup_end, c.index_date) >= 365) AS has_12m_followup,
       (tx.first_fill_date IS NOT NULL AND datediff(tx.first_fill_date, c.index_date) <= 365) AS treated_within_12m,
       (surg.ptid IS NOT NULL) AS bariatric_surgery_after_index, surg.surgery_date,
       (c.death_date IS NOT NULL AND c.death_date <= c.followup_end) AS died_in_followup
FROM c
LEFT JOIN payer ON c.ptid = payer.ptid
LEFT JOIN bmi ON c.ptid = bmi.ptid
LEFT JOIN cm ON c.ptid = cm.ptid
LEFT JOIN tx ON c.ptid = tx.ptid
LEFT JOIN surg ON c.ptid = surg.ptid
""")
save_sdf(gold, "gold_patient_cohort")
display(spark.sql("""SELECT payer_at_index, diabetes_status, COUNT(*) AS patients, ROUND(AVG(CAST(treated AS INT)) * 100, 1) AS pct_treated
                     FROM gold_patient_cohort GROUP BY 1, 2 ORDER BY 1, 2"""))
