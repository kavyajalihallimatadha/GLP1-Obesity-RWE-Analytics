# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Project Configuration
# MAGIC
# MAGIC Shared settings and helper functions. Every other notebook loads this one with `%run`.
# MAGIC
# MAGIC | Setting | Value |
# MAGIC |---|---|
# MAGIC | Schema | `glp1_rwe` (inside your current catalog) |
# MAGIC | Simulated patients | 50,000 |
# MAGIC | Study window | 2018-01-01 to 2025-12-31 |
# MAGIC | Data window (lookback for baseline) | 2016-01-01 to 2025-12-31 |
# MAGIC
# MAGIC **Layer naming**
# MAGIC - `ref_*` – reference code lists (ICD-10, NDC, CPT, LOINC, geography, market events)
# MAGIC - `sim_*` – clean simulated source data (the "answer key", used only by the generator)
# MAGIC - `bronze_*` – raw landing tables with real-world data-quality problems (all columns are strings)
# MAGIC - `silver_*` – cleaned, standardized, de-duplicated tables + `dq_log`
# MAGIC - `gold_*` – analysis-ready tables that feed Tableau

# COMMAND ----------

SCHEMA = "glp1_rwe"
SEED = 2026
N_PATIENTS = 50_000

DATA_START = "2016-01-01"     # earliest date in the data (baseline lookback)
STUDY_START = "2018-01-01"    # cohort entry window start
STUDY_END = "2025-12-31"      # end of data / cohort entry window end

# Analysis rules (used in Silver/Gold)
BASELINE_DAYS = 180           # continuous enrollment required before index
MIN_FOLLOWUP_DAYS = 180       # continuous enrollment required after index
ENROLL_GAP_ALLOWED = 31       # enrollment gaps up to 31 days are bridged
PERSISTENCE_GRACE_DAYS = 60   # gap after run-out of supply that ends a treatment episode
PDC_WINDOW_DAYS = 365         # adherence window after treatment start
PDC_ADHERENT = 0.80           # PDC threshold for "adherent"

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
spark.sql(f"USE SCHEMA {SCHEMA}")
CATALOG = spark.sql("SELECT current_catalog()").first()[0]
print(f"Using {CATALOG}.{SCHEMA}")


def tbl(name: str) -> str:
    """Fully qualified table name."""
    return f"`{CATALOG}`.`{SCHEMA}`.`{name}`"

# COMMAND ----------

import numpy as np
import pandas as pd
from pyspark.sql import functions as F

try:
    spark.conf.set("spark.sql.execution.arrow.pyspark.enabled", "true")
except Exception:
    pass  # some serverless configs are read-only; Arrow is on by default there


def save_pdf(pdf: pd.DataFrame, name: str, mode: str = "overwrite") -> None:
    """Write a pandas DataFrame to a Delta table (NaN -> NULL)."""
    sdf = spark.createDataFrame(pdf)
    for c, t in sdf.dtypes:
        if t in ("void", "null"):                       # all-empty column: store as string
            sdf = sdf.withColumn(c, F.col(c).cast("string"))
        elif t in ("double", "float"):
            sdf = sdf.withColumn(c, F.when(F.isnan(F.col(c)), None).otherwise(F.col(c)))
    (sdf.write.mode(mode).option("overwriteSchema", "true").saveAsTable(tbl(name)))
    print(f"saved {name}: {len(pdf):,} rows")


def load_pdf(name: str) -> pd.DataFrame:
    """Read a Delta table into pandas."""
    return spark.table(tbl(name)).toPandas()


def save_sdf(sdf, name: str, mode: str = "overwrite") -> None:
    """Write a Spark DataFrame to a Delta table."""
    sdf.write.mode(mode).option("overwriteSchema", "true").saveAsTable(tbl(name))
    print(f"saved {name}: {spark.table(tbl(name)).count():,} rows")

# COMMAND ----------

# Data-quality log helpers (used by the Silver notebooks)
_DQ_ROWS = []


def log_dq(table: str, rule: str, rows_affected: int, action: str) -> None:
    """Record one cleaning rule and how many rows it touched."""
    _DQ_ROWS.append({"table_name": table, "rule": rule,
                     "rows_affected": int(rows_affected), "action": action})
    print(f"[DQ] {table:<28} {rule:<55} {int(rows_affected):>9,}  -> {action}")


def flush_dq(notebook: str) -> None:
    """Replace this notebook's rows in dq_log with the rows logged in this run."""
    rows = pd.DataFrame(_DQ_ROWS, columns=["table_name", "rule", "rows_affected", "action"])
    rows.insert(0, "notebook", notebook)
    rows["run_ts"] = pd.Timestamp.now()
    spark.sql(f"""CREATE TABLE IF NOT EXISTS {tbl('dq_log')}
                  (notebook STRING, table_name STRING, rule STRING,
                   rows_affected BIGINT, action STRING, run_ts TIMESTAMP)""")
    spark.sql(f"DELETE FROM {tbl('dq_log')} WHERE notebook = '{notebook}'")
    if len(rows):
        spark.createDataFrame(rows).write.mode("append").saveAsTable(tbl("dq_log"))
    _DQ_ROWS.clear()
    print(f"dq_log updated for {notebook}: {len(rows)} rules")

# COMMAND ----------

# Common date parser for bronze string dates (handles the three formats found in the raw files)
def parse_date_col(col_name: str):
    return F.coalesce(
        F.expr(f"try_to_date(trim(`{col_name}`), 'yyyy-MM-dd')"),
        F.expr(f"try_to_date(trim(`{col_name}`), 'M/d/yyyy')"),
        F.expr(f"try_to_date(trim(`{col_name}`), 'yyyyMMdd')"),
    )
