#!/usr/bin/env python3
"""Emulated sampling-sensitivity of the pipeline keys to the logger PID cadence (M379b, analyses/M379_spec.md Rev 2 and Rev 3). Library.
The raw logs are one row per logger tick with each PID non-missing only when it was updated. To emulate a SLOWER cadence on a fast-cadence drive, every data PID
column is thinned independently: starting from its first sample, the next kept sample is the available sample NEAREST to (last kept time + a drawn interval), the drawn
intervals coming from the empirical slow-regime interval distribution of the SAME column (pooled over slow-regime drives, seeded); a column without enough slow-regime
samples uses the slow-regime I-PID pool scaled by (the column's native median interval / the native median I-PID interval of the drive). The GPS columns and the time
column are not thinned. The result is NOT a causal cadence effect: PID-set / polling-order changes, I-V co-timing, jitter and app-internal calculations are not emulated.
analyze_bytes (compute_drive_summary_v6) is run on the original and on the emulated bytes; nothing is written to the master. The post-step offset keys are recomputed
from the emitted drive quantities with the frozen formula checked against the master (offset_kwh_removed = I_offset_A_applied * integr_time_h * V_pack_median / 1000)."""
import io, os, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
GPS = ("Latitude", "Longtitude")
MIN_POOL = 200
# keys reported by the study (frozen in Rev 2): name -> kind
KEYS = {"gross_throughput_kwh": "ratio", "gross_discharge_kwh": "ratio", "gross_charge_kwh": "ratio", "distance_km": "ratio",
        "net_draw_kwh_corr": "net", "energy_residual_kwh": "net", "offset_kwh_removed": "net", "net_draw_per100km_corr": "net100",
        "engine_on_pct": "pct", "regen_share_of_charge": "pct", "ev_dist_pct": "pct",
        "peak_discharge_kw": "peak", "peak_I_charge": "peak",
        "n_I_samples": "count", "n_loaded_spread_samples": "count",
        "rf_efc": "ratio", "fce": "ratio", "soc_delta_kwh": "net", "ev_kwh_per100km": "net100", "standstill_draw_kw": "net",
        "vsag_R_pack_mohm": "net", "iv_alignment_gap_s": "net"}
BASE_KEYS = [k for k in KEYS if k not in ("net_draw_kwh_corr", "offset_kwh_removed", "net_draw_per100km_corr")] + ["net_draw_kwh", "integr_time_h", "V_pack_median"]


def read_frame(csv_bytes):
    df = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    t = pd.to_timedelta(df.iloc[:, 0]).dt.total_seconds().values
    return df, t


def data_columns(df):
    return [c for c in df.columns[1:] if c not in GPS]


def intervals(df, t, cols):
    out = {}
    for c in cols:
        m = pd.to_numeric(df[c], errors="coerce").notna().values
        ts = t[m]
        if len(ts) > 2:
            d = np.diff(ts)
            d = d[(d > 0.05) & (d < 120.0)]
            if len(d):
                out[c] = d
    return out


def build_pools(slow_paths, max_per_col=20000):
    """Pooled slow-regime inter-sample intervals per column (seconds)."""
    acc = {}
    for p in slow_paths:
        df, t = read_frame(open(p, "rb").read())
        for c, d in intervals(df, t, data_columns(df)).items():
            acc.setdefault(c, []).append(d)
    pools = {c: np.concatenate(v) for c, v in acc.items()}
    return {c: (v if len(v) <= max_per_col else v[np.linspace(0, len(v) - 1, max_per_col).astype(int)]) for c, v in pools.items()}


def thin_column(ts, draws, keep_all=False, rng=None):
    """Indices (into ts) of the kept samples: the first sample, then repeatedly a sample next to (last kept time + next drawn interval). The two samples that bracket the
    target time are chosen with probability proportional to closeness (dithering), so the expected kept time equals the target and the median interval is not snapped to
    multiples of the native spacing."""
    n = len(ts)
    if keep_all or n < 3:
        return np.arange(n)
    keep = [0]
    t_last = ts[0]
    k = 0
    while True:
        t_next = t_last + draws[k % len(draws)]
        k += 1
        hi = int(np.searchsorted(ts, t_next))
        if hi >= n:
            break
        lo = hi - 1
        if lo < 0 or ts[hi] == ts[lo]:
            j = hi
        elif rng is None:        # nearest-sample variant (emulator-robustness check, Rev 3): no dithering
            j = hi if (ts[hi] - t_next) < (t_next - ts[lo]) else lo
        else:
            w = (t_next - ts[lo]) / (ts[hi] - ts[lo])
            j = hi if rng.random() < w else lo
        if j <= keep[-1]:
            j = keep[-1] + 1
            if j >= n:
                break
        keep.append(j)
        t_last = ts[j]
    return np.array(keep)


def emulate(csv_bytes, pools, rng, factor=1.0, keep_all=False, dither=True):
    """Return (emulated csv bytes, report dict with the median I-PID interval before / after)."""
    df, t = read_frame(csv_bytes)
    cols = data_columns(df)
    nat = intervals(df, t, cols)
    icol = next((c for c in cols if "HV Battery Current (A)" in c), None)
    i_native = float(np.median(nat[icol])) if icol in nat else None
    out = df.copy()
    rep = {}
    for c in cols:
        v = pd.to_numeric(df[c], errors="coerce")
        m = v.notna().values
        idx = np.flatnonzero(m)
        if len(idx) < 3:
            continue
        ts = t[idx]
        pool = pools.get(c)
        if pool is None or len(pool) < MIN_POOL:
            ip = pools.get(icol)
            if ip is None or i_native is None or c not in nat:
                continue
            pool = ip * (float(np.median(nat[c])) / i_native)
        draws = rng.choice(pool, size=max(4, int(len(ts) * 2)), replace=True) * factor
        kept = thin_column(ts, draws, keep_all=keep_all or factor <= 0, rng=rng if dither else None)
        drop = np.setdiff1d(np.arange(len(idx)), kept)
        if len(drop):
            out.iloc[idx[drop], out.columns.get_loc(c)] = np.nan
        if c == icol:
            kt = ts[kept]
            dd = np.diff(kt)
            dc = dd[dd < 5.0]
            rep["I_interval_median_s"] = float(np.median(dd)) if len(dd) else None
            if len(dc):
                rep["I_interval_lt5"] = {"n": int(len(dc)), "mean": float(dc.mean()), "median": float(np.median(dc)), "q": [float(x) for x in np.percentile(dc, [10, 25, 75, 90])]}
            rep["I_native_median_s"] = i_native
            rep["nI_before"], rep["nI_after"] = int(len(ts)), int(len(kept))
    return out.to_csv(index=False, lineterminator="\n").encode("utf-8"), rep


def keys_of(analysis, i_offset):
    """Study keys from one analyze_bytes row (+ the three post-step offset keys recomputed with the frozen formula)."""
    r = dict(analysis)
    out = {k: r.get(k) for k in BASE_KEYS}
    try:
        off = float(i_offset) * float(r["integr_time_h"]) * float(r["V_pack_median"]) / 1000.0
        out["offset_kwh_removed"] = off
        out["net_draw_kwh_corr"] = float(r["net_draw_kwh"]) - off
        out["net_draw_per100km_corr"] = out["net_draw_kwh_corr"] / float(r["distance_km"]) * 100.0 if float(r["distance_km"]) > 0 else None
    except (TypeError, ValueError, KeyError):
        out["offset_kwh_removed"] = out["net_draw_kwh_corr"] = out["net_draw_per100km_corr"] = None
    return {k: (None if v is None or (isinstance(v, float) and v != v) else v) for k, v in out.items() if k in KEYS}


def run_drive(path, pools, seed, drive_index, factor, i_offset, keep_all=False, dither=True):
    """Emulate one drive at one seed and return (keys, report)."""
    import compute_drive_summary_v6 as C
    rng = np.random.default_rng(seed * 100003 + drive_index)
    b, rep = emulate(open(path, "rb").read(), pools, rng, factor=factor, keep_all=keep_all, dither=dither)
    r = C.analyze_bytes(b, os.path.basename(path))
    return keys_of(r, i_offset), rep
