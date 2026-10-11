#!/usr/bin/env python3
"""M403 (analyses/M403_spec.md v4): apparent capacity of the logged BMS SoC scale, estimated. Additive: writes ONLY the payload block summary_arrays.json['capacityBasis'];
no master column, no headline, no existing payload leaf changes. Never 'measured', 'usable', 'true' or 'actual' capacity, never SoH: this is the Ah (and kWh) that the
logged current integrates to per 100 points of the logged SoC, over the SoC range actually observed.

Estimators (fixed list; the point estimate is B, the rest form the descriptive METHOD RANGE; adding an entry needs a spec amendment):
  B   (primary) SoC-transition events: at each 0.5-point step of the logged SoC, charge Q (Ah, trapezoid of the charge-positive current, no integration across a current gap > 10 s)
      is regressed on the event level with segment fixed effects and a pooled drift term (absorbs a constant current offset): Q = a_seg + C*level + c*t.  Ah/100 = 100*C.
  Bgap3 / Bzoh   B with a 3 s gap cap / zero-order-hold integration.  Brev   reverse regression (level on Q, drift): the attenuation bracket from above.
  A   segment level: dQ = C*dSoC + c*T over segments of >= 10 min (errors-in-variables attenuated, reported as such).
  W5 / W10 / W15  non-overlapping SoC-excursion windows (>= target pp within <= 600 s, >= 10 s; no bridging of a current gap > 5 s, a SoC gap > 5 s or a SoC jump > 2 pp within 5 s;
      endpoints exact under linear interpolation of the logged samples; M403: both window ends are threshold crossings of the logged SoC in the same direction, because an arbitrary start biases dSoC by up to a quantisation step): charge model Q = Qscale*dSoC/100 + b*hours; energy model E = Kscale*dSoC/100 + bE*integral(V dt).
  whole-drive fit, discharge-only / charge-only windows (net-direction fraction >= 0.8), fast / slow logging regime, matched-support lag -2 s / +2 s (windows valid at all lags).
Inference: calendar day is the resampling cluster; percentile bootstrap with per-day sufficient statistics (seed 42, 4000 draws); singular draws are skipped and counted. The bootstrap CI is
conditional on the specified logged-signal model; the method range is a min-max over the fixed list. They are reported side by side and never combined. Drive population: ens_outlier_v2 explicitly
False with usable current, SoC and (for energy) voltage series; drives with a NaN flag are added in test (d). Per-drive extraction is cached by raw sha256 (capacity_cache/, not tracked).
Usage: python tools/capacity_basis.py [--dry-run] [--rebuild]"""
import copy, glob, hashlib, json, os, pickle, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
METHOD_VERSION = 3
N_BOOT, SEED = 4000, 42
GAP_S, GAP3_S = 10.0, 3.0
MIN_SEG_SAMPLES = 20
EVENT_STEP = 0.5
WINDOW_TARGETS = (5, 10, 15)
WINDOW_MAX_S, WINDOW_MIN_S, CUR_GAP_S, SOC_GAP_S, SOC_JUMP_PP = 600.0, 10.0, 5.0, 5.0, 2.0
LAGS = (-2, 2)
DIRECTION_MIN = 0.8
CHRONO_CUT = "2026-08-01"
TOST_MARGIN_AH = 0.25
CACHE_DIR = os.path.join(ROOT, "capacity_cache")


# ------------------------------------------------------------------------------------------------ per-drive extraction
def _cumint(t, y, zoh=False):
    """Cumulative integral (Ah if y is A and t is s) at the sample times."""
    if zoh:
        return np.r_[0.0, np.cumsum(y[:-1] * np.diff(t))] / 3600.0
    return np.r_[0.0, np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(t))] / 3600.0


def _segments(tI, gap):
    br = np.where(np.diff(tI) > gap)[0]
    st, en = np.r_[0, br + 1], np.r_[br + 1, len(tI)]
    return [(a, b) for a, b in zip(st, en) if b - a > MIN_SEG_SAMPLES]


def _seg_records(tI, I, tV, V, tS, S, gap, zoh):
    """Segment records (scalars + event arrays) of one drive for one integration variant."""
    Vi = np.interp(tI, tV, V) if len(V) > 10 else np.full_like(I, np.nan)
    out = []
    for a, b in _segments(tI, gap):
        t, i, v = tI[a:b], I[a:b], Vi[a:b]
        Q, E = _cumint(t, i, zoh), _cumint(t, i * v, zoh) / 1000.0
        Qc, Qd = _cumint(t, np.clip(i, 0, None), zoh), _cumint(t, np.clip(i, None, 0), zoh)
        m = (tS >= t[0]) & (tS <= t[-1])
        ts, s = tS[m], S[m]
        if len(s) < 10:
            continue
        rec = {"T": float((t[-1] - t[0]) / 3600.0), "dS": float(np.median(s[-5:]) - np.median(s[:5])), "dQ": float(Q[-1]), "dE": float(E[-1]),
               "Vmed": float(np.nanmedian(v)) if np.isfinite(v).any() else float("nan"), "Smin": float(s.min()), "Smax": float(s.max())}
        ds = np.diff(s)
        k = np.where(np.abs(np.abs(ds) - EVENT_STEP) < 1e-6)[0]
        if len(k) >= 3:
            te = 0.5 * (ts[k] + ts[k + 1])
            rec["ev"] = {"lev": 0.5 * (s[k] + s[k + 1]), "Q": np.interp(te, t, Q), "E": np.interp(te, t, E), "Qc": np.interp(te, t, Qc), "Qd": np.interp(te, t, Qd),
                         "th": (te - t[0]) / 3600.0, "up": (ds[k] > 0).astype(float)}
        out.append(rec)
    return out


def _prim(t, y, at):
    """Integral (units of y x hours) of the piecewise-linear signal (t, y) from t[0] to `at`, exact under linear interpolation."""
    dt = np.diff(t)
    cum = np.r_[0.0, np.cumsum((y[:-1] + y[1:]) * dt / 7200.0)]
    ix = np.clip(np.searchsorted(t, at, side="right") - 1, 0, len(t) - 2)
    dx = at - t[ix]
    return cum[ix] + (y[ix] * dx + (y[ix + 1] - y[ix]) * dx * dx / (2 * dt[ix])) / 3600.0


def _align(t, st, sv, tol=1.5):
    """Nearest sample of (st, sv) within tol seconds of each t, else NaN."""
    if not len(st):
        return np.full(len(t), np.nan)
    j = np.searchsorted(st, t, side="right") - 1
    jl, jr = np.clip(j, 0, len(st) - 1), np.clip(j + 1, 0, len(st) - 1)
    ix = np.where(np.abs(st[jl] - t) <= np.abs(st[jr] - t), jl, jr)
    return np.where(np.abs(t - st[ix]) <= tol, sv[ix], np.nan)


def _windows(it, iv, vt, vv, st, sv, temp, fast):
    """Window rows (targets 5/10/15 pp) and the whole-drive row. Current iv is charge-positive. Lags +-2 s are evaluated on the same windows (NaN when not valid)."""
    out = {"windows": [], "whole": None}
    ki = np.r_[True, np.diff(it) > 0]
    it, iv = it[ki], iv[ki]
    ks = np.r_[True, np.diff(st) > 0]
    st, sv = st[ks], sv[ks]
    v = _align(it, vt, vv, 1.5)
    ok = np.isfinite(v)
    et, ep, ev = it[ok], iv[ok] * v[ok] / 1000.0, v[ok]
    if len(it) < 10 or len(st) < 10 or len(et) < 10:
        return out
    si = (st >= max(it[0], et[0])) & (st <= min(it[-1], et[-1]))
    st, sv = st[si], sv[si]
    if len(st) < 10:
        return out
    q, e, vh, absq = _prim(it, iv, st), _prim(et, ep, st), _prim(et, ev, st), _prim(it, np.abs(iv), st)
    gapq, gape = np.r_[0, np.cumsum(np.diff(it) > CUR_GAP_S)], np.r_[0, np.cumsum(np.diff(et) > CUR_GAP_S)]
    qi = np.clip(np.searchsorted(it, st, side="right") - 1, 0, len(it) - 1)
    ei = np.clip(np.searchsorted(et, st, side="right") - 1, 0, len(et) - 1)
    qe = np.clip(np.searchsorted(it, st, side="left"), 0, len(it) - 1)
    ee = np.clip(np.searchsorted(et, st, side="left"), 0, len(et) - 1)
    bads = np.r_[0, np.cumsum((np.diff(st) > SOC_GAP_S) | ((np.abs(np.diff(sv)) > SOC_JUMP_PP) & (np.diff(st) <= SOC_GAP_S)))]
    shifted = {lag: (_prim(it, iv, st + lag), _prim(et, ep, st + lag), _prim(et, ev, st + lag), st + lag) for lag in LAGS}

    def row(a, b):
        r = {"start_s": float(st[a]), "end_s": float(st[b]), "dsoc": float(sv[b] - sv[a]), "hours": float((st[b] - st[a]) / 3600.0), "q_ah": float(q[b] - q[a]),
             "e_kwh": float(e[b] - e[a]), "vhours": float(vh[b] - vh[a]), "soc_start": float(sv[a]), "soc_end": float(sv[b]), "temp_C": temp, "fast": bool(fast),
             "net_dir": float(abs(q[b] - q[a]) / max(absq[b] - absq[a], 1e-10))}
        for lag, (sq, se, sw, at) in shifted.items():
            valid = at[a] >= max(it[0], et[0]) and at[b] <= min(it[-1], et[-1])
            if valid:
                aa, bb = np.searchsorted(it, at[a], side="right") - 1, np.searchsorted(it, at[b], side="left")
                ae, be = np.searchsorted(et, at[a], side="right") - 1, np.searchsorted(et, at[b], side="left")
                valid = gapq[min(bb, len(gapq) - 1)] == gapq[max(aa, 0)] and gape[min(be, len(gape) - 1)] == gape[max(ae, 0)]
            for name, arr in (("q_ah", sq), ("e_kwh", se), ("vhours", sw)):
                r["%s_lag%d" % (name, lag)] = float(arr[b] - arr[a]) if valid else float("nan")
        return r

    if bads[-1] == 0 and gapq[qe[-1]] == gapq[qi[0]] and gape[ee[-1]] == gape[ei[0]]:
        out["whole"] = row(0, len(st) - 1)
    dsv = np.r_[0.0, np.diff(sv)]
    for target in WINDOW_TARGETS:
        a = 0
        while a < len(st) - 1:
            end = np.searchsorted(st, st[a] + WINDOW_MAX_S, side="right")
            ix = np.flatnonzero(np.abs(sv[a + 1:end] - sv[a]) >= target)
            if not len(ix):
                a = end
                continue
            b = a + 1 + ix[0]
            # M403: both ends must be threshold crossings in the SAME direction, otherwise the quantisation band of the logged SoC biases dSoC (a window that starts right after a
            # turnaround would span 0.5 pp less true SoC than its reading). Re-anchor the start at the last crossing into the level exactly `target` away from the end.
            d = 1.0 if sv[b] > sv[a] else -1.0
            lvl = sv[b] - d * target
            cand = np.flatnonzero((np.abs(sv[a:b] - lvl) < 1e-9) & (dsv[a:b] * d > 0))
            a2 = a + int(cand[-1]) if len(cand) else None
            if a2 is not None and abs(sv[b] - sv[a2]) >= target - 1e-9 and st[b] - st[a2] >= WINDOW_MIN_S and bads[b] == bads[a2]                     and gapq[qe[b]] == gapq[qi[a2]] and gape[ee[b]] == gape[ei[a2]]:
                r = row(a2, b)
                r["target_pp"] = target
                out["windows"].append(r)
            a = b
    # literal (audit-package) definition, target 10 pp only: the window starts at an arbitrary sample (the end of the previous window) and ends at the first sample 10 pp away. Its dSoC carries
    # an endpoint-selection bias and its lag sensitivity differs from the anchored windows: kept as a separate pre-registered sensitivity (target_pp = 1010), not as the window definition.
    a = 0
    while a < len(st) - 1:
        end = np.searchsorted(st, st[a] + WINDOW_MAX_S, side="right")
        ix = np.flatnonzero(np.abs(sv[a + 1:end] - sv[a]) >= 10)
        if not len(ix):
            a = end
            continue
        b = a + 1 + ix[0]
        if st[b] - st[a] >= WINDOW_MIN_S and bads[b] == bads[a] and gapq[qe[b]] == gapq[qi[a]] and gape[ee[b]] == gape[ei[a]]:
            r = row(a, b)
            r["target_pp"] = 1010
            out["windows"].append(r)
        a = b
    return out


def extract_drive(csv_bytes):
    """Everything the estimators need from one raw drive CSV (cached). None when current, SoC and voltage series are not usable."""
    import compute_drive_summary_v6 as D
    df, t = D._prep_bytes(csv_bytes)
    I = D._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900]
    V = D._series(df, t, "V", lo=200, hi=450)
    S = D._series(df, t, "soc")
    if I is None or S is None or len(I) <= MIN_SEG_SAMPLES or len(S) < 10:          # the written definition: segments need more than 20 current samples and 10 SoC samples
        return None
    if S is not None:
        S = S[S["v"] > 0].reset_index(drop=True)                 # raw SoC = 0 artefacts never define support or events
    t0 = min(I["t"].iloc[0], S["t"].iloc[0])
    sec = lambda s: ((s["t"] - t0).dt.total_seconds().to_numpy(), s["v"].to_numpy(dtype=float))
    tI, Iv = sec(I)
    tS, Sv = sec(S)
    tV, Vv = sec(V) if V is not None else (np.array([]), np.array([]))
    fast = float(np.median(np.diff(tI))) < 1.05
    Tc = D._series(df, t, "T1", lo=-50, hi=100) if "T1" in df.columns else None
    temp = float(np.median(Tc["v"])) if Tc is not None and len(Tc) else float("nan")
    rec = {"fast": bool(fast), "has_v": bool(len(tV) > 10), "nI": int(len(tI)), "nS": int(len(tS)),
           "variants": {"primary": _seg_records(tI, Iv, tV, Vv, tS, Sv, GAP_S, False), "gap3": _seg_records(tI, Iv, tV, Vv, tS, Sv, GAP3_S, False),
                        "zoh": _seg_records(tI, Iv, tV, Vv, tS, Sv, GAP_S, True)}}
    rec.update(_windows(tI, Iv, tV, Vv, tS, Sv, temp, fast) if len(tV) > 10 else {"windows": [], "whole": None})
    return rec


def load_records(master, loader, sha_lookup=None, cache_dir=CACHE_DIR, rebuild=False):
    """{file: extraction record | None} for the given master rows; per-drive cache keyed by raw sha256 and METHOD_VERSION."""
    os.makedirs(cache_dir, exist_ok=True)
    out = {}
    for f in master["file"]:
        sha = sha_lookup(f) if sha_lookup else None
        cp = os.path.join(cache_dir, "%s.v%d.pkl" % (f, METHOD_VERSION))
        if sha and not rebuild and os.path.exists(cp):
            c = pickle.load(open(cp, "rb"))
            if c.get("sha") == sha:
                out[f] = c["rec"]
                continue
        b = loader(f)
        if b is None:
            out[f] = None
            continue
        h = hashlib.sha256(b).hexdigest()
        if not rebuild and os.path.exists(cp):
            c = pickle.load(open(cp, "rb"))
            if c.get("sha") == h:
                out[f] = c["rec"]
                continue
        rec = extract_drive(b)
        pickle.dump({"sha": h, "rec": rec}, open(cp, "wb"))
        out[f] = rec
    return out


# ------------------------------------------------------------------------------------------------ grouped regression with day-cluster bootstrap
def boot_weights(n_days, nb=None, seed=SEED):
    nb = N_BOOT if nb is None else nb
    rng = np.random.default_rng(seed)
    return rng.multinomial(n_days, np.ones(n_days) / n_days, size=nb).astype(float)


def grouped_fit(day_ix, X, y, n_days, W, tr):
    """OLS of y on X pooled over rows; day-cluster percentile bootstrap from per-day X'X, X'y. tr(beta) -> scalar. Returns dict(est, ci95, nDrawsUsed) or None when singular."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    if X.ndim == 1:
        X = X[:, None]
    p = X.shape[1]
    if len(y) < p + 2:
        return None
    XX, Xy = np.zeros((n_days, p, p)), np.zeros((n_days, p))
    np.add.at(XX, day_ix, X[:, :, None] * X[:, None, :])
    np.add.at(Xy, day_ix, X * y[:, None])
    A = XX.sum(0)
    if np.linalg.matrix_rank(A) < p:
        return None
    est = float(tr(np.linalg.solve(A, Xy.sum(0))))
    bs = []
    for w in W:
        a, b = np.tensordot(w, XX, 1), np.tensordot(w, Xy, 1)
        if np.linalg.matrix_rank(a) < p:
            continue                                           # singular draw: skipped and counted
        bs.append(tr(np.linalg.solve(a, b)))
    if not bs:
        return {"est": est, "ci95": [float("nan"), float("nan")], "nDrawsUsed": 0}
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"est": est, "ci95": [float(lo), float(hi)], "nDrawsUsed": len(bs)}


def _event_rows(recs, variant="primary", with_up=False):
    """Pooled, segment-demeaned event rows over drive records [(day_index, drive record)]: dict of arrays + day index."""
    cols = {k: [] for k in ("lev", "Q", "E", "Qc", "Qd", "th", "up", "levup", "day")}
    for d, r in recs:
        for sg in r["variants"][variant]:
            e = sg.get("ev")
            if e is None:
                continue
            for k in ("lev", "Q", "E", "Qc", "Qd", "th"):
                cols[k].append(e[k] - e[k].mean())
            lu = e["lev"] * e["up"]
            cols["up"].append(e["up"])
            cols["levup"].append(lu - lu.mean())
            cols["day"].append(np.full(len(e["lev"]), d))
    return {k: (np.concatenate(v) if v else np.array([])) for k, v in cols.items()}


def _seg_rows(recs, variant="primary", min_h=1 / 6):
    rows = [(d, sg) for d, r in recs for sg in r["variants"][variant] if sg["T"] >= min_h]
    return np.array([d for d, _ in rows], int), {k: np.array([sg[k] for _, sg in rows], float) for k in ("T", "dS", "dQ", "dE")}


def _fit_events(recs, n_days, W, variant="primary"):
    """B family on one set of drive records."""
    ev = _event_rows(recs, variant)
    if not len(ev["lev"]):
        return {}
    d = ev["day"].astype(int)
    h = lambda b: 100.0 * b[0]
    out = {"B": grouped_fit(d, np.column_stack([ev["lev"], ev["th"]]), ev["Q"], n_days, W, h),
           "B_offset_A": grouped_fit(d, np.column_stack([ev["lev"], ev["th"]]), ev["Q"], n_days, W, lambda b: b[1]),
           "B_nooffset": grouped_fit(d, ev["lev"], ev["Q"], n_days, W, h),
           "B_rev": grouped_fit(d, np.column_stack([ev["Q"], ev["th"]]), ev["lev"], n_days, W, lambda b: 100.0 / b[0]),
           "B_kwh": grouped_fit(d, np.column_stack([ev["lev"], ev["th"]]), ev["E"], n_days, W, h)}
    di, sr = _seg_rows(recs, variant)
    if len(di):
        out["A"] = grouped_fit(di, np.column_stack([sr["dS"], sr["T"]]), sr["dQ"], n_days, W, h)
    out["nEvents"] = int(len(ev["lev"]))
    return out


def _fit_windows(rows, n_days, W, lag=None):
    """Window charge and energy models on a frame of window/whole rows with a 'day' column; lag in {-2, 2} uses the shifted integrals."""
    if rows is None or len(rows) < 10:
        return None
    sfx = "" if lag is None else "_lag%d" % lag
    d = rows.dropna(subset=["q_ah" + sfx, "e_kwh" + sfx, "vhours" + sfx])
    if len(d) < 10:
        return None
    z, ix = d["dsoc"].to_numpy() / 100.0, d["day_ix"].to_numpy(int)
    q, e, vh = d["q_ah" + sfx].to_numpy(), d["e_kwh" + sfx].to_numpy(), d["vhours" + sfx].to_numpy() / 1000.0
    h = d["hours"].to_numpy()
    return {"n": int(len(d)), "nDays": int(d["day_ix"].nunique()), "nDrives": int(d["file"].nunique()),
            "Q_Ah": grouped_fit(ix, np.column_stack([z, h]), q, n_days, W, lambda b: b[0]),
            "bias_A": grouped_fit(ix, np.column_stack([z, h]), q, n_days, W, lambda b: b[1]),
            "E_kWh": grouped_fit(ix, np.column_stack([z, vh]), e, n_days, W, lambda b: b[0]),
            "bias_E_A": grouped_fit(ix, np.column_stack([z, vh]), e, n_days, W, lambda b: b[1]),
            "medianWindowS": float(np.median(h) * 3600.0)}


def _round(o, nd=4):
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v, nd) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else round(float(o), nd)
    if isinstance(o, (np.integer,)):
        return int(o)
    return o


def _est(f):
    return None if not f else f["est"]


def _tost_halves(recs, dates, n_days_total):
    """Test (a): B on odd vs even ISO calendar weeks, independent day bootstrap per half; equivalence within +-TOST_MARGIN_AH on the 90 % percentile interval of the difference."""
    halves = {0: [], 1: []}
    for (d, r), dt in zip(recs, dates):
        halves[int(pd.Timestamp(dt).isocalendar()[1]) % 2].append((d, r))
    res, boots = {}, {}
    for k, rr in halves.items():
        days = sorted({d for d, _ in rr})
        remap = {d: i for i, d in enumerate(days)}
        rr2 = [(remap[d], r) for d, r in rr]
        if len(days) < 3:
            return {"evaluable": False, "reason": "fewer than 3 days in a half"}
        W = boot_weights(len(days), None, SEED + 1 + k)
        ev = _event_rows(rr2)
        di = ev["day"].astype(int)
        X, y = np.column_stack([ev["lev"], ev["th"]]), ev["Q"]
        p = X.shape[1]
        XX, Xy = np.zeros((len(days), p, p)), np.zeros((len(days), p))
        np.add.at(XX, di, X[:, :, None] * X[:, None, :])
        np.add.at(Xy, di, X * y[:, None])
        pt = 100.0 * np.linalg.solve(XX.sum(0), Xy.sum(0))[0]
        bs = np.array([100.0 * np.linalg.solve(np.tensordot(w, XX, 1), np.tensordot(w, Xy, 1))[0] for w in W if np.linalg.matrix_rank(np.tensordot(w, XX, 1)) == p])
        res[k] = {"est": float(pt), "nDays": len(days), "nDrives": len({id(r) for _, r in rr})}
        boots[k] = bs
    m = min(len(boots[0]), len(boots[1]))
    diff = boots[0][:m] - boots[1][:m]
    lo90, hi90 = np.percentile(diff, [5, 95])
    half = float((hi90 - lo90) / 2.0)
    powered = half < TOST_MARGIN_AH
    equivalent = bool(powered and lo90 > -TOST_MARGIN_AH and hi90 < TOST_MARGIN_AH)
    return {"evaluable": True, "oddWeeksAh100": res[1]["est"], "evenWeeksAh100": res[0]["est"], "difference": float(res[1]["est"] - res[0]["est"]),
            "ci90Difference": [float(lo90), float(hi90)], "marginAh": TOST_MARGIN_AH, "halfWidth90": half, "powered": bool(powered), "equivalent": equivalent,
            "nDaysOdd": res[1]["nDays"], "nDaysEven": res[0]["nDays"],
            "outcome": "equivalent" if equivalent else ("not powered (interval wider than the margin): escalate" if not powered else "not equivalent: escalate"),
            "note": "heterogeneity check across interleaved weeks, not a correctness check; an unpowered test defaults to the conservative outcome"}


def estimate(master, records):
    """Pure: capacityBasis block from the master frame (file, date, ens_outlier_v2) and the extraction records {file: rec|None}."""
    flag = master["ens_outlier_v2"].map(lambda v: str(v).strip().lower())
    strict = master.loc[flag == "false", "file"].tolist()
    nanflag = master.loc[~flag.isin(["true", "false"]), "file"].tolist()
    date = dict(zip(master["file"], master["date"].astype(str)))

    def pop(files):
        return [(f, records[f]) for f in files if records.get(f) is not None and any(records[f]["variants"]["primary"])]

    base = pop(strict)
    days = sorted({date[f] for f, _ in base})
    dix = {d: i for i, d in enumerate(days)}
    recs = [(dix[date[f]], r) for f, r in base]
    nd = len(days)
    W = boot_weights(nd)
    rng_note = "calendar day = cluster; percentile bootstrap, seed %d, %d draws, per-day sufficient statistics" % (SEED, N_BOOT)

    prim = _fit_events(recs, nd, W, "primary")
    g3, zh = _fit_events(recs, nd, W, "gap3"), _fit_events(recs, nd, W, "zoh")
    fast = _fit_events([(d, r) for d, r in recs if r["fast"]], nd, W)
    slow = _fit_events([(d, r) for d, r in recs if not r["fast"]], nd, W)

    wrows = []
    for (f, r) in base:
        for w in r["windows"]:
            wrows.append(dict(w, file=f, date=date[f], day_ix=dix[date[f]]))
        if r["whole"] is not None:
            wrows.append(dict(r["whole"], file=f, date=date[f], day_ix=dix[date[f]], target_pp=0))
    wf = pd.DataFrame(wrows) if wrows else pd.DataFrame()
    win = {}
    for tgt in WINDOW_TARGETS:
        s = wf[wf["target_pp"] == tgt] if len(wf) else wf
        win[str(tgt)] = _fit_windows(s, nd, W)
    whole = _fit_windows(wf[wf["target_pp"] == 0] if len(wf) else wf, nd, W)
    w10 = wf[wf["target_pp"] == 10] if len(wf) else wf
    direction = {"discharge": _fit_windows(w10[(w10["dsoc"] < 0) & (w10["net_dir"] >= DIRECTION_MIN)], nd, W) if len(w10) else None,
                 "charge": _fit_windows(w10[(w10["dsoc"] > 0) & (w10["net_dir"] >= DIRECTION_MIN)], nd, W) if len(w10) else None}
    # matched-support lag scenarios: windows valid at every lag; the 0 s fit uses the same windows
    wl = wf[wf["target_pp"] == 1010] if len(wf) else wf
    lit = {}
    if len(wl):
        ml_ = wl.dropna(subset=["q_ah_lag-2", "e_kwh_lag-2", "vhours_lag-2", "q_ah_lag2", "e_kwh_lag2", "vhours_lag2"])
        lit = {"n": int(len(wl)), "matchedWindows": int(len(ml_)), "0": _fit_windows(ml_, nd, W), "-2": _fit_windows(ml_, nd, W, -2), "2": _fit_windows(ml_, nd, W, 2), "all": _fit_windows(wl, nd, W),
               "note": "audit-package window definition (arbitrary start); carries an endpoint-selection bias in dSoC and a different lag sensitivity than the anchored windows; kept as a pre-registered sensitivity"}
    lag = {}
    if len(w10):
        m = w10.dropna(subset=["q_ah_lag-2", "e_kwh_lag-2", "vhours_lag-2", "q_ah_lag2", "e_kwh_lag2", "vhours_lag2"])
        lag = {"matchedWindows": int(len(m)), "matchedDrives": int(m["file"].nunique()), "matchedDays": int(m["day_ix"].nunique()),
               "0": _fit_windows(m, nd, W), "-2": _fit_windows(m, nd, W, -2), "2": _fit_windows(m, nd, W, 2),
               "note": "scenario sensitivity on identical support, not a confidence interval; the lag is frozen and is not identifiable from round-robin logs"}
    # chronological (descriptive): 10-pp windows before / after the cut, free-scale held-out RMSE of the energy model
    chrono = {}
    if len(w10):
        early, late = w10[w10["date"] < CHRONO_CUT], w10[w10["date"] >= CHRONO_CUT]
        chrono = {"cut": CHRONO_CUT, "nEarly": int(len(early)), "nLate": int(len(late)), "earlyAh": _est((_fit_windows(early, nd, W) or {}).get("Q_Ah")),
                  "lateAh": _est((_fit_windows(late, nd, W) or {}).get("Q_Ah")), "heldOut": {},
                  "note": "descriptive; confounded with season and with the fast/slow logging regime; says nothing about fade"}
        for label, tr, te in (("earlyToLate", early, late), ("lateToEarly", late, early)):
            if len(tr) >= 10 and len(te) >= 10:
                Xt = np.column_stack([tr["dsoc"] / 100.0, tr["vhours"] / 1000.0])
                b = np.linalg.lstsq(Xt, tr["e_kwh"].to_numpy(), rcond=None)[0]
                res = te["e_kwh"].to_numpy() - np.column_stack([te["dsoc"] / 100.0, te["vhours"] / 1000.0]) @ b
                chrono["heldOut"][label] = {"nTrain": int(len(tr)), "nTest": int(len(te)), "kwhPer100Train": float(b[0]), "rmseWh": float(1000.0 * np.sqrt(np.mean(res ** 2)))}

    # test (d): NaN-flag drives added
    extra = pop(nanflag)
    all_days = sorted({date[f] for f, _ in base + extra})
    adix = {d: i for i, d in enumerate(all_days)}
    arecs = [(adix[date[f]], r) for f, r in base + extra]
    withnan = _fit_events(arecs, len(all_days), boot_weights(len(all_days)))
    p0, p1 = _est(prim.get("B")), _est(withnan.get("B"))
    test_d = {"nNanFlagDrives": len(nanflag), "nWithUsableSeries": len(extra), "estimateWithAdded": p1, "delta": None if p0 is None or p1 is None else p1 - p0,
              "deltaRelative": None if not p0 or p1 is None else (p1 - p0) / p0,
              "outcome": "no effect, k = 0" if not extra else ("within 1 % of the primary" if p0 and p1 is not None and abs(p1 - p0) <= 0.01 * abs(p0) else "exceeds 1 % of the primary: escalate")}
    test_a = _tost_halves(recs, [date[f] for f, _ in base], nd)

    ah_entries = {"B_primary": _est(prim.get("B")), "B_reverse": _est(prim.get("B_rev")), "A_segments": _est(prim.get("A")), "B_gap3s": _est(g3.get("B")), "B_zoh": _est(zh.get("B")),
                  "B_fast_regime": _est(fast.get("B")), "B_slow_regime": _est(slow.get("B")), "W5": _est((win["5"] or {}).get("Q_Ah")),
                  "W10": _est((win["10"] or {}).get("Q_Ah")), "W15": _est((win["15"] or {}).get("Q_Ah")), "whole_drive": _est((whole or {}).get("Q_Ah")),
                  "W10_discharge_only": _est(((direction["discharge"] or {}).get("Q_Ah"))), "W10_charge_only": _est(((direction["charge"] or {}).get("Q_Ah"))),
                  "W10_lag_minus2s": _est(((lag.get("-2") or {}).get("Q_Ah"))) if lag else None, "W10_lag_plus2s": _est(((lag.get("2") or {}).get("Q_Ah"))) if lag else None,
                  "W10_literal": _est((lit.get("all") or {}).get("Q_Ah")) if lit else None, "W10_literal_lag_minus2s": _est((lit.get("-2") or {}).get("Q_Ah")) if lit else None,
                  "W10_literal_lag_plus2s": _est((lit.get("2") or {}).get("Q_Ah")) if lit else None}
    kwh_entries = {"B_terminal": _est(prim.get("B_kwh")), "W5": _est((win["5"] or {}).get("E_kWh")), "W10": _est((win["10"] or {}).get("E_kWh")), "W15": _est((win["15"] or {}).get("E_kWh")),
                   "whole_drive": _est((whole or {}).get("E_kWh")), "W10_lag_minus2s": _est(((lag.get("-2") or {}).get("E_kWh"))) if lag else None,
                   "W10_lag_plus2s": _est(((lag.get("2") or {}).get("E_kWh"))) if lag else None,
                   "W10_literal": _est((lit.get("all") or {}).get("E_kWh")) if lit else None, "W10_literal_lag_minus2s": _est((lit.get("-2") or {}).get("E_kWh")) if lit else None,
                   "W10_literal_lag_plus2s": _est((lit.get("2") or {}).get("E_kWh")) if lit else None}
    rng = lambda e: [min(v for v in e.values() if v is not None), max(v for v in e.values() if v is not None)] if any(v is not None for v in e.values()) else None
    soc_lo = [r["variants"]["primary"][0]["Smin"] for _, r in base if r["variants"]["primary"]]
    soc_hi = [r["variants"]["primary"][0]["Smax"] for _, r in base if r["variants"]["primary"]]
    block = {
        "_provenance": "GENERATED by tools/capacity_basis.py (M403); do not hand-edit. Additive block: no headline, master column or other payload leaf depends on it.",
        "methodVersion": METHOD_VERSION,
        "quantity": "apparent capacity of the logged BMS SoC scale, estimated: Ah (and kWh) integrated from the logged current per 100 points of logged SoC, over the observed SoC range; not full capacity, not accessible-window capacity, not state of health",
        "population": {"rule": "ens_outlier_v2 explicitly False with usable current and SoC series (energy models also need voltage)", "nDrives": len(base), "nDays": nd,
                       "nEvents": prim.get("nEvents"), "nNanFlagDrivesExcluded": len(nanflag), "socRangeObservedP1P99": [float(np.percentile(soc_lo, 1)), float(np.percentile(soc_hi, 99))] if soc_lo else None},
        "ahPer100": {"point": _est(prim.get("B")), "bootstrapCI95": (prim.get("B") or {}).get("ci95"), "nDrawsUsed": (prim.get("B") or {}).get("nDrawsUsed"),
                     "methodRange": rng(ah_entries), "methodRangeEntries": ah_entries,
                     "uncertaintyIncluded": ["day-to-day sampling variation within the specified logged-signal model (bootstrapCI95)"],
                     "uncertaintyOmitted": ["BMS SoC semantics and any remapping", "current-sensor gain and offset calibration", "logging-time skew between channels (lag is a scenario, not a CI)",
                                           "voltage-model, quantization and integration-policy effects beyond the listed method-range entries"],
                     "reporting": "bootstrapCI95 and methodRange are separate; the range is a min-max over a fixed list, not a confidence interval; they are never merged"},
        "kWhPer100": {"point": _est(prim.get("B_kwh")), "bootstrapCI95": (prim.get("B_kwh") or {}).get("ci95"), "methodRange": rng(kwh_entries), "methodRangeEntries": kwh_entries,
                      "note": "terminal energy (includes resistive loss on charge and discharge); fitted separately from the charge model; not Ah x a voltage"},
        "currentOffsetFitA": {"value": _est(prim.get("B_offset_A")), "bootstrapCI95": (prim.get("B_offset_A") or {}).get("ci95"),
                              "note": "pooled drift term of the charge model: a model term that absorbs a constant current offset, resistive-loss form differences, timing and capacity effects; not a calibrated sensor zero"},
        "eventsB": {"noOffsetTermAh100": _est(prim.get("B_nooffset")), "reverseAh100": _est(prim.get("B_rev")), "segmentAAh100": _est(prim.get("A")),
                    "note": "reverse regression brackets from above (attenuation); segment-level A is errors-in-variables attenuated"},
        "windows": {k: v for k, v in win.items()}, "wholeDrive": whole, "direction": direction, "lag": lag, "windowsLiteral10": lit, "chronological": chrono,
        "testA_oddEvenWeeks": test_a, "testD_nanFlagDrives": test_d,
        "registry": [
            {"id": "CAP_AH_RATED", "class": "documentary", "quantity": "rated capacity (full reference)", "unit": "Ah", "source": "constantProvenance.CAP_AH_RATED", "automaticSwitch": False},
            {"id": "CAP_KWH", "class": "assumed", "quantity": "legacy energy normalisation scenario (basis undefined)", "unit": "kWh", "source": "constantProvenance.CAP_KWH", "automaticSwitch": False},
            {"id": "Q_SOC_EST", "class": "estimated", "quantity": "apparent charge scale of the logged BMS SoC (SoC range observed)", "unit": "Ah per 100 SoC points",
             "value": _est(prim.get("B")), "source": "capacityBasis.ahPer100.point", "automaticSwitch": False},
            {"id": "E_PER_SOC100_EST", "class": "estimated", "quantity": "apparent terminal-energy scale of the logged BMS SoC (SoC range observed)", "unit": "kWh per 100 SoC points",
             "value": _est(prim.get("B_kwh")), "source": "capacityBasis.kWhPer100.point", "automaticSwitch": False}],
        "inference": rng_note,
        "limits": ["one vehicle, May-October data", "SoC range observed about 42-88 % (little outside 44-83 %); per-100 is an extrapolation beyond it",
                   "shared current-sensor gain error cannot be cancelled or tested", "the BMS SoC is not a pure charge counter (key-on reset, flicker)",
                   "a gross 2.1 kWh with a hidden buffer of up to ~15 % cannot be tested from BMS data", "full vs remapped SoC window (F16c) is not identifiable from the logs"],
    }
    return _round(block, 4)


# ------------------------------------------------------------------------------------------------ stage
ALLOWED = ["/capacityBasis", "/constantProvenance/CAP_AH_RATED", "/_artifactStamps/capacityBasis"]


def _paths(a, b, p=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [x for k in sorted(set(a) | set(b)) for x in (_paths(a.get(k), b.get(k), "%s/%s" % (p, k)) if (k in a and k in b) else ["%s/%s" % (p, k)])]
    return [] if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else [p]


def splice(A, blk, cfg, master_md5="", now=None):
    """Pure: copy of the payload with capacityBasis, its artifact stamp (build gate: every top-level key is stamped; copied from fuelContract, kept unchanged when the block and the corpus hash are
    unchanged) and the documentary CAP_AH_RATED provenance entry (from the config, its single source). Returns (new, changed paths, paths outside the allow-list)."""
    import datetime
    new = copy.deepcopy(A)
    new["capacityBasis"] = blk
    new.setdefault("constantProvenance", {})["CAP_AH_RATED"] = cfg["auditMetadata"]["constantProvenance"]["CAP_AH_RATED"]
    old = (A.get("_artifactStamps") or {}).get("capacityBasis")
    if old and A.get("capacityBasis") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["capacityBasis"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M403: derived by tools/capacity_basis.py from the raw logs (current, SoC, voltage) of the eligible drives; additive, no published value recomputed; apparent scale of the logged SoC, estimated; not M299-reproducible.",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        new["_artifactStamps"]["capacityBasis"] = st
    ch = _paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    import ah_throughput as AH
    master = pd.read_csv("drive_master.csv", low_memory=False)
    recs = load_records(master, AH.raw_loader(), AH.manifest_sha_lookup(), rebuild="--rebuild" in argv)
    blk = estimate(master, recs)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    cfg = json.load(open("summary_config.json", encoding="utf-8"))
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, changed, bad = splice(json.loads(raw), blk, cfg, md5)
    print(json.dumps({"changedPaths": changed[:6], "nChanged": len(changed), "outsideAllowList": bad, "ahPer100": blk["ahPer100"]["point"], "ci95": blk["ahPer100"]["bootstrapCI95"],
                      "methodRange": blk["ahPer100"]["methodRange"], "kWhPer100": blk["kWhPer100"]["point"], "nDrives": blk["population"]["nDrives"], "nDays": blk["population"]["nDays"]}))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
