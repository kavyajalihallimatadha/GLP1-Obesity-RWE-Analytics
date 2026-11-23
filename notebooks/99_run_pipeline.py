# Databricks notebook source
# MAGIC %md
# MAGIC # 99 · Run the Whole Pipeline
# MAGIC
# MAGIC Runs every notebook in order. Each step can also be opened and run on its own.
# MAGIC
# MAGIC | Stage | Notebooks |
# MAGIC |---|---|
# MAGIC | Reference | 01 |
# MAGIC | Simulation → Bronze | 02 – 08 |
# MAGIC | Silver (cleaning + data quality) | 10 – 13 |
# MAGIC | Gold (analysis) | 20 – 25 |
# MAGIC | Export for Tableau | 30 |
# MAGIC
# MAGIC Expected run time on a small serverless cluster: roughly 15–25 minutes, most of it in notebook 05.

# COMMAND ----------

import time

PIPELINE = [
    "01_reference/01_reference_codes",
    "02_simulation/02_sim_providers",
    "02_simulation/03_sim_patients_enrollment",
    "02_simulation/04_sim_encounters_diagnoses",
    "02_simulation/05_sim_pharmacy",
    "02_simulation/06_sim_procedures",
    "02_simulation/07_sim_observations_labs",
    "02_simulation/08_build_bronze_with_dq_issues",
    "03_silver/10_silver_patient_enrollment",
    "03_silver/11_silver_clinical",
    "03_silver/12_silver_pharmacy",
    "03_silver/13_data_quality_report",
    "04_gold/20_gold_cohort",
    "04_gold/21_gold_treatment_patterns",
    "04_gold/22_gold_persistence_adherence",
    "04_gold/23_gold_market_trends",
    "04_gold/24_gold_equity",
    "04_gold/25_gold_outcomes",
    "05_export/30_export_for_tableau",
]

START_AT = 0   # change to resume from a later step, e.g. PIPELINE.index("03_silver/10_silver_patient_enrollment")

for nb in PIPELINE[START_AT:]:
    t0 = time.time()
    print(f"▶ {nb}")
    dbutils.notebook.run(f"./{nb}", timeout_seconds=3600)
    print(f"  done in {time.time() - t0:,.0f}s")
print("Pipeline finished.")
