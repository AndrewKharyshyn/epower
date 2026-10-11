"""Independent audit implementation (M403). Run: python -I analyses/M403_audit/auditor_impl.py"""
import os, re, json, pickle
import numpy as np, pandas as pd

ROOT = r"C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\Repo\xtrail-repo"
OUT = os.path.join(ROOT, "analyses", "M403_audit")
CACHE = os.path.join(os.environ.get("TEMP", OUT), "m403_series_cache.pkl")
TC, IC, VC, SC = "time", "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)", "[BMS] HV State of charge (%)"


def digits(s):
    return re.sub(r"\D", "", s)


def parse_time(ser):
    p = ser.astype(str).str.extract(r"^\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
    t = (p[0].astype(float) * 3600 + p[1].astype(float) * 60 + p[2].astype(float)).to_numpy(dtype=float, copy=True)
    ok = ~np.isnan(t)
    tv = t[ok]
    if len(tv) > 1:
        back = np.diff(tv) < -12 * 3600
        tv = tv + np.concatenate([[0], np.cumsum(back)]) * 86400
    t[ok] = tv
    return t


def load_all():
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    m = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file", "date", "ens_outlier_v2"],
                    dtype=str, keep_default_na=False)
    m = m[m.ens_outlier_v2.str.strip() == "False"]
    rawmap = {digits(f): f for f in os.listdir(os.path.join(ROOT, "raw")) if f.lower().endswith(".csv")}
    drives, miss = {}, []
    for _, r in m.iterrows():
        k = digits(r.file.replace(".csv", ""))
        if k not in rawmap:
            miss.append(r.file)
            continue
        df = pd.read_csv(os.path.join(ROOT, "raw", rawmap[k]), usecols=[TC, IC, VC, SC], low_memory=False)
        t = parse_time(df[TC])
        out = {"date": r.date, "file": r.file}
        for nm, c in (("I", IC), ("V", VC), ("S", SC)):
            v = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float, copy=True)
            ok = ~np.isnan(v) & ~np.isnan(t)
            tt, vv = t[ok], v[ok]
            o = np.argsort(tt, kind="stable")
            out[nm] = (tt[o], vv[o])
        drives[r.file] = out
    res = (drives, miss)
    pickle.dump(res, open(CACHE, "wb"))
    return res


def uniq(t, y):
    u = np.concatenate([[True], np.diff(t) > 0])
    return t[u], y[u]


def clean_series(d):
    tI, I = d["I"]
    k = np.abs(I) < 900
    tI, I = uniq(tI[k], I[k])
    tV, V = d["V"]
    k = (V >= 200) & (V <= 450)
    tV, V = uniq(tV[k], V[k])
    tS, S = d["S"]
    k = S > 0
    tS, S = tS[k], S[k]
    return tI, I, tV, V, tS, S


def deglitch(tS, S, jump=20.0, win=5.0):
    keep = np.ones(len(S), bool)
    n = len(S)
    last = 0
    for i in range(1, n):
        if abs(S[i] - S[last]) >= jump:
            j = i + 1
            rev = False
            while j < n and tS[j] - tS[i] <= win:
                if abs(S[j] - S[last]) < jump:
                    rev = True
                    break
                j += 1
            if rev:
                keep[i] = False
                continue
        last = i
    return tS[keep], S[keep]


def cumint(t, y, mode="trap"):
    dt = np.diff(t)
    inc = 0.5 * (y[1:] + y[:-1]) * dt if mode == "trap" else y[:-1] * dt
    return np.concatenate([[0.0], np.cumsum(inc)])


def cum_at(tq, t, C, y, mode):
    """cumulative integral C (A*s based) evaluated at tq consistent with integration rule"""
    if mode == "trap":
        return np.interp(tq, t, C)
    idx = np.clip(np.searchsorted(t, tq, side="right") - 1, 0, len(t) - 1)
    return C[idx] + y[idx] * (tq - t[idx])


def segments(tI, gap, minn=20):
    br = np.where(np.diff(tI) > gap)[0]
    st = np.concatenate([[0], br + 1])
    en = np.concatenate([br + 1, [len(tI)]])
    return [(a, b) for a, b in zip(st, en) if (b - a) > minn]


def prep(d, glitch=True):
    tI, I, tV, V, tS, S = clean_series(d)
    if glitch and len(S) > 2:
        tS, S = deglitch(tS, S)
    return tI, I, tV, V, tS, S


def collect_B(drives, gap=10.0, mode="trap", glitch=True, min_events=3, with_A=False):
    rows, segA = [], []
    for f, d in drives.items():
        if len(d["I"][0]) < 2 or len(d["S"][0]) < 2:
            continue
        tI, I, tV, V, tS, S = prep(d, glitch)
        if len(tI) < 21:
            continue
        for a, b in segments(tI, gap):
            t, i = tI[a:b], I[a:b]
            v = np.interp(t, tV, V) if len(V) >= 2 else np.full(len(t), np.nan)
            iv = i * v / 1000.0
            Q = cumint(t, i, mode) / 3600.0
            E = cumint(t, iv, mode) / 3600.0
            m = (tS >= t[0]) & (tS <= t[-1])
            ts, s = tS[m], S[m]
            if len(s) < 10:
                continue
            if with_A and (t[-1] - t[0]) >= 600:
                segA.append((f, d["date"], np.median(s[-5:]) - np.median(s[:5]), Q[-1], (t[-1] - t[0]) / 3600.0))
            ev = np.where(np.abs(np.abs(np.diff(s)) - 0.5) < 1e-6)[0]
            if len(ev) < min_events:
                continue
            lev = 0.5 * (s[ev] + s[ev + 1])
            te = 0.5 * (ts[ev] + ts[ev + 1])
            qe = cum_at(te, t, Q * 3600.0, i, mode) / 3600.0
            ee = cum_at(te, t, E * 3600.0, iv, mode) / 3600.0
            th = (te - t[0]) / 3600.0
            rows.append((f, d["date"], lev - lev.mean(), qe - qe.mean(), ee - ee.mean(), th - th.mean()))
    return rows, segA


def ols2(x1, x2, y):
    X = np.column_stack([x1, x2])
    return np.linalg.lstsq(X, y, rcond=None)[0]


def fitB(rows):
    lev = np.concatenate([r[2] for r in rows])
    Q = np.concatenate([r[3] for r in rows])
    E = np.concatenate([r[4] for r in rows])
    th = np.concatenate([r[5] for r in rows])
    bq, be, br = ols2(lev, th, Q), ols2(lev, th, E), ols2(Q, th, lev)
    return dict(ah=100 * bq[0], offs=bq[1], kwh=100 * be[0], rev=100 / br[0], n_events=len(lev))


def boot_B(rows, B=4000, seed=42):
    days = sorted(set(r[1] for r in rows))
    S = []
    for dd in days:
        rr = [r for r in rows if r[1] == dd]
        lev = np.concatenate([r[2] for r in rr]); Q = np.concatenate([r[3] for r in rr])
        E = np.concatenate([r[4] for r in rr]); th = np.concatenate([r[5] for r in rr])
        suf = lambda a, b, y: np.array([a @ a, a @ b, b @ b, a @ y, b @ y])
        S.append(np.stack([suf(lev, th, Q), suf(lev, th, E), suf(Q, th, lev)]))
    M = np.stack(S)
    rng = np.random.default_rng(seed)
    D = len(days)
    out = np.empty((B, 3))
    for b in range(B):
        T = M[rng.integers(0, D, D)].sum(0)
        aa, ab, bb, ay, by = T.T
        out[b] = (bb * ay - ab * by) / (aa * bb - ab * ab)
    q = lambda x: [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))]
    return dict(ah=q(100 * out[:, 0]), kwh=q(100 * out[:, 1]), rev=q(100 / out[:, 2]), D=D)


def fitA(segA):
    dS = np.array([s[2] for s in segA]); Q = np.array([s[3] for s in segA]); T = np.array([s[4] for s in segA])
    be = ols2(dS, T, Q)
    return dict(ah=100 * be[0], drift=be[1], n=len(segA), n_drives=len(set(s[0] for s in segA)))


def windows(drives, target=10.0, glitch=True, skip_to_b=False):
    W = []
    for f, d in drives.items():
        if len(d["I"][0]) < 2 or len(d["S"][0]) < 2 or len(d["V"][0]) < 2:
            continue
        tI, I, tV, V, tS, S = prep(d, glitch)
        if len(tI) < 2 or len(tV) < 2 or len(tS) < 2:
            continue
        lo, hi = max(tI[0], tV[0]), min(tI[-1], tV[-1])
        m = (tS >= lo) & (tS <= hi)
        t, s = uniq(tS[m], S[m])
        n = len(s)
        Qc = cumint(tI, I, "trap") / 3600.0
        a = 0
        while a < n - 1:
            b = None
            j = a + 1
            while j < n and t[j] - t[a] <= 600:
                if abs(s[j] - s[a]) >= target:
                    b = j
                    break
                j += 1
            if b is None:
                a += 1
                continue
            ok = (t[b] - t[a]) >= 10
            if ok:
                ts_, ss_ = t[a:b + 1], s[a:b + 1]
                if np.any(np.diff(ts_) > 5) or np.any(np.abs(np.diff(ss_)) > 2):
                    ok = False
                else:
                    ia = np.searchsorted(tI, t[a], side="right") - 1
                    ib = np.searchsorted(tI, t[b], side="left")
                    if ia < 0 or ib >= len(tI) or np.any(np.diff(tI[ia:ib + 1]) > 5):
                        ok = False
            if not ok:
                a = b if skip_to_b else a + 1
                continue
            dsgn = np.sign(s[b] - s[a])
            L = s[b] - dsgn * target
            kk = None
            for k in range(b - 1, a - 1, -1):
                if abs(s[k] - L) < 1e-6 and k >= 1 and np.sign(s[k] - s[k - 1]) == dsgn:
                    kk = k
                    break
            if kk is None:
                a = b if skip_to_b else a + 1
                continue
            Qw = np.interp(t[b], tI, Qc) - np.interp(t[kk], tI, Qc)
            W.append((f, d["date"], Qw, s[b] - s[kk], (t[b] - t[kk]) / 3600.0))
            a = b
    return W


def fitW(W):
    Q = np.array([w[2] for w in W]); dS = np.array([w[3] for w in W]) / 100.0; h = np.array([w[4] for w in W])
    be = ols2(dS, h, Q)
    return dict(ah=be[0], bias=be[1], n=len(W), n_drives=len(set(w[0] for w in W)), n_days=len(set(w[1] for w in W)))


def main():
    drives, miss = load_all()
    print("drives loaded", len(drives), "missing raw", miss)
    rows, segA = collect_B(drives, with_A=True)
    fB, bs, fA = fitB(rows), boot_B(rows), fitA(segA)
    W = windows(drives)
    fW = fitW(W)
    res = dict(B_ah_per100=fB["ah"], B_ci95=bs["ah"], B_kwh_per100=fB["kwh"], B_kwh_ci95=bs["kwh"],
               B_offset_A=fB["offs"], B_reverse_ah_per100=fB["rev"], B_reverse_ci95=bs["rev"],
               A_segment_ah_per100=fA["ah"], A_segment_drift_A=fA["drift"], A_n_segments=fA["n"], A_n_drives=fA["n_drives"],
               W10_anchored_ah_per100=fW["ah"], W10_bias_A=fW["bias"], W10_n_drives=fW["n_drives"], W10_n_days=fW["n_days"],
               n_drives=len(set(r[0] for r in rows)), n_days=len(set(r[1] for r in rows)),
               n_events=fB["n_events"], n_windows=fW["n"], n_segments_B=len(rows), n_master_false=len(drives))
    sens = {}

    def run(name, **kw):
        r, _ = collect_B(drives, **kw)
        f = fitB(r)
        sens[name] = dict(ah=f["ah"], kwh=f["kwh"], rev=f["rev"], n_events=f["n_events"], n_segments=len(r),
                          n_drives=len(set(x[0] for x in r)))
    run("primary")
    run("gap3", gap=3.0)
    run("zoh", mode="zoh")
    run("no_glitch_removal", glitch=False)
    run("min_events_1", min_events=1)
    run("min_events_2", min_events=2)
    sens["W10_noglitch"] = fitW(windows(drives, glitch=False))
    sens["W10_skip_to_b"] = fitW(windows(drives, skip_to_b=True))
    base = sens["primary"]["ah"]
    res["sensitivity_B"] = sens
    res["max_sens_pct_B_ah"] = max(abs(v["ah"] / base - 1) * 100 for k, v in sens.items()
                                   if k.startswith(("gap", "zoh", "no_glitch", "min_")))
    res["choices"] = (
        "Drives: ens_outlier_v2 string == 'False' (blank/True excluded); raw matched by digits; calendar day = master date. "
        "Time HH:MM:SS.fff, midnight unwrapped on cumulative backward jumps >12 h over file rows. Current: non-NaN, |I|<900, sorted, duplicate times dropped (first kept). "
        "V 200-450 np.interp (edge clamped). SoC>0; primary applies glitch removal (drop sample jumping >=20 pp from last kept sample if a sample within 5 s returns to <20 pp of last kept value). "
        "Segments: gaps >10 s, >20 samples. B: SoC samples with time in [seg start, seg end], >=10; event = consecutive SoC pair differing by 0.5 (tol 1e-6, either sign); >=3 events/seg; segment demeaned; pooled OLS no intercept; trapezoid. "
        "Reverse: level~a*Q+b*th, 100/a. A: segments >=10 min and >=10 SoC samples; medians of first/last 5 SoC. "
        "Windows: SoC restricted to span covered by I and V, strictly increasing times; failed window advances a by one sample, successful advances to b; "
        "SoC jump >2 pp check on all consecutive pairs in window (all <=5 s after gap check); current-gap check on current samples bracketing [t_a,t_b]; re-anchor needs k>=1 with sign(s[k]-s[k-1])==d. "
        "Bootstrap: resample calendar days with replacement, default_rng(42), 4000 draws, percentile 2.5/97.5, refit from per-day sufficient statistics.")
    json.dump(res, open(os.path.join(OUT, "auditor_results.json"), "w", encoding="utf-8"), indent=1, default=float)
    print(json.dumps({k: v for k, v in res.items() if k != "choices"}, indent=1, default=float))


if __name__ == "__main__":
    main()
