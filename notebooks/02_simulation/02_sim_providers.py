# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Simulate Providers
# MAGIC
# MAGIC Creates the provider directory used by both the EHR side (`Provider`) and the claims side
# MAGIC (`Claims Provider`). Each provider gets a specialty (with its NUCC taxonomy code), a state,
# MAGIC and a census region / division.
# MAGIC
# MAGIC **Output:** `sim_provider` (one row per provider, both EHR and claims identifiers)

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

rng = np.random.default_rng(SEED + 2)
geo = load_pdf("ref_geography")
spec = load_pdf("ref_specialty")

N_PROV = max(300, N_PATIENTS // 16)

# Region share of providers (roughly follows US population by region)
region_p = {"South": 0.38, "West": 0.24, "Midwest": 0.21, "Northeast": 0.17}
regions = rng.choice(list(region_p), N_PROV, p=list(region_p.values()))

states = []
for r in regions:
    st = geo.loc[geo["region"] == r, "state"].to_numpy()
    states.append(rng.choice(st))
prov = pd.DataFrame({"region": regions, "state": states})
prov = prov.merge(geo, on=["region", "state"], how="left")

sp_idx = rng.choice(len(spec), N_PROV, p=(spec["share"] / spec["share"].sum()).to_numpy())
prov["specialty"] = spec["specialty"].to_numpy()[sp_idx]
prov["taxonomy"] = spec["taxonomy"].to_numpy()[sp_idx]

prov["provid"] = [f"PV{1000000 + i}" for i in range(N_PROV)]           # EHR provider id
claims_ids = pd.unique(rng.integers(100_000_000, 999_999_999, N_PROV * 2))[:N_PROV]
prov["prov_unique"] = claims_ids.astype(str)                            # claims id
prov["prim_spec_ind"] = "Y"
prov["prov_type"] = np.where(prov["specialty"] == "Nurse Practitioner", "Non-Physician Practitioner", "Physician")
prov["grp_practice"] = [f"GRP{rng.integers(1000, 9999)}" for _ in range(N_PROV)]
prov["hosp_affil"] = np.where(rng.random(N_PROV) < 0.55, "Y", "N")

save_pdf(prov, "sim_provider")
display(prov.groupby(["region", "specialty"]).size().unstack(fill_value=0))
