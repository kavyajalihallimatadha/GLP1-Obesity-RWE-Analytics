# Databricks notebook source
# MAGIC %md
# MAGIC # 24 · Gold: Equity of Access to Treatment
# MAGIC
# MAGIC **Business question:** *Are some patient groups less likely to receive treatment, even after
# MAGIC accounting for clinical need and insurance?*
# MAGIC
# MAGIC **Population:** cohort patients with at least 12 months of follow-up.
# MAGIC **Outcome:** started a GLP-1 / anti-obesity medication within 12 months of the index date.
# MAGIC
# MAGIC **Methods**
# MAGIC 1. **Crude treatment rates** by race, ethnicity, sex, age, payer, region, BMI class and diabetes
# MAGIC    status, with 95% Wilson confidence intervals and the difference from a reference group.
# MAGIC 2. **Adjusted odds ratios** from a logistic regression that includes all of those factors together
# MAGIC    plus number of comorbidities and index year, so a gap that remains is not explained by the
# MAGIC    other factors in the model. Run for everyone and separately for patients with / without type 2
# MAGIC    diabetes (coverage rules differ a lot between the two).
# MAGIC
# MAGIC > The simulation contains a built-in access gap, so this analysis is a demonstration of the
# MAGIC > method. The numbers describe the simulated data only.
# MAGIC
# MAGIC **Outputs:** `gold_equity_rates`, `gold_equity_adjusted_or`

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

from math import erfc, sqrt

coh = load_pdf("gold_patient_cohort")
pop = coh[coh["has_12m_followup"] & (coh["payer_at_index"] != "Unknown")].copy()
pop["y"] = pop["treated_within_12m"].astype(int)
pop["index_year"] = pop["index_year"].astype(str)
print(f"eligible for 12-month analysis: {len(pop):,} | treated within 12 months: {pop['y'].mean():.1%}")

DIMENSIONS = {  # dimension -> reference group
    "race": "Caucasian", "ethnicity": "Not Hispanic", "gender": "F", "age_group": "50-64",
    "payer_at_index": "Commercial", "region": "Midwest", "bmi_category": "Class 1 (30-34.9)",
    "diabetes_status": "No type 2 diabetes",
}
POPULATIONS = {"All eligible patients": pop,
               "Type 2 diabetes": pop[pop["diabetes_status"] == "Type 2 diabetes"],
               "No type 2 diabetes": pop[pop["diabetes_status"] == "No type 2 diabetes"]}

# COMMAND ----------

# MAGIC %md ## Crude rates with 95% CIs

# COMMAND ----------

def wilson(k, n, z=1.96):
    if n == 0:
        return np.nan, np.nan
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


rows = []
for pname, d in POPULATIONS.items():
    for dim, ref in DIMENSIONS.items():
        if pname != "All eligible patients" and dim == "diabetes_status":
            continue
        g = d.groupby(dim)["y"].agg(["sum", "count"])
        if ref not in g.index:
            continue
        pr = g.loc[ref, "sum"] / g.loc[ref, "count"]
        nr = g.loc[ref, "count"]
        for lvl, (k, n) in g.iterrows():
            p = k / n
            lo, hi = wilson(k, n)
            se = sqrt(p * (1 - p) / n + pr * (1 - pr) / nr)
            rows.append({"population": pname, "dimension": dim, "group": str(lvl), "patients": int(n), "treated": int(k),
                         "rate_pct": round(100 * p, 1), "ci_low_pct": round(100 * lo, 1), "ci_high_pct": round(100 * hi, 1),
                         "reference_group": ref, "is_reference": lvl == ref,
                         "diff_vs_ref_pct_pts": round(100 * (p - pr), 1),
                         "diff_ci_low": round(100 * (p - pr - 1.96 * se), 1), "diff_ci_high": round(100 * (p - pr + 1.96 * se), 1)})
rates = pd.DataFrame(rows)
rates["significant_gap"] = (~rates["is_reference"]) & ((rates["diff_ci_high"] < 0) | (rates["diff_ci_low"] > 0))
save_pdf(rates, "gold_equity_rates")
display(rates[(rates["population"] == "All eligible patients")])

# COMMAND ----------

# MAGIC %md ## Adjusted odds ratios (logistic regression, fitted with IRLS in NumPy)

# COMMAND ----------

def design(d, dims, refs):
    cols, names = [np.ones(len(d))], [("Intercept", "", "")]
    for dim in dims:
        for lvl in sorted(d[dim].astype(str).unique()):
            if lvl == refs[dim]:
                continue
            cols.append((d[dim].astype(str) == lvl).to_numpy(float))
            names.append((dim, lvl, refs[dim]))
    cols.append(d["n_comorbidities"].to_numpy(float))
    names.append(("n_comorbidities", "per additional condition", "0"))
    return np.column_stack(cols), names


def logit_irls(X, y, iters=50, tol=1e-8):
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        eta = X @ beta
        p = 1 / (1 + np.exp(-eta))
        w = np.clip(p * (1 - p), 1e-9, None)
        z = eta + (y - p) / w
        xtwx = X.T @ (w[:, None] * X)
        new = np.linalg.solve(xtwx, X.T @ (w * z))
        if np.max(np.abs(new - beta)) < tol:
            beta = new
            break
        beta = new
    cov = np.linalg.inv(xtwx)
    return beta, np.sqrt(np.diag(cov))


or_rows = []
for pname, d in POPULATIONS.items():
    dims = [k for k in DIMENSIONS if not (pname != "All eligible patients" and k == "diabetes_status")] + ["index_year"]
    refs = dict(DIMENSIONS, index_year=sorted(d["index_year"].unique())[0])
    # drop levels too small to estimate
    keep = np.ones(len(d), dtype=bool)
    for dim in dims:
        small = d[dim].value_counts()
        keep &= ~d[dim].isin(small[small < 30].index).to_numpy()
    dd = d[keep]
    X, names = design(dd, dims, refs)
    beta, se = logit_irls(X, dd["y"].to_numpy(float))
    for (var, lvl, ref), b, s in zip(names, beta, se):
        if var == "Intercept":
            continue
        zval = b / s
        or_rows.append({"population": pname, "variable": var, "level": lvl, "reference": ref,
                        "odds_ratio": round(float(np.exp(b)), 3), "ci_low": round(float(np.exp(b - 1.96 * s)), 3),
                        "ci_high": round(float(np.exp(b + 1.96 * s)), 3), "p_value": float(erfc(abs(zval) / sqrt(2))),
                        "patients_in_model": len(dd)})
ors = pd.DataFrame(or_rows)
ors["significant"] = ors["p_value"] < 0.05
save_pdf(ors, "gold_equity_adjusted_or")
display(ors[(ors["population"] == "All eligible patients")])
