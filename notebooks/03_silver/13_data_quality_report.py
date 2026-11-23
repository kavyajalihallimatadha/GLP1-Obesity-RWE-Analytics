# Databricks notebook source
# MAGIC %md
# MAGIC # 13 · Data-Quality Report
# MAGIC
# MAGIC Brings together:
# MAGIC - `dq_injection_log` – what problems were put into the raw data (notebook 08)
# MAGIC - `dq_log` – what each cleaning rule found and did (notebooks 10–12)
# MAGIC - row counts before (bronze) and after (silver)
# MAGIC
# MAGIC **Outputs (feed the "Data Quality" Tableau page)**
# MAGIC - `gold_dq_rules` – one row per cleaning rule
# MAGIC - `gold_dq_tables` – bronze rows vs silver rows per table, problems injected vs rows fixed

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

rules = spark.table(tbl("dq_log"))
save_sdf(rules.select("notebook", "table_name", "rule", "rows_affected", "action"), "gold_dq_rules")
display(rules.orderBy("notebook", "table_name"))

# COMMAND ----------

pairs = [  # bronze table(s) -> silver table
    ("bronze_patient", "silver_patient"),
    ("bronze_member_enrollment", "silver_enrollment_spans"),
    ("bronze_provider", "silver_provider"),
    ("bronze_encounter", "silver_encounter"),
    ("bronze_diagnosis", "silver_diagnosis"),
    ("bronze_claims_med_diagnosis", "silver_diagnosis"),
    ("bronze_claims_med_services", "silver_med_claims"),
    ("bronze_observation", "silver_vitals"),
    ("bronze_lab", "silver_hba1c"),
    ("bronze_procedure", "silver_bariatric_surgery"),
    ("bronze_claims_rx", "silver_rx_fills"),
    ("bronze_rx_written", "silver_rx_written"),
]
inj = {r["table_name"]: r["n"] for r in
       spark.table(tbl("dq_injection_log")).groupBy("table_name").agg(F.sum("rows_injected").alias("n")).collect()}
fixed = {r["table_name"]: r["n"] for r in rules.groupBy("table_name").agg(F.sum("rows_affected").alias("n")).collect()}

rows = []
for b, s in pairs:
    rows.append({"bronze_table": b, "silver_table": s,
                 "bronze_rows": spark.table(tbl(b)).count(), "silver_rows": spark.table(tbl(s)).count(),
                 "problems_injected": int(inj.get(b, 0)), "rows_touched_by_rules": int(fixed.get(s, 0))})
summary = pd.DataFrame(rows)
summary["note"] = np.where(summary["silver_table"] == "silver_vitals",
                           "silver_vitals has one row per encounter (weight + BMI combined)", "")
save_pdf(summary, "gold_dq_tables")
display(summary)

# COMMAND ----------

# MAGIC %md
# MAGIC **How to read this:** `problems_injected` counts the problems placed into each raw table;
# MAGIC `rows_touched_by_rules` counts rows each cleaning rule changed, removed or flagged in the matching
# MAGIC silver table. They are not expected to match exactly: one raw row can trip several rules, and
# MAGIC some rules (like date parsing) also touch rows that were already valid in a different format.
