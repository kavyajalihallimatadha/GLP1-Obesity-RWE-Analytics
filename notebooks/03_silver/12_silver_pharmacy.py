# Databricks notebook source
# MAGIC %md
# MAGIC # 12 · Silver: Pharmacy Claims and Prescriptions Written
# MAGIC
# MAGIC Pharmacy claims are the backbone of treatment analysis, so this is the most careful cleaning step.
# MAGIC
# MAGIC **NDC standardization** – raw NDCs arrive in four shapes. All are converted to the 11-digit 5-4-2
# MAGIC billing format and matched to `ref_ndc`:
# MAGIC
# MAGIC | Raw shape | Example | Rule |
# MAGIC |---|---|---|
# MAGIC | 11 digits | `00169452414` | keep |
# MAGIC | hyphenated 5-4-2 | `00169-4524-14` | remove hyphens |
# MAGIC | hyphenated 10-digit label (4-4-2, 5-3-2, 5-4-1) | `0169-4524-14` | zero-pad each segment to 5-4-2 |
# MAGIC | leading zeros lost | `169452414` | left-pad to 11 digits |
# MAGIC
# MAGIC **Other rules:** remove duplicates; net out reversed claims; keep rejected claims in a separate
# MAGIC access table; fix days supply (0, 999, blank → product default); drop fills for patients not in the
# MAGIC patient table and fills after death.
# MAGIC
# MAGIC **Outputs:** `silver_rx_fills`, `silver_rx_rejections`, `silver_rx_written`

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

NB = "12_silver_pharmacy"
ref_ndc = spark.table(tbl("ref_ndc"))
ref_product = spark.table(tbl("ref_product"))
ndc_list = [r["ndc11"] for r in ref_ndc.select("ndc11").collect()]


def standardize_ndc(col_name):
    raw = F.trim(F.col(col_name))
    parts = F.split(raw, "-")
    hyphen = F.concat(F.lpad(parts.getItem(0), 5, "0"), F.lpad(parts.getItem(1), 4, "0"), F.lpad(parts.getItem(2), 2, "0"))
    digits = F.regexp_replace(raw, r"[^0-9]", "")
    # 10 digits without hyphens is ambiguous: try the three possible zero positions against the reference list
    c1 = F.concat(F.lit("0"), digits)
    c2 = F.concat(F.substring(digits, 1, 5), F.lit("0"), F.substring(digits, 6, 5))
    c3 = F.concat(F.substring(digits, 1, 9), F.lit("0"), F.substring(digits, 10, 1))
    ten = F.when(c1.isin(ndc_list), c1).when(c2.isin(ndc_list), c2).when(c3.isin(ndc_list), c3)
    return (F.when(raw.contains("-") & (F.size(parts) == 3), hyphen)
             .when(F.length(digits) == 11, digits)
             .when(F.length(digits) == 10, ten)
             .when(F.length(digits) < 10, F.lpad(digits, 11, "0")))


def ndc_shape(col_name):
    raw = F.col(col_name)
    return (F.when(raw.rlike(r"^\d{11}$"), "11-digit")
             .when(raw.rlike(r"^\d{5}-\d{4}-\d{2}$"), "hyphenated 5-4-2")
             .when(raw.rlike(r"^\d{4,5}-\d{3,4}-\d{1,2}$"), "hyphenated 10-digit label")
             .when(F.trim(raw) != raw, "padded with spaces")
             .when(raw.rlike(r"^\d{1,10}$"), "leading zeros lost")
             .otherwise("other"))

# COMMAND ----------

# MAGIC %md ## Pharmacy claims

# COMMAND ----------

rx = spark.table(tbl("bronze_claims_rx"))
n_raw = rx.count()
rx = rx.dropDuplicates()
log_dq("silver_rx_fills", "exact duplicate rows", n_raw - rx.count(), "removed")

shapes = {r["shape"]: r["count"] for r in rx.groupBy(ndc_shape("Ndc").alias("shape")).count().collect()}
for shape in ["hyphenated 5-4-2", "hyphenated 10-digit label", "leading zeros lost", "padded with spaces", "other"]:
    log_dq("silver_rx_fills", f"NDC format: {shape}", shapes.get(shape, 0), "converted to 11-digit 5-4-2")

rx = rx.withColumn("ndc11", standardize_ndc("Ndc"))
unmatched = rx.join(ref_ndc.select("ndc11"), "ndc11", "left_anti").count()
log_dq("silver_rx_fills", "NDC not found in reference list after standardizing", unmatched, "removed")
rx = rx.join(ref_ndc.select("ndc11", "product_key", "dose_step", F.col("strength").alias("ndc_strength")), "ndc11", "inner")

log_dq("silver_rx_fills", "Brnd_nm mixed case / trailing space",
       rx.filter(F.col("Brnd_nm") != F.upper(F.trim(F.col("Brnd_nm")))).count(), "ignored: product comes from NDC")
log_dq("silver_rx_fills", "Fill_dt in non-ISO format", rx.filter(~F.col("Fill_dt").rlike(r"^\d{4}-\d{2}-\d{2}$")).count(), "parsed")
rx = rx.withColumn("fill_date", parse_date_col("Fill_dt")).withColumn("ttype", F.upper(F.trim("Transaction_Type")))

# --- rejected claims -> access table
rej = rx.filter(F.col("ttype") == "REJECTED")
silver_rej = rej.select(F.col("PTID").alias("ptid"), "fill_date", "ndc11", "product_key",
                        F.col("Reject_Code").alias("reject_code"), F.col("Payer_Type").alias("payer_type"))
save_sdf(silver_rej, "silver_rx_rejections")
log_dq("silver_rx_fills", "rejected claims (not dispensed)", silver_rej.count(), "moved to silver_rx_rejections")

# --- reversals: drop the reversal and the paid claim it cancels
reversed_ids = rx.filter(F.col("ttype") == "REVERSAL").select("Clmid").distinct()
log_dq("silver_rx_fills", "paid claims later reversed", reversed_ids.count(), "removed with their reversal rows")
paid = rx.filter(F.col("ttype") == "PAID").join(reversed_ids, "Clmid", "left_anti")

# --- days supply
ds = F.expr("try_cast(Days_Sup as int)")
log_dq("silver_rx_fills", "Days_Sup = 0", paid.filter(ds == 0).count(), "replaced with product default")
log_dq("silver_rx_fills", "Days_Sup > 90 (e.g. 999)", paid.filter(ds > 90).count(), "replaced with product default")
log_dq("silver_rx_fills", "Days_Sup missing", paid.filter(ds.isNull()).count(), "replaced with product default")
paid = (paid.join(ref_product.select("product_key", F.col("days_supply").alias("default_ds")), "product_key")
            .withColumn("days_supply", F.when(ds.between(1, 90), ds).otherwise(F.col("default_ds"))))

# --- patients not in the patient table, fills after death
pt = spark.table(tbl("silver_patient")).select(F.col("ptid").alias("PTID"), "death_date")
orph = paid.join(pt, "PTID", "left_anti").count()
log_dq("silver_rx_fills", "PTID not found in patient table", orph, "removed")
paid = paid.join(pt, "PTID", "inner")
after_death = paid.filter(F.col("death_date").isNotNull() & (F.col("fill_date") > F.col("death_date"))).count()
log_dq("silver_rx_fills", "fill dated after patient's death", after_death, "removed")
paid = paid.filter(F.col("death_date").isNull() | (F.col("fill_date") <= F.col("death_date")))
log_dq("silver_rx_fills", "unparseable fill date", paid.filter(F.col("fill_date").isNull()).count(), "removed")
paid = paid.filter(F.col("fill_date").isNotNull())

silver_fills = (paid.join(ref_product.select("product_key", "brand_name", "generic_name", "molecule", "drug_class",
                                             "indication_group", "is_generic"), "product_key")
                    .select(F.col("PTID").alias("ptid"), F.col("Clmid").alias("clmid"), "fill_date", "ndc11", "product_key",
                            "brand_name", "generic_name", "molecule", "drug_class", "indication_group", "is_generic",
                            "dose_step", F.col("ndc_strength").alias("strength"), "days_supply",
                            F.expr("try_cast(Quantity as double)").alias("quantity"),
                            F.expr("try_cast(Copay as double)").alias("copay"),
                            F.expr("try_cast(Std_Cost as double)").alias("std_cost"),
                            F.col("Payer_Type").alias("payer_type"), F.col("Prov_Unique").alias("prov_unique"),
                            F.col("Prov_Specialty").alias("prescriber_specialty"), F.col("Mail_Ind").alias("mail_order")))
save_sdf(silver_fills, "silver_rx_fills")
display(silver_fills.groupBy(F.year("fill_date").alias("year")).pivot("brand_name").count().orderBy("year"))

# COMMAND ----------

# MAGIC %md ## Prescriptions written (EHR)

# COMMAND ----------

rw = spark.table(tbl("bronze_rx_written")).drop("Drug_class", "Strength")   # avoid name clash with ref columns
log_dq("silver_rx_written", "RX_date in non-ISO format", rw.filter(~F.col("RX_date").rlike(r"^\d{4}-\d{2}-\d{2}$")).count(), "parsed")
rw = rw.withColumn("rx_date", parse_date_col("RX_date")).withColumn("ndc11", standardize_ndc("NDC"))
by_ndc = rw.filter(F.col("ndc11").isNotNull()).join(ref_ndc.select("ndc11", "product_key", "dose_step"), "ndc11", "left")

# missing NDC: match the product from the drug name (brand name is the first word(s) of Drug_name)
missing = rw.filter(F.col("ndc11").isNull())
log_dq("silver_rx_written", "NDC missing", missing.count(), "product matched from drug name")
log_dq("silver_rx_written", "Drug_name lower case", rw.filter(F.col("Drug_name") == F.lower(F.col("Drug_name"))).count(),
       "matched case-insensitively")
by_name = (missing.join(ref_product.select("product_key", "brand_name"),
                        F.lower(F.col("Drug_name")).startswith(F.lower(F.col("brand_name"))), "left")
                  .drop("brand_name").withColumn("dose_step", F.lit(None).cast("int")))
rw_all = by_ndc.unionByName(by_name.select(by_ndc.columns))
silver_rw = (rw_all.join(ref_product.select("product_key", "brand_name", "molecule", "drug_class"), "product_key", "left")
                   .select(F.col("PtId").alias("ptid"), "rx_date", "product_key", "brand_name", "molecule", "drug_class",
                           "dose_step", F.col("Provid").alias("provid"), F.col("Discontinue_Reason").alias("discontinue_reason")))
save_sdf(silver_rw, "silver_rx_written")

# COMMAND ----------

flush_dq(NB)
