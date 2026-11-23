# Databricks notebook source
# MAGIC %md
# MAGIC # 21 · Gold: Treatment Episodes, Lines of Therapy and Switching
# MAGIC
# MAGIC **Business questions:** *Which product do patients start on? How long do they stay on it? When they
# MAGIC stop, do they switch, restart or drop out of treatment entirely?*
# MAGIC
# MAGIC **Definitions**
# MAGIC - **Episode:** continuous use of one product. A fill starts a new episode when it comes more than
# MAGIC   60 days after the previous supply ran out (supply from overlapping fills is carried forward).
# MAGIC - **Line of therapy:** a new line starts each time the patient starts a *different* product. Restarting
# MAGIC   the same product after a break stays in the same line (re-treatment).
# MAGIC - **Switch:** the next product starts within 60 days of the previous supply running out.
# MAGIC - Only fills between index date and end of follow-up are used.
# MAGIC
# MAGIC **Outputs:** `gold_treatment_episodes`, `gold_treatment_pathways`, `gold_switch_matrix`

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

G = PERSISTENCE_GRACE_DAYS

spark.sql("""
CREATE OR REPLACE TABLE work_cohort_fills AS
SELECT f.*, c.index_date, c.followup_end
FROM silver_rx_fills f
JOIN gold_patient_cohort c ON f.ptid = c.ptid AND f.fill_date BETWEEN c.index_date AND c.followup_end
""")

# COMMAND ----------

# MAGIC %md ## Episodes

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE work_episodes AS
WITH a AS (
  SELECT *, date_add(fill_date, days_supply) AS runout,
         MAX(date_add(fill_date, days_supply)) OVER (
             PARTITION BY ptid, product_key ORDER BY fill_date, clmid
             ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_runout
  FROM work_cohort_fills),
b AS (
  SELECT *, CASE WHEN prev_runout IS NULL OR datediff(fill_date, prev_runout) > {G} THEN 1 ELSE 0 END AS new_ep
  FROM a),
c AS (
  SELECT *, SUM(new_ep) OVER (PARTITION BY ptid, product_key ORDER BY fill_date, clmid ROWS UNBOUNDED PRECEDING) AS ep_no
  FROM b)
SELECT ptid, product_key, ep_no,
       MIN(fill_date) AS start_date, MAX(runout) AS supply_end_date,
       COUNT(*) AS n_fills, SUM(days_supply) AS days_supplied, MAX(dose_step) AS max_dose_step,
       first(brand_name) AS brand_name, first(molecule) AS molecule, first(drug_class) AS drug_class,
       first(indication_group) AS indication_group, MAX(followup_end) AS followup_end,
       min_by(payer_type, fill_date) AS payer_at_start
FROM c GROUP BY ptid, product_key, ep_no
""")

episodes = spark.sql(f"""
WITH o AS (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY ptid ORDER BY start_date, product_key) AS episode_seq,
         LAG(product_key) OVER (PARTITION BY ptid ORDER BY start_date, product_key) AS prev_product,
         LEAD(product_key) OVER (PARTITION BY ptid ORDER BY start_date, product_key) AS next_product,
         LEAD(brand_name) OVER (PARTITION BY ptid ORDER BY start_date, product_key) AS next_brand,
         LEAD(start_date) OVER (PARTITION BY ptid ORDER BY start_date, product_key) AS next_start
  FROM work_episodes),
l AS (
  SELECT *, SUM(CASE WHEN prev_product IS NULL OR prev_product <> product_key THEN 1 ELSE 0 END)
              OVER (PARTITION BY ptid ORDER BY episode_seq ROWS UNBOUNDED PRECEDING) AS line_number
  FROM o)
SELECT ptid, episode_seq, line_number, product_key, brand_name, molecule, drug_class, indication_group, payer_at_start,
       start_date, supply_end_date, followup_end, n_fills, days_supplied, max_dose_step,
       datediff(LEAST(supply_end_date, followup_end), start_date) AS days_on_therapy,
       (date_add(supply_end_date, {G}) < followup_end) AS discontinued,
       next_brand, datediff(next_start, supply_end_date) AS gap_to_next_days,
       CASE
         WHEN NOT (date_add(supply_end_date, {G}) < followup_end) AND next_product IS NULL THEN 'Still on treatment (censored)'
         WHEN next_product IS NOT NULL AND next_product <> product_key AND datediff(next_start, supply_end_date) <= {G}
              THEN 'Switched to another product'
         WHEN next_product IS NOT NULL AND next_product <> product_key THEN 'Stopped, later started another product'
         WHEN next_product = product_key THEN 'Stopped, later restarted same product'
         ELSE 'Stopped, no further treatment'
       END AS episode_outcome
FROM l
""")
save_sdf(episodes, "gold_treatment_episodes")
display(spark.sql("SELECT brand_name, episode_outcome, COUNT(*) n FROM gold_treatment_episodes WHERE episode_seq = 1 GROUP BY 1, 2 ORDER BY 1, 3 DESC"))

# COMMAND ----------

# MAGIC %md ## Pathways (for the Sankey / flow chart) and switch matrix

# COMMAND ----------

pathways = spark.sql("""
WITH firsts AS (
  SELECT ptid, line_number, min_by(brand_name, episode_seq) AS brand
  FROM gold_treatment_episodes GROUP BY ptid, line_number)
SELECT c.ptid, c.payer_at_index, c.diabetes_status, c.index_year,
       COALESCE(MAX(CASE WHEN f.line_number = 1 THEN f.brand END), 'No treatment') AS line1,
       COALESCE(MAX(CASE WHEN f.line_number = 2 THEN f.brand END), 'No further line') AS line2,
       COALESCE(MAX(CASE WHEN f.line_number = 3 THEN f.brand END), 'No further line') AS line3,
       COALESCE(MAX(f.line_number), 0) AS n_lines
FROM gold_patient_cohort c LEFT JOIN firsts f ON c.ptid = f.ptid
GROUP BY c.ptid, c.payer_at_index, c.diabetes_status, c.index_year
""").withColumn("pathway", F.concat_ws(" > ", "line1",
                                       F.when(F.col("line2") != "No further line", F.col("line2")),
                                       F.when(F.col("line3") != "No further line", F.col("line3"))))
save_sdf(pathways, "gold_treatment_pathways")

switch = spark.sql("""
WITH firsts AS (
  SELECT ptid, line_number, min_by(brand_name, episode_seq) AS brand, MIN(start_date) AS start_date,
         max_by(supply_end_date, episode_seq) AS end_date
  FROM gold_treatment_episodes GROUP BY ptid, line_number),
t AS (
  SELECT a.ptid, a.line_number AS from_line, a.brand AS from_brand, b.brand AS to_brand,
         datediff(b.start_date, a.end_date) AS gap_days
  FROM firsts a JOIN firsts b ON a.ptid = b.ptid AND b.line_number = a.line_number + 1)
SELECT from_line, from_brand, to_brand, COUNT(*) AS patients,
       percentile_approx(gap_days, 0.5) AS median_gap_days
FROM t GROUP BY from_line, from_brand, to_brand
""")
save_sdf(switch, "gold_switch_matrix")
display(switch.orderBy(F.desc("patients")).limit(20))
