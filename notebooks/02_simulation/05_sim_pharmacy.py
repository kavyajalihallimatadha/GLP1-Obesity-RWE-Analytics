# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · Simulate Treatment: Prescriptions Written and Pharmacy Claims
# MAGIC
# MAGIC This is the core of the market simulation. For each patient it decides **whether**, **when** and
# MAGIC **with what** obesity / GLP-1 treatment they start, and then simulates every pharmacy fill.
# MAGIC
# MAGIC **Real-world rules applied (verified, see `docs/verified_reference.md`)**
# MAGIC - A product can only be filled after its US approval / availability date
# MAGIC - Dose escalation follows each label's NDC sequence (e.g. Wegovy 0.25 → 0.5 → 1 → 1.7 → 2.4 mg)
# MAGIC - FDA shortage periods (semaglutide 2022–Feb 2025, tirzepatide Dec 2022–Oct 2024) reduce new starts
# MAGIC   and cause gaps between fills
# MAGIC - Medicare Part D cannot pay for weight-loss use; from 2024-03-08 Wegovy can be covered for the
# MAGIC   cardiovascular indication only (patients with heart disease). Other Medicare weight-loss use is
# MAGIC   cash-pay, so it appears in EHR prescriptions but **not** in pharmacy claims
# MAGIC
# MAGIC **Simulation parameters (assumptions, not real statistics):** uptake by year, payer and
# MAGIC demographic multipliers (including a built-in access gap by race/ethnicity so the equity
# MAGIC analysis has something to detect), discontinuation hazards, switching probabilities, costs.
# MAGIC
# MAGIC **Outputs**
# MAGIC - `sim_rx_fill_truth` – every fill including cash-pay (answer key)
# MAGIC - `sim_claims_rx` – pharmacy claims (paid + rejected) in Market Clarity Rx layout
# MAGIC - `sim_rx_written` – EHR **Prescriptions Written** (includes prescriptions never filled)

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

rng = np.random.default_rng(SEED + 5)
truth = load_pdf("sim_patient_truth")
enroll = load_pdf("sim_member_enrollment")
prov = load_pdf("sim_provider")
products = load_pdf("ref_product").set_index("product_key")
ndc = load_pdf("ref_ndc")
events = load_pdf("ref_market_events")

END = pd.Timestamp(STUDY_END)
CV_COVERAGE = pd.Timestamp("2024-03-08")

shortages = {r.product_key: (r.start_date, r.end_date)
             for r in events[events["event_type"] == "SHORTAGE"].itertuples()}
ndc_by_step = {(r.product_key, r.dose_step): r for r in ndc.itertuples()}
max_step = ndc.groupby("product_key")["dose_step"].max().to_dict()

spans_by_pt = {k: g.sort_values("Eligeff").to_dict("records") for k, g in enroll.groupby("PTID")}

# COMMAND ----------

# MAGIC %md ## Simulation parameters

# COMMAND ----------

T2D_PRODUCTS = {"VICTOZA": 14, "TRULICITY": 26, "OZEMPIC": 34, "RYBELSUS": 10, "MOUNJARO": 40,
                "LIRA_GEN_T2D": 12, "WEGOVY": 6, "ZEPBOUND": 6}
OBESITY_PRODUCTS = {"SAXENDA": 22, "QSYMIA": 18, "CONTRAVE": 18, "WEGOVY": 60, "ZEPBOUND": 75,
                    "LIRA_GEN_WM": 12, "OZEMPIC": 10, "MOUNJARO": 8}   # Ozempic/Mounjaro here = off-label use

UPTAKE_T2D = {2016: .55, 2017: .6, 2018: .7, 2019: .75, 2020: .8, 2021: .9, 2022: 1.0, 2023: 1.05, 2024: 1.1, 2025: 1.1}
UPTAKE_OB = {2016: .25, 2017: .28, 2018: .3, 2019: .33, 2020: .36, 2021: .55, 2022: .75, 2023: .95, 2024: 1.1, 2025: 1.15}

RACE_MULT = {"Caucasian": 1.0, "African American": 0.78, "Asian": 0.92, "Other/Unknown": 0.90}
ETH_MULT = {"Not Hispanic": 1.0, "Hispanic": 0.85, "Unknown": 0.95}
REGION_MULT = {"Northeast": 1.05, "Midwest": 1.0, "South": 0.95, "West": 1.0}

HAZARD = {"ZEPBOUND": .045, "MOUNJARO": .035, "WEGOVY": .060, "OZEMPIC": .040, "RYBELSUS": .070,
          "TRULICITY": .045, "VICTOZA": .070, "SAXENDA": .100, "LIRA_GEN_T2D": .070, "LIRA_GEN_WM": .090,
          "QSYMIA": .110, "CONTRAVE": .120}
MAINT = {"WEGOVY": {5: .8, 4: .2}, "ZEPBOUND": {2: .25, 4: .35, 6: .40}, "MOUNJARO": {2: .25, 4: .35, 6: .40},
         "OZEMPIC": {1: .3, 2: .45, 3: .25}, "RYBELSUS": {2: .55, 3: .45}, "TRULICITY": {2: .5, 3: .3, 4: .2},
         "VICTOZA": {1: .4, 2: .6}, "LIRA_GEN_T2D": {1: .4, 2: .6}}
COST = {"WEGOVY": 1050, "ZEPBOUND": 1000, "MOUNJARO": 1010, "OZEMPIC": 900, "RYBELSUS": 880, "TRULICITY": 860,
        "VICTOZA": 1100, "SAXENDA": 1250, "LIRA_GEN_T2D": 380, "LIRA_GEN_WM": 520, "QSYMIA": 190, "CONTRAVE": 560}
FREQ = {"Oral": "once daily", "SC": "once weekly"}
DAILY_SC = {"VICTOZA", "SAXENDA", "LIRA_GEN_T2D", "LIRA_GEN_WM"}


def in_shortage(pk, d):
    s = shortages.get(pk)
    return s is not None and s[0] <= d <= (s[1] if pd.notna(s[1]) else END)


def span_at(pt, d):
    for s in spans_by_pt.get(pt, []):
        if s["Eligeff"] <= d <= s["Eligend"]:
            return s
    return None


def product_weights(d, t2d, bus, ascvd, cash):
    base = T2D_PRODUCTS if t2d else OBESITY_PRODUCTS
    keys, w = [], []
    y = d.year
    for pk, b in base.items():
        if d < products.loc[pk, "avail_date"]:
            continue
        f = b
        if pk == "VICTOZA":
            f *= max(0.2, 1 - 0.15 * (y - 2018))
        if pk == "TRULICITY" and y >= 2022:
            f *= {2022: .8, 2023: .6, 2024: .5}.get(y, .45)
        if pk == "SAXENDA" and d >= pd.Timestamp("2021-06-05"):
            f *= .45 if y < 2023 else .3
        if pk in ("QSYMIA", "CONTRAVE") and y >= 2022:
            f *= {2022: .6, 2023: .45}.get(y, .4)
        if pk == "OZEMPIC":
            f *= {2018: .6, 2019: .8}.get(y, 1.0)
        if not t2d and pk in ("OZEMPIC", "MOUNJARO"):
            f *= {2022: 1.5, 2023: 1.5, 2024: .5, 2025: .4}.get(y, 1.0)
        if in_shortage(pk, d):
            f *= 0.45
        if not t2d and bus == "MCR" and not cash:
            f *= 1.0 if (pk == "WEGOVY") else 0.0       # only Wegovy (CV indication) is a Part D drug
        if not t2d and bus == "MCD" and pk in ("WEGOVY", "ZEPBOUND"):
            f *= 0.6
        if f > 0:
            keys.append(pk); w.append(f)
    return keys, np.array(w) / np.sum(w) if w else None

# COMMAND ----------

# MAGIC %md ## Who starts treatment, and when

# COMMAND ----------

N = len(truth)
idx_date = truth["first_obesity_date"]
end_obs = pd.to_datetime(np.minimum(truth["ehr_end"].values, END.to_datetime64()))
comorb = truth[["htn", "dyslip", "t2d", "osa", "ascvd"]].any(axis=1)
indicated = (truth["bmi_class"] != "OW") | comorb

lag = rng.exponential(240, N).astype(int)
start = idx_date + pd.to_timedelta(lag, unit="D")

decisions = []
for i in range(N):
    t = truth.iloc[i]
    s_date = start.iloc[i]
    if s_date > end_obs[i] or t["t1d"]:
        decisions.append(("NONE", None, None, False)); continue
    sp = None if t["ehr_only"] else span_at(t["ptid"], s_date)
    bus = sp["Bus"] if sp else "NONE"
    y = s_date.year
    if t["t2d"]:
        p = 0.55 * UPTAKE_T2D[y]
        p *= {"COM": 1.0, "MCD": .85, "MCR": .90, "NONE": .40}[bus]
    else:
        p = (0.38 if indicated.iloc[i] else 0.06) * UPTAKE_OB[y]
        if bus == "MCR":
            p *= (0.70 if (t["ascvd"] and s_date >= CV_COVERAGE) else 0.12)
        else:
            p *= {"COM": 1.0, "MCD": .60, "NONE": .35}[bus]
    p *= RACE_MULT[t["race"]] * ETH_MULT[t["ethnicity"]] * REGION_MULT[t["region"]]
    p *= 1.10 if t["sex"] == "F" else 1.0
    p *= 0.70 if (y - t["birth_yr"]) >= 75 else 1.0
    if t["pharmacy_cov"] == "N":
        p *= 0.30
    p = min(p, 0.90)
    u = rng.random()
    if u < p:
        decisions.append(("TREATED", s_date, bus, True))
    elif u < p * 1.5:
        decisions.append(("ABANDONED", s_date, bus, False))      # prescribed but never filled
    else:
        decisions.append(("NONE", None, None, False))

dec = pd.DataFrame(decisions, columns=["status", "start", "bus_at_start", "treated"])
display(dec["status"].value_counts())

# COMMAND ----------

# MAGIC %md ## Fill-by-fill simulation

# COMMAND ----------

prov_by_region = {r: g for r, g in prov.groupby("region")}
fills, written, rejects = [], [], []
fill_seq = 0


def prescriber(t):
    g = prov_by_region[t["region"]]
    if t["t2d"] and rng.random() < 0.30:
        return rng.choice(g.loc[g["specialty"] == "Endocrinology", "provid"].to_numpy())
    return t["pcp"]


def write_rx(t, pk, step, d, provid, num_refills, disc_reason=None):
    r = ndc_by_step[(pk, step)]
    prod = products.loc[pk]
    written.append({
        "PtId": t["ptid"], "RX_date": d - pd.Timedelta(days=int(rng.integers(0, 8))),
        "RxTime": f"{rng.integers(8, 18):02d}:{rng.integers(0, 60):02d}",
        "Drug_name": f"{prod['brand_name']} {r.strength}", "NDC": r.ndc_labeled, "NDC_source": "Prescribed",
        "Provid": provid, "Route": "SUBCUTANEOUS" if prod["route"] == "SC" else "ORAL",
        "Quantity_of_dose": 1, "Strength": r.strength, "Strength_unit": None,
        "Dosage_form": "INJECTION, SOLUTION" if prod["route"] == "SC" else ("CAPSULE" if pk == "QSYMIA" else "TABLET"),
        "Daily_dose": None,
        "Dose_frequency": "once daily" if pk in DAILY_SC else ("twice daily" if pk == "CONTRAVE" else FREQ[prod["route"]]),
        "Quantity_per_fill": r.package_qty, "Num_refills": num_refills, "Days_supply": int(prod["days_supply"]),
        "Generic_desc": prod["generic_name"], "Drug_class": prod["drug_class"],
        "Discontinue_Reason": disc_reason, "NDC_Mapped_Attributes": None, "SourceID": "EHR",
    })


for i in np.flatnonzero(dec["status"].to_numpy() != "NONE"):
    t = truth.iloc[i]
    d = dec.at[i, "start"]
    stop_at = end_obs[i]
    provid = prescriber(t)

    if dec.at[i, "status"] == "ABANDONED":
        sp = None if t["ehr_only"] else span_at(t["ptid"], d)
        keys, w = product_weights(d, t["t2d"], sp["Bus"] if sp else "NONE", t["ascvd"], cash=True)
        if keys:
            pk = rng.choice(keys, p=w)
            write_rx(t, pk, 1, d, provid, int(rng.integers(0, 6)))
            if sp and sp["Pharmacy_coverage_ind"] == "Y" and rng.random() < 0.5:
                code = "70" if (sp["Bus"] == "MCR" and not t["t2d"] and pk != "WEGOVY") else "75"
                rejects.append((t, sp, pk, 1, d, code))
        continue

    n_ep, used = 0, set()
    while d <= stop_at and n_ep < 4:
        sp = None if t["ehr_only"] else span_at(t["ptid"], d)
        bus = sp["Bus"] if sp else "NONE"
        cov_ok = sp is not None and sp["Pharmacy_coverage_ind"] == "Y"
        mcr_block = (bus == "MCR") and not t["t2d"] and not (t["ascvd"] and d >= CV_COVERAGE)
        cash = (not cov_ok) or mcr_block
        keys, w = product_weights(d, t["t2d"], bus, t["ascvd"], cash)
        if not keys:
            break
        if used and rng.random() < 0.8:                    # switches go to a different product
            k2 = [k for k in keys if k not in used]
            if k2:
                w2 = np.array([w[keys.index(k)] for k in k2]); keys, w = k2, w2 / w2.sum()
        pk = rng.choice(keys, p=w)
        used.add(pk)
        n_ep += 1
        ep_id = f"{t['ptid']}_{n_ep}"
        mx = max_step[pk]
        maint = rng.choice(list(MAINT[pk]), p=list(MAINT[pk].values())) if pk in MAINT else mx
        ds = int(products.loc[pk, "days_supply"])
        step, n_fill, last_step_written = 1, 0, 0
        # prior-authorization rejection before the first paid fill (commercial weight-loss drugs)
        if not cash and bus == "COM" and not t["t2d"] and rng.random() < 0.15:
            rejects.append((t, sp, pk, 1, d - pd.Timedelta(days=int(rng.integers(3, 20))), "75"))
        discontinued = False
        while d <= stop_at:
            if step != last_step_written:
                write_rx(t, pk, step, d, provid, int(rng.integers(0, 12)))
                last_step_written = step
            fill_seq += 1
            fills.append((t["ptid"], i, ep_id, n_ep, pk, step, d, ds, cash, provid, n_fill))
            n_fill += 1
            if step < maint:
                step += 1
            short = in_shortage(pk, d)
            h = HAZARD[pk] * (1.6 if n_fill <= 3 else 1.0) * (1.6 if cash else 1.0) * (1.4 if short else 1.0)
            h *= 0.85 if t["t2d"] else (1.25 if bus in ("MCD", "MCR") else 1.0)
            if rng.random() < h:
                discontinued = True
                break
            late = rng.gamma(1.5, 2.0)                      # usual refill delay: ~3 days on average
            if rng.random() < (0.20 if short else 0.07):
                late += rng.uniform(35, 90)                 # interruption (may break the episode)
            d = d + pd.Timedelta(days=int(ds + late))
        if not discontinued:
            break
        if rng.random() < 0.25:
            written[-1]["Discontinue_Reason"] = rng.choice(["Side effects", "Cost / coverage", "Drug not available",
                                                            "Goal reached", "Patient preference"])
        u = rng.random()
        if u < 0.35:
            d = d + pd.Timedelta(days=int(ds + rng.uniform(14, 120)))       # switch
        elif u < 0.47:
            used.discard(pk)
            d = d + pd.Timedelta(days=int(ds + rng.uniform(90, 240)))      # restart later
        else:
            break

fill_df = pd.DataFrame(fills, columns=["ptid", "pi", "episode_id", "episode_num", "product_key", "dose_step",
                                       "fill_date", "days_supply", "cash", "provid", "fill_num"])
print(f"fills (all, incl. cash): {len(fill_df):,} | patients treated: {fill_df['ptid'].nunique():,}")

# COMMAND ----------

# MAGIC %md ## Pharmacy claims (only plan-paid fills while enrolled with pharmacy coverage)

# COMMAND ----------

prov_unique = prov.set_index("provid")["prov_unique"]
prov_spec = prov.set_index("provid")["specialty"]
pharmacies = [f"PH{n:06d}" for n in rng.integers(0, 999999, 4000)]

rows = []
for r in fill_df.itertuples():
    if r.cash:
        continue
    sp = span_at(r.ptid, r.fill_date)
    if sp is None or sp["Pharmacy_coverage_ind"] != "Y":
        continue                                            # lost coverage mid-treatment -> fill not in claims
    n_r = ndc_by_step[(r.product_key, r.dose_step)]
    prod = products.loc[r.product_key]
    bus = sp["Bus"]
    generic = prod["is_generic"] == "Y"
    copay = {"COM": rng.choice([25, 50, 100], p=[.5, .3, .2]) if not generic else 10,
             "MCR": rng.choice([35, 47, 95]) if not generic else 8, "MCD": 3}[bus]
    rows.append({
        "PTID": r.ptid, "Pat_planid": sp["Pat_planid"], "Clmid": f"RX{7000000000 + len(rows)}",
        "Fill_dt": r.fill_date, "Chk_Dt": r.fill_date + pd.Timedelta(days=int(rng.integers(3, 15))),
        "Ndc": n_r.ndc11, "Brnd_nm": prod["brand_name"].upper(), "Gnrc_Nm": prod["generic_name"].upper(),
        "Gnrc_Ind": "Y" if generic else "N", "Days_Sup": r.days_supply, "Quantity": float(n_r.package_qty),
        "Strength": n_r.strength, "Copay": float(copay), "Deduct": float(0 if rng.random() < .9 else rng.integers(20, 200)),
        "Dispfee": round(float(rng.uniform(1, 3)), 2),
        "Std_Cost": round(COST[r.product_key] * rng.uniform(0.95, 1.05), 2), "Std_Cost_Yr": r.fill_date.year,
        "Prov_Unique": prov_unique[r.provid], "Prov_Specialty": prov_spec[r.provid],
        "Pharm": rng.choice(pharmacies), "Mail_Ind": "Y" if rng.random() < 0.08 else "N",
        "Rfl_Nbr": int(r.fill_num % 12), "Fst_Fill": "Y" if r.fill_num == 0 else "N",
        "Daw": "0", "Form_Ind": "Y", "Spclt_Ind": "N",
        "Transaction_Type": "PAID", "Reject_Code": None, "Prescript_id": f"{r.episode_id}_{n_r.dose_step}",
        "Payer_Type": bus,
    })
for t, sp, pk, step, d, code in rejects:
    n_r = ndc_by_step[(pk, step)]
    prod = products.loc[pk]
    rows.append({
        "PTID": t["ptid"], "Pat_planid": sp["Pat_planid"], "Clmid": f"RX{7000000000 + len(rows)}",
        "Fill_dt": d, "Chk_Dt": None, "Ndc": n_r.ndc11, "Brnd_nm": prod["brand_name"].upper(),
        "Gnrc_Nm": prod["generic_name"].upper(), "Gnrc_Ind": "Y" if prod["is_generic"] == "Y" else "N",
        "Days_Sup": int(prod["days_supply"]), "Quantity": float(n_r.package_qty), "Strength": n_r.strength,
        "Copay": 0.0, "Deduct": 0.0, "Dispfee": 0.0, "Std_Cost": 0.0, "Std_Cost_Yr": d.year,
        "Prov_Unique": prov_unique[t["pcp"]], "Prov_Specialty": prov_spec[t["pcp"]],
        "Pharm": rng.choice(pharmacies), "Mail_Ind": "N", "Rfl_Nbr": 0, "Fst_Fill": "Y", "Daw": "0",
        "Form_Ind": "N" if code == "70" else "Y", "Spclt_Ind": "N",
        "Transaction_Type": "REJECTED", "Reject_Code": code, "Prescript_id": None, "Payer_Type": sp["Bus"],
    })
claims_rx = pd.DataFrame(rows)
print(claims_rx["Transaction_Type"].value_counts())

# COMMAND ----------

# MAGIC %md ## Save

# COMMAND ----------

fill_df["fill_date"] = pd.to_datetime(fill_df["fill_date"])
save_pdf(fill_df.drop(columns=["pi"]), "sim_rx_fill_truth")
save_pdf(claims_rx, "sim_claims_rx")
rx_written = pd.DataFrame(written)
save_pdf(rx_written, "sim_rx_written")

display(claims_rx[claims_rx["Transaction_Type"] == "PAID"]
        .assign(year=lambda x: x["Fill_dt"].dt.year)
        .pivot_table(index="year", columns="Brnd_nm", values="Clmid", aggfunc="count", fill_value=0))
