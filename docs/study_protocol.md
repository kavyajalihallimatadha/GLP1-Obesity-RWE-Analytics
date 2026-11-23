# Study Protocol

**Title:** Treatment patterns, persistence, access and real-world outcomes of GLP-1 receptor agonists and
other anti-obesity medications among US adults with obesity or overweight: a retrospective new-user cohort study

**Version:** 1.0 · **Data:** simulated linked commercial claims + EHR (portfolio project)

> The data analyzed under this protocol is fully simulated. The protocol is written the way a real
> real-world-evidence (RWE) study would be, so the design, definitions and analysis plan can be
> reviewed and reused with real data.

---

## 1. Background and rationale

GLP-1 receptor agonists (semaglutide, liraglutide, dulaglutide) and the dual GIP/GLP-1 receptor agonist
tirzepatide have changed obesity and type 2 diabetes care. Between 2018 and 2025 the US market saw:

- launches of weight-management products (Wegovy, June 2021; Zepbound, November 2023)
- FDA-declared shortages of semaglutide (2022 – February 2025) and tirzepatide (December 2022 – October 2024)
- a CMS change in March 2024 allowing Medicare Part D to cover Wegovy for its cardiovascular indication,
  while weight-loss use stays excluded by law
- the first generic GLP-1 (liraglutide) in 2024 and the first generic of Saxenda in 2025
- new ICD-10-CM obesity class codes from October 1, 2024

These changes affect who gets treated, with which product, for how long, and with what result.
Brand, market-access and medical-affairs teams need real-world evidence on all four questions.
Sources for each fact: [`verified_reference.md`](verified_reference.md).

## 2. Objectives

| Type | Objective |
|---|---|
| **Primary** | Describe the use of GLP-1 RAs and other anti-obesity medications (AOMs) among adults with obesity or overweight + comorbidity, including first-line product choice and how it changed from 2018 to 2025 |
| Secondary 1 | Describe treatment pathways: lines of therapy, switching, discontinuation and restarting |
| Secondary 2 | Estimate persistence (Kaplan-Meier) and adherence (PDC) on the first product |
| Secondary 3 | Describe market dynamics: fills, new-to-brand starts, share, payer rejections, and the impact of shortages and launches |
| Secondary 4 | Assess differences in treatment initiation across demographic and insurance groups, adjusted for clinical need |
| Secondary 5 | Describe real-world percent weight change and HbA1c change at 6 and 12 months by product |

## 3. Study design

Retrospective, observational **new-user cohort** study using linked administrative claims and
electronic health records.

```
   Baseline period                Index date                       Follow-up period
   (180 days)                     (day 0)                          (variable length)
|------------------------------|---------------------------------------------------------------->|
 - continuous coverage           first qualifying                - treatment start, product, line
 - comorbidities (365 d)         obesity / overweight            - persistence, adherence (PDC)
 - baseline BMI (-180 / +30 d)   + comorbidity evidence          - weight / HbA1c change
 - exclusions: T1D, pregnancy,   in 2018-01-01 to 2025-12-31     - bariatric surgery, death
   prior surgery, prior AOM use                                  ends at: coverage end, death,
                                                                 or 2025-12-31 (earliest)
```

## 4. Data source

Simulated linked database with the structure of a commercial claims + EHR research database:

| Component | Content |
|---|---|
| Claims – enrollment | Coverage spans, payer type (Commercial, Medicare, Medicaid), medical and pharmacy coverage flags |
| Claims – medical | Professional and facility claim lines (CPT, place of service), claim diagnoses (ICD-10-CM) |
| Claims – pharmacy | Paid, rejected and reversed pharmacy transactions with 11-digit NDCs, days supply, cost |
| EHR | Patients, encounters, diagnoses with status, prescriptions written, vital signs, labs, procedures |

Data window: 2016-01-01 to 2025-12-31 (2016–2017 used only as baseline look-back).

## 5. Study population

### 5.1 Inclusion criteria
1. **Qualifying evidence** between 2018-01-01 and 2025-12-31 (first date = index):
   - Obesity: ICD-10-CM E66.01, E66.09, E66.8, E66.9, E66.811, E66.812, E66.813, E66.89; BMI Z-codes Z68.30–Z68.45; or measured BMI ≥ 30, **or**
   - Overweight: E66.3, Z68.27–Z68.29, or measured BMI 27–29.9 **with** a weight-related comorbidity
     (type 2 diabetes, hypertension, dyslipidemia, obstructive sleep apnea, ASCVD, MASH, CKD) in the prior 365 days
   - Only EHR diagnoses with status "Diagnosis of" count as qualifying evidence
2. Age ≥ 18 at index
3. Linked claims with continuous medical **and** pharmacy coverage from 180 days before to 180 days after index (gaps ≤ 31 days allowed)

### 5.2 Exclusion criteria
1. Type 1 diabetes (E10.x) at any time
2. Pregnancy (Z33.1) within ±180 days of index
3. Bariatric surgery (CPT 43775, 43644) before index
4. Any GLP-1 RA / AOM fill in the 180-day baseline (**new-user design** – removes prevalent users whose
   early treatment experience happened before the study window)

Attrition at each step is reported (`gold_cohort_attrition`).

## 6. Exposures (treatments of interest)

| Class | Products (brand – molecule) |
|---|---|
| GIP/GLP-1 RA | Mounjaro, Zepbound – tirzepatide |
| GLP-1 RA (semaglutide) | Ozempic, Wegovy (injection); Rybelsus (oral) |
| GLP-1 RA (other) | Victoza, Saxenda, generic liraglutide – liraglutide; Trulicity – dulaglutide |
| Non-GLP-1 AOM | Qsymia – phentermine/topiramate ER; Contrave – naltrexone/bupropion ER |

Identified from pharmacy claims by 11-digit NDC (`ref_ndc`).

| Concept | Definition |
|---|---|
| Treatment initiation | First paid fill of any study product on or after index |
| First-line product | Product of the first fill after index |
| Episode | Run of fills of one product; a new episode starts when a fill comes > 60 days after the previous supply ran out (overlapping supply carried forward) |
| Discontinuation | Supply runs out and no refill within 60 days, before end of follow-up |
| Line of therapy | A new line starts with each new, different product; restarting the same product is re-treatment within the same line |
| Switch | Start of a different product within 60 days of the previous supply running out |

## 7. Outcomes

| Outcome | Definition | Window |
|---|---|---|
| Treatment within 12 months | Initiation within 365 days of index | Patients with ≥ 365 days follow-up |
| Time to treatment | Days from index to first fill | Treated patients |
| Persistence | Days from first fill to discontinuation (censored at end of follow-up) | Up to 365 days |
| Adherence | Proportion of days covered (PDC) by the first product; adherent = PDC ≥ 0.80 | 365 days after first fill; patients with ≥ 365 days follow-up |
| Weight change | % change from baseline weight (−90 to +7 days of first fill) to closest weight at 6 months (150–210 d) and 12 months (330–400 d) | Treated patients with readings |
| HbA1c change | Change in HbA1c (NGSP %), same windows | Treated patients with type 2 diabetes |
| Market measures | Monthly fills, new-to-brand starts (no fill of the product in prior 180 days), new-to-therapy starts, share, rejection rate | All pharmacy claims 2018–2025 |

## 8. Covariates (measured at baseline)

Age group, sex, race, ethnicity, census region and division, payer type and plan product at index,
baseline BMI and BMI class, comorbidities (type 2 diabetes, hypertension, dyslipidemia, OSA, ASCVD,
MASH, CKD), number of comorbidities, index year, index evidence source.

## 9. Statistical analysis plan

| Objective | Analysis |
|---|---|
| Primary | Counts and percentages of treated patients and first-line products, overall and by index year, payer and diabetes status |
| Pathways | Distribution of episode outcomes; most common line 1 → line 2 → line 3 pathways; from → to switch matrix with median gap |
| Persistence | Kaplan-Meier curves overall and by product, payer, diabetes status and start year; % persistent at 90, 180, 365 days; median time on therapy |
| Adherence | Mean PDC and % adherent by product and patient group |
| Market | Monthly trends with approval, shortage, coverage and generic-entry markers; annual share of fills and new starts; rejection rates by payer and product |
| Equity | Crude 12-month initiation rates with 95% Wilson CIs and differences from a reference group; multivariable logistic regression (all covariates above + index year) giving adjusted odds ratios with 95% CIs; run overall and stratified by type 2 diabetes status |
| Outcomes | Mean and median % weight change; % reaching ≥ 5%, ≥ 10%, ≥ 15% loss; mean HbA1c change; shown for all starters and for patients still persistent at the time point |

Groups with fewer than 20–30 patients are suppressed or not modeled.

**Sensitivity analyses (planned):** grace period of 30 and 90 days instead of 60; requiring 12 months
of follow-up for all persistence analyses; using only claims-based diagnoses for cohort entry.

## 10. Data quality management

Raw tables land as text (bronze). Cleaning rules in the silver layer standardize codes, units and
dates, remove duplicates, reversals, impossible values, fills after death and orphan records. Every
rule logs the rows it affected (`dq_log`) and the report compares bronze and silver row counts.
Details: README → *Data quality*.

## 11. Limitations

- **Simulated data:** results demonstrate the method only; they are not evidence about real products, payers or populations.
- **Cash-pay fills are not in claims.** Weight-loss drug use paid out of pocket (common in Medicare before 2024) is missed, so treatment rates are underestimated, most of all for Medicare.
- **Obesity is under-coded.** Cohort entry also uses measured BMI to reduce this, but some eligible patients will be missed.
- **Fills are not use.** A pharmacy fill does not prove the drug was taken.
- **Weight readings are irregular** and only exist when patients visit; outcome analyses include only patients with readings in the windows.
- **Confounding:** the equity model adjusts for measured factors only; unmeasured factors (income, prescriber preference, formulary details) can explain part of any gap.

## 12. Ethics and privacy

No real patient data is used, so no IRB review or data-use agreement is needed. With real data, this
protocol would need an IRB exemption/approval and a data-use agreement, and small cells (< 11
patients) would be suppressed in outputs.

## 13. Deliverables

Databricks pipeline (bronze → silver → gold), gold tables exported for Tableau, seven Tableau Public
dashboards, this protocol, the data dictionary and the verified-facts reference.
