"""
compute_seasonal.py  —  additive seasonal-management engine
===========================================================
Reads (READ-ONLY):
    drive_master.csv          (186-col per-drive master; MD5-anchored, untouched)
    summary_config.json       (legacy ambientByDrive)
    seasonal_config.json      (thresholds, versions, schema)
    event_ledger.json         (tyre/service/PID/ECU epochs, exclusions, e4orce list)
    manual_observations.csv   (optional; blank-tolerant per-drive metadata)

Writes:
    seasonal_drive_master.csv     (per-drive derived master; new artifact)
    seasonal_arrays.json          (dashboard-ready cohort objects + coverage + warnings)
    manual_observations_template.csv  (367-row blank template if none supplied)
    ambient_samples.json          (legacy ambient migrated to timestamped samples)

drive_master.csv is never modified. MD5 is asserted before and after.

M291 (audit B6): distance_km is the SINGLE authoritative field — it is copied from
drive_master.csv (never re-derived from the raw odometer here), and a post-build
invariant asserts the seasonal master's total distance equals the primary master's
over the same canonical drives, so a repair applied to the master (e.g. the
20260906_122920 odometer-reset fix, -2.5 -> 0.44 km) can never leave the seasonal
master carrying a stale/divergent distance.
"""
from __future__ import annotations
import csv, json, hashlib, os, sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import seasonal_core as sc

HERE = os.path.dirname(os.path.abspath(__file__))
def P(name): return os.path.join(HERE, name)

MANUAL_COLUMNS = [
    "file", "logging_delay_class", "logging_delay_min", "unlogged_use",
    "last_unlogged_use_end_local", "parking_environment", "initial_condition",
    "precipitation_type", "precipitation_intensity", "road_surface",
    "wind_strength", "occupants_total", "cargo_band", "hvac_class",
    "hvac_setpoint_c", "windows_open_substantially", "cruise_class",
    "exception_flags", "notes",
]

def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

def _f(x):
    try:
        if x is None or x == "": return None
        return float(x)
    except (TypeError, ValueError):
        return None

# ---------------------------------------------------------------------------
def load_master(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return rows

def load_manual(path):
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out[row.get("file", "").strip()] = row
    return out

def epoch_for(ledger, etype, drive_local_iso):
    dt = datetime.fromisoformat(drive_local_iso)
    active = "unknown"
    best = None
    for ev in ledger["events"]:
        if ev["type"] != etype and not (etype == "tyre_set" and ev["type"] == "tyre_set"):
            if ev["type"] != etype:
                continue
        if ev["type"] != etype:
            continue
        ev_dt = datetime.fromisoformat(ev["timestampLocal"])
        if ev_dt <= dt and (best is None or ev_dt >= best):
            best = ev_dt
            active = ev.get("epoch", "unknown")
    return active

# ---------------------------------------------------------------------------
def build(master_path=None, out_dir=None):
    master_path = master_path or P("drive_master.csv")
    out_dir = out_dir or HERE
    os.makedirs(out_dir, exist_ok=True)
    cfg = json.load(open(P("seasonal_config.json")))
    ledger = json.load(open(P("event_ledger.json")))
    scfg = json.load(open(P("summary_config.json")))
    ambient_by_drive = scfg.get("ambientByDrive", {})
    th = cfg["thermalThresholds"]

    md5_before = md5(master_path)
    rows = load_master(master_path)
    manual = load_manual(P("manual_observations.csv"))
    # raw-derived temperature triplets (from raw_temp_pass.py), if present
    triplets = {}
    tp = P("raw_temperature_triplets.csv")
    if os.path.exists(tp):
        with open(tp, newline="") as f:
            for t in csv.DictReader(f):
                triplets[t["file"].strip()] = t

    exclusions = set(ledger.get("typedExclusions", []))
    e4orce = set(ledger.get("e4orceSegregated", []))

    ambient_samples_out = {}
    derived = []

    # first pass: per-drive derived fields
    for r in rows:
        fname = r["file"].strip()
        if fname in exclusions or fname in e4orce:
            continue  # canonical FWD seasonal corpus only

        # --- calendar / local-utc ---
        tstart = r.get("time_start") or ""
        cal = sc.parse_drive_local_utc(fname, time_of_day=(tstart or None))
        drive_start_local = datetime.fromisoformat(cal["local_iso"])
        dur_s = _f(r.get("duration_s")) or 0.0
        drive_end_local = drive_start_local + timedelta(seconds=dur_s)

        # --- ambient ---
        rec = ambient_by_drive.get(fname)
        samples = sc.read_ambient_record(rec, filename=fname,
                                         drive_start_local=drive_start_local,
                                         drive_end_local=drive_end_local)
        amb = sc.ambient_derived_fields(samples)
        ambient_samples_out[fname] = {
            "samples": [
                {"timestampLocal": (s["t"].isoformat() if s["t"] else None),
                 "temperatureC": s["temperatureC"], "source": s["source"],
                 "uncertaintyClass": s["uncertaintyClass"]}
                for s in samples
            ]
        }

        regime = sc.classify_thermal_regime(amb["ambient_time_mean_c"], th)
        season = sc.meteorological_season(cal["calendar_month"])

        # --- temperature block: prefer raw-derived triplets, fall back to master ---
        tr = triplets.get(fname, {})
        def _tv(k):
            v = tr.get(k)
            try:
                return float(v) if v not in (None, "") else None
            except (TypeError, ValueError):
                return None
        pack_mean = _tv("pack_temp_time_mean_c")
        if pack_mean is None:
            pack_mean = _f(r.get("T_pack_mean_avg"))
        pack_max = _tv("pack_temp_max_c") or _f(r.get("T_pack_mean_max"))
        probe_max = _tv("pack_probe_max_c")
        if probe_max is None:
            probe_max = max([v for v in (_f(r.get("T1_peak")), _f(r.get("T2_peak")),
                                         _f(r.get("T3_peak")), _f(r.get("T4_peak")))
                             if v is not None], default=None)
        oil_max = _tv("oil_temp_max_c") or _f(r.get("T_oil_max"))
        eng_cool_max = _tv("engine_coolant_max_c") or _f(r.get("T_eng_coolant_max"))
        vcm_cool_max = _tv("vcm_coolant_max_c") or _f(r.get("T_coolant_max"))
        pack_start = _tv("pack_temp_start_c")
        oil_start = _tv("oil_temp_start_c")
        eng_cool_start = _tv("engine_coolant_start_c")
        temp_cov = "raw_derived" if tr else "unavailable"

        # --- SoC block (user-flagged thermal candidates) ---
        soc_min = _f(r.get("soc_min")); soc_max = _f(r.get("soc_max"))
        soc_span = (soc_max - soc_min) if (soc_min is not None and soc_max is not None) else None

        # --- payload from manual (blank-tolerant) ---
        m = manual.get(fname, {})
        payload = derive_payload(m, cfg)

        # --- ledger epochs ---
        tyre_epoch = epoch_for(ledger, "tyre_set", cal["local_iso"])
        ecu_epoch = epoch_for(ledger, "ecu_firmware", cal["local_iso"])

        d = {
            "file": fname,
            "date": r.get("date"),
            "local_iso": cal["local_iso"], "utc_iso": cal["utc_iso"],
            "utc_offset_h": cal["utc_offset_h"],
            "calendar_year": cal["calendar_year"],
            "calendar_month": cal["calendar_month"],
            "meteorological_season": season,
            "thermal_regime": regime,
            "thermal_regime_version": cfg["thermalRegimeVersion"],
            "odo_start": _f(r.get("odo_start")), "odo_end": _f(r.get("odo_end")),
            # authoritative distance: copied from drive_master.csv (single distance
            # function — B6/M291). Never re-derived from the raw odometer here, so a
            # master-side repair (e.g. 20260906_122920: -2.5 -> 0.44 km) propagates.
            "distance_km": _f(r.get("distance_km")),
            "duration_s": dur_s,
            "integr_time_h": _f(r.get("integr_time_h")),
            "drive_type": r.get("drive_type"),
            # ambient
            **amb,
            # pack/engine temps (max/time-mean available now; start/spread staged)
            "pack_temp_time_mean_c": pack_mean,
            "pack_temp_max_c": pack_max,
            "pack_probe_max_c": probe_max,
            "pack_temp_start_c": pack_start,
            "pack_spread_time_mean_c": _tv("pack_spread_time_mean_c"),
            "pack_spread_max_c": _tv("pack_spread_max_c") or _f(r.get("cell_spread_max_mv")),
            "oil_temp_max_c": oil_max, "oil_temp_start_c": oil_start,
            "oil_temp_time_mean_c": _tv("oil_temp_time_mean_c"),
            "engine_coolant_max_c": eng_cool_max, "engine_coolant_start_c": eng_cool_start,
            "engine_coolant_time_mean_c": _tv("engine_coolant_time_mean_c"),
            "vcm_coolant_max_c": vcm_cool_max, "vcm_coolant_start_c": _tv("vcm_coolant_start_c"),
            "batt_intake_start_c": _tv("batt_intake_start_c"),
            "batt_intake_time_mean_c": _tv("batt_intake_time_mean_c"),
            "motor_temp_start_c": _tv("motor_temp_start_c"),
            "motor_temp_max_c": _tv("motor_temp_max_c") or _f(r.get("T_motor_max")),
            "temp_start_coverage": temp_cov,
            # SoC (thermal candidates)
            "soc_min": soc_min, "soc_max": soc_max, "soc_range_span_pp": soc_span,
            "soc_mean_wtd_pct": _f(r.get("rf_socmean_wtd_pct")),
            "rf_n_cycles": _f(r.get("rf_n_cycles")), "rf_efc": _f(r.get("rf_efc")),
            # engine / EV / dissipation candidates
            "engine_on_pct": _f(r.get("engine_on_pct")),
            "ev_dist_pct": _f(r.get("ev_dist_pct")),
            "ev_dist_km": _f(r.get("ev_dist_km")),
            "ev_nr_km": _f(r.get("ev_nr_km")),
            "regen_influenced_ev_km": (
                (_f(r.get("ev_dist_km")) - _f(r.get("ev_nr_km")))
                if _f(r.get("ev_dist_km")) is not None and _f(r.get("ev_nr_km")) is not None
                else None),
            "ev_kwh_per100km": _f(r.get("ev_kwh_per100km")),
            "charge_eng_off_kwh": _f(r.get("charge_eng_off_kwh")),
            "regen_share_of_charge": _f(r.get("regen_share_of_charge")),
            "standstill_draw_kw": _f(r.get("standstill_draw_kw")),
            "vsag_R_pack_mohm": _f(r.get("vsag_R_pack_mohm")),
            # exposure / energy
            "gross_throughput_kwh": _f(r.get("gross_throughput_kwh")),
            "gtc": _f(r.get("gtc")),
            # payload / manual
            **payload,
            "hvac_class": m.get("hvac_class") or "HU",
            "cruise_class": m.get("cruise_class") or "CU",
            "precipitation_type": m.get("precipitation_type") or "unknown",
            "road_surface": m.get("road_surface") or "unknown",
            "logging_delay_class": m.get("logging_delay_class") or "unknown",
            # epochs
            "tyre_epoch": tyre_epoch, "ecu_epoch": ecu_epoch,
            # provenance
            "source_master_md5": md5_before,
            "seasonal_core_version": cfg["seasonalCoreVersion"],
        }
        derived.append(d)

    # second pass: parking continuity + cold-soak (needs ordered neighbours)
    derived.sort(key=lambda x: x["local_iso"])
    prev = None
    for d in derived:
        m = manual.get(d["file"], {})
        unlogged = (m.get("unlogged_use") or "unknown").strip() or "unknown"
        if prev is None:
            cont = {"logged_gap_h": None, "odometer_gap_km": None,
                    "odometer_gap_adj_km": None, "unlogged_distance_est_km": None,
                    "unlogged_use": unlogged, "parking_duration_lower_h": None,
                    "parking_duration_upper_h": None,
                    "continuity_status": "uncertain",
                    "continuity_reason_codes": ["first_drive_no_predecessor"]}
        else:
            cont = sc.parking_continuity(
                prev_end_local=datetime.fromisoformat(prev["local_iso"])
                + timedelta(seconds=prev["duration_s"]),
                prev_odo_end=_master_odo(prev, "end"),
                cur_start_local=datetime.fromisoformat(d["local_iso"]),
                cur_odo_start=_master_odo(d, "start"),
                unlogged_use=unlogged,
                odo_tolerance_km=cfg["continuity"]["odoToleranceKm"])
        d.update(cont)
        soak = sc.cold_soak_status(
            cont, pack_start_c=d["pack_temp_start_c"],
            engine_start_c=d["engine_coolant_start_c"],
            ambient_mean_c=d["ambient_time_mean_c"],
            pack_ambient_tol_c=cfg["coldSoak"]["packAmbientTolC"],
            engine_ambient_tol_c=cfg["coldSoak"]["engineAmbientTolC"])
        d.update(soak)
        prev = d

    # M291 (audit B6): single-distance-source invariant. The seasonal master's total
    # distance MUST equal the primary master's over the same canonical drives — the two
    # can never diverge because distance is copied, not re-derived. This guard fails the
    # build if a stale/divergent distance ever slips in (as the pre-M291 artifact did:
    # seasonal -2.5 vs master 0.44 on 20260906_122920).
    _seasonal_km = sum(d["distance_km"] for d in derived if d.get("distance_km") is not None)
    _master_km = sum(_f(r.get("distance_km")) for r in rows
                     if r["file"].strip() not in exclusions and r["file"].strip() not in e4orce
                     and _f(r.get("distance_km")) is not None)
    assert abs(_seasonal_km - _master_km) < 1e-6, (
        "distance divergence (B6): seasonal %.4f km != master %.4f km" % (_seasonal_km, _master_km))

    # ---- write per-drive derived master ----
    seasonal_master_path = os.path.join(out_dir, "seasonal_drive_master.csv")
    cols = list(derived[0].keys()) if derived else []
    with open(seasonal_master_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for d in derived:
            w.writerow({k: _serialize(v) for k, v in d.items()})

    # ---- cohort arrays ----
    arrays = build_arrays(derived, cfg)
    arrays_path = os.path.join(out_dir, "seasonal_arrays.json")
    json.dump(arrays, open(arrays_path, "w"), indent=1, ensure_ascii=False)

    # ---- ambient samples migration ----
    json.dump(ambient_samples_out, open(os.path.join(out_dir, "ambient_samples.json"), "w"),
              indent=0, ensure_ascii=False)

    # ---- manual template (only if none present) ----
    tmpl_path = os.path.join(out_dir, "manual_observations_template.csv")
    with open(tmpl_path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(MANUAL_COLUMNS)
        for d in derived:
            w.writerow([d["file"]] + [""] * (len(MANUAL_COLUMNS) - 1))

    md5_after = md5(master_path)
    assert md5_before == md5_after, "drive_master.csv MUTATED — abort"
    return {
        "n_canonical": len(derived),
        "master_md5": md5_after, "master_md5_unchanged": True,
        "seasonal_master": seasonal_master_path, "arrays": arrays_path,
        "cohorts": {k: v["coverage"]["n_drives"] for k, v in arrays["cohorts"].items()},
    }

def _master_odo(d, which):
    return d.get(f"odo_{which}")

def derive_payload(m, cfg):
    occ = m.get("occupants_total"); band = m.get("cargo_band")
    occ_n = None
    try:
        occ_n = int(occ) if occ not in (None, "", "missing") else None
    except ValueError:
        occ_n = None
    mids = cfg["payload"]["cargoMidpointsKg"]
    cargo_mid = mids.get(band) if band in mids else None
    add_kg = None
    if occ_n is not None:
        add_kg = cfg["payload"]["occupantMassKg"] * (occ_n - 1)
        if cargo_mid is not None:
            add_kg += cargo_mid
    pclass = "PU_unknown"
    if band == "over_200":
        pclass = "P3_heavy"
    elif add_kg is not None:
        if add_kg <= 25: pclass = "P0_minimal"
        elif add_kg <= 100: pclass = "P1_light"
        elif add_kg <= 250: pclass = "P2_moderate"
        else: pclass = "P3_heavy"
    return {"occupants_total": occ_n, "cargo_band": band or "unknown",
            "additional_payload_kg": add_kg, "payload_class": pclass}

# ---------------------------------------------------------------------------
def build_arrays(derived, cfg):
    """Recompute all cohort values from underlying drives via ratio-of-sums."""
    regimes = {"All observations": lambda d: True,
               "Warm": lambda d: d["thermal_regime"] == "warm",
               "Shoulder": lambda d: d["thermal_regime"] == "shoulder",
               "Cold": lambda d: d["thermal_regime"] == "cold"}
    dep = json.load(open(P("seasonal_dependency.json")))
    warn_cfg = cfg["warnings"]

    cohorts = {}
    for label, pred in regimes.items():
        pool = [d for d in derived if pred(d)]
        cov = sc.cohort_coverage(pool)
        metrics = {}
        # exposure totals
        for k in ["distance_km", "gross_throughput_kwh"]:
            metrics[k] = {"kind": "exposure_total", "value": sc.cohort_total(pool, k)}
        # per-100km rates (ratio-of-sums)
        for k in ["gross_throughput_kwh"]:
            metrics[k + "_per100km"] = {"kind": "rate",
                "value": sc.cohort_per_100km(pool, k)}
        # thermal-candidate drive-weighted means + pooled medians
        for k in ["engine_on_pct", "ev_dist_pct", "soc_range_span_pp",
                  "soc_mean_wtd_pct", "regen_share_of_charge",
                  "standstill_draw_kw", "vsag_R_pack_mohm", "rf_n_cycles"]:
            metrics[k] = {
                "kind": "drive_weighted_mean",
                "value": sc.cohort_drive_mean(pool, k),
                "pooled_median": sc.cohort_pooled_median(pool, k),
                "day_weighted_mean": sc.cohort_day_weighted_mean(pool, k),
            }
        # warnings
        warnings = []
        if cov["independent_days"] < warn_cfg["minIndependentDaysPerCohort"]:
            warnings.append(f"cohort_too_few_days:{cov['independent_days']}")
        if cov["n_drives"] < warn_cfg["minDrivesPerCohort"]:
            warnings.append(f"cohort_too_few_drives:{cov['n_drives']}")
        if cov["n_drives"] == 0:
            warnings.append("cohort_empty")
        cohorts[label] = {"coverage": cov, "metrics": metrics, "warnings": warnings}

    # cross-cohort support / adjusted-model availability
    cold_n = cohorts["Cold"]["coverage"]["n_drives"]
    shoulder_n = cohorts["Shoulder"]["coverage"]["n_drives"]
    global_warnings = []
    if cold_n == 0:
        global_warnings.append("no_cold_observations_adjusted_contrast_unavailable")
    if not _twelve_month_window(derived):
        global_warnings.append("observation_window_under_12_months_all_year_disabled")
    global_warnings.append("tyre_and_temperature_effects_not_separable_single_epoch")

    return {
        "_provenance": {
            "seasonalCoreVersion": cfg["seasonalCoreVersion"],
            "thermalRegimeVersion": cfg["thermalRegimeVersion"],
            "thresholds": cfg["thermalThresholds"],
            "generatedFrom": "seasonal_drive_master.csv (derived from drive_master.csv, read-only)",
        },
        "cohortLabelAll": cfg["cohorts"]["allLabel"],
        "allYearEnabled": _twelve_month_window(derived),
        "cohorts": cohorts,
        "seasonalDependency": dep,
        "adjustedContrastAvailable": cold_n > 0,
        "globalWarnings": global_warnings,
    }

def _twelve_month_window(derived):
    dates = sorted(d["date"] for d in derived if d.get("date"))
    if not dates:
        return False
    d0 = datetime.fromisoformat(dates[0]); d1 = datetime.fromisoformat(dates[-1])
    return (d1 - d0).days >= 365

def _serialize(v):
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return "" if v is None else v

if __name__ == "__main__":
    res = build()
    print(json.dumps(res, indent=2))
