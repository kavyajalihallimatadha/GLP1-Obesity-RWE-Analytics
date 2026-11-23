# Databricks notebook source
# MAGIC %md
# MAGIC # 10 · Silver: Patients, Providers and Insurance Enrollment
# MAGIC
# MAGIC Cleans the raw patient, provider and enrollment tables. Every rule writes a row to `dq_log`
# MAGIC (rule, rows affected, action) so the data-quality dashboard can show exactly what was fixed.
# MAGIC
# MAGIC | Output | Grain | Main fixes |
# MAGIC |---|---|---|
# MAGIC | `silver_patient` | 1 row per patient | duplicates, gender/race/region standardization, invalid birth years, death date from YYYYMM |
# MAGIC | `silver_provider` / `silver_claims_provider` | 1 row per provider | specialty standardization |
# MAGIC | `silver_enrollment_spans` | 1 row per coverage span | date parsing (3 formats), swapped dates, payer code case, overlap removal |
# MAGIC | `silver_enrollment_continuous` | 1 row per continuous medical + pharmacy coverage period | gaps ≤ 31 days bridged |
# MAGIC | `silver_insurance_ehr` | 1 row per encounter-level payer record | date parsing |

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

from pyspark.sql import Window

NB = "10_silver_patient_enrollment"

# COMMAND ----------

# MAGIC %md ## Patients

# COMMAND ----------

raw = spark.table(tbl("bronze_patient"))
n_raw = raw.count()
p = raw.dropDuplicates()
log_dq("silver_patient", "exact duplicate rows", n_raw - p.count(), "removed")

g = F.upper(F.trim(F.col("Gender")))
log_dq("silver_patient", "Gender not coded as F/M", p.filter(~F.coalesce(F.col("Gender"), F.lit("")).isin("F", "M")).count(),
       "standardized (Female/f -> F, Male/m -> M, other -> U)")
p = p.withColumn("gender", F.when(g.isin("F", "FEMALE"), "F").when(g.isin("M", "MALE"), "M").otherwise("U"))

r = F.upper(F.trim(F.col("Race")))
std_race = ["Caucasian", "African American", "Asian", "Other/Unknown"]
log_dq("silver_patient", "Race not in standard list", p.filter(~F.col("Race").isin(std_race)).count(),
       "mapped (White -> Caucasian, Black / African-American -> African American, Unknown/Other -> Other/Unknown)")
p = p.withColumn("race", F.when(r.isin("CAUCASIAN", "WHITE"), "Caucasian")
                          .when(r.isin("AFRICAN AMERICAN", "AFRICAN-AMERICAN", "BLACK"), "African American")
                          .when(r == "ASIAN", "Asian").otherwise("Other/Unknown"))

eth = F.upper(F.trim(F.col("Ethnicity")))
p = p.withColumn("ethnicity", F.when(eth == "HISPANIC", "Hispanic").when(eth == "NOT HISPANIC", "Not Hispanic")
                               .otherwise("Unknown"))

reg = F.upper(F.regexp_replace(F.col("Region"), r"\s", ""))
log_dq("silver_patient", "Region not in standard list",
       p.filter(~F.col("Region").isin("Northeast", "Midwest", "South", "West")).count(), "standardized")
p = p.withColumn("region", F.when(reg == "NORTHEAST", "Northeast").when(reg == "MIDWEST", "Midwest")
                            .when(reg == "SOUTH", "South").when(reg == "WEST", "West").otherwise("Unknown"))

by = F.expr("try_cast(trim(Birth_yr) as int)")
bad_by = p.filter(by.isNull() | (by < 1900) | (by > 2025)).count()
log_dq("silver_patient", "Birth_yr missing, non-numeric or outside 1900-2025", bad_by, "set to NULL (patient fails age rule)")
p = p.withColumn("birth_yr", F.when((by >= 1900) & (by <= 2025), by))

p = (p.withColumn("death_date", F.last_day(F.expr("try_to_date(concat(Date_of_death, '01'), 'yyyyMMdd')")))
      .withColumn("deceased", F.col("Deceased_indicator") == "1")
      .withColumn("ehr_first_month", F.expr("try_to_date(concat(First_month_active, '01'), 'yyyyMMdd')"))
      .withColumn("ehr_last_month", F.last_day(F.expr("try_to_date(concat(Last_month_active, '01'), 'yyyyMMdd')")))
      .withColumn("has_claims", F.col("Market_clarity") == "Y"))

silver_patient = p.select(
    F.col("PtId").alias("ptid"), "birth_yr", "gender", "race", "ethnicity", "region",
    F.col("Division").alias("division"), "deceased", "death_date", F.col("Provid_pcp").alias("provid_pcp"),
    "ehr_first_month", "ehr_last_month", "has_claims")
dups = silver_patient.groupBy("ptid").count().filter("count > 1").count()
assert dups == 0, f"{dups} patients still duplicated"
save_sdf(silver_patient, "silver_patient")

# COMMAND ----------

# MAGIC %md ## Providers (EHR provider file and claims provider file)

# COMMAND ----------

pv = spark.table(tbl("bronze_provider"))
s = F.upper(F.trim(F.col("Specialty")))
spec = (F.when(s.isin("ENDOCRINOLOGY", "ENDO", "ENDOCRINOLOGY, DIABETES & METABOLISM"), "Endocrinology")
         .when(s.isin("FAMILY MEDICINE", "FAMILY PRACTICE", "FAMILY MED"), "Family Medicine")
         .when(s.isin("INTERNAL MEDICINE", "INT MED"), "Internal Medicine")
         .when(s.isin("NURSE PRACTITIONER", "NP"), "Nurse Practitioner")
         .when(s.isin("CARDIOLOGY", "CARDIOVASCULAR DISEASE"), "Cardiology")
         .when(s.isin("GASTROENTEROLOGY", "GI"), "Gastroenterology")
         .when(s.isin("SURGERY", "GENERAL SURGERY"), "Surgery")
         .otherwise("Other"))
std_spec = ["Endocrinology", "Family Medicine", "Internal Medicine", "Nurse Practitioner", "Cardiology",
            "Gastroenterology", "Surgery"]
log_dq("silver_provider", "Specialty not in standard list", pv.filter(~F.col("Specialty").isin(std_spec)).count(),
       "standardized")
pv = pv.withColumn("specialty", spec)

silver_provider = pv.select(F.col("ProvId").alias("provid"), "specialty", F.col("Taxonomy").alias("taxonomy"))
cp = spark.table(tbl("bronze_claims_provider"))
silver_claims_provider = cp.select(F.col("Prov_Unique").alias("prov_unique"), F.col("Prov_State").alias("prov_state"),
                                   F.col("Prov_Type").alias("prov_type"), F.col("Taxonomy1").alias("taxonomy"))
save_sdf(silver_claims_provider, "silver_claims_provider")
save_sdf(silver_provider, "silver_provider")

# COMMAND ----------

# MAGIC %md ## Enrollment spans

# COMMAND ----------

e = spark.table(tbl("bronze_member_enrollment"))
n_raw = e.count()
e = e.dropDuplicates()
log_dq("silver_enrollment_spans", "exact duplicate rows", n_raw - e.count(), "removed")

nonstd = e.filter(~F.col("Eligeff").rlike(r"^\d{4}-\d{2}-\d{2}$") | ~F.col("Eligend").rlike(r"^\d{4}-\d{2}-\d{2}$")).count()
log_dq("silver_enrollment_spans", "Eligeff/Eligend in non-ISO date format", nonstd, "parsed (MM/DD/YYYY and YYYYMMDD)")
e = e.withColumn("eff", parse_date_col("Eligeff")).withColumn("end", parse_date_col("Eligend"))
bad = e.filter(F.col("eff").isNull() | F.col("end").isNull()).count()
log_dq("silver_enrollment_spans", "unparseable enrollment date", bad, "removed")
e = e.filter(F.col("eff").isNotNull() & F.col("end").isNotNull())

swapped = e.filter(F.col("eff") > F.col("end")).count()
log_dq("silver_enrollment_spans", "Eligeff after Eligend (swapped)", swapped, "swapped back")
e = (e.withColumn("eligeff", F.least("eff", "end")).withColumn("eligend", F.greatest("eff", "end")))

log_dq("silver_enrollment_spans", "Bus (payer) not upper case", e.filter(F.col("Bus") != F.upper(F.col("Bus"))).count(),
       "upper-cased")
e = e.withColumn("bus", F.upper(F.trim(F.col("Bus"))))

spans = e.select(F.col("PTID").alias("ptid"), F.col("Pat_planid").alias("pat_planid"), "bus",
                 F.col("Product").alias("plan_product"), "eligeff", "eligend",
                 (F.col("Medical_coverage_ind") == "Y").alias("medical_cov"),
                 (F.col("Pharmacy_coverage_ind") == "Y").alias("pharmacy_cov"))

# overlapping spans for the same plan: keep the earliest start / latest end per plan "island"
w = Window.partitionBy("ptid", "pat_planid").orderBy("eligeff", "eligend")
spans = (spans.withColumn("prev_end", F.max("eligend").over(w.rowsBetween(Window.unboundedPreceding, -1)))
              .withColumn("new_grp", F.when(F.col("prev_end").isNull() | (F.col("eligeff") > F.col("prev_end")), 1).otherwise(0))
              .withColumn("grp", F.sum("new_grp").over(w.rowsBetween(Window.unboundedPreceding, 0))))
overlaps = spans.filter(F.col("new_grp") == 0).count()
log_dq("silver_enrollment_spans", "overlapping spans for the same plan", overlaps, "merged")
spans = (spans.groupBy("ptid", "pat_planid", "bus", "plan_product", "medical_cov", "pharmacy_cov", "grp")
              .agg(F.min("eligeff").alias("eligeff"), F.max("eligend").alias("eligend")).drop("grp"))
save_sdf(spans, "silver_enrollment_spans")

# COMMAND ----------

# MAGIC %md ## Continuous medical + pharmacy coverage (gaps of up to 31 days are bridged)

# COMMAND ----------

spans.filter("medical_cov AND pharmacy_cov").createOrReplaceTempView("cov")
continuous = spark.sql(f"""
WITH o AS (
  SELECT ptid, eligeff, eligend,
         MAX(eligend) OVER (PARTITION BY ptid ORDER BY eligeff, eligend
                            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max_end
  FROM cov),
f AS (
  SELECT *, CASE WHEN prev_max_end IS NULL OR datediff(eligeff, prev_max_end) > {ENROLL_GAP_ALLOWED}
                 THEN 1 ELSE 0 END AS new_island
  FROM o),
g AS (
  SELECT *, SUM(new_island) OVER (PARTITION BY ptid ORDER BY eligeff, eligend ROWS UNBOUNDED PRECEDING) AS island
  FROM f)
SELECT ptid, island, MIN(eligeff) AS cov_start, MAX(eligend) AS cov_end,
       datediff(MAX(eligend), MIN(eligeff)) + 1 AS cov_days
FROM g GROUP BY ptid, island
""")
save_sdf(continuous, "silver_enrollment_continuous")

# COMMAND ----------

# MAGIC %md ## EHR insurance records

# COMMAND ----------

ins = spark.table(tbl("bronze_insurance"))
silver_ins = ins.select(F.col("PtId").alias("ptid"), F.col("EncId").alias("encid"),
                        parse_date_col("Insurance_date").alias("insurance_date"), F.col("Ins_type").alias("ins_type"))
save_sdf(silver_ins, "silver_insurance_ehr")

# COMMAND ----------

flush_dq(NB)
