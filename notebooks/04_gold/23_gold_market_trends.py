# Databricks notebook source
# MAGIC %md
# MAGIC # 23 · Gold: Market Trends, Share and Access
# MAGIC
# MAGIC **Business questions:** *How has the market shifted between products since 2018? How did the
# MAGIC 2022–2025 shortages and new launches change new patient starts? Where do payers block access?*
# MAGIC
# MAGIC Uses **all** pharmacy claims in the data (market view), not only the study cohort.
# MAGIC
# MAGIC **Definitions**
# MAGIC - **Fills (TRx proxy):** paid pharmacy claims
# MAGIC - **New-to-brand start (NBRx proxy):** a fill of a product with no fill of the same product in the prior 180 days
# MAGIC - **New to therapy:** the patient's first-ever GLP-1 / anti-obesity fill in the data
# MAGIC - **Rejection rate:** rejected claims ÷ (rejected claims + new-to-brand starts)
# MAGIC
# MAGIC **Outputs:** `gold_market_monthly`, `gold_market_share_annual`, `gold_access_annual`, `gold_market_events`

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

monthly = spark.sql(f"""
WITH f AS (
  SELECT *,
         LAG(fill_date) OVER (PARTITION BY ptid, product_key ORDER BY fill_date, clmid) AS prev_same_product,
         ROW_NUMBER() OVER (PARTITION BY ptid ORDER BY fill_date, clmid) AS nth_fill_any
  FROM silver_rx_fills)
SELECT CAST(date_trunc('MONTH', fill_date) AS DATE) AS month,
       brand_name, molecule, drug_class, indication_group, is_generic,
       CASE payer_type WHEN 'COM' THEN 'Commercial' WHEN 'MCR' THEN 'Medicare' WHEN 'MCD' THEN 'Medicaid' ELSE 'Other' END AS payer,
       COUNT(*) AS fills,
       COUNT(DISTINCT ptid) AS patients,
       SUM(CASE WHEN prev_same_product IS NULL OR datediff(fill_date, prev_same_product) > 180 THEN 1 ELSE 0 END) AS new_to_brand_starts,
       SUM(CASE WHEN nth_fill_any = 1 THEN 1 ELSE 0 END) AS new_to_therapy_starts,
       ROUND(SUM(std_cost), 2) AS total_cost,
       ROUND(SUM(copay), 2) AS total_copay
FROM f
WHERE fill_date BETWEEN DATE'{STUDY_START}' AND DATE'{STUDY_END}'
GROUP BY 1, 2, 3, 4, 5, 6, 7
""")
save_sdf(monthly, "gold_market_monthly")

# COMMAND ----------

share = spark.sql("""
WITH y AS (
  SELECT year(month) AS year, brand_name, drug_class, SUM(fills) AS fills, SUM(new_to_brand_starts) AS nbrx
  FROM gold_market_monthly GROUP BY 1, 2, 3)
SELECT *, ROUND(100 * fills / SUM(fills) OVER (PARTITION BY year), 1) AS fill_share_pct,
          ROUND(100 * nbrx / SUM(nbrx) OVER (PARTITION BY year), 1) AS new_start_share_pct
FROM y
""")
save_sdf(share, "gold_market_share_annual")
display(share.orderBy("year", F.desc("fills")))

# COMMAND ----------

access = spark.sql(f"""
WITH rej AS (
  SELECT year(r.fill_date) AS year, p.brand_name,
         CASE r.payer_type WHEN 'COM' THEN 'Commercial' WHEN 'MCR' THEN 'Medicare' WHEN 'MCD' THEN 'Medicaid' ELSE 'Other' END AS payer,
         SUM(CASE WHEN r.reject_code = '75' THEN 1 ELSE 0 END) AS rejected_prior_auth,
         SUM(CASE WHEN r.reject_code = '70' THEN 1 ELSE 0 END) AS rejected_not_covered,
         COUNT(*) AS rejected_total
  FROM silver_rx_rejections r JOIN ref_product p ON r.product_key = p.product_key
  WHERE r.fill_date BETWEEN DATE'{STUDY_START}' AND DATE'{STUDY_END}'
  GROUP BY 1, 2, 3),
starts AS (
  SELECT year(month) AS year, brand_name, payer, SUM(new_to_brand_starts) AS new_starts
  FROM gold_market_monthly GROUP BY 1, 2, 3)
SELECT COALESCE(s.year, r.year) AS year, COALESCE(s.brand_name, r.brand_name) AS brand_name,
       COALESCE(s.payer, r.payer) AS payer, COALESCE(s.new_starts, 0) AS new_starts,
       COALESCE(r.rejected_prior_auth, 0) AS rejected_prior_auth, COALESCE(r.rejected_not_covered, 0) AS rejected_not_covered,
       COALESCE(r.rejected_total, 0) AS rejected_total,
       ROUND(100 * COALESCE(r.rejected_total, 0) / NULLIF(COALESCE(r.rejected_total, 0) + COALESCE(s.new_starts, 0), 0), 1) AS rejection_rate_pct
FROM starts s FULL OUTER JOIN rej r ON s.year = r.year AND s.brand_name = r.brand_name AND s.payer = r.payer
""")
save_sdf(access, "gold_access_annual")

# COMMAND ----------

events = spark.sql("""
SELECT e.event_type, COALESCE(p.brand_name, 'All products') AS brand_name, e.description, e.start_date, e.end_date
FROM ref_market_events e LEFT JOIN ref_product p ON e.product_key = p.product_key
UNION ALL
SELECT 'APPROVAL', brand_name, concat(brand_name, ' US approval'), approval_date, CAST(NULL AS TIMESTAMP)
FROM ref_product WHERE approval_date >= '2018-01-01'
""")
save_sdf(events, "gold_market_events")
