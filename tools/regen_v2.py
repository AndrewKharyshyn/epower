#!/usr/bin/env python3
"""M441 (spec analyses/M441_spec.md Rev 2.1): interval-based extractor v2 of the apparent battery-side KE recovery (regen programme, stage MC).
extract_drive(df, ...) works on NATIVE samples (raw rows with a numeric in-range value), never on a fixed 1 s grid:
  - speed intervals = spans between consecutive native speed samples (dt in (0, 5] s; longer spans are gaps and are never bridged);
  - current and voltage are interpolated piecewise-linearly through EVERY native sample (each bracketing gap <= 5 s); charge energy = integral of max(I V / 1000, 0) (BMS current is charge-positive) on equal slices of <= 0.05 s (trapezoid);
  - engine-off = RPM known and <= 300 at both interval ends (latest native sample, age <= 5 s) and no native RPM sample inside above 300; unknown is never off;
  - episodes: maximal runs of consecutive valid engine-off intervals with v1 <= v0; leading/trailing plateaus are trimmed (reported, not in the estimator); inner plateaus enter with KE 0 and their charge;
  - speed bins by the INSTANTANEOUS speed (linear inside an interval): each slice's exact KE loss and charge go to the 10 km/h bin of its mid-point speed (bins 0..12, bin 13 = overflow >= 130 km/h);
  - pack temperature (all four probes, age <= 10 s) and SOC (age <= 10 s, 0-100) are attributes at the interval START.
Mass-free quantities are stored (dv2 in (km/h)^2); the class mass and the cohort are applied at aggregation. Nothing here uses ambient temperature."""
import hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)

EXTRACTOR_VERSION = "regen-v2.2"
POLICY = {"dtMaxS": 5.0, "rpmAgeS": 5.0, "tempAgeS": 10.0, "socAgeS": 10.0, "ivGapS": 5.0, "sliceS": 0.05, "engineOffRpm": 300.0, "speedBinKmh": 10, "nSpeedBins": 14, "overflowFromKmh": 130,
          "speedRange": [0, 260], "voltageRange": [200, 450], "tempRange": [-40, 90], "socRange": [0, 100]}
POLICY_HASH = hashlib.sha256(json.dumps(POLICY, sort_keys=True).encode()).hexdigest()[:16]
NB = POLICY["nSpeedBins"]
KE_FACTOR = 0.5 / (3.6 ** 2) / 3.6e6                    # ke_kwh = KE_FACTOR * mass_kg * dv2[(km/h)^2]
REASONS = ["speedGap", "notDecelOrFlat", "rpmUnknown", "engineOn", "currentOrVoltageUnsupported"]


def _csa():
    import compute_summary_arrays as C
    return C


def native(t_s, series, lo=None, hi=None, decimate=None, harm=None, interp=False):
    """(times, values) of the native samples of one channel: numeric and inside the range gate; duplicate timestamps keep the last value; sorted by time.
    decimate = (k, phase) keeps every k-th native sample from index `phase` (an int d means (2, d)); harm = (delta, t0): M442 common grid, the latest native sample in (t_j - delta, t_j] at its native time."""
    if series is None:
        return np.array([]), np.array([])
    v = pd.to_numeric(series, errors="coerce").values.astype(float)
    m = np.isfinite(v)
    if lo is not None:
        m &= v >= lo
    if hi is not None:
        m &= v <= hi
    t = t_s[m]; v = v[m]
    if t.size == 0:
        return t, v
    o = np.argsort(t, kind="stable")
    t, v = t[o], v[o]
    keep = np.r_[t[1:] != t[:-1], True]               # the last of equal timestamps
    t, v = t[keep], v[keep]
    if decimate is not None:
        k_, ph_ = (2, decimate) if isinstance(decimate, (int, np.integer)) else decimate
        t, v = t[ph_::k_], v[ph_::k_]
    if harm is not None and t.size and interp:
        # EXPLORATORY (M442 dev): linear interpolation onto the exact grid t_j = t0 + j delta; a node needs native samples on both sides and a bracketing gap of at most 5 s
        delta, t0 = harm
        j0 = int(np.ceil((t[0] - t0) / delta - 1e-9)); j1 = int(np.floor((t[-1] - t0) / delta + 1e-9))
        g = t0 + delta * np.arange(j0, j1 + 1)
        if g.size:
            ib = np.clip(np.searchsorted(t, g, side="right") - 1, 0, t.size - 2); ia = ib + 1
            okb = (t[ia] - t[ib]) <= 5.0
            g = g[okb]; ib = ib[okb]; ia = ia[okb]
            w = (g - t[ib]) / np.maximum(t[ia] - t[ib], 1e-9)
            return g, v[ib] + w * (v[ia] - v[ib])
        return g, np.array([])
    if harm is not None and t.size:
        delta, t0 = harm
        j = np.ceil((t - t0) / delta - 1e-9)
        last = np.r_[j[1:] != j[:-1], True]            # sorted: the last native sample of each grid cell
        t, v = t[last], v[last]
    return t, v


def latest(tn, vn, t, max_age):
    """Value of the latest native sample at or before t with age <= max_age (NaN if none)."""
    if tn.size == 0:
        return np.full(np.shape(t), np.nan), np.full(np.shape(t), np.inf)
    i = np.searchsorted(tn, t, side="right") - 1
    ok = i >= 0
    ic = np.clip(i, 0, None)
    age = np.where(ok, t - tn[ic], np.inf)
    val = np.where(ok & (age <= max_age), vn[ic], np.nan)
    return val, age


def bracket_ok(tn, t0, t1, max_gap):
    """True where native samples bracket [t0, t1] (one at or before t0, one at or after t1) and every gap between consecutive native samples in between is <= max_gap."""
    if tn.size < 2:
        return np.zeros(np.shape(t0), bool)
    ib = np.searchsorted(tn, t0, side="right") - 1
    ia = np.searchsorted(tn, t1, side="left")
    ok = (ib >= 0) & (ia < tn.size)
    bad = np.r_[0, np.cumsum(np.diff(tn) > max_gap)]
    ibc, iac = np.clip(ib, 0, tn.size - 1), np.clip(ia, 0, tn.size - 1)
    return ok & (bad[iac] - bad[ibc] == 0)


def _median_dt(t):
    return float(np.median(np.diff(t))) if t.size > 1 else float("nan")


def _boxcar_power(i_t, i_v, v_t, v_v, i_off, w, lo, hi):
    """Centred moving average over w seconds of P = I V / 1000 on a uniform 20 Hz grid between lo - w and hi + w; returns (grid time, smoothed power) (M442 sensitivity P3)."""
    g = np.arange(lo - w, hi + w, 0.05)
    p = (np.interp(g, i_t, i_v) + i_off) * np.interp(g, v_t, v_v) / 1000.0
    n = max(int(round(w / 0.05)), 1)
    c = np.r_[0.0, np.cumsum(p)]
    k = np.arange(len(g))
    a = np.clip(k - n // 2, 0, len(g)); b = np.clip(k + n - n // 2, 0, len(g))
    return g, (c[b] - c[a]) / np.maximum(b - a, 1)


def _slice_energy(t0, dt, v0, v1, i_t, i_v, v_t, v_v, i_off, h, boxcar=None):
    """Slice arrays of the intervals: owner interval, speed-bin index (mid-point speed), dv2, charge, offset charge."""
    nsl = np.maximum(np.ceil(dt / h - 1e-6).astype(int), 1)       # 1e-6 slice tolerance: 1.4 / 0.05 must give 28, not 29
    tot = int(nsl.sum())
    owner = np.repeat(np.arange(t0.size), nsl)
    start = np.cumsum(nsl) - nsl
    j = np.arange(tot) - np.repeat(start, nsl)
    fa = j / np.repeat(nsl, nsl); fb = (j + 1) / np.repeat(nsl, nsl)
    T0, DT = np.repeat(t0, nsl), np.repeat(dt, nsl)
    ta, tb = T0 + DT * fa, T0 + DT * fb
    V0, V1 = np.repeat(v0, nsl), np.repeat(v1, nsl)
    va, vb = V0 + (V1 - V0) * fa, V0 + (V1 - V0) * fb
    Ia, Ib = np.interp(ta, i_t, i_v), np.interp(tb, i_t, i_v)
    Va, Vb = np.interp(ta, v_t, v_v), np.interp(tb, v_t, v_v)
    pc = lambda I_, V_: np.maximum(I_ * V_ / 1000.0, 0.0)
    sl_dt = DT / np.repeat(nsl, nsl)
    if boxcar:
        lo_, hi_ = float(t0.min()), float((t0 + dt).max())
        g, ps = _boxcar_power(i_t, i_v, v_t, v_v, 0.0, boxcar, lo_, hi_)
        ch = (np.maximum(np.interp(ta, g, ps), 0.0) + np.maximum(np.interp(tb, g, ps), 0.0)) / 2.0 * sl_dt / 3600.0
        cho = None
        if i_off is not None:
            g2, ps2 = _boxcar_power(i_t, i_v, v_t, v_v, i_off, boxcar, lo_, hi_)
            cho = (np.maximum(np.interp(ta, g2, ps2), 0.0) + np.maximum(np.interp(tb, g2, ps2), 0.0)) / 2.0 * sl_dt / 3600.0
    else:
        ch = (pc(Ia, Va) + pc(Ib, Vb)) / 2.0 * sl_dt / 3600.0
        cho = (pc(Ia + i_off, Va) + pc(Ib + i_off, Vb)) / 2.0 * sl_dt / 3600.0 if i_off is not None else None
    vm = (va + vb) / 2.0
    bn = np.minimum((np.maximum(vm, 0) // POLICY["speedBinKmh"]).astype(int), NB - 1)
    return {"owner": owner, "bin": bn, "dv2": va ** 2 - vb ** 2, "ch": ch, "cho": cho}


def extract_drive(df, C=None, i_off=None, dt_max=None, iv_gap=None, iv_lag_s=0.0, decimate=None, harmonize=None, boxcar_s=None, harm_interp=False):
    """Returns dict(intervals=<arrays of the in-episode intervals incl. trimmed ones>, bins=<(n_int, NB) arrays>, counts, nCandidates, cadence). intervals is None if there is none."""
    C = C or _csa()
    P = dict(POLICY)
    if dt_max is not None:
        P["dtMaxS"] = dt_max
    if iv_gap is not None:
        P["ivGapS"] = iv_gap
    df, _ = C._apply_speed_priority(df)
    df = df.rename(columns={k: v for k, v in C.RAW_MAP.items() if k in df.columns})
    counts = {r: 0 for r in REASONS}
    empty = {"intervals": None, "bins": None, "counts": counts, "nCandidates": 0, "cadence": {"speedDtMed": float("nan"), "ivDtMed": float("nan")}}
    if "time" not in df:
        return empty
    tt = C._ft(df["time"], mixed=True)
    ns = tt.values.astype("datetime64[ns]").astype("int64")
    t_s = (ns - ns[np.isfinite(ns)].min() if ns.size else ns) / 1e9          # seconds from the first sample (epoch seconds in float64 lose 2e-7 s)
    g = lambda c: df[c] if c in df else None
    def q90(t_):
        d_ = np.diff(t_); d_ = d_[(d_ > 0) & (d_ <= 5.0)]
        return float(np.percentile(d_, 90)) if d_.size > 1 else float("nan")
    nat = {"speed": native(t_s, g("speed"), *P["speedRange"])[0], "I": native(t_s, g("I"))[0], "V": native(t_s, g("V"), *P["voltageRange"])[0]}
    nat_q90 = {k_: q90(t_) for k_, t_ in nat.items()}                       # native sampling-interval 90 % quantiles (M442 support rule), before any reduction
    if harmonize is not None:                       # M442 C2: the grid origin is the first native sample of any channel (before decimation); phase offsets are added to it
        firsts = [native(t_s, g(c_), lo_, hi_)[0] for c_, lo_, hi_ in (("speed", *P["speedRange"]), ("I", None, None), ("V", *P["voltageRange"]), ("eng_rpm", 0, None), ("soc", *P["socRange"]),
                                                                       ("T1", *P["tempRange"]), ("T2", *P["tempRange"]), ("T3", *P["tempRange"]), ("T4", *P["tempRange"]))]
        origin = min([f_[0] for f_ in firsts if f_.size] or [0.0])
        harmonize = (harmonize[0], origin + harmonize[1])
    sp_t, sp_v = native(t_s, g("speed"), *P["speedRange"], decimate=decimate, harm=harmonize, interp=harm_interp)
    if sp_t.size < 2:
        empty["cadence"] = {"speedDtMed": float("nan"), "ivDtMed": float("nan"), "nativeDtQ90": nat_q90}
        return empty
    rpm_t, rpm_v = native(t_s, g("eng_rpm"), 0, None, decimate=decimate, harm=harmonize)
    i_t, i_v = native(t_s, g("I"), decimate=decimate, harm=harmonize, interp=harm_interp)
    v_t, v_v = native(t_s, g("V"), *P["voltageRange"], decimate=decimate, harm=harmonize, interp=harm_interp)
    soc_t, soc_v = native(t_s, g("soc"), *P["socRange"], decimate=decimate, harm=harmonize)
    T_n = [native(t_s, g(k), *P["tempRange"], decimate=decimate, harm=harmonize) for k in ("T1", "T2", "T3", "T4")]
    cad = {"speedDtMed": _median_dt(sp_t), "ivDtMed": float(np.nanmean([_median_dt(i_t), _median_dt(v_t)])), "nativeDtQ90": nat_q90}
    if iv_lag_s:
        i_t = i_t + iv_lag_s; v_t = v_t + iv_lag_s
    t0, t1 = sp_t[:-1], sp_t[1:]
    v0, v1 = sp_v[:-1], sp_v[1:]
    dt = t1 - t0
    n = t0.size
    ok_dt = (dt > 0) & (dt <= P["dtMaxS"])
    counts["speedGap"] = int((~ok_dt).sum())
    r0, _ = latest(rpm_t, rpm_v, t0, P["rpmAgeS"]); r1, _ = latest(rpm_t, rpm_v, t1, P["rpmAgeS"])
    known = np.isfinite(r0) & np.isfinite(r1)
    cs = np.r_[0, np.cumsum((rpm_v > P["engineOffRpm"]).astype(int))]
    if rpm_t.size:
        i0 = np.searchsorted(rpm_t, t0, side="right"); i1 = np.searchsorted(rpm_t, t1, side="left")
        inside_on = (cs[np.clip(i1, 0, rpm_t.size)] - cs[np.clip(i0, 0, rpm_t.size)]) > 0
    else:
        inside_on = np.zeros(n, bool)
    off = known & (r0 <= P["engineOffRpm"]) & (r1 <= P["engineOffRpm"]) & ~inside_on
    iv_ok = bracket_ok(i_t, t0, t1, P["ivGapS"]) & bracket_ok(v_t, t0, t1, P["ivGapS"])
    counts["rpmUnknown"] = int((ok_dt & ~known).sum())
    counts["engineOn"] = int((ok_dt & known & ~off).sum())
    counts["currentOrVoltageUnsupported"] = int((ok_dt & off & ~iv_ok).sum())
    valid = ok_dt & off & iv_ok
    nonincr = v1 <= v0
    strict = v1 < v0
    counts["notDecelOrFlat"] = int((valid & ~nonincr).sum())
    # episodes: only a break reason (gap, I/V unsupported, RPM unknown, engine on) or a speed increase ends one; trimmed plateaus are flagged, not dropped
    ep = np.full(n, -1, dtype=np.int64)
    cur = -1
    run_ok = valid & nonincr
    for k in range(n):
        if run_ok[k]:
            if k == 0 or ep[k - 1] < 0:
                cur += 1
            ep[k] = cur
    trimmed = np.zeros(n, bool)
    for e in range(cur + 1):
        idx = np.where(ep == e)[0]
        s_idx = idx[strict[idx]]
        if s_idx.size == 0:
            trimmed[idx] = True                     # an episode of plateaus only: no event
            continue
        trimmed[idx[idx < s_idx[0]]] = True; trimmed[idx[idx > s_idx[-1]]] = True
    kidx = np.where(ep >= 0)[0]
    if kidx.size == 0:
        empty["nCandidates"] = int(n); empty["cadence"] = cad
        return empty
    tprobe = np.vstack([latest(tn, vn, t0[kidx], P["tempAgeS"])[0] for tn, vn in T_n])
    nprobe = np.isfinite(tprobe).sum(axis=0)
    tpack = np.where(nprobe == 4, tprobe.mean(axis=0), np.nan)
    soc0, _ = latest(soc_t, soc_v, t0[kidx], P["socAgeS"])
    S = _slice_energy(t0[kidx], dt[kidx], v0[kidx], v1[kidx], i_t, i_v, v_t, v_v, i_off, P["sliceS"], boxcar=boxcar_s)
    m = kidx.size
    comb = S["owner"] * NB + S["bin"]
    size = m * NB
    bins = {"dv2": np.bincount(comb, weights=S["dv2"], minlength=size).reshape(m, NB), "charge": np.bincount(comb, weights=S["ch"], minlength=size).reshape(m, NB),
            "touch": (np.bincount(comb, minlength=size).reshape(m, NB) > 0).astype(np.int8)}
    iv = {"t0": t0[kidx], "dt": dt[kidx], "v0": v0[kidx], "v1": v1[kidx], "dv2": v0[kidx] ** 2 - v1[kidx] ** 2, "charge": bins["charge"].sum(axis=1),
          "tpack": tpack, "nprobe": nprobe.astype(np.int8), "soc": soc0, "cls": np.where(v0[kidx] < 10, 0, np.where(v1[kidx] < 10, 1, 2)).astype(np.int8),
          "plateau": (v1[kidx] == v0[kidx]), "trimmed": trimmed[kidx], "endsAtStandstill": v1[kidx] == 0, "episode": ep[kidx]}
    if S["cho"] is not None:
        bins["chargeOff"] = np.bincount(comb, weights=S["cho"], minlength=size).reshape(m, NB)
        iv["chargeOff"] = bins["chargeOff"].sum(axis=1)
    return {"intervals": iv, "bins": bins, "counts": counts, "nCandidates": int(n), "cadence": cad}
