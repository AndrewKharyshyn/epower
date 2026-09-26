"""
derived_literals.py -- prose literals that quote pipeline counts must be
computed from the arrays, not hand-typed (audit Section 8, Limitation 1:
"145/374 drives (~17% of corpus km), urban/cold-skewed" was frozen at the
374-drive corpus while the arrays carried 181/410, and 'cold-skewed' had no
support: the fuel subset contains 0 Cold-cohort drives).

gtr_limitations_head(arr, master_km_total, master_type_counts) -> (L1, L2)   strings for
generatorTractionRecon.limitations[0:2]. release_check.py asserts equality.
"""
from __future__ import annotations


def gtr_limitations_head(arr: dict, master_km_total: float, master_type_counts: dict):
    g = arr["generatorTractionRecon"]
    meta = arr["seasonalCharts"]["_meta"]["cohortCounts"]
    n_fuel, n_all = int(g["nProduction"]), int(meta["all"])
    km_share = 100.0 * float(g["kmProduction"]) / float(master_km_total)
    split = {r["type"]: r for r in g["driveTypeSplit"]}
    n_urban = split.get("urban", {}).get("n", 0)
    coh = arr["seasonalCharts"]["charts"]["GeneratorTractionRecon"]["data"]
    n_sh = int((coh.get("shoulder") or {}).get("nProduction", 0))
    n_cold = int((coh.get("cold") or {}).get("nProduction", 0)) if coh.get("cold") else 0
    sh_fuel = 100.0 * n_sh / n_fuel
    sh_all = 100.0 * meta["shoulder"] / n_all
    n_hw_all = int(master_type_counts.get("highway", 0))
    n_hw_f = split.get("highway", {}).get("n", 0)
    l1 = (f"Fuel-flow PID coverage is {n_fuel}/{n_all} drives (~{km_share:.0f}% of corpus km) and is urban-skewed "
          f"({n_urban}/{n_fuel} fuel drives are urban; only {n_hw_f}/{n_hw_all} highway drives are fuel-instrumented) and shoulder-enriched ({sh_fuel:.0f}% of fuel drives vs {sh_all:.0f}% of the corpus; "
          f"{n_cold} Cold-cohort drives) — the headline figures rest on that subset, not the full corpus.")
    n_hw = split.get("highway", {}).get("n", 0)
    n_mh = split.get("mixed_highway", {}).get("n", 0)
    l2 = (f"Highway (n={n_hw}) and mixed-highway (n={n_mh}) drive-type splits are thin, fuel-instrumented samples; "
          f"read as indicative, not settled.")
    return l1, l2
