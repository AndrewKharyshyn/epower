"""
seasonal_core.py  —  X-Trail T33 e-POWER seasonal-management foundation
=======================================================================

Pure, deterministic, side-effect-free functions shared by the compute engine
(`compute_seasonal.py`), the aggregator, and the test suite (`test_seasonal.py`).

Design rules honoured here (from the implementation handoff and project methodology):
  * Never mutate a raw CSV. This module only *reads* derived values passed in.
  * Ratio-of-sums for rates; pooled recompute for medians/quantiles; never
    mean-of-drive-ratios and never average-of-seasonal-medians.
  * Missing channels stay missing (None/NaN), never coerced to physical zero.
  * Thermal regimes are reporting bins over a continuous variable; thresholds
    live in config and are versioned.
  * Local time is Europe/Kyiv, DST-aware; both local-aware and UTC are retained.

Author stamp: SEASONAL_CORE_VERSION below.
"""
from __future__ import annotations

import hashlib
import math
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SEASONAL_CORE_VERSION = "seasonal_core_v1.0.0"
PROJECT_TZ = ZoneInfo("Europe/Kyiv")

# ---------------------------------------------------------------------------
# Thermal-regime binning  (continuous var -> reporting bin)
# ---------------------------------------------------------------------------
# Defaults; the live values are read from seasonal_config.json at compute time
# and passed in explicitly so sensitivity runs can override them.
DEFAULT_THERMAL_THRESHOLDS = {"cold_max_c": 5.0, "warm_min_c": 15.0}
THERMAL_REGIME_VERSION = "regime_v1_5_15"


def classify_thermal_regime(temp_c, thresholds=None):
    """Bin a drive-mean ambient (deg C) into cold/shoulder/warm.

    Boundary convention (exact, testable):
        cold     : temp <= cold_max_c        (<= 5.0)
        shoulder : cold_max_c < temp < warm_min_c   (5.0 < t < 15.0)
        warm     : temp >= warm_min_c         (>= 15.0)

    Returns None when temp is missing — a missing ambient must not be silently
    binned as any regime.
    """
    if temp_c is None or (isinstance(temp_c, float) and math.isnan(temp_c)):
        return None
    th = thresholds or DEFAULT_THERMAL_THRESHOLDS
    if temp_c <= th["cold_max_c"]:
        return "cold"
    if temp_c >= th["warm_min_c"]:
        return "warm"
    return "shoulder"


def meteorological_season(month, hemisphere_north=True):
    """Meteorological season from calendar month (N. hemisphere by default)."""
    if month is None:
        return None
    winter, spring, summer, autumn = (12, 1, 2), (3, 4, 5), (6, 7, 8), (9, 10, 11)
    if month in winter:
        return "winter"
    if month in spring:
        return "spring"
    if month in summer:
        return "summer"
    return "autumn"


# ---------------------------------------------------------------------------
# Local-time parsing  (Europe/Kyiv, DST-aware)
# ---------------------------------------------------------------------------
def parse_drive_local_utc(filename, time_of_day=None):
    """Parse a canonical drive filename (YYYYMMDD_HHMMSS[.csv], optional
    e4ORCE_ prefix) into (local_aware_iso, utc_iso, calendar_year,
    calendar_month). If `time_of_day` (HH:MM:SS[.ms]) is given it overrides the
    filename time component (used when the first valid CSV row differs).

    DST is resolved by zoneinfo. Kyiv is UTC+2 (EET) in winter, UTC+3 (EEST)
    in summer; the last-Sunday transitions are handled by the tz database.
    """
    stem = filename
    for pref in ("e4ORCE_", "e4orce_"):
        if stem.startswith(pref):
            stem = stem[len(pref):]
    stem = stem.split(".")[0]
    # accept "YYYYMMDD_HHMMSS" and trailing suffixes like "_B_D_comparison"
    parts = stem.split("_")
    datestr = parts[0]
    timestr = parts[1] if len(parts) > 1 else "000000"
    # dual-format: compact YYYYMMDD or dashed YYYY-MM-DD (filename convention
    # changed 2026-09; the seasonal toolchain predated it — this accepts both).
    if "-" in datestr:
        y, mo, d = (int(x) for x in datestr.split("-"))
    else:
        y, mo, d = int(datestr[0:4]), int(datestr[4:6]), int(datestr[6:8])
    if time_of_day:
        t = time_of_day.split(".")[0].split(":")
        hh, mm, ss = int(t[0]), int(t[1]), int(t[2]) if len(t) > 2 else 0
    elif "-" in timestr:
        hh, mm, ss = (int(x) for x in timestr.split("-"))
    else:
        hh, mm, ss = int(timestr[0:2]), int(timestr[2:4]), int(timestr[4:6])
    local = datetime(y, mo, d, hh, mm, ss, tzinfo=PROJECT_TZ)
    utc = local.astimezone(ZoneInfo("UTC"))
    return {
        "local_iso": local.isoformat(),
        "utc_iso": utc.isoformat(),
        "calendar_year": y,
        "calendar_month": mo,
        "utc_offset_h": local.utcoffset().total_seconds() / 3600.0,
    }


# ---------------------------------------------------------------------------
# Ambient temperature: legacy-array reader + timestamped-sample derivation
# ---------------------------------------------------------------------------
def read_ambient_record(record, filename=None, drive_start_local=None,
                        drive_end_local=None):
    """Normalise either the LEGACY representation or the NEW timestamped-sample
    representation into a common list of samples:
        [{"t": datetime|None, "temperatureC": float, "source": str,
          "uncertaintyClass": str}, ...]

    Legacy inputs accepted (project convention -> vehicle_sensor unless an
    explicit weather override is present on the record):
        [start, end]                       -> 2 samples
        [start, interim, end]              -> 3 samples
        scalar                             -> 1 sample
    A dict with {"samples":[...]} is treated as already-new; a dict with
    {"source":"weather..."} on a legacy array applies that source instead of
    defaulting to vehicle_sensor (do NOT mislabel weather as vehicle-measured).
    """
    default_source = "vehicle_sensor"
    default_unc = "vehicle_uncalibrated"

    # New representation ---------------------------------------------------
    if isinstance(record, dict) and "samples" in record:
        out = []
        for s in record["samples"]:
            out.append({
                "t": _parse_iso(s.get("timestampLocal")),
                "temperatureC": _f(s.get("temperatureC")),
                "source": s.get("source", default_source),
                "uncertaintyClass": s.get("uncertaintyClass", default_unc),
            })
        return out

    # Legacy dict wrapper with explicit override --------------------------
    override_source = None
    override_unc = None
    arr = record
    if isinstance(record, dict):
        arr = record.get("values") or record.get("array")
        if record.get("source"):
            override_source = record["source"]
        if record.get("uncertaintyClass"):
            override_unc = record["uncertaintyClass"]
    src = override_source or default_source
    unc = override_unc or ("weather_reanalysis" if src != "vehicle_sensor"
                           else default_unc)

    if isinstance(arr, (int, float)):
        arr = [arr]
    if not isinstance(arr, (list, tuple)) or len(arr) == 0:
        return []

    # Distribute legacy points across the drive span if start/end known.
    n = len(arr)
    ts = [None] * n
    if drive_start_local is not None and drive_end_local is not None and n >= 2:
        span = (drive_end_local - drive_start_local).total_seconds()
        for i in range(n):
            frac = i / (n - 1)
            ts[i] = drive_start_local + timedelta(seconds=span * frac)
    elif drive_start_local is not None:
        ts[0] = drive_start_local
    return [{"t": ts[i], "temperatureC": _f(arr[i]),
             "source": src, "uncertaintyClass": unc} for i in range(n)]


def ambient_derived_fields(samples):
    """Compute the required ambient derived fields from a normalised sample
    list. Time-weighted mean uses trapezoidal integration when >=2 samples
    carry timestamps; otherwise falls back to the arithmetic mean and the
    result is flagged `interpolated` (start/end only -> interpolated drive
    mean, NOT a continuous mean).

        ambient_time_mean = sum(((T[i]+T[i+1])/2)*dt[i]) / sum(dt[i])
    """
    vals = [s["temperatureC"] for s in samples if s["temperatureC"] is not None]
    if not vals:
        return {
            "ambient_start_c": None, "ambient_end_c": None,
            "ambient_time_mean_c": None, "ambient_time_mean_kind": "unavailable",
            "ambient_sampled_min_c": None, "ambient_sampled_max_c": None,
            "ambient_n_points": 0, "ambient_source_primary": None,
            "ambient_source_mixed": False, "ambient_uncertainty_class": None,
            "ambient_source_timestamps": [],
        }
    sources = [s["source"] for s in samples if s["temperatureC"] is not None]
    uncs = [s["uncertaintyClass"] for s in samples if s["temperatureC"] is not None]
    primary = statistics.mode(sources) if sources else None
    mixed = len(set(sources)) > 1

    timed = [s for s in samples
             if s["temperatureC"] is not None and s["t"] is not None]
    mean_kind = "arithmetic_fallback"
    if len(timed) >= 2:
        timed = sorted(timed, key=lambda s: s["t"])
        num = den = 0.0
        for a, b in zip(timed, timed[1:]):
            dt = (b["t"] - a["t"]).total_seconds()
            if dt <= 0:
                continue
            num += ((a["temperatureC"] + b["temperatureC"]) / 2.0) * dt
            den += dt
        if den > 0:
            time_mean = num / den
            mean_kind = ("trapezoidal" if len(timed) >= 3
                         else "interpolated_start_end")
        else:
            time_mean = statistics.fmean(vals)
    else:
        time_mean = statistics.fmean(vals)

    return {
        "ambient_start_c": vals[0],
        "ambient_end_c": vals[-1],
        "ambient_time_mean_c": round(time_mean, 4),
        "ambient_time_mean_kind": mean_kind,
        "ambient_sampled_min_c": min(vals),   # sampled-point extremum, not continuous
        "ambient_sampled_max_c": max(vals),
        "ambient_n_points": len(vals),
        "ambient_source_primary": primary,
        "ambient_source_mixed": mixed,
        "ambient_uncertainty_class": (uncs[0] if len(set(uncs)) == 1 else "mixed"),
        "ambient_source_timestamps": [
            (s["t"].isoformat() if s["t"] is not None else None) for s in samples
        ],
    }


# ---------------------------------------------------------------------------
# Parking continuity + cold-soak (interval-censored, evidence classes)
# ---------------------------------------------------------------------------
def parking_continuity(prev_end_local, prev_odo_end, cur_start_local,
                       cur_odo_start, unlogged_use="unknown",
                       odo_tolerance_km=1.0):
    """Compute continuity between two consecutive canonical FWD drives.

    Returns logged gap, odometer-gap estimate (tolerance-adjusted and raw),
    an interval-censored parking bound, and a continuity_status in
    {consistent, broken, uncertain} with reason codes. When use is unknown the
    logged gap is only an UPPER bound on parking duration.
    """
    reason = []
    logged_gap_h = None
    if prev_end_local is not None and cur_start_local is not None:
        logged_gap_h = (cur_start_local - prev_end_local).total_seconds() / 3600.0

    odo_gap_raw = None
    if prev_odo_end is not None and cur_odo_start is not None:
        odo_gap_raw = cur_odo_start - prev_odo_end
    odo_gap_adj = None
    unlogged_km = 0.0
    if odo_gap_raw is not None:
        odo_gap_adj = odo_gap_raw if abs(odo_gap_raw) > odo_tolerance_km else 0.0
        unlogged_km = max(0.0, odo_gap_adj)

    # continuity status
    if unlogged_use == "yes":
        status = "broken"
        reason.append("explicit_unlogged_use")
    elif odo_gap_adj is not None and odo_gap_adj > odo_tolerance_km:
        status = "broken"
        reason.append("odometer_discontinuity")
    elif unlogged_use == "no" and (odo_gap_adj is not None and odo_gap_adj <= odo_tolerance_km):
        status = "consistent"
        reason.append("odo_within_tolerance_no_unlogged")
    else:
        status = "uncertain"
        if unlogged_use == "unknown":
            reason.append("unlogged_use_unknown")
        if odo_gap_raw is None:
            reason.append("odometer_gap_unavailable")

    # interval censoring: parking duration lower/upper
    park_lower = None
    park_upper = None
    if logged_gap_h is not None:
        if status == "consistent":
            park_lower = park_upper = logged_gap_h
        else:
            park_lower = 0.0            # could have been driven right up to start
            park_upper = logged_gap_h   # logged gap is an upper bound only

    return {
        "logged_gap_h": _r(logged_gap_h),
        "odometer_gap_km": _r(odo_gap_raw),
        "odometer_gap_adj_km": _r(odo_gap_adj),
        "unlogged_distance_est_km": _r(unlogged_km),
        "unlogged_use": unlogged_use,
        "parking_duration_lower_h": _r(park_lower),
        "parking_duration_upper_h": _r(park_upper),
        "continuity_status": status,
        "continuity_reason_codes": reason,
    }


# parked-cooling time constant documented in the study (M-series thermal decay)
PARK_COOLING_TAU_H = 17.6


def cold_soak_status(continuity, pack_start_c, engine_start_c, ambient_mean_c,
                     long_park_6h=None, long_park_12h=None,
                     pack_ambient_tol_c=3.0, engine_ambient_tol_c=5.0):
    """Strict cold-soak classification kept SEPARATE from calendar/ambient/park.

    A `confirmed` cold soak requires (a) a long gap, (b) continuity consistent
    with no unlogged use, and (c) observed starting thermal proximity to
    ambient. Six hours alone is NOT a complete soak (tau ~= 17.6 h): a 6 h gap
    recovers only ~1-exp(-6/17.6) ~= 29% toward ambient. Thresholds are
    configurable and sensitivity to them is reported upstream.
    Emits `confirmed|probable|not_cold_soaked|unknown` + confidence + reasons.
    """
    reason = []
    gap = continuity.get("logged_gap_h")
    status_cont = continuity.get("continuity_status")

    if long_park_6h is None:
        long_park_6h = (gap is not None and gap >= 6.0)
    if long_park_12h is None:
        long_park_12h = (gap is not None and gap >= 12.0)

    pack_near = (pack_start_c is not None and ambient_mean_c is not None
                 and abs(pack_start_c - ambient_mean_c) <= pack_ambient_tol_c)
    eng_near = (engine_start_c is not None and ambient_mean_c is not None
                and abs(engine_start_c - ambient_mean_c) <= engine_ambient_tol_c)

    # unknown if we lack the thermal evidence to judge proximity at all
    if pack_start_c is None and engine_start_c is None:
        reason.append("no_start_thermal_channel")
        return {"long_park_6h": long_park_6h, "long_park_12h": long_park_12h,
                "pack_near_ambient": None, "engine_near_ambient": None,
                "cold_soak_status": "unknown", "cold_soak_confidence": 0.0,
                "cold_soak_reason_codes": reason}

    if long_park_12h and status_cont == "consistent" and pack_near and eng_near:
        status, conf = "confirmed", 0.9
        reason += ["long_park_12h", "continuity_consistent", "pack_near_ambient",
                   "engine_near_ambient"]
    elif long_park_6h and status_cont in ("consistent", "uncertain") and pack_near:
        status, conf = "probable", 0.5
        reason += ["long_park_6h", "pack_near_ambient"]
        if status_cont == "uncertain":
            reason.append("continuity_uncertain_caps_confidence")
    elif (gap is not None and gap < 6.0) or (pack_start_c is not None and not pack_near):
        status, conf = "not_cold_soaked", 0.7
        if gap is not None and gap < 6.0:
            reason.append("short_gap")
        if pack_start_c is not None and not pack_near:
            reason.append("pack_warm_at_start")
    else:
        status, conf = "unknown", 0.2
        reason.append("insufficient_evidence")

    return {"long_park_6h": bool(long_park_6h), "long_park_12h": bool(long_park_12h),
            "pack_near_ambient": pack_near, "engine_near_ambient": eng_near,
            "cold_soak_status": status, "cold_soak_confidence": conf,
            "cold_soak_reason_codes": reason}


# ---------------------------------------------------------------------------
# Cohort aggregation  (ratio-of-sums; pooled medians; drive/day weighting)
# ---------------------------------------------------------------------------
def aggregate_cohort(drives, distance_key="distance_km"):
    """Aggregate a list of per-drive dicts into cohort totals & rates using
    the ONE correct method:

        total(x)          = sum(x_i)
        per_100km(x)      = 100 * sum(x_i) / sum(distance_i)
        events_per_100km  = 100 * sum(events_i) / sum(distance_i)
        hourly_rate(x)    = sum(x_i) / sum(valid_hours_i)
        pooled_median(x)  = median over the pooled per-drive values
                            (NOT mean of per-drive medians)
        drive_mean(x)     = mean over drives            (label: drive-weighted)
        day_mean(x)       = mean over per-day means      (label: day-weighted)

    Also returns cohort coverage: n drives, km, independent days, date range,
    ambient range. Returns a well-formed EMPTY result for an empty cohort
    (never raises, never renders as zero-that-looks-real).
    """
    n = len(drives)
    if n == 0:
        return {"n_drives": 0, "km": 0.0, "independent_days": 0,
                "date_range": None, "ambient_range_c": None,
                "empty": True, "sum": {}, "per100km": {}, "pooled_median": {},
                "drive_mean": {}, "day_weighted_mean": {}, "hourly_rate": {}}

    def _vals(key):
        return [d[key] for d in drives
                if d.get(key) is not None and not _isnan(d.get(key))]

    total_km = sum(_vals(distance_key))
    days = sorted({d.get("date") for d in drives if d.get("date")})
    amb = _vals("ambient_time_mean_c")

    out = {
        "n_drives": n,
        "km": round(total_km, 3),
        "independent_days": len(days),
        "date_range": [days[0], days[-1]] if days else None,
        "ambient_range_c": [min(amb), max(amb)] if amb else None,
        "empty": False,
        "sum": {}, "per100km": {}, "pooled_median": {},
        "drive_mean": {}, "day_weighted_mean": {}, "hourly_rate": {},
    }
    return out, total_km, days  # partial; specific metrics filled by helpers


def cohort_total(drives, key):
    return sum(d[key] for d in drives if d.get(key) is not None and not _isnan(d[key]))


def _pair_eligible(drives, quantity_key, distance_key="distance_km"):
    """Drives that contribute to BOTH numerator and denominator of a rate:
    the quantity is present & finite AND the exposure (distance/hours) is
    present, finite and strictly positive. A drive failing either test
    contributes to NEITHER sum — a missing/NaN numerator can never inject its
    exposure into the denominator (the M284 low-bias defect), and the paired
    basis (n, exposure) is auditable via cohort_per_100km_detail."""
    def ok(d, k):
        v = d.get(k)
        return v is not None and not _isnan(v)
    return [d for d in drives
            if ok(d, quantity_key) and ok(d, distance_key) and d[distance_key] > 0]


def cohort_per_100km_detail(drives, quantity_key, distance_key="distance_km"):
    """Paired ratio-of-sums WITH the paired basis exposed. Returns
    {"value", "paired_n", "paired_km"} where value = 100*sum(num)/sum(exposure)
    over the paired-eligible drives only, paired_n is how many drives that was,
    and paired_km is the exposure (distance) actually in the denominator. Every
    displayed rate can therefore state exactly the n and km behind it, and a
    null-numerator drive never inflates the denominator (its distance is
    excluded because it is not paired-eligible)."""
    elig = _pair_eligible(drives, quantity_key, distance_key)
    num = sum(d[quantity_key] for d in elig)
    den = sum(d[distance_key] for d in elig)
    return {"value": (100.0 * num / den) if den > 0 else None,
            "paired_n": len(elig), "paired_km": round(den, 3)}


def cohort_per_100km(drives, quantity_key, distance_key="distance_km"):
    """Ratio-of-sums over PAIRED-eligible drives only (M284): numerator and denominator are summed
    over the same drives. Previously the denominator also counted distance of drives whose numerator
    was missing, biasing the rate low (e.g. kWh/100km 16.69 vs 17.10 on the 410-drive corpus).
    Thin wrapper over cohort_per_100km_detail (M291: single paired-eligibility definition)."""
    return cohort_per_100km_detail(drives, quantity_key, distance_key)["value"]


def cohort_events_per_100km(drives, events_key, distance_key="distance_km"):
    return cohort_per_100km(drives, events_key, distance_key)


def cohort_events_per_100km_detail(drives, events_key, distance_key="distance_km"):
    return cohort_per_100km_detail(drives, events_key, distance_key)


def cohort_hourly_rate(drives, events_key, hours_key="integr_time_h"):
    """Paired ratio-of-sums per hour (M291: paired-eligibility, matching
    cohort_per_100km). A drive whose event count is missing/NaN no longer
    contributes its hours to the denominator (the same low-bias defect that
    was fixed for the per-100km rates)."""
    elig = _pair_eligible(drives, events_key, hours_key)
    num = sum(d[events_key] for d in elig)
    den = sum(d[hours_key] for d in elig)
    return (num / den) if den > 0 else None


def cohort_pooled_median(drives, key):
    vals = [d[key] for d in drives if d.get(key) is not None and not _isnan(d[key])]
    return statistics.median(vals) if vals else None


def cohort_pooled_quantile(drives, key, q):
    vals = sorted(d[key] for d in drives
                  if d.get(key) is not None and not _isnan(d[key]))
    if not vals:
        return None
    idx = q * (len(vals) - 1)
    lo, hi = int(math.floor(idx)), int(math.ceil(idx))
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (idx - lo)


def cohort_drive_mean(drives, key):
    vals = [d[key] for d in drives if d.get(key) is not None and not _isnan(d[key])]
    return statistics.fmean(vals) if vals else None


def cohort_day_weighted_mean(drives, key):
    """Aggregate within day first (mean per day), then mean across days."""
    by_day = {}
    for d in drives:
        v = d.get(key)
        if v is None or _isnan(v):
            continue
        by_day.setdefault(d.get("date"), []).append(v)
    day_means = [statistics.fmean(vs) for vs in by_day.values() if vs]
    return statistics.fmean(day_means) if day_means else None


def cohort_coverage(drives, distance_key="distance_km"):
    days = sorted({d.get("date") for d in drives if d.get("date")})
    amb = [d["ambient_time_mean_c"] for d in drives
           if d.get("ambient_time_mean_c") is not None
           and not _isnan(d["ambient_time_mean_c"])]
    return {
        "n_drives": len(drives),
        "km": round(cohort_total(drives, distance_key), 3),
        "independent_days": len(days),
        "date_range": [days[0], days[-1]] if days else None,
        "ambient_range_c": [round(min(amb), 1), round(max(amb), 1)] if amb else None,
    }


# ---------------------------------------------------------------------------
# Schema hashing / PID epoch
# ---------------------------------------------------------------------------
def raw_schema_hash(header_fields):
    """Stable hash of a normalised raw-CSV header (order-preserving)."""
    norm = "|".join(h.strip() for h in header_fields)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _r(x, nd=4):
    return None if x is None else round(x, nd)


def _isnan(x):
    return isinstance(x, float) and math.isnan(x)


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None
