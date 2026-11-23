# Verified Reference Facts

All patient-level data in this project is **simulated**. The facts below are real-world rules
(approval dates, codes, coverage policy, shortage periods) used to make the simulated data
behave like real claims + EHR data. Each fact was checked against a public source.

Study window: **2018-01-01 to 2025-12-31**.

---

## 1. Products in scope

| Brand | Generic (molecule) | Manufacturer | Main US use | First US approval | Source |
|---|---|---|---|---|---|
| Victoza | liraglutide 1.8 mg | Novo Nordisk | Type 2 diabetes | Jan 2010 | TechTarget GLP-1 overview |
| Saxenda | liraglutide 3.0 mg | Novo Nordisk | Chronic weight management | Dec 2014 | TechTarget GLP-1 overview |
| Trulicity | dulaglutide | Eli Lilly | Type 2 diabetes | Sep 2014 | TechTarget; Trulicity label |
| Ozempic | semaglutide (injection) | Novo Nordisk | Type 2 diabetes | Dec 5, 2017 | Drugs.com approval history |
| Rybelsus | semaglutide (oral) | Novo Nordisk | Type 2 diabetes | Sep 2019 | TechTarget; Rybelsus label |
| Wegovy | semaglutide 2.4 mg | Novo Nordisk | Chronic weight management | Jun 4, 2021 | Drugs.com; Drugs@FDA N215256 |
| Mounjaro | tirzepatide | Eli Lilly | Type 2 diabetes | 2022 | FDA label ("Initial U.S. Approval: 2022") |
| Zepbound | tirzepatide | Eli Lilly | Chronic weight management | Nov 2023 | GLP-1 approval timelines |
| Qsymia | phentermine/topiramate ER | Vivus | Chronic weight management | 2012 | Qsymia label |
| Contrave | naltrexone/bupropion ER | Nalpropion | Chronic weight management | 2014 | PMC review; Contrave label |
| Generic liraglutide | liraglutide | Hikma / Teva and others | T2D (Victoza generic) | First generic approved Dec 2024; authorized generic launched Jun 2024 | FDA press release; Healio |
| Generic liraglutide (Saxenda generic) | liraglutide 3.0 mg | Teva | Weight management | Aug 2025 | Healio; Pharmacy Times |

## 2. Market and policy events built into the simulation

| Event | Date | Source |
|---|---|---|
| Wegovy shortage begins | Mar 2022 | FDA declaratory order (semaglutide) |
| Ozempic shortage begins | Aug 2022 | FDA declaratory order (semaglutide) |
| Tirzepatide (Mounjaro/Zepbound) shortage begins | Dec 15, 2022 | FDA declaratory order (tirzepatide) |
| Tirzepatide shortage resolved | Oct 2, 2024 (re-confirmed Dec 19, 2024) | FDA declaratory order (tirzepatide) |
| Semaglutide injection shortage resolved | Feb 21, 2025 | FDA statement |
| Wegovy cardiovascular-risk indication | Mar 8, 2024 | Healio |
| Medicare Part D may cover Wegovy for the CV indication only (weight-loss use still excluded by law) | Mar 2024 | CMS guidance reported by Healio, NPR, Managed Healthcare Executive |
| Zepbound obstructive sleep apnea indication | 2024 | FDA label |
| New ICD-10-CM obesity class codes effective | Oct 1, 2024 | CDC fact sheet |

**Outside the window (README only, not simulated):** oral Wegovy tablets (approved Dec 22, 2025, launched 2026),
orforglipron (Foundayo), 2026 Medicare obesity coverage changes.

## 3. NDC codes used (FDA labeled 10-digit -> 11-digit billing format)

Claims data uses the 11-digit 5-4-2 format. The FDA label uses 10 digits; the billing format pads the short segment with a zero.

| Brand | Strength / pack | Labeled NDC | 11-digit NDC | Source |
|---|---|---|---|---|
| Wegovy | 0.25 mg/0.5 mL, 4 pens | 0169-4525-14 | 00169452514 | DailyMed |
| Wegovy | 0.5 mg/0.5 mL, 4 pens | 0169-4505-14 | 00169450514 | DailyMed |
| Wegovy | 1 mg/0.5 mL, 4 pens | 0169-4501-14 | 00169450114 | McKesson catalog / DailyMed |
| Wegovy | 1.7 mg/0.75 mL, 4 pens | 0169-4517-14 | 00169451714 | DailyMed list (remaining single-dose pen strength) |
| Wegovy | 2.4 mg/0.75 mL, 4 pens | 0169-4524-14 | 00169452414 | DailyMed / ndclist |
| Zepbound | 2.5 mg pen x4 | 0002-2506-80 | 00002250680 | Lilly PA resource guide |
| Zepbound | 5 mg pen x4 | 0002-2495-80 | 00002249580 | Lilly PA resource guide |
| Zepbound | 7.5 mg pen x4 | 0002-2484-80 | 00002248480 | Lilly PA resource guide |
| Zepbound | 10 mg pen x4 | 0002-2471-80 | 00002247180 | Lilly PA resource guide |
| Zepbound | 12.5 mg pen x4 | 0002-2460-80 | 00002246080 | Lilly PA resource guide |
| Zepbound | 15 mg pen x4 | 0002-2457-80 | 00002245780 | Lilly PA resource guide |
| Mounjaro | 2.5 mg pen x4 | 0002-1506-80 | 00002150680 | Lilly WAC disclosure sheet |
| Mounjaro | 5 mg pen x4 | 0002-1495-80 | 00002149580 | Lilly WAC disclosure sheet |
| Mounjaro | 7.5 mg pen x4 | 0002-1484-80 | 00002148480 | Lilly WAC disclosure sheet |
| Mounjaro | 10 mg pen x4 | 0002-1471-80 | 00002147180 | Lilly WAC disclosure sheet |
| Mounjaro | 12.5 mg pen x4 | 0002-1460-80 | 00002146080 | Lilly WAC disclosure sheet |
| Mounjaro | 15 mg pen x4 | 0002-1457-80 | 00002145780 | Lilly WAC disclosure sheet |
| Ozempic | 0.25/0.5 mg pen (2 mg/3 mL) | 0169-4181-13 | 00169418113 | Novo prescribing page |
| Ozempic | 1 mg pen (4 mg/3 mL) | 0169-4130-13 | 00169413013 | Maryland PDAB NDC list |
| Ozempic | 2 mg pen (8 mg/3 mL) | 0169-4772-12 | 00169477212 | Novo prescribing page |
| Rybelsus | 3 mg x30 | 0169-4303-30 | 00169430330 | Novo pharmacist page |
| Rybelsus | 7 mg x30 | 0169-4307-30 | 00169430730 | Novo pharmacist page |
| Rybelsus | 14 mg x30 | 0169-4314-30 | 00169431430 | Novo pharmacist page |
| Trulicity | 0.75 mg pen x4 | 0002-1433-80 | 00002143380 | Trulicity label |
| Trulicity | 1.5 mg pen x4 | 0002-1434-80 | 00002143480 | Trulicity label |
| Trulicity | 3 mg pen x4 | 0002-2236-80 | 00002223680 | Trulicity label |
| Trulicity | 4.5 mg pen x4 | 0002-3182-80 | 00002318280 | Trulicity label |
| Victoza | 2-pen pack | 0169-4060-12 | 00169406012 | Novo pharmacist page |
| Victoza | 3-pen pack | 0169-4060-13 | 00169406013 | Novo pharmacist page |
| Saxenda | 5-pen carton | 0169-2800-15 | 00169280015 | FDA SPL |
| Liraglutide (generic, Hikma) | 3 pens | 0143-9144-03 | 00143914403 | openFDA listing / McKesson |
| Liraglutide (authorized generic, Teva) | 2 pens | 0480-3667-20 (as 00480-3667-20) | 00480366720 | Teva catalog |
| Liraglutide (Saxenda generic, Teva) | 5 pens | 0480-7250-46 (as 00480-7250-46) | 00480725046 | Teva catalog |
| Qsymia | 7.5 mg/46 mg x30 | 62541-201-30 | 62541020130 | ndclist (FDA) |
| Contrave | 8 mg/90 mg x120 | 51267-890-99 | 51267089099 | FDA label (ndclist) |

## 4. Diagnosis codes (ICD-10-CM)

| Code | Meaning | Note |
|---|---|---|
| E66.811 / E66.812 / E66.813 | Obesity class 1 / 2 / 3 | New Oct 1, 2024 (CDC, AAPC) |
| E66.89 | Other obesity not elsewhere classified | New Oct 1, 2024 |
| E66.01, E66.09, E66.8, E66.9 | Older obesity codes | CDC asks coders to move from these to the new codes |
| E66.3 | Overweight | |
| Z68.25-Z68.29, Z68.30-Z68.39, Z68.41-Z68.45 | Adult BMI codes | Used together with E66 codes |
| E11.x | Type 2 diabetes | |
| E10.x | Type 1 diabetes | Exclusion |
| I10 | Essential hypertension | Comorbidity |
| E78.5 | Hyperlipidemia, unspecified | Comorbidity |
| G47.33 | Obstructive sleep apnea | Comorbidity |
| I25.10 | Atherosclerotic heart disease | Established CVD |
| K75.81 | Nonalcoholic steatohepatitis | Comorbidity |
| N18.3x | Chronic kidney disease stage 3 | Comorbidity |
| Z33.1 | Pregnant state, incidental | Exclusion |

## 5. Procedure and lab codes

| Code | Meaning | Source |
|---|---|---|
| CPT 43775 | Laparoscopic sleeve gastrectomy | AAPC; ASMBS code list |
| CPT 43644 | Laparoscopic Roux-en-Y gastric bypass (limb <=150 cm) | AAPC; ASMBS code list |
| LOINC 4548-4 | Hemoglobin A1c (NGSP, %) - US reporting | LOINC |
| LOINC 59261-8 | Hemoglobin A1c (IFCC, mmol/mol) | LOINC |
| LOINC 39156-5 | Body mass index | HL7 US Core vital signs |
| LOINC 29463-7 | Body weight | HL7 US Core vital signs |

## 6. Label facts used for dose escalation

- Wegovy: 0.25 -> 0.5 -> 1 -> 1.7 -> 2.4 mg, every 4 weeks (Wegovy label / EMA SmPC)
- Zepbound / Mounjaro: start 2.5 mg for 4 weeks, +2.5 mg steps every >=4 weeks, max 15 mg (labels)
- Rybelsus: 3 mg for 30 days -> 7 mg -> optional 14 mg (label)
- Zepbound eligibility: BMI >=30, or BMI >=27 with >=1 weight-related comorbidity (Lilly stocking guide)

## 7. What is a simulation assumption (NOT a real-world finding)

Treatment rates, disparity effects, persistence, weight-loss amounts, costs and copays are
**parameters chosen for the simulation**. They exist so the analysis has realistic structure
to find. They must never be quoted as real-world results.
