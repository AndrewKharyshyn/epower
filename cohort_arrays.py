"""
cohort_arrays.py  —  additive per-cohort chart-data layer (Phase 1: thermal charts)
===================================================================================
Produces {All observations, Warm, Shoulder, Cold} variants of the data backing the
primary dashboard's thermal charts, so each chart can render a selected cohort and a
comparison. Reads seasonal_drive_master.csv (+ drive_master.csv for a few extra
per-drive columns) READ-ONLY; recomputes with the tested seasonal_core aggregation
(ratio-of-sums, pooled medians, drive/day weighting). Nothing baked corpus-wide.

Comparison type is gated by dependency class (thermal here -> direct overlay, with the
current 'inconclusive' caveat). season_associated / not_applicable charts are Phase 2/3.
Empty cohorts return well-formed nulls (never zero-as-real). Staged charts (fitted
surfaces / per-second trajectories) are registered with a reason, not faked.

M291: every rate metric now exposes its paired basis (`paired_n`, `paired_km`) — the
exact drive count and distance behind the ratio-of-sums — via seasonal_core's
cohort_per_100km_detail; and the starts-per-100km events path no longer coerces a
missing event count to 0 (which had let a null-event drive add its distance to the
denominator). See test_cohort_rates.py.
"""
from __future__ import annotations
import csv, json, os
import seasonal_core as sc

HERE = os.path.dirname(os.path.abspath(__file__))
def P(n): return os.path.join(HERE, n)

COHORTS = ["All observations", "Warm", "Shoulder", "Cold"]
PRED = {
    "All observations": lambda d: True,
    "Warm": lambda d: d.get("thermal_regime") == "warm",
    "Shoulder": lambda d: d.get("thermal_regime") == "shoulder",
    "Cold": lambda d: d.get("thermal_regime") == "cold",
}

# chart -> spec. kind: rate|drive_mean|pooled_median|distribution
# ct (comparison type): scalar_dumbbell | distribution_overlay | multiline_curve
PHASE1 = {
    "RegenChart": {"class": "thermal", "ct": "scalar_dumbbell", "ready": True,
        "metrics": {
            "regen_share_of_charge": "drive_mean",
            "regen_peak_Crate": "drive_mean",
            "motor_regen_lower_pct": "drive_mean",
            "motor_regen_upper_pct": "drive_mean"}},
    "BatteryThermalChart": {"class": "thermal", "ct": "distribution_overlay", "ready": True,
        "metrics": {
            "pack_temp_start_c": "distribution",
            "pack_temp_time_mean_c": "drive_mean",
            "pack_temp_max_c": "drive_mean",
            "pack_spread_time_mean_c": "drive_mean"}},
    "BmsVcmChart": {"class": "thermal", "ct": "scalar_dumbbell", "ready": True,
        "metrics": {
            "vcm_coolant_start_c": "drive_mean",
            "engine_coolant_start_c": "drive_mean",
            "oil_temp_start_c": "drive_mean"}},
    "CycleRateChart": {"class": "thermal", "ct": "scalar_dumbbell", "ready": True,
        "metrics": {"rf_n_cycles": "drive_mean", "rf_efc": "drive_mean"}},
    "EngineCyclingChart": {"class": "thermal", "ct": "scalar_dumbbell", "ready": True,
        "metrics": {"engine_on_pct": "drive_mean", "starts_per_100km": "rate_events"}},
    "SocLevelSensitivityChart": {"class": "thermal", "ct": "distribution_overlay", "ready": True,
        "metrics": {"soc_mean_wtd_pct": "drive_mean", "soc_range_span_pp": "distribution"}},
    "TempChart": {"class": "thermal", "ct": "distribution_overlay", "ready": True,
        "metrics": {"ambient_time_mean_c": "distribution", "pack_temp_time_mean_c": "drive_mean"}},
}
STAGED = {
    "SocHysteresisChart": "fitted SoC-control surface (m119v2) — needs per-cohort refit (degenerate without cold data)",
    "BufferImpulseChart": "per-second engine-start SoC/current transients — needs raw current+engine-state extraction",
    "RampLatencyChart": "per-second engine-on→target-RPM latency — needs raw RPM+engine-state extraction",
    "CycleProjectionChart": "seasonalAssumptions extrapolation — model, labelled separately from observed",
}
# WarmupCurve: now data-ready as a per-cohort multiline curve over elapsed-time bins.
WARMUP = {"WarmupCurve": {"ct": "multiline_curve", "bins": [30, 60, 120, 300, 600],
          "series": {"oil": "oil_wu", "engine_coolant": "cool_wu"}}}

# Phase 3: not-season-dependent charts. FROZEN — one value under any cohort filter,
# never a per-season copy. Registered so the dashboard labels them, not silently drops.
PHASE3_FROZEN = {
    "BaroCompensation": "barometric-compensation method/constant — not season-dependent",
    "EfcDefinitionCard": "EFC/FCE/Rainflow-EFC definitions — constants, not season-dependent",
    "CalibrationCard": "current-sensor offset / sign convention — manifest constant, fixed under filter",
    "ExposureTotalsCard": "distance / gross-throughput totals — exposure, labelled 'Exposure total' not a rate",
}

# Phase 2: season_associated charts. Per-cohort recompute for filtering; comparison is
# ADJUSTED (composition-standardized), not a raw overlay. `adjustOutcome` names the
# per-drive outcome standardized to pooled composition; None = descriptive covariate only.
PHASE2 = {
    "EfficChart": {"ct": "scalar_dumbbell_adjusted", "ready": True,
        "metrics": {"gross_throughput_kwh_per100km": "rate"},
        "adjustOutcome": "gross_throughput_kwh_per100km"},
    "SpeedChart": {"ct": "distribution_overlay", "ready": True,
        "metrics": {"speed_mean_moving": "distribution"}, "adjustOutcome": None},
    "DriveDurationDist": {"ct": "distribution_overlay", "ready": True,
        "metrics": {"distance_km": "distribution"}, "adjustOutcome": None},
    "DriveTypeChart": {"ct": "distribution_overlay", "ready": True,
        "metrics": {"stationary_pct": "distribution"}, "adjustOutcome": None},
}
ADJ_COVARIATES = ["speed_mean_moving", "stationary_pct", "pct_highway", "distance_km"]

# distribution bin edges per metric (fixed so cohorts share axes)
BINS = {
    "pack_temp_start_c": list(range(-10, 55, 5)),
    "soc_range_span_pp": list(range(0, 60, 5)),
    "ambient_time_mean_c": list(range(-15, 45, 5)),
    "speed_mean_moving": list(range(0, 110, 10)),
    "distance_km": list(range(0, 55, 5)),
    "stationary_pct": list(range(0, 55, 5)),
}


def _f(x):
    try:
        return float(x) if x not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def load_drives():
    sm = {r["file"]: r for r in csv.DictReader(open(P("seasonal_drive_master.csv")))}
    dm = {r["file"]: r for r in csv.DictReader(open(P("drive_master.csv")))}
    tr = {}
    if os.path.exists(P("raw_temperature_triplets.csv")):
        tr = {r["file"]: r for r in csv.DictReader(open(P("raw_temperature_triplets.csv")))}
    drives = []
    for fn, r in sm.items():
        d = {k: _f(v) for k, v in r.items()
             if k not in ("file", "date", "thermal_regime", "drive_type",
                          "local_iso", "utc_iso", "meteorological_season",
                          "continuity_status", "cold_soak_status",
                          "temp_start_coverage", "hvac_class", "cruise_class",
                          "precipitation_type", "road_surface", "logging_delay_class",
                          "payload_class", "cargo_band", "tyre_epoch", "ecu_epoch",
                          "continuity_reason_codes", "cold_soak_reason_codes",
                          "ambient_source_primary", "ambient_uncertainty_class",
                          "ambient_source_timestamps", "seasonal_core_version",
                          "source_master_md5", "ambient_time_mean_kind",
                          "thermal_regime_version", "unlogged_use")}
        d["file"] = fn
        d["date"] = r["date"]
        d["thermal_regime"] = r["thermal_regime"]
        d["drive_type"] = r.get("drive_type")
        # extras from drive_master (read-only): composition covariates + regen peaks
        m = dm.get(fn, {})
        for k in ("regen_peak_Crate", "motor_regen_lower_pct", "motor_regen_upper_pct",
                  "n_sign_crossings", "speed_mean_moving", "stationary_pct",
                  "pct_highway", "speed_mean"):
            d[k] = _f(m.get(k))
        # per-drive workload rate (season_associated outcome): kWh/100km
        gt = d.get("gross_throughput_kwh"); dist = d.get("distance_km")
        # M295 (audit 2026-09-24 P0): canonical-clean energy eligibility. A drive flagged ens_invalid or
        # ens_outlier_v2 (explicit True only) is excluded from every energy RATE and from the adjusted
        # contrast outcome, matching the EnergyIntensity headline; exposure totals are unaffected.
        d["ens_excluded"] = (str(m.get("ens_invalid")).strip().lower() == "true"
                             or str(m.get("ens_outlier_v2")).strip().lower() == "true")
        d["gross_throughput_kwh_per100km"] = ((100.0 * gt / dist) if (gt and dist) else None) \
            if not d["ens_excluded"] else None
        d["starts_per_100km_events"] = d.get("n_sign_crossings")
        # warm-up trajectory bins (from raw_temperature_triplets)
        t = tr.get(fn, {})
        for b in (30, 60, 120, 300, 600):
            d[f"oil_wu_{b}s"] = _f(t.get(f"oil_wu_{b}s"))
            d[f"cool_wu_{b}s"] = _f(t.get(f"cool_wu_{b}s"))
        drives.append(d)
    return drives


def histogram(vals, edges):
    counts = [0] * (len(edges) - 1)
    for v in vals:
        if v is None:
            continue
        for i in range(len(edges) - 1):
            if edges[i] <= v < edges[i + 1]:
                counts[i] += 1
                break
    return {"edges": edges, "counts": counts, "n": sum(counts)}


def metric_cohort(pool, key, kind):
    vals = [d[key] for d in pool if d.get(key) is not None and not sc._isnan(d[key])]
    out = {"n": len(vals)}
    if not vals and kind not in ("rate", "rate_events"):
        out.update({"value": None, "pooled_median": None, "p10": None, "p90": None})
        if kind == "distribution":
            out["hist"] = histogram([], BINS.get(key, [0, 1]))
        return out
    if kind == "rate":
        # ratio-of-sums over paired-eligible drives; numerator is the underlying exposure total,
        # NOT the per-drive rate column (M284 fix). M291: expose the paired basis (paired_n/paired_km)
        # so the denominator behind every displayed rate is auditable and a null numerator can never
        # inject its distance into it.
        num_key = key[:-len("_per100km")] if key.endswith("_per100km") else key
        detail = sc.cohort_per_100km_detail([d for d in pool if not d.get("ens_excluded")], num_key)
        out["eligibility"] = "canonical_clean"
        out["value"] = detail["value"]
        out["paired_n"] = detail["paired_n"]
        out["paired_km"] = detail["paired_km"]
    elif kind == "rate_events":
        # events per 100km from an events proxy column. M291: keep a MISSING event count as None
        # (was coerced to 0 via `e or 0`, which let a null-event drive add distance to the
        # denominator and biased the rate low); paired-eligibility then excludes it cleanly.
        ev_pool = [{"e": d.get("starts_per_100km_events"), "distance_km": d.get("distance_km")}
                   for d in pool]
        detail = sc.cohort_per_100km_detail(ev_pool, "e")
        out["value"] = detail["value"]
        out["paired_n"] = detail["paired_n"]
        out["paired_km"] = detail["paired_km"]
    else:
        out["value"] = sc.cohort_drive_mean(pool, key)
    out["pooled_median"] = sc.cohort_pooled_median(pool, key)
    out["p10"] = sc.cohort_pooled_quantile(pool, key, 0.10)
    out["p90"] = sc.cohort_pooled_quantile(pool, key, 0.90)
    out["day_weighted_mean"] = sc.cohort_day_weighted_mean(pool, key)
    if kind == "distribution":
        out["hist"] = histogram(vals, BINS.get(key, [min(vals), max(vals) + 1]))
    return out


def build():
    drives = load_drives()
    pools = {c: [d for d in drives if PRED[c](d)] for c in COHORTS}
    dep = json.load(open(P("seasonal_dependency.json")))
    warm_pool = pools["Warm"]

    charts = {}
    for chart, spec in PHASE1.items():
        metrics = {}
        for key, kind in spec["metrics"].items():
            per_cohort = {}
            for c in COHORTS:
                mc = metric_cohort(pools[c], key, kind)
                # warm-relative comparison delta (percent) where support exists
                wv = metric_cohort(warm_pool, key, kind).get("value")
                if c != "Warm" and wv not in (None, 0) and mc.get("value") is not None:
                    mc["vs_warm_pct"] = round(100 * (mc["value"] - wv) / wv, 2)
                else:
                    mc["vs_warm_pct"] = None
                per_cohort[c] = mc
            metrics[key] = per_cohort
        charts[chart] = {
            "dependencyClass": spec["class"],
            "comparisonType": spec["ct"],
            "dataReady": True,
            "metrics": metrics,
            "coverage": {c: sc.cohort_coverage(pools[c]) for c in COHORTS},
        }
    for chart, reason in STAGED.items():
        charts[chart] = {"dependencyClass": "thermal", "dataReady": False,
                         "stagedReason": reason}

    # ---- Phase 2: season_associated charts (per-cohort + adjusted contrast) ----
    import seasonal_adjust as SA
    for chart, spec in PHASE2.items():
        metrics = {}
        for key, kind in spec["metrics"].items():
            per_cohort = {}
            for c in COHORTS:
                mc = metric_cohort(pools[c], key, kind)
                wv = metric_cohort(warm_pool, key, kind).get("value")
                mc["vs_warm_pct"] = (round(100 * (mc["value"] - wv) / wv, 2)
                                     if c != "Warm" and wv not in (None, 0)
                                     and mc.get("value") is not None else None)
                per_cohort[c] = mc
            metrics[key] = per_cohort
        entry = {"dependencyClass": "season_associated", "comparisonType": spec["ct"],
                 "dataReady": True, "metrics": metrics,
                 "coverage": {c: sc.cohort_coverage(pools[c]) for c in COHORTS},
                 "requiresAdjustment": spec["adjustOutcome"] is not None}
        # attach adjusted contrast(s): warm vs shoulder (now), warm vs cold (when data)
        if spec["adjustOutcome"]:
            entry["adjusted"] = {
                "warm_vs_shoulder": SA.adjusted_contrast(
                    drives, spec["adjustOutcome"], "thermal_regime", "warm", "shoulder",
                    covariates=ADJ_COVARIATES, n_boot=2000),
                "warm_vs_cold": SA.adjusted_contrast(
                    drives, spec["adjustOutcome"], "thermal_regime", "warm", "cold",
                    covariates=ADJ_COVARIATES, n_boot=200),
            }
        charts[chart] = entry

    # ---- WarmupCurve: per-cohort multiline warm-up trajectory (raw-derived) ----
    for chart, spec in WARMUP.items():
        series = {}
        for sname, pfx in spec["series"].items():
            per_cohort = {}
            for c in COHORTS:
                pts = []
                for b in spec["bins"]:
                    key = f"{pfx}_{b}s"
                    m = sc.cohort_drive_mean(pools[c], key)
                    n = len([d for d in pools[c] if d.get(key) is not None])
                    pts.append({"elapsed_s": b, "mean_c": (round(m, 2) if m is not None else None), "n": n})
                per_cohort[c] = pts
            series[sname] = per_cohort
        charts[chart] = {"dependencyClass": "thermal", "comparisonType": "multiline_curve",
                         "dataReady": True, "series": series, "bins": spec["bins"],
                         "coverage": {c: sc.cohort_coverage(pools[c]) for c in COHORTS}}

    # ---- Phase 3: frozen not-season-dependent charts (labelled, never per-season) ----
    frozen = {name: {"dependencyClass": "not_applicable", "frozen": True,
                     "note": note, "comparisonType": "none"}
              for name, note in PHASE3_FROZEN.items()}
    for name, meta in frozen.items():
        charts[name] = meta

    payload = {
        "_provenance": {
            "layer": "cohort_arrays Phase 1 (thermal charts)",
            "seasonalCoreVersion": sc.SEASONAL_CORE_VERSION,
            "generatedFrom": "seasonal_drive_master.csv + drive_master.csv (read-only)",
            "rule": "per-cohort recompute via ratio-of-sums / pooled median / drive-day weighting; "
                    "no baked corpus-wide arrays; empty cohorts -> nulls, never zero-as-real; "
                    "comparison type gated by dependency class; rates expose paired_n/paired_km (M291); energy rates "
                    "and the adjusted energy contrast use canonical-clean eligibility (ens_invalid/ens_outlier_v2 excluded; M295)",
        },
        "cohorts": COHORTS,
        "comparisonPrimitives": {
            "scalar_dumbbell": "per-cohort scalar with warm-relative delta + CI (CI when >=2 cohorts have support)",
            "distribution_overlay": "shared-axis per-cohort histograms",
            "multiline_curve": "per-cohort fitted/binned curves (Phase-1 staged charts)",
        },
        "adjustedContrastAvailable": any(
            pools[c] for c in ("Cold",)),  # False until cold data
        "dataReadyCharts": [c for c, s in PHASE1.items()],
        "phase2Charts": [c for c in PHASE2],
        "warmupCharts": [c for c in WARMUP],
        "frozenCharts": {c: PHASE3_FROZEN[c] for c in PHASE3_FROZEN},
        "stagedCharts": {c: r for c, r in STAGED.items()},
        "charts": charts,
    }
    json.dump(payload, open(P("cohort_arrays.json"), "w"), indent=1, ensure_ascii=False)
    return payload


if __name__ == "__main__":
    p = build()
    print("charts:", len(p["charts"]),
          "| data-ready:", len(p["dataReadyCharts"]),
          "| staged:", len(p["stagedCharts"]))
    # quick sanity: regen share by cohort
    rg = p["charts"]["RegenChart"]["metrics"]["regen_share_of_charge"]
    for c in COHORTS:
        print(f"  regen_share {c:18s} n={rg[c]['n']:3d} value={rg[c]['value']} vs_warm%={rg[c]['vs_warm_pct']}")
