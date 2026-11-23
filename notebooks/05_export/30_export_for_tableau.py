# Databricks notebook source
# MAGIC %md
# MAGIC # 30 · Export Gold Tables for Tableau Public
# MAGIC
# MAGIC Tableau Public connects to files only (CSV, Excel, Google Sheets…), not to Databricks. This notebook
# MAGIC writes every Gold table to a Unity Catalog **volume** as CSV, plus one Excel workbook with a sheet per
# MAGIC table (easiest to load into Tableau Public).
# MAGIC
# MAGIC **Download:** Catalog Explorer → your catalog → `glp1_rwe` → Volumes → `tableau_exports`
# MAGIC → select a file → Download.

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

GOLD_TABLES = [
    "gold_cohort_attrition", "gold_patient_cohort",
    "gold_treatment_episodes", "gold_treatment_pathways", "gold_switch_matrix",
    "gold_persistence_curve", "gold_persistence_summary", "gold_adherence",
    "gold_market_monthly", "gold_market_share_annual", "gold_access_annual", "gold_market_events",
    "gold_equity_rates", "gold_equity_adjusted_or",
    "gold_outcomes_patient", "gold_outcomes_summary",
    "gold_dq_tables", "gold_dq_rules",
]

VOLUME = "tableau_exports"
try:
    spark.sql(f"CREATE VOLUME IF NOT EXISTS {SCHEMA}.{VOLUME}")
    out_dir = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
except Exception as err:
    out_dir = None
    print("Could not create a volume (workspace may not use Unity Catalog):", err)

# COMMAND ----------

import datetime as dt

frames = {}
for t in GOLD_TABLES:
    pdf = load_pdf(t)
    for c in pdf.columns:                      # write dates as ISO text so Tableau reads them cleanly
        s = pdf[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            pdf[c] = s.dt.strftime("%Y-%m-%d")
        elif s.dtype == object:
            nn = s.dropna()
            if len(nn) and isinstance(nn.iloc[0], (dt.date, dt.datetime)):
                pdf[c] = pd.to_datetime(s).dt.strftime("%Y-%m-%d")
    frames[t] = pdf
    if out_dir:
        pdf.to_csv(f"{out_dir}/{t}.csv", index=False)
    print(f"{t:<28} {len(pdf):>8,} rows")

# COMMAND ----------

if out_dir:
    try:
        xlsx = f"{out_dir}/glp1_obesity_rwe_tableau.xlsx"
        with pd.ExcelWriter(xlsx) as xw:
            for t, pdf in frames.items():
                pdf.to_excel(xw, sheet_name=t.replace("gold_", "")[:31], index=False)
        print("Excel workbook written:", xlsx)
    except Exception as err:
        print("Excel export skipped (openpyxl not available). Use the CSV files.", err)
    display(dbutils.fs.ls(out_dir))
else:
    print("Fallback: run `display(spark.table('<table>'))` for each table and use the download button under the result.")
