# Databricks notebook source
# MAGIC %md
# MAGIC # 11 · Silver: Encounters, Diagnoses, Vitals, Labs and Procedures
# MAGIC
# MAGIC | Output | Main fixes |
# MAGIC |---|---|
# MAGIC | `silver_encounter` | duplicates, date formats, encounter-type spelling |
# MAGIC | `silver_diagnosis` | EHR + claims diagnoses in one table; ICD-10 codes standardized (case, spaces, dots), ICD-9 leftovers removed, retired E66.8 after Oct 2024 remapped, categories from `ref_icd10` |
# MAGIC | `silver_med_claims` | duplicates, date formats, negative adjustment lines flagged |
# MAGIC | `silver_vitals` | weight in kg (lb/kg spellings, missing units inferred), BMI (decimal-shift fixed, implausible removed), height in cm (incl. 5' 6" text), BMI derived where missing |
# MAGIC | `silver_hba1c` | IFCC mmol/mol converted to NGSP %, missing units inferred, non-results removed, censored values handled |
# MAGIC | `silver_bariatric_surgery` | EHR procedures + surgical claims, one row per patient surgery |

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

from pyspark.sql import Window

NB = "11_silver_clinical"
ref_icd = spark.table(tbl("ref_icd10"))

# COMMAND ----------

# MAGIC %md ## Encounters

# COMMAND ----------

en = spark.table(tbl("bronze_encounter"))
n_raw = en.count()
en = en.dropDuplicates()
log_dq("silver_encounter", "exact duplicate rows", n_raw - en.count(), "removed")
log_dq("silver_encounter", "Interaction_date in non-ISO format",
       en.filter(~F.col("Interaction_date").rlike(r"^\d{4}-\d{2}-\d{2}$")).count(), "parsed")
it = F.lower(F.trim(F.col("Interaction_type")))
log_dq("silver_encounter", "Interaction_type upper-case variant",
       en.filter(F.col("Interaction_type") == F.upper(F.col("Interaction_type"))).count(), "standardized")
silver_encounter = en.select(
    F.col("PtId").alias("ptid"), F.col("EncId").alias("encid"), F.col("VisitId").alias("visitid"),
    F.when(it == "office or clinic patient", "Office").when(it == "telehealth", "Telehealth")
     .when(it == "emergency patient", "Emergency").when(it == "inpatient", "Inpatient").otherwise("Other").alias("encounter_type"),
    parse_date_col("Interaction_date").alias("enc_date"), F.col("provid"))
save_sdf(silver_encounter, "silver_encounter")

# COMMAND ----------

# MAGIC %md ## Diagnoses (EHR + claims)

# COMMAND ----------

def clean_code(col):
    """Upper case, no spaces, no decimal point."""
    return F.upper(F.regexp_replace(F.col(col), r"[\s\.]", ""))


# --- EHR diagnoses
dx = spark.table(tbl("bronze_diagnosis"))
n_raw = dx.count()
dx = dx.dropDuplicates()
log_dq("silver_diagnosis", "EHR: exact duplicate rows", n_raw - dx.count(), "removed")

icd9 = dx.filter(F.col("Diagnosis_cd_type") != "ICD10").count()
log_dq("silver_diagnosis", "EHR: legacy ICD-9 rows", icd9, "removed (study period is ICD-10 only)")
dx = dx.filter(F.col("Diagnosis_cd_type") == "ICD10")

raw_code = F.col("Diagnosis_cd")
log_dq("silver_diagnosis", "EHR: code without decimal point",
       dx.filter((F.length(F.trim(raw_code)) > 3) & ~raw_code.contains(".")).count(), "standardized")
log_dq("silver_diagnosis", "EHR: code in lower case", dx.filter(raw_code != F.upper(raw_code)).count(), "upper-cased")
log_dq("silver_diagnosis", "EHR: code with leading/trailing spaces", dx.filter(raw_code != F.trim(raw_code)).count(), "trimmed")

ehr = dx.select(F.col("PtId").alias("ptid"), parse_date_col("Diag_date").alias("dx_date"),
                clean_code("Diagnosis_cd").alias("icd10_nodot"), F.col("Diagnosis_status").alias("dx_status"),
                F.col("EncId").alias("source_id"), F.lit("EHR").alias("source"))

# --- claims diagnoses
cd = spark.table(tbl("bronze_claims_med_diagnosis"))
n_raw = cd.count()
cd = cd.dropDuplicates()
log_dq("silver_diagnosis", "Claims: exact duplicate rows", n_raw - cd.count(), "removed")
log_dq("silver_diagnosis", "Claims: code with decimal point", cd.filter(F.col("Diag").contains(".")).count(), "removed dot")
log_dq("silver_diagnosis", "Claims: code in lower case", cd.filter(F.col("Diag") != F.upper(F.col("Diag"))).count(), "upper-cased")
clm = cd.select(F.col("PTID").alias("ptid"), parse_date_col("FST_DT").alias("dx_date"),
                clean_code("Diag").alias("icd10_nodot"), F.lit("Diagnosis of").alias("dx_status"),
                F.col("Clmid").alias("source_id"), F.lit("CLAIMS").alias("source"))

alldx = ehr.unionByName(clm)

# retired parent code E66.8 used after the Oct 1, 2024 code expansion -> map to E66.89
retired = alldx.filter((F.col("icd10_nodot") == "E668") & (F.col("dx_date") >= F.lit("2024-10-01")))
log_dq("silver_diagnosis", "E66.8 used after 2024-10-01 (no longer billable)", retired.count(),
       "remapped to E66.89 (other obesity NEC)")
alldx = alldx.withColumn("icd10_nodot", F.when((F.col("icd10_nodot") == "E668") & (F.col("dx_date") >= F.lit("2024-10-01")),
                                               "E6689").otherwise(F.col("icd10_nodot")))

bad_date = alldx.filter(F.col("dx_date").isNull()).count()
log_dq("silver_diagnosis", "unparseable diagnosis date", bad_date, "removed")
alldx = alldx.filter(F.col("dx_date").isNotNull())

silver_dx = (alldx.join(ref_icd.select("icd10_nodot", "icd10_code", "category", "bmi_low", "bmi_high"), "icd10_nodot", "left")
             .withColumn("icd10_code", F.coalesce(
                 F.col("icd10_code"),
                 F.when(F.length("icd10_nodot") > 3, F.concat(F.substring("icd10_nodot", 1, 3), F.lit("."),
                                                             F.expr("substring(icd10_nodot, 4)"))).otherwise(F.col("icd10_nodot"))))
             .withColumn("category", F.coalesce("category", F.lit("OTHER")))
             .dropDuplicates(["ptid", "dx_date", "icd10_nodot", "dx_status", "source_id", "source"]))
save_sdf(silver_dx, "silver_diagnosis")
display(silver_dx.groupBy("source", "category").count().orderBy("source", "category"))

# COMMAND ----------

# MAGIC %md ## Medical claim lines

# COMMAND ----------

ms = spark.table(tbl("bronze_claims_med_services"))
n_raw = ms.count()
ms = ms.dropDuplicates()
log_dq("silver_med_claims", "exact duplicate rows", n_raw - ms.count(), "removed")
log_dq("silver_med_claims", "Fst_dt in non-ISO format", ms.filter(~F.col("Fst_dt").rlike(r"^\d{4}-\d{2}-\d{2}$")).count(), "parsed")
cost = F.expr("try_cast(Std_cost as double)")
log_dq("silver_med_claims", "negative Std_cost (adjustment line)", ms.filter(cost < 0).count(),
       "kept, flagged is_adjustment = true")
silver_ms = ms.select(F.col("PTID").alias("ptid"), F.col("Clmid").alias("clmid"), parse_date_col("Fst_dt").alias("fst_dt"),
                      parse_date_col("Lst_dt").alias("lst_dt"), F.col("Proc_cd").alias("proc_cd"), F.col("Pos").alias("pos"),
                      F.col("Prov_Unique").alias("prov_unique"), cost.alias("std_cost"), (cost < 0).alias("is_adjustment"),
                      F.col("Paid_Status").alias("paid_status"))
save_sdf(silver_ms, "silver_med_claims")

# COMMAND ----------

# MAGIC %md ## Vitals: weight, height, BMI

# COMMAND ----------

ob = spark.table(tbl("bronze_observation"))
n_raw = ob.count()
ob = ob.dropDuplicates()
log_dq("silver_vitals", "exact duplicate rows", n_raw - ob.count(), "removed")
ob = (ob.withColumn("obs_date", parse_date_col("Obs_date"))
        .withColumn("val", F.expr("try_cast(trim(Obs_result) as double)"))
        .withColumn("unit", F.lower(F.trim(F.col("Obs_unit")))))

text_vals = ob.filter(F.col("val").isNull() & ~((F.col("Obs_type") == "HT") & (F.col("unit") == "ft/in"))).count()
log_dq("silver_vitals", "non-numeric result (refused, see note, blank)", text_vals, "removed")

# --- weight
wt = ob.filter((F.col("Obs_type") == "WT") & F.col("val").isNotNull())
log_dq("silver_vitals", "weight unit spelled non-standard (LBS, Kg, kgs ...)",
       wt.filter(F.col("unit").isNotNull() & ~F.col("Obs_unit").isin("lb", "kg")).count(), "standardized")
wt = wt.withColumn("unit_std", F.when(F.col("unit").isin("lb", "lbs"), "lb").when(F.col("unit").isin("kg", "kgs"), "kg"))
wt = wt.withColumn("kg_known", F.when(F.col("unit_std") == "lb", F.col("val") / 2.20462)
                                 .when(F.col("unit_std") == "kg", F.col("val")))
med = wt.filter(F.col("kg_known").between(30, 350)).groupBy("PtId").agg(F.expr("percentile_approx(kg_known, 0.5)").alias("med_kg"))
wt = wt.join(med, "PtId", "left")
# missing unit: choose the reading (as kg or as lb) closest to the patient's usual weight
as_kg_gap = F.abs(F.col("val") - F.col("med_kg"))
as_lb_gap = F.abs(F.col("val") / 2.20462 - F.col("med_kg"))
inferred = F.when(F.col("unit_std").isNull() & F.col("med_kg").isNotNull(),
                  F.when(as_kg_gap <= as_lb_gap, F.col("val")).otherwise(F.col("val") / 2.20462))
log_dq("silver_vitals", "weight unit missing", wt.filter(F.col("unit_std").isNull()).count(),
       "inferred from patient's other weights (kg vs lb, whichever is closer)")
wt = wt.withColumn("weight_kg", F.coalesce(F.col("kg_known"), inferred))
implaus = wt.filter(F.col("weight_kg").isNotNull() & ~F.col("weight_kg").between(30, 350)).count()
log_dq("silver_vitals", "weight outside 30-350 kg (decimal shift / typo)", implaus, "set to NULL")
wt = wt.withColumn("weight_kg", F.when(F.col("weight_kg").between(30, 350), F.round("weight_kg", 1)))

# --- height (cm, inches, or feet-inches text like 5' 6")
ht = ob.filter(F.col("Obs_type") == "HT")
ft = F.expr(r"try_cast(regexp_extract(Obs_result, '(\\d+)\\s*\'', 1) as double)")     # feet
inch = F.expr(r"try_cast(regexp_extract(Obs_result, '\'\\s*(\\d+)', 1) as double)")    # inches
log_dq("silver_vitals", "height recorded as feet-inches text", ht.filter(F.col("unit") == "ft/in").count(), "converted to cm")
ht = ht.withColumn("height_cm", F.when(F.col("unit") == "cm", F.col("val"))
                                  .when(F.col("unit") == "in", F.col("val") * 2.54)
                                  .when(F.col("unit") == "ft/in", (ft * 12 + inch) * 2.54))
ht = ht.withColumn("height_cm", F.when(F.col("height_cm").between(120, 220), F.round("height_cm", 1)))
pt_height = ht.groupBy("PtId").agg(F.expr("percentile_approx(height_cm, 0.5)").alias("height_cm"))

# --- BMI
bm = ob.filter((F.col("Obs_type") == "BMI") & F.col("val").isNotNull())
shift = bm.filter((F.col("val") > 90) & (F.col("val") / 10).between(12, 90)).count()
log_dq("silver_vitals", "BMI decimal shift (e.g. 352 instead of 35.2)", shift, "divided by 10")
bm = bm.withColumn("bmi", F.when(F.col("val").between(12, 90), F.col("val"))
                           .when((F.col("val") > 90) & (F.col("val") / 10).between(12, 90), F.col("val") / 10))
log_dq("silver_vitals", "BMI outside 12-90 after correction", bm.filter(F.col("bmi").isNull()).count(), "removed")

# one row per patient + encounter + date with weight, height and BMI (derived when not recorded)
v = (wt.select("PtId", "EncId", "obs_date", "weight_kg")
       .join(bm.select("PtId", "EncId", "obs_date", "bmi"), ["PtId", "EncId", "obs_date"], "full")
       .join(pt_height, "PtId", "left"))
derived = F.round(F.col("weight_kg") / F.pow(F.col("height_cm") / 100, 2), 1)
log_dq("silver_vitals", "BMI not recorded but weight + height available",
       v.filter(F.col("bmi").isNull() & F.col("weight_kg").isNotNull() & F.col("height_cm").isNotNull()).count(), "BMI derived")
silver_vitals = (v.withColumn("bmi_source", F.when(F.col("bmi").isNotNull(), "recorded").when(derived.isNotNull(), "derived"))
                  .withColumn("bmi", F.round(F.coalesce(F.col("bmi"), derived), 1))
                  .filter(F.col("obs_date").isNotNull() & (F.col("bmi").isNotNull() | F.col("weight_kg").isNotNull()))
                  .groupBy(F.col("PtId").alias("ptid"), F.col("EncId").alias("encid"), "obs_date")
                  .agg(F.avg("weight_kg").alias("weight_kg"), F.avg("bmi").alias("bmi"), F.first("height_cm").alias("height_cm"),
                       F.first("bmi_source").alias("bmi_source")))
save_sdf(silver_vitals, "silver_vitals")

# COMMAND ----------

# MAGIC %md ## HbA1c

# COMMAND ----------

lb = spark.table(tbl("bronze_lab"))
n_raw = lb.count()
lb = lb.dropDuplicates()
log_dq("silver_hba1c", "exact duplicate rows", n_raw - lb.count(), "removed")

res = F.trim(F.col("Test_result"))
censored = res.rlike(r"^[<>]\s*\d")
log_dq("silver_hba1c", "censored result ('<4.0' / '>14.0')", lb.filter(censored).count(), "kept at the limit value")
lb = lb.withColumn("num", F.coalesce(F.expr("try_cast(trim(Test_result) as double)"),
                                     F.expr(r"try_cast(regexp_replace(Test_result, '[<>\\s]', '') as double)")))
log_dq("silver_hba1c", "result is not a value (Pending, Cancelled, hemolyzed)", lb.filter(F.col("num").isNull()).count(), "removed")
lb = lb.filter(F.col("num").isNotNull())

unit = F.lower(F.trim(F.col("Result_unit")))
log_dq("silver_hba1c", "unit missing", lb.filter(F.col("Result_unit").isNull()).count(),
       "inferred: value > 20 means IFCC mmol/mol, otherwise NGSP %")
lb = lb.withColumn("unit_std", F.coalesce(unit, F.when(F.col("num") > 20, "mmol/mol").otherwise("%")))
log_dq("silver_hba1c", "IFCC result in mmol/mol", lb.filter(F.col("unit_std") == "mmol/mol").count(),
       "converted to NGSP %: 0.09148 * IFCC + 2.152")
lb = lb.withColumn("hba1c_pct", F.when(F.col("unit_std") == "mmol/mol", 0.09148 * F.col("num") + 2.152).otherwise(F.col("num")))
log_dq("silver_hba1c", "HbA1c outside 3-20%", lb.filter(~F.col("hba1c_pct").between(3, 20)).count(), "removed")
silver_a1c = (lb.filter(F.col("hba1c_pct").between(3, 20))
                .select(F.col("PtId").alias("ptid"), F.col("EncId").alias("encid"),
                        F.coalesce(parse_date_col("Result_date"), parse_date_col("Collected_date")).alias("result_date"),
                        F.round("hba1c_pct", 1).alias("hba1c_pct"), F.col("Loinc").alias("loinc_original")))
save_sdf(silver_a1c, "silver_hba1c")

# COMMAND ----------

# MAGIC %md ## Bariatric surgery (EHR procedure table + surgical claims)

# COMMAND ----------

pr = spark.table(tbl("bronze_procedure"))
log_dq("silver_bariatric_surgery", "Proc_code_type label inconsistent (CPT, cpt4, HCPCS/CPT)",
       pr.filter(F.col("Proc_code_type") != "CPT4").count(), "standardized to CPT4")
bar_codes = ["43775", "43644"]
ehr_s = pr.filter(F.col("Proc_code").isin(bar_codes)).select(
    F.col("PtId").alias("ptid"), parse_date_col("Proc_date").alias("surgery_date"), F.col("Proc_code").alias("cpt"),
    F.lit("EHR").alias("source"))
clm_s = silver_ms.filter(F.col("proc_cd").isin(bar_codes)).select(
    "ptid", F.col("fst_dt").alias("surgery_date"), F.col("proc_cd").alias("cpt"), F.lit("CLAIMS").alias("source"))
both = ehr_s.unionByName(clm_s)
silver_surg = (both.groupBy("ptid", "cpt").agg(F.min("surgery_date").alias("surgery_date"),
                                               F.concat_ws("+", F.sort_array(F.collect_set("source"))).alias("found_in")))
save_sdf(silver_surg, "silver_bariatric_surgery")
display(silver_surg.groupBy("found_in").count())

# COMMAND ----------

flush_dq(NB)
