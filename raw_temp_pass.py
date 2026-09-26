"""
raw_temp_pass.py  —  per-second raw temperature extraction (STAGED item now built)
==================================================================================
Reads canonical FWD raw CSVs (READ-ONLY), alias-normalises temperature channels
across all 34 header signatures, and derives per channel:
  * start   : median of valid samples in the first 30 s after that channel's
              first valid timestamp (NOT the first CSV row — PIDs refresh async)
  * time_mean : trapezoidal integral over actual sample intervals, gaps capped
  * max     : domain-validated maximum (missing never coerced to zero)
  * coverage: valid sample count, covered seconds, % of drive duration

Pack composite = per-timestamp arithmetic mean of valid T1-T4; spread = max-min
of valid probes at that timestamp. Individual probe maxima retained.

Output: raw_temperature_triplets.csv (keyed by canonical filename). Never mutates raw.
"""
from __future__ import annotations
import csv, glob, os, re, sys, statistics, json

RAW_DIR = "/mnt/project"
START_WINDOW_S = 30.0
GAP_CAP_S = 30.0     # intervals longer than this are treated as logging gaps

# alias sets (normalised exact-match, order = priority). ℃ char preserved.
ALIASES = {
    "T1": ["[BMS] HV Battery Temperature Sensor 1 (℃)"],
    "T2": ["[BMS] HV Battery Temperature Sensor 2 (℃)"],
    "T3": ["[BMS] HV Battery Temperature Sensor 3 (℃)"],
    "T4": ["[BMS] HV Battery Temperature Sensor 4 (℃)"],
    "batt_intake": ["[BMS] HV Battery Intake Air Temperature (℃)"],
    "vcm_coolant": ["[VCM] HV Coolant Temperature (℃)"],
    "motor": ["[VCM] Traction motor temperature (℃)"],
    "eng_oil": ["Температура олії у двигуні (℃)"],
    "eng_coolant": ["Температура охолодної рідини (℃)"],
}
# NOTE: the raw vehicle-ambient PID ("Температура оточуючого повітря") is intentionally
# NOT extracted as an ambient source. Ambient is supplied manually per drive
# (ambientByDrive, source=vehicle_sensor = driver-recorded from the vehicle readout).
# The raw PID is sparse (~4/367) and not the ambient measurement channel for this study.
# physical domain gates (°C): (lo, hi)
DOMAIN = {
    "T1": (-40, 80), "T2": (-40, 80), "T3": (-40, 80), "T4": (-40, 80),
    "batt_intake": (-40, 80), "vcm_coolant": (-40, 150), "motor": (-40, 180),
    "eng_oil": (-40, 160), "eng_coolant": (-40, 130), "veh_ambient": (-50, 60),
}

def parse_tod(s):
    """HH:MM:SS.mmm -> seconds of day (float). None if unparseable."""
    try:
        hh, mm, rest = s.split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(rest)
    except Exception:
        return None

def resolve_indices(header):
    idx = {}
    hmap = {h: i for i, h in enumerate(header)}
    for chan, names in ALIASES.items():
        for n in names:
            if n in hmap:
                idx[chan] = hmap[n]
                break
    tcol = 0  # 'time' is always col 0 in this archive
    return tcol, idx

def _valid(chan, v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    lo, hi = DOMAIN[chan]
    return x if (lo <= x <= hi) else None

def trajectory(series, bins_s):
    """Temp at elapsed-time bins since the channel's first valid sample (nearest
    sample within 0.5*bin tolerance). Returns {bin: value|None}. For warm-up curves."""
    if not series:
        return {b: None for b in bins_s}
    t0 = series[0][0]
    out = {}
    for b in bins_s:
        target = t0 + b
        best = None; bestdt = None
        for (t, v) in series:
            dt = abs(t - target)
            if bestdt is None or dt < bestdt:
                bestdt, best = dt, v
        tol = max(5.0, 0.5 * b)
        out[b] = round(best, 2) if (bestdt is not None and bestdt <= tol) else None
    return out


WARMUP_BINS = [30, 60, 120, 300, 600]


def channel_stats(series):
    """series: list of (t_s, value) valid pairs, time-ordered. Returns
    start/time_mean/max/coverage."""
    if not series:
        return {"start": None, "time_mean": None, "max": None,
                "n_valid": 0, "covered_s": 0.0}
    t0 = series[0][0]
    window = [v for (t, v) in series if t - t0 <= START_WINDOW_S]
    start = statistics.median(window) if window else series[0][1]
    # trapezoidal time-mean with gap cap
    num = den = 0.0
    for (ta, va), (tb, vb) in zip(series, series[1:]):
        dt = tb - ta
        if dt <= 0 or dt > GAP_CAP_S:
            continue
        num += ((va + vb) / 2.0) * dt
        den += dt
    time_mean = (num / den) if den > 0 else statistics.fmean(v for _, v in series)
    return {"start": round(start, 3), "time_mean": round(time_mean, 3),
            "max": round(max(v for _, v in series), 3),
            "n_valid": len(series), "covered_s": round(den, 1)}

def process_file(path, hold_s=10.0):
    """hold_s: probes T1-T4 refresh round-robin on separate rows; hold each
    probe's last valid value for up to hold_s seconds so the per-timestamp pack
    mean/spread use all currently-fresh probes rather than a single probe."""
    with open(path, newline="") as f:
        rd = csv.reader(f)
        header = next(rd)
        tcol, idx = resolve_indices(header)
        want = list(idx.keys())
        chan_series = {c: [] for c in want}
        pack_mean_series = []   # (t, mean of fresh valid T1-4)
        pack_spread_series = [] # (t, max-min of fresh valid T1-4, >=2 probes)
        probe_max = {p: None for p in ("T1", "T2", "T3", "T4")}
        probe_hold = {p: None for p in ("T1", "T2", "T3", "T4")}  # (t_last, v_last)
        first_t = last_t = None
        base = 0.0
        prev_raw = None
        for row in rd:
            if not row:
                continue
            t = parse_tod(row[tcol])
            if t is None:
                continue
            if prev_raw is not None and t + base < last_t - 1:
                base += 86400.0  # midnight wrap
            tt = t + base
            prev_raw = t
            if first_t is None:
                first_t = tt
            last_t = tt
            probe_updated = False
            for c in want:
                v = _valid(c, row[idx[c]]) if idx[c] < len(row) else None
                if v is not None:
                    chan_series[c].append((tt, v))
                    if c in probe_max:
                        probe_max[c] = v if probe_max[c] is None else max(probe_max[c], v)
                        probe_hold[c] = (tt, v)
                        probe_updated = True
            if probe_updated:
                fresh = [pv for ph in probe_hold.values() if ph is not None
                         for (pt, pv) in [ph] if tt - pt <= hold_s]
                if fresh:
                    pack_mean_series.append((tt, statistics.fmean(fresh)))
                    if len(fresh) >= 2:
                        pack_spread_series.append((tt, max(fresh) - min(fresh)))
        dur = (last_t - first_t) if (first_t is not None and last_t is not None) else 0.0

        out = {"file": os.path.basename(path), "drive_span_s": round(dur, 1)}
        # pack composite
        pk = channel_stats(pack_mean_series)
        out.update({"pack_temp_start_c": pk["start"],
                    "pack_temp_time_mean_c": pk["time_mean"],
                    "pack_temp_max_c": pk["max"],
                    "pack_temp_n_valid": pk["n_valid"],
                    "pack_temp_cov_pct": round(100 * pk["covered_s"] / dur, 1) if dur > 0 else None})
        sp = channel_stats(pack_spread_series)
        out.update({"pack_spread_time_mean_c": sp["time_mean"],
                    "pack_spread_max_c": sp["max"]})
        out["pack_probe_max_c"] = max([v for v in probe_max.values() if v is not None], default=None)
        # single channels
        for c in ("eng_oil", "eng_coolant", "vcm_coolant", "batt_intake", "motor"):
            st = channel_stats(chan_series.get(c, []))
            pfx = {"eng_oil": "oil_temp", "eng_coolant": "engine_coolant",
                   "vcm_coolant": "vcm_coolant", "batt_intake": "batt_intake",
                   "motor": "motor_temp"}[c]
            out[f"{pfx}_start_c"] = st["start"]
            out[f"{pfx}_time_mean_c"] = st["time_mean"]
            out[f"{pfx}_max_c"] = st["max"]
            out[f"{pfx}_cov_pct"] = (round(100 * st["covered_s"] / dur, 1)
                                     if dur > 0 and st["n_valid"] else None)
        # warm-up trajectories (oil + engine coolant) for WarmupCurve
        for c, pfx in (("eng_oil", "oil_wu"), ("eng_coolant", "cool_wu")):
            traj = trajectory(chan_series.get(c, []), WARMUP_BINS)
            for b in WARMUP_BINS:
                out[f"{pfx}_{b}s"] = traj[b]
        return out

def canonical_files():
    files = []
    for p in sorted(glob.glob(os.path.join(RAW_DIR, "*.csv"))):
        b = os.path.basename(p)
        if b.startswith(("e4ORCE_", "e4orce_")) or "_comparison" in b:
            continue
        if not re.match(r"^(\d{8}_\d{6}|\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.csv$", b):
            continue
        files.append(p)
    return files

if __name__ == "__main__":
    import pickle
    args = sys.argv[1:]
    files = canonical_files()
    if len(args) == 2:  # chunked: START END
        s, e = int(args[0]), int(args[1])
        files = files[s:e]
        rows = [process_file(p) for p in files]
        pickle.dump(rows, open(f"_temp_chunk_{s}_{e}.pkl", "wb"))
        print(f"chunk {s}:{e} -> {len(rows)} drives")
    else:
        rows = [process_file(p) for p in files]
        cols = list(rows[0].keys())
        with open("raw_temperature_triplets.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
            for r in rows:
                w.writerow({k: ("" if v is None else v) for k, v in r.items()})
        print(f"wrote raw_temperature_triplets.csv: {len(rows)} drives, {len(cols)} cols")
