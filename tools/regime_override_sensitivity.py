#!/usr/bin/env python3
"""M426 (Director ruling 2026-10-13): override-off sensitivity of the cohort energy intensity to the owner's recorded thermal-regime overrides.

For every entry of seasonal_config.json cohorts.regimeOverrides the published EnergyIntensity of the two cohorts it touches (physical and assigned regime) is
recomputed twice with the SAME estimator as the published value (refresh_seasonal_kpis: canonical-clean paired ratio of sums, calendar-day clustered percentile
bootstrap, seed 20260919, B = 4000): `applied` (the override in force, equals the published cohort value) and `removed` (the physical regime restored). Pure
function; the caller (tools/build_ambient_table.py) stores the result in ambientTable.regimeOverrides[i].sensitivity. Descriptive: a classification choice,
not a threshold change; the cohorts are route-mix and season confounded.
"""
import os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)


def _pack(c):
    if c is None:
        return None
    return {"value": round(c["point"], 3), "n": c["n"], "pairedKm": c["km"],
            "ci95": {"lo": round(c["lo"], 3), "hi": round(c["hi"], 3), "nClusters": c["clusters"], "essDays": round(c["ess"], 2)}}


def sensitivity(rows, overrides, RK):
    """rows: refresh_seasonal_kpis.load() rows (thermal_regime = the regime in force). overrides: cohorts.regimeOverrides. RK: the refresh_seasonal_kpis module.
    Returns {file: {cohort: {"applied": pack, "removed": pack}}} for the physical and the assigned cohort of each override."""
    out = {}
    for f, ov in (overrides or {}).items():
        phys, assigned = ov["physicalRegime"], ov["regime"]
        hit = [r for r in rows if r["file"] == f]
        if len(hit) != 1 or hit[0]["thermal_regime"] != assigned:
            raise ValueError("override %s: the seasonal master does not carry the drive in %r (override not in force)" % (f, assigned))
        undone = [dict(r, thermal_regime=phys) if r["file"] == f else r for r in rows]
        res = {}
        for c in (phys, assigned):
            res[c] = {"applied": _pack(RK.ratio_ci(RK.clean([r for r in rows if r["thermal_regime"] == c]))),
                      "removed": _pack(RK.ratio_ci(RK.clean([r for r in undone if r["thermal_regime"] == c])))}
        out[f] = res
    return out
