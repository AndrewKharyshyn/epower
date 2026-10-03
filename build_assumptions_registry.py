#!/usr/bin/env python3
"""
build_assumptions_registry.py -- typed assumptions registry (audit Section 8).

Collects every load-bearing constant/assumption that is NOT a measured channel
into one typed list and writes it to summary_arrays.json -> assumptionsRegistry.
Values are READ from their live source of truth (model_constants.py,
summary_config.json, summary_arrays.constantProvenance, seasonal thresholds),
never re-typed here, so the registry cannot drift from the code that consumes
them. A drift test (test_assumptions_registry.py) re-derives every entry.

Entry schema (all fields required):
  id         stable slug
  symbol     code identifier / short symbol
  label      human label
  value      display string (rendered verbatim by the dashboard)
  raw        machine value (number | list | dict) as read from source
  unit       unit string ('' if dimensionless)
  klass      one of: measured_external | nameplate_unverified | literature |
                     assumed | policy | derived_corpus_constant
  verified   bool  (True only if checked against an authoritative document)
  source     provenance string
  usedBy     list of pipeline outputs that scale with / depend on it
  sensitivity one-sentence impact statement (direction / proportionality)
  band       optional [lo, hi] plausible span carried by the pipeline (else null)

Usage: python3 build_assumptions_registry.py [--arrays P] [--config P] [--dry]
"""
from __future__ import annotations
import argparse, json, os, sys
import model_constants as MC

KLASSES = ("measured_external", "nameplate_unverified", "literature", "assumed",
           "policy", "derived_corpus_constant")
# M353: registry entry id -> model_constants symbols whose class (MC.CONSTANT_CLASS) the entry carries; all components must agree.
CLASS_SOURCES = {"fuel_density": ["RHO_G_PER_L"], "fuel_lhv": ["LHV_MJ_PER_KG"], "bsfc_surface": ["BSFC", "BSFC_FLOOR"],
                 "eta_gen_pe": ["ETA_GEN", "ETA_PE"], "p_aux": ["P_AUX_KW"], "cold_gate_engine": ["COLD_OIL_T_C", "COLD_T_C"]}


def _klass(entry_id):
    cs = {MC.CONSTANT_CLASS[s] for s in CLASS_SOURCES[entry_id]}
    assert len(cs) == 1 and next(iter(cs)) in KLASSES, (entry_id, cs)
    return next(iter(cs))
FIELDS = ("id", "symbol", "label", "value", "raw", "unit", "klass", "verified",
          "source", "usedBy", "sensitivity", "band")


def _f(x, nd=3):
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def _bsfc_sens(arr):
    """Derived from generatorTractionRecon.sensitivity (never retyped)."""
    rows = {r["axis"]: r for r in arr["generatorTractionRecon"]["sensitivity"]}
    base = rows["BASE (central)"]["gen100"]
    o = next(v for k, v in rows.items() if k.startswith("BSFC optimistic"))["gen100"]
    c = next(v for k, v in rows.items() if k.startswith("BSFC conservative"))["gen100"]
    return (f"BSFC scalers {MC.SCEN['optimistic']:g} / {MC.SCEN['conservative']:g} move generator energy by "
            f"{(o/base-1)*100:+.1f} % / {(c/base-1)*100:+.1f} % (lower BSFC = more generator energy for the same fuel).")


def build(cfg, arr):
    cp = arr["constantProvenance"]
    veh = cfg["vehicle"]
    kx = cfg["kExponentLadder"]
    sm = arr["seasonalCharts"]["_meta"]
    E = []

    def add(**k):
        k.setdefault("band", None)
        E.append(k)

    # ---- pack / vehicle ----------------------------------------------------
    add(id="cap_kwh", symbol="CAP_KWH", label="Assumed pack energy capacity",
        raw=cp["CAP_KWH"]["value"], value=f'{_f(cp["CAP_KWH"]["value"])} kWh', unit="kWh",
        klass="nameplate_unverified", verified=bool(cp["CAP_KWH"]["verified"]),
        source=cp["CAP_KWH"]["source"],
        usedBy=["GTC", "FCE", "C-rate", "cap_ah_est", "cycle-count projections"],
        sensitivity="Every GTC / FCE / C-rate figure scales linearly with this value; %, A, mV, mOhm and degC outputs are invariant.")
    add(id="scenario_threshold_gtc", symbol="SCENARIO_THRESHOLD_GTC", label="Reference throughput threshold",
        raw=cp["SCENARIO_THRESHOLD_GTC"]["value"], value=f'{cp["SCENARIO_THRESHOLD_GTC"]["value"]:,} GTC', unit="GTC",
        klass="assumed", verified=bool(cp["SCENARIO_THRESHOLD_GTC"]["verified"]),
        source=cp["SCENARIO_THRESHOLD_GTC"]["source"],
        usedBy=["scenario life projections", "k-exponent ladder"],
        sensitivity="Scenario parameter only; not a Nissan rating and not an 80 % SOH criterion. Projected years scale inversely with it.")
    mk = cp["MASS_BY_DRIVE_TYPE_KG"]
    add(id="mass_kg", symbol="MASS_BY_DRIVE_TYPE_KG", label="Class-conditional curb mass",
        raw=mk["value"], value=f'highway/mixed-highway {_f(mk["value"]["highway"])} kg; urban/mixed {_f(mk["value"]["urban"])} kg',
        unit="kg", klass="assumed", verified=bool(mk["verified"]), source=mk["source"],
        usedBy=["regen-capture KE loss", "descent-energy budget"],
        sensitivity="Mass-scaled physics estimates carry a closed-form range from the urban/mixed sensitivity span.",
        band=mk["urbanMixedSensitivityRangeKg"])
    add(id="odometer_km", symbol="vehicle.odometerKm", label="Dash odometer reading",
        raw=veh["odometerKm"], value=f'{veh["odometerKm"]:,} km (as of {veh["odometerAsOf"]})', unit="km",
        klass="measured_external", verified=True,
        source="instrument-cluster reading recorded by the operator; not derivable from OBD logs",
        usedBy=["lifetime-% anchor", "cycle-projection start point", "logging-coverage ratio"],
        sensitivity="Anchors lifetime fraction only; does not enter any per-drive statistic.")
    add(id="motor_spec", symbol="vehicle.motorPowerKw / motorTorqueNm / topSpeedKmh", label="Public OEM motor / top-speed spec",
        raw={"kW": veh["motorPowerKw"], "Nm": veh["motorTorqueNm"], "kmh": veh["topSpeedKmh"]},
        value=f'{veh["motorPowerKw"]} kW, {veh["motorTorqueNm"]} N·m, {veh["topSpeedKmh"]} km/h', unit="",
        klass="nameplate_unverified", verified=bool(veh["motorSpecVerified"] and veh["topSpeedVerified"]),
        source=veh["motorSpecSource"], usedBy=["near-limiter census", "torque/power utilisation"],
        sensitivity="Denominator of utilisation ratios; ratios scale inversely.")

    # ---- damage / life -----------------------------------------------------
    add(id="woehler_k", symbol="RF_DAMAGE_K (k)", label="Woehler DoD damage exponent",
        raw={"reference": kx["kReference"], "grid": kx["kGrid"]},
        value=f'k = {_f(kx["kReference"])} (grid {", ".join(_f(k) for k in kx["kGrid"])})', unit="",
        klass="literature", verified=False,
        source="generic depth-of-discharge proxy; not derived from this vehicle's cells",
        usedBy=["rfDamageK2Sum", "k-exponent sensitivity ladder"],
        sensitivity="Depth-weighted damage falls steeply with k; the ladder reports k = 1 to 3 rather than a single value.",
        band=[min(kx["kGrid"]), max(kx["kGrid"])])

    # ---- fuel / generator chain -------------------------------------------
    lo = lambda t: [t[1], t[2]]
    add(id="fuel_density", symbol="RHO_G_PER_L", label="E10 fuel density", raw=MC.RHO_G_PER_L[0],
        value=f"{_f(MC.RHO_G_PER_L[0])} g/L", unit="g/L", klass=_klass("fuel_density"), verified=False,
        source="EN 228 E10 @15 degC; fuel volume to mass only", usedBy=["fuel mass", "BSFC engine energy"],
        sensitivity="Engine/generator energy scales linearly with density.", band=lo(MC.RHO_G_PER_L))
    add(id="fuel_lhv", symbol="LHV_MJ_PER_KG", label="E10 lower heating value", raw=MC.LHV_MJ_PER_KG[0],
        value=f"{_f(MC.LHV_MJ_PER_KG[0])} MJ/kg", unit="MJ/kg", klass=_klass("fuel_lhv"), verified=False,
        source="E10 literature value", usedBy=["fuel chemical energy", "thermal efficiency"],
        sensitivity="Affects chemical-energy and efficiency only; not the BSFC-derived generator energy.", band=lo(MC.LHV_MJ_PER_KG))
    add(id="bsfc_surface", symbol="BSFC (regime table)", label="BSFC by regime (central)", raw=dict((k, v[0]) for k, v in MC.BSFC.items()),
        value="; ".join(f"{k} {_f(v[0])}" for k, v in MC.BSFC.items()) + f" g/kWh (floor {_f(MC.BSFC_FLOOR)})", unit="g/kWh",
        klass=_klass("bsfc_surface"), verified=False,
        source="Nissan TR No.89 minimum (217 g/kWh @ 2000 rpm) used as floor; regime centrals are modelled",
        usedBy=["generator energy", "f_gen", "generator to traction split"],
        sensitivity=_bsfc_sens(arr),
        band=[min(v[1] for v in MC.BSFC.values()), max(v[2] for v in MC.BSFC.values())])
    add(id="eta_gen_pe", symbol="ETA_GEN x ETA_PE", label="Generator x power-electronics efficiency",
        raw={"eta_gen": MC.ETA_GEN[0], "eta_pe": MC.ETA_PE[0]},
        value=f"{_f(MC.ETA_GEN[0])} x {_f(MC.ETA_PE[0])} = {MC.ETA_GEN[0]*MC.ETA_PE[0]:.3f}", unit="",
        klass=_klass("eta_gen_pe"), verified=False, source="PM machine + rectifier literature range",
        usedBy=["generator electrical energy", "f_gen"], sensitivity="Generator energy scales proportionally.",
        band=[round(MC.ETA_GEN[1]*MC.ETA_PE[1], 4), round(MC.ETA_GEN[2]*MC.ETA_PE[2], 4)])
    add(id="p_aux", symbol="P_AUX_KW", label="Drive-constant auxiliary HV load", raw=MC.P_AUX_KW[0],
        value=f"{_f(MC.P_AUX_KW[0])} kW", unit="kW", klass=_klass("p_aux"), verified=False,
        source="not separable in motion; standstill median ~1.2 kW measured, in-motion value assumed",
        usedBy=["traction demand", "f_gen"], sensitivity="+/-1 kW moves traction demand by less than 1 kWh/100 km.", band=lo(MC.P_AUX_KW))

    # ---- thermal gates / cohorts ------------------------------------------
    add(id="cold_gate_engine", symbol="COLD_OIL_T_C / COLD_T_C", label="Engine cold-start gate",
        raw={"oil_c": MC.COLD_OIL_T_C, "coolant_c": MC.COLD_T_C, "cold_mult": MC.COLD_MULT[0]},
        value=f"oil < {_f(MC.COLD_OIL_T_C)} degC (coolant < {_f(MC.COLD_T_C)} degC fallback); BSFC x{_f(MC.COLD_MULT[0])}", unit="degC",
        klass=_klass("cold_gate_engine"), verified=False, source="empirical enrichment zone; oil temperature persists across e-POWER restarts",
        usedBy=["cold-fuel fraction", "generator energy"], sensitivity="Cold penalty OFF / x1.45 bracket the generator estimate (see sensitivity table).",
        band=[MC.COLD_MULT[1], MC.COLD_MULT[2]])
    th = sm["thresholds"]
    add(id="thermal_regime_bins", symbol="thermal_regime (" + sm["thermalRegimeVersion"] + ")", label="Ambient thermal regime thresholds (drive-mean ambient)",
        raw=th, value=f'cold {th["cold"]} degC; shoulder {th["shoulder"]} degC; warm {th["warm"]} degC', unit="degC",
        klass="policy", verified=False, source="reporting bins over a continuous variable; versioned in seasonal_config.json",
        usedBy=["Warm / Shoulder / Cold cohort selector", "seasonal contrast"],
        sensitivity="Cohort membership is discontinuous at the cut points; the contrast estimator adjusts for continuous ambient within cohort.")
    add(id="cohort_min_support", symbol="COHORT_MIN_SUPPORT_DRIVES", label="Minimum drives to enable a cohort", raw=10,
        value="10 drives", unit="drives", klass="policy", verified=False,
        source="declared front-end gate (M284); cohort disabled below this count, never silently replaced by all-data",
        usedBy=["cohort selector availability"], sensitivity="Lower values enable thinner cohorts; the Cold class has "
        + str(arr["cohortMeta"]["cold"]["observed"]) + " observed drives (" + str(arr["cohortMeta"]["cold"]["eligibleForCohortView"]) + " analysed as a cohort).")
    ou = arr["offsetUncertainty"]; cs_ = ou["correctionScope"]; og = arr["energyUncertaintyMC"]["offsetGrossSensitivity"]
    import pandas as _pd
    _dm = _pd.read_csv("drive_master.csv", low_memory=False)
    _v5 = _dm["I_offset_A_applied"].dropna().round(4); _p2 = _dm["I_offset_2p_A_applied"].dropna().round(4)
    assert _v5.nunique() == 1 and _p2.nunique() == 1 and abs(float(_p2.iloc[0]) - ou["pointEstimateA"]) < 1e-4, "offset is no longer single-valued: rewrite this entry"
    add(id="i_offset", symbol="I_offset_2p_A_applied", label="BMS current offset (one corpus-wide constant, re-solved per corpus build)", raw=ou["pointEstimateA"],
        value=f'{_f(ou["pointEstimateA"])} A (two-pass solve; 95% CI {_f(ou["ci95A"][0])} to {_f(ou["ci95A"][1])}; v5 single-pass {_f(float(_v5.iloc[0]))} A)', unit="A",
        klass="derived_corpus_constant", verified=False,
        source=(f'M24/M107 two-pass SoC-anchored solve, estimated (not measured): fitted on the {ou["nDrives"]} domain-clean drives ({ou["nDays"]} days; excludes f_domain_2p), '
                f'day-cluster bootstrap CI; stamped on the {int(_p2.size)} drives that have a SoC-anchored energy residual and subtracted from every drive with V_pack_median and duration; '
                f'the v5 single-pass value feeds the retired net_draw_*_corr columns; coupled to the unverified CAP_KWH (capacitySensitivity); '
                f'extra uncertainty sigma {_f(MC.I_OFFSET_SIGMA_A)} A carried in Monte Carlo'),
        usedBy=list(cs_["appliesTo"]),
        sensitivity=(f'Net-draw and residual correction only: not applied to gross throughput, GTC or FCE (released convention; notAppliedTo: {", ".join(cs_["notAppliedTo"])}). '
                     f'The corrected energy residual is the SoC-anchored residual minus the offset energy; it sums to about zero on the fit set by construction and depends on CAP_KWH, so it is not an independent validation. '
                     f'Applying the offset before the discharge/charge split would raise gross throughput by {_f(og["throughputShiftPct"])} % ({_f(og["throughputShiftKwh"])} kWh; energyUncertaintyMC.offsetGrossSensitivity). '
                     f'Point and interval are method-dependent (day-cluster bootstrap, Methodology B).'),
        band=list(ou["ci95A"]))
    return E


def validate(E):
    ids = set()
    for e in E:
        assert set(e.keys()) == set(FIELDS), (e["id"], set(FIELDS) ^ set(e.keys()))
        assert e["klass"] in KLASSES, e["id"]
        assert e["id"] not in ids, e["id"]; ids.add(e["id"])
        assert isinstance(e["verified"], bool) and e["value"] and e["source"] and e["usedBy"], e["id"]
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arrays", default="summary_arrays.json")
    ap.add_argument("--config", default="summary_config.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    cfg = json.load(open(a.config)); arr = json.load(open(a.arrays))
    E = build(cfg, arr); validate(E)
    if a.dry:
        print(json.dumps(E, indent=1, ensure_ascii=False)[:3000]); return
    arr["assumptionsRegistry"] = {
        "_provenance": "M284 (2026-09-19; audit Section 8). Built by build_assumptions_registry.py from model_constants.py, "
                       "summary_config.json (vehicle, kExponentLadder) and summary_arrays (constantProvenance, seasonalCharts._meta). "
                       "Values are read from source, not retyped; test_assumptions_registry.py re-derives every entry.",
        "nEntries": len(E), "nUnverified": sum(1 for e in E if not e["verified"]), "entries": E}
    json.dump(arr, open(a.arrays, "w"), ensure_ascii=False, indent=1)
    print(f"assumptionsRegistry: {len(E)} entries, {sum(1 for e in E if not e['verified'])} unverified")


if __name__ == "__main__":
    main()
