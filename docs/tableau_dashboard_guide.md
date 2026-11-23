# Tableau Dashboard Build Guide (Tableau Public)

Data source: `glp1_obesity_rwe_tableau.xlsx` from the Databricks volume `tableau_exports`
(one sheet per gold table). In Tableau Public: **Connect → Microsoft Excel**, then drag each sheet
you need onto the canvas as its **own data source** (Data → New Data Source). The gold tables are
already shaped for each chart, so no joins are needed.

**Design system (use on every dashboard)**
- Size: 1400 × 900, fixed. White background, title top-left, one-line takeaway under each title.
- Product colors (keep identical everywhere): Zepbound, Mounjaro (tirzepatide) = two shades of one hue;
  Wegovy, Ozempic, Rybelsus (semaglutide) = three shades of a second hue; Victoza, Saxenda,
  liraglutide generics, Trulicity = muted greys/blues; Qsymia, Contrave = a third muted hue.
- Global filters (apply to all sheets using the same source): Payer, Diabetes status, Index year.
- Every dashboard footer: "Simulated data for portfolio purposes. Not real patient data."

---

## 1 · Cohort & Patient Profile

| Sheet | Source | Build |
|---|---|---|
| Attrition funnel | gold_cohort_attrition | Rows: `step_label` (sort by `step`). Columns: SUM(`patients`). Bar chart, label with patients and `pct_of_start`. |
| KPI tiles | gold_patient_cohort | 4 text tiles: COUNT(ptid); % treated = AVG(INT([treated])); median age; median baseline BMI. |
| Age × sex | gold_patient_cohort | Rows `age_group`, Columns COUNT(ptid), Color `gender` (side-by-side bars). |
| Race / ethnicity | gold_patient_cohort | Bar by `race`, color by `ethnicity`, show % of total (Quick table calc → Percent of total). |
| BMI class | gold_patient_cohort | Bar by `bmi_category`. |
| Comorbidities | gold_patient_cohort | Calculated fields: `% T2D = AVG([has_t2d])`, same for each `has_*`. Use Measure Names/Values bar chart. |
| Payer mix | gold_patient_cohort | Bar by `payer_at_index`, color `diabetes_status`. |

**Takeaway text example:** "X adults met the cohort definition; Y% had type 2 diabetes; Z% started treatment."

## 2 · Market Trends

| Sheet | Source | Build |
|---|---|---|
| Monthly fills by product | gold_market_monthly | Columns: `month` (continuous month). Rows: SUM(`fills`). Color: `brand_name`. Area chart (stacked). |
| New-to-brand starts | gold_market_monthly | Same as above with SUM(`new_to_brand_starts`), line chart. |
| Shortage bands | gold_market_events | Filter `event_type` = SHORTAGE. Add as reference **bands** on the time axis: Analytics → Reference Band from `start_date` to `end_date` (use a dual-axis or build the bands with a Gantt bar: start = `start_date`, size = DATEDIFF('day', [start_date], [end_date])). |
| Approval markers | gold_market_events | Filter APPROVAL / GENERIC / COVERAGE. Shape marks on the time axis with tooltip = `description`. |
| Annual share | gold_market_share_annual | Columns `year`, Rows SUM(`fill_share_pct`), Color `brand_name`, 100% stacked bars. |
| Rejection rate | gold_access_annual | Rows `payer`, Columns `year`, color = `rejection_rate_pct` (heatmap) — filter to obesity-indicated brands to show the Medicare effect. |

**Story to tell:** semaglutide/tirzepatide take over the market; shortage periods flatten new starts;
Medicare rejections for weight-loss use; the first generic liraglutide appears in 2024.

## 3 · Treatment Journey

| Sheet | Source | Build |
|---|---|---|
| First product | gold_patient_cohort (treated = TRUE) | Bar by `first_brand`, color by `first_drug_class`. |
| First product over time | gold_patient_cohort | Columns `index_year`, Rows COUNT(ptid), Color `first_brand`, 100% stacked. |
| Top pathways | gold_treatment_pathways | Filter `n_lines` ≥ 1. Rows `pathway`, Columns COUNT(ptid), Top 15 filter by count. |
| Switch matrix | gold_switch_matrix | Rows `from_brand`, Columns `to_brand`, Color/label SUM(`patients`) (highlight table). Tooltip `median_gap_days`. |
| Episode outcomes | gold_treatment_episodes (episode_seq = 1) | Rows `brand_name`, Columns COUNT, Color `episode_outcome`, 100% stacked bar. |

Optional Sankey: build from gold_treatment_pathways (line1 → line2) with the standard Tableau
Public Sankey template (sigmoid curve calculation). The highlight table above is the simpler, robust option.

## 4 · Persistence & Adherence

| Sheet | Source | Build |
|---|---|---|
| Kaplan-Meier curves | gold_persistence_curve | Filter `group_type` = Product (parameter to switch to Payer / Diabetes status / Start year). Columns `day` (continuous), Rows AVG(`pct_persistent`), Color `group_value`, Line (step) mark. Y axis 0–100. |
| 12-month persistence | gold_persistence_summary | Bar `group_value` by `pct_persistent_365d`, sorted, same `group_type` parameter. |
| PDC distribution | gold_adherence | Columns `pdc_band`, Rows COUNT(ptid), Color `brand_name` (or small multiples by brand). |
| % adherent by product | gold_adherence | Bar `brand_name` × AVG(INT([adherent])). |

**Parameter for the curves:** create parameter `Group by` (list: Product, Payer, Diabetes status, Start year)
and calculated field `[group_type] = [Group by]` as a filter.

## 5 · Equity of Access

| Sheet | Source | Build |
|---|---|---|
| Treatment rate with CIs | gold_equity_rates | Filter `population`. Rows `dimension`, `group`. Columns: dual axis — circle at `rate_pct`, and a Gantt bar from `ci_low_pct` with size = `ci_high_pct` − `ci_low_pct`. Color by `significant_gap`. |
| Adjusted odds ratios (forest plot) | gold_equity_adjusted_or | Filter `population`; exclude `index_year`. Rows `variable`, `level`. Columns: circle at `odds_ratio` + Gantt CI bar (start `ci_low`, size `ci_high` − `ci_low`). **Log scale** X axis, reference line at 1. Color by `significant`. |
| Text box | — | Explain: OR < 1 = less likely to be treated than the reference group, after adjusting for the other factors. |

## 6 · Real-World Outcomes

| Sheet | Source | Build |
|---|---|---|
| Weight change by product | gold_outcomes_summary | Filter `time_point` = 12 months. Rows `brand_name`, Columns `mean_pct_weight_change`, Color `view` (All starters vs Persistent), side-by-side bars. |
| Responder bands | gold_outcomes_summary | Measure Names: `pct_lost_5pct_or_more`, `pct_lost_10pct_or_more`, `pct_lost_15pct_or_more` by brand. |
| Distribution | gold_outcomes_patient | Box plot of `pct_weight_change_12m` by `brand_name`. |
| HbA1c change | gold_outcomes_summary | Bar of `mean_hba1c_change` by brand (T2D only). |

Add a visible note: "Effect sizes come from simulation parameters and are not evidence about real products."

## 7 · Data Quality

| Sheet | Source | Build |
|---|---|---|
| Rows in vs out | gold_dq_tables | Rows `silver_table`, Columns `bronze_rows` and `silver_rows` (Measure Values, side-by-side). |
| Problems injected | gold_dq_tables | Bar `bronze_table` by `problems_injected`. |
| Rules applied | gold_dq_rules | Table: `table_name`, `rule`, `rows_affected`, `action`, sorted by rows affected. |

---

## Publish
1. File → Save to Tableau Public (sign in).
2. Copy the public link into the README.
3. Save screenshots of each dashboard to `tableau/screenshots/` (01_cohort.png, 02_market.png, …).
4. Download the workbook (.twbx) from your Tableau Public profile and add it to `tableau/`.
