# Data Dictionary

All tables live in the `glp1_rwe` schema. Layers: `ref_*` → `sim_*` → `bronze_*` → `silver_*` → `gold_*`.

---

## Gold tables (used by Tableau)

### gold_cohort_attrition — one row per cohort step
| Column | Description |
|---|---|
| step | 0–7 |
| step_label | Rule applied at this step |
| patients | Patients remaining |
| removed | Patients removed at this step |
| pct_of_start | Patients remaining as % of all patients |

### gold_patient_cohort — one row per cohort patient
| Column | Description |
|---|---|
| ptid | Patient ID |
| index_date, index_year | First qualifying obesity / overweight + comorbidity date |
| index_source | What qualified the patient (diagnosis code, BMI Z-code, measured BMI, overweight + comorbidity) |
| followup_end, followup_days | End of continuous coverage, death, or 2025-12-31 (earliest) |
| age_at_index, age_group | Age and band (18-34, 35-49, 50-64, 65-74, 75+) |
| gender, race, ethnicity, region, division | Demographics (standardized) |
| payer_code, payer_at_index, plan_product | Insurance at index (Commercial / Medicare / Medicaid) |
| baseline_bmi, baseline_weight_kg, bmi_category | Closest reading −180 to +30 days around index |
| has_t2d … has_ckd, n_comorbidities, diabetes_status | Comorbidities in the 365 days before index (+30) |
| treated | Any GLP-1 / anti-obesity fill during follow-up |
| first_fill_date, days_to_treatment | First fill after index and days from index |
| first_product_key, first_brand, first_molecule, first_drug_class, first_indication_group | First product used |
| n_products_used, n_fills | Distinct products and fills in follow-up |
| has_12m_followup, treated_within_12m | Used by the equity analysis |
| bariatric_surgery_after_index, surgery_date | Bariatric surgery during follow-up |
| died_in_followup | Death recorded during follow-up |

### gold_treatment_episodes — one row per continuous use of one product
| Column | Description |
|---|---|
| episode_seq | Order of the episode for the patient |
| line_number | Line of therapy (new line = different product) |
| product_key, brand_name, molecule, drug_class, indication_group | Product |
| payer_at_start | Payer on the first fill of the episode |
| start_date, supply_end_date | First fill; date the last supply ran out |
| n_fills, days_supplied, max_dose_step | Fill count, total days supplied, highest label dose step reached |
| days_on_therapy | Days from start to supply end (capped at follow-up end) |
| discontinued | Supply ran out + 60 days before end of follow-up |
| next_brand, gap_to_next_days | Next product and gap |
| episode_outcome | Still on treatment / switched / stopped then started another / stopped then restarted / stopped |

### gold_treatment_pathways — one row per cohort patient
`line1`, `line2`, `line3` (brand or "No treatment" / "No further line"), `n_lines`, `pathway` (e.g. "Saxenda > Wegovy"), plus payer, diabetes status and index year for filtering.

### gold_switch_matrix — one row per from → to product transition
`from_line`, `from_brand`, `to_brand`, `patients`, `median_gap_days`

### gold_persistence_curve — Kaplan-Meier curve points
`group_type` (Overall / Product / Payer / Diabetes status / Start year), `group_value`, `day` (0–365), `pct_persistent`, `n_at_risk`

### gold_persistence_summary
`group_type`, `group_value`, `patients`, `pct_persistent_90d`, `pct_persistent_180d`, `pct_persistent_365d`, `median_days_persistent`

### gold_adherence — one row per patient with 365 days of follow-up after first fill
`pdc` (0–1), `adherent` (PDC ≥ 0.80), `pdc_band`, `fills_in_window`, product and patient attributes

### gold_market_monthly — month × product × payer
`month`, `brand_name`, `molecule`, `drug_class`, `indication_group`, `is_generic`, `payer`, `fills`, `patients`,
`new_to_brand_starts`, `new_to_therapy_starts`, `total_cost`, `total_copay` (cost and copay are simulated)

### gold_market_share_annual
`year`, `brand_name`, `drug_class`, `fills`, `nbrx`, `fill_share_pct`, `new_start_share_pct`

### gold_access_annual — year × product × payer
`new_starts`, `rejected_prior_auth` (reject code 75), `rejected_not_covered` (reject code 70), `rejected_total`, `rejection_rate_pct`

### gold_market_events — for reference lines on time charts
`event_type` (SHORTAGE / COVERAGE / CODING / GENERIC / APPROVAL), `brand_name`, `description`, `start_date`, `end_date`

### gold_equity_rates
`population` (All / Type 2 diabetes / No type 2 diabetes), `dimension`, `group`, `patients`, `treated`, `rate_pct`,
`ci_low_pct`, `ci_high_pct`, `reference_group`, `is_reference`, `diff_vs_ref_pct_pts`, `diff_ci_low`, `diff_ci_high`, `significant_gap`

### gold_equity_adjusted_or
`population`, `variable`, `level`, `reference`, `odds_ratio`, `ci_low`, `ci_high`, `p_value`, `significant`, `patients_in_model`

### gold_outcomes_patient — one row per treated patient (first product)
`weight_baseline`, `weight_6m`, `weight_12m`, `hba1c_baseline`, `hba1c_6m`, `hba1c_12m`, `pct_weight_change_6m`, `pct_weight_change_12m`,
`hba1c_change_6m`, `hba1c_change_12m`, `persistent_at_6m`, `persistent_at_12m`, product and patient attributes

### gold_outcomes_summary
`time_point`, `view` (All starters / Persistent), `brand_name`, `patients`, `mean_pct_weight_change`, `median_pct_weight_change`,
`pct_lost_5pct_or_more`, `pct_lost_10pct_or_more`, `pct_lost_15pct_or_more`, `t2d_patients_with_hba1c`, `mean_hba1c_change`

### gold_dq_tables / gold_dq_rules
Bronze vs silver row counts and problems injected per table; every cleaning rule with rows affected and action taken.

---

## Silver tables

| Table | Grain | Notes |
|---|---|---|
| silver_patient | patient | standardized demographics, death date |
| silver_provider / silver_claims_provider | provider | standardized specialty |
| silver_enrollment_spans | coverage span | parsed, swapped dates fixed, overlaps merged |
| silver_enrollment_continuous | continuous medical + pharmacy coverage period | gaps ≤ 31 days bridged |
| silver_insurance_ehr | EHR payer record | |
| silver_encounter | encounter | |
| silver_diagnosis | diagnosis (EHR + claims) | `icd10_code`, `icd10_nodot`, `category`, `dx_status`, `source` |
| silver_med_claims | medical claim line | `is_adjustment` flag |
| silver_vitals | patient × encounter × date | `weight_kg`, `bmi`, `height_cm`, `bmi_source` |
| silver_hba1c | lab result | `hba1c_pct` (NGSP %) |
| silver_bariatric_surgery | surgery | `found_in` = EHR / CLAIMS / both |
| silver_rx_fills | paid, non-reversed fill | 11-digit NDC, product attributes, cleaned days supply |
| silver_rx_rejections | rejected pharmacy claim | `reject_code` |
| silver_rx_written | prescription order | product matched by NDC or name |
| dq_log | cleaning rule | rows affected and action |

---

## Reference tables

`ref_product`, `ref_ndc`, `ref_icd10`, `ref_procedure`, `ref_loinc`, `ref_geography`, `ref_market_events`, `ref_specialty` —
see `notebooks/01_reference/01_reference_codes` and `docs/verified_reference.md`.
