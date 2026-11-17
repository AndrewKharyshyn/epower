#!/usr/bin/env python3
"""P-R2 (spec analyses/M708_spec.md Rev 2, section 5): the two-state (interior / probe) park model and the pre-registered gate that decides whether the second state is justified. Fresh code under tools/.

Model (exactly as stated in the exploratory report, nothing added): C_i dT_i/dt = q - G_ip (T_i - T_p);  C_p dT_p/dt = G_ip (T_i - T_p) - G_pb (T_p - T_b);  q = alpha' I^2 while driving, 0 parked; T_b = the M709 diurnal boundary
(linear ambient trend plus sinusoid, offset). Only rate ratios are identifiable: k1 = G_ip/C_i, k2 = G_ip/C_p, k3 = G_pb/C_p, alpha = alpha'/C_i, reported as tau_tot = (1 + r)/k3, tau_ip = 1/(k1 + k2), r = C_i/C_p.
While driving the probe state is the logged probe trace (input, 10 s grid, probe mean interpolated from the native readings) and the interior state is integrated (heat input alpha I^2 on the 10 s grid) and carried across stops;
the interior state is reset to the logged start whenever a pair is excluded. alpha >= 0 and the offset are solved linearly for every rate triple. Fit: log-space bounds tau_tot [1, 80] h, tau_ip [0.01, 20] h, r [0.02, 50], four starting points.
GATE P-R2 (frozen before this run): the second state is adopted ONLY IF the held-out (month-blocked: fit May-Aug, test Sep-Nov) MAE of the one-state model M2 minus the two-state MAE is >= 0.25 C in a gap class of 1 h or more, or >= 0.5 C below 1 h,
with the day-clustered paired interval of that difference excluding zero, AND tau_ip and r are interior to their bounds with a profile interval (nominal dev < 3.84) narrower than one decade. Otherwise M2 stays the model of record and the two-state model is reported
as not justified. "Not justified" is not "two states do not exist". Logged probe readings are "logged"; all model quantities are "estimated / model-derived".
Usage: python tools/park_two_state.py [--dir analyses/M718] [--raw-dir DIR] [--workers N]    writes <dir>/park_two_state.json (and a per-drive trace cache pickle that is not committed)"""
import argparse, hashlib, json, math, os, sys
from multiprocessing import Pool
import numpy as np
import pandas as pd
from scipy.optimize import least_squares

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import restart_census as RC
import park_model as PM
import raw_resolver as RR

W = 2 * np.pi / 24.0
DT_H = 10.0 / 3600.0
LO = np.log([1.0, 0.01, 0.02])
HI = np.log([80.0, 20.0, 50.0])
STARTS = [(8.0, 0.3, 1.0), (8.0, 0.1, 0.3), (8.0, 1.0, 3.0), (10.0, 3.0, 1.0)]
TAU_IP_GRID = (0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.5, 3.0, 6.0, 12.0)
R_GRID = (0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
GAIN_LONG, GAIN_SHORT = 0.25, 0.5                      # pre-registered thresholds (C): gap classes >= 1 h / below 1 h
PROFILE_DEV = 3.84                                      # nominal 95 % set of the profile deviance


# ----------------------------------------------------------------------------------- per-drive driving traces ----------------------------------------
def traces_one(path):
    """(Tp[nb], I2[nb], nb) on a 10 s grid: probe mean interpolated from the native readings (probes with >= 2 readings), I^2 = time-weighted mean of I^2 per bin (native sample interval capped at 2.5 s); None without >= 4 probe readings."""
    cols = RC.COLS
    hdr = pd.read_csv(path, nrows=0, encoding="utf-8").columns
    I_col = "[BMS] HV Battery Current (A)"
    use = ["time"] + [cols[p] for p in RC.PROBES if cols[p] in hdr] + ([I_col] if I_col in hdr else [])
    d = pd.read_csv(path, usecols=use, low_memory=False, encoding="utf-8")
    t = pd.to_datetime(d["time"], format="%H:%M:%S.%f", errors="coerce")
    ok = t.notna().values
    sec = (t[ok] - pd.Timestamp("1900-01-01")).dt.total_seconds().values
    sec = sec + np.concatenate([[0], np.cumsum(np.diff(sec) < -12 * 3600)]) * 86400.0
    rel = sec - sec[0]
    d = d[ok].reset_index(drop=True)
    nb = int(np.floor(rel[-1] / 10.0)) + 1
    tm = (np.arange(nb) + 0.5) * 10.0
    tr = []
    nread = 0
    for p in RC.PROBES:
        c = cols[p]
        if c not in d:
            continue
        v = pd.to_numeric(d[c], errors="coerce").values
        m = np.isfinite(v) & (v <= 70) & (v >= -40)
        nread += int(m.sum())
        if m.sum() >= 2:
            tr.append(np.interp(tm, rel[m], v[m]))
    if not tr or nread < 4:
        return None
    Tp = np.mean(tr, axis=0)
    I2 = np.zeros(nb)
    if I_col in d:
        I = pd.to_numeric(d[I_col], errors="coerce").values
        mI = np.isfinite(I) & (np.abs(I) < 900)
        tI, vI = rel[mI], I[mI]
        if len(tI) > 3:
            dt = np.minimum(np.diff(tI, append=tI[-1]), 2.5)
            b = np.floor(tI / 10.0).astype(int)
            w = np.bincount(b, dt, nb)
            s2 = np.bincount(b, dt * vI * vI, nb)
            I2 = np.where(w > 0, s2 / np.maximum(w, 1e-9), 0.0)
    return Tp, I2, nb


def _tr(path):
    try:
        return traces_one(path)
    except Exception:
        return None


def load_traces(E, raw_dir, workers=1, cache=None):
    if cache and os.path.exists(cache):
        return pd.read_pickle(cache)
    res = RR.resolve(raw_dir, os.path.join(ROOT, "raw_manifest.json"))
    paths = [res.index.get(k) for k in E["key"]]
    todo = [p for p in paths if p]
    if workers > 1:
        with Pool(workers) as pool:
            out = pool.map(_tr, todo, chunksize=4)
    else:
        out = [_tr(p) for p in todo]
    it = iter(out)
    tr = [next(it) if p else None for p in paths]
    if cache:
        pd.to_pickle(tr, cache)
    return tr


# ----------------------------------------------------------------------------------- the chain --------------------------------------------------------
class TwoState:
    """Pair frame D (rows = adjacent drive pairs in order; columns gap_h, clock0, p_Abar_e, slope, p_amp, p_hpk, x0, y, use, day, gc, month), per-drive traces (length N + 1, None = unavailable) and the logged start of every drive."""

    def __init__(self, D, traces, startT):
        self.D = D.reset_index(drop=True)
        self.N = len(self.D)
        self.drv = traces
        self.startT = np.asarray(startT, float)
        g = self.D
        self.g = g["gap_h"].values.astype(float)
        self.clock = (g["clock0"].values % 24).astype(float)
        self.Abar = g["p_Abar_e"].values.astype(float)
        self.sl = g["slope"].values.astype(float)
        self.amp = g["p_amp"].values.astype(float)
        self.hpk = g["p_hpk"].values.astype(float)
        self.x0 = g["x0"].values.astype(float)
        self.y = g["y"].values.astype(float)
        self.use = g["use"].values.astype(bool)

    def chain(self, tau_tot, tau_ip, r, use=None):
        """components (base, alpha coefficient, offset coefficient) of the predicted probe-region temperature at each next start [N, 3] (NaN where the pair is not predictable)."""
        use = self.use if use is None else use
        N = self.N
        k3 = (1 + r) / tau_tot
        s = 1.0 / tau_ip
        k1 = s / (1 + r)
        k2 = s * r / (1 + r)
        A = np.array([[-k1, k1], [k2, -k2 - k3]])
        lam, V = np.linalg.eig(A)
        lam, V = lam.real, V.real
        Vi = np.linalg.inv(V)
        c = Vi @ np.array([0.0, k3])
        tj = -1.0 / lam
        sj = c * tj
        G = 1.0 / np.sqrt(1 + (W * tj) ** 2)
        phi = np.arctan(W * tj)
        gA, clk, Ab, sl, amp, hpk = self.g, self.clock, self.Abar, self.sl, self.amp, self.hpk
        with np.errstate(all="ignore"):
            PB0 = np.stack([Ab - sl * tj[j] + G[j] * amp * np.cos(W * (clk - hpk) - phi[j]) for j in range(2)])
            PBg = np.stack([Ab + sl * gA - sl * tj[j] + G[j] * amp * np.cos(W * (clk + gA - hpk) - phi[j]) for j in range(2)])
            ex = np.stack([np.exp(-gA / tj[j]) for j in range(2)])
        out = np.full((N, 3), np.nan)
        f1 = math.exp(-k1 * DT_H)
        Ti = np.array([self.startT[0], 0.0, 0.0]) if np.isfinite(self.startT[0]) else None
        for n in range(N + 1):
            d = self.drv[n]
            if d is not None and Ti is None:
                Ti = np.array([d[0][0], 0.0, 0.0])
            if d is None:
                Ti_end = None
            else:
                Tp, I2, nb = d
                wj = (1 - f1) * f1 ** np.arange(nb - 1, -1, -1)
                F = f1 ** nb
                Ti_end = np.array([F * Ti[0] + wj @ Tp, F * Ti[1] + (wj @ I2) / k1, F * Ti[2]])
            if n == N:
                break
            if use[n] and Ti_end is not None:
                xb = np.array([[Ti_end[0], self.x0[n]], [Ti_end[1], 0.0], [Ti_end[2], 0.0]])
                y0 = xb @ Vi.T
                yb = sj * PBg[:, n] + (y0[0] - sj * PB0[:, n]) * ex[:, n]
                ya = y0[1] * ex[:, n]
                yo = sj * (1 - ex[:, n]) + y0[2] * ex[:, n]
                xg = np.stack([yb, ya, yo]) @ V.T
                out[n] = xg[:, 1]
                Ti = xg[:, 0].copy()
            else:
                Ti = np.array([self.startT[n + 1], 0.0, 0.0]) if np.isfinite(self.startT[n + 1]) else None
        return out

    def solve_lin(self, comp, mask):
        """alpha >= 0 and the offset by linear least squares on the masked pairs."""
        X = comp[mask][:, 1:]
        yy = self.y[mask] - comp[mask][:, 0]
        b = np.linalg.lstsq(X, yy, rcond=None)[0]
        if b[0] < 0:
            b = np.array([0.0, float(np.sum(X[:, 1] * yy) / np.sum(X[:, 1] ** 2))])
        return b

    def predict(self, th, mask):
        comp = self.chain(*th)                                  # the chain always runs over every usable pair (the interior state is carried); `mask` only selects the pairs of the linear solve
        b = self.solve_lin(comp, mask & np.isfinite(comp[:, 0]))
        return comp[:, 0] + b[0] * comp[:, 1] + b[1] * comp[:, 2], b

    def fit(self, mask, x0=(8.0, 0.3, 1.0), fixed=None):
        """fixed: {index: value} for profiling. Parameters in log space. Returns (theta, (alpha, offset), prediction for all pairs, SSE)."""
        free = [i for i in range(3) if not (fixed and i in fixed)]

        def unpack(z):
            th = np.zeros(3)
            for j, i in enumerate(free):
                th[i] = math.exp(z[j])
            if fixed:
                for i, v in fixed.items():
                    th[i] = v
            return th

        def f(z):
            pr, _ = self.predict(unpack(z), mask)
            r = (pr - self.y)[mask]
            return np.where(np.isfinite(r), r, 0.0)
        best = None
        for st in [x0] + STARTS:
            z0 = np.clip(np.log([st[i] for i in free]), LO[free] + 1e-6, HI[free] - 1e-6)
            try:
                o = least_squares(f, z0, bounds=(LO[free], HI[free]), diff_step=1e-3, max_nfev=60)
            except Exception:
                continue
            if best is None or o.cost < best.cost:
                best = o
            if fixed:
                break
        th = unpack(best.x)
        pr, b = self.predict(th, mask)
        return th, b, pr, 2 * best.cost


# ----------------------------------------------------------------------------------- the gate -------------------------------------------------------
def gate(gains, interior, profile_ok):
    """gains: {class: {'est', 'lo', 'hi'}} of MAE(one-state) - MAE(two-state) on the hold-out (positive = the two-state model is better). Returns the pre-registered verdict."""
    cond = {}
    for cls, v in gains.items():
        thr = GAIN_SHORT if cls == "<1 h" else GAIN_LONG
        if cls in ("<10 min", "10-60 min", "all"):
            continue                                              # the rule names the pooled below-1-h class and the classes of 1 h or more
        cond[cls] = bool(v["est"] is not None and v["est"] >= thr and v["lo"] is not None and v["lo"] > 0)
    gain_ok = any(cond.values())
    return {"gainRule": {"classesOf1hOrMore": ">= %.2f C" % GAIN_LONG, "below1h": ">= %.2f C" % GAIN_SHORT, "pairedIntervalExcludesZero": True}, "classMeetsGain": cond, "gainOk": gain_ok,
            "parametersInterior": interior, "profileNarrowerThanOneDecade": profile_ok, "pass": bool(gain_ok and interior and profile_ok)}


def profile_width(th2, model, mask, grid, idx):
    """Nominal profile interval (dev < 3.84) of parameter idx over the grid: returns (values within, ratio max/min)."""
    n = int(mask.sum())
    _, _, _, sse0 = model.fit(mask, x0=tuple(th2))
    keep = []
    rows = []
    for v in grid:
        th_, b_, _, s_ = model.fit(mask, x0=tuple(th2), fixed={idx: v})
        dev = n * math.log(s_ / sse0)
        rows.append({"value": v, "dev": round(dev, 2), "SSE": round(s_, 2)})
        if dev < PROFILE_DEV:
            keep.append(v)
    ratio = (max(keep) / min(keep)) if keep else None
    return rows, keep, ratio


def build_model(E, P, traces):
    D, par = PM.model_frame(E, P)
    D = D.reset_index(drop=True)
    D["use"] = D["use"].astype(bool)
    startT = np.r_[RC_first_start(E), D["y"].values]
    return TwoState(D, traces, startT), D


def RC_first_start(E):
    s = E[["%s_s" % p for p in RC.PROBES]].iloc[0].values.astype(float)
    return float(np.mean(s)) if np.isfinite(s).all() else np.nan


def evaluate(E, P, traces, profile=True):
    """Full evaluation: full-sample fit, profiles, hold-out (fit May-Aug, test Sep-Nov) against the one-state M2, gate P-R2."""
    model, D = build_model(E, P, traces)
    use = model.use
    out = {"nPairsModel": int(use.sum()), "nDays": int(D.loc[use, "day"].nunique())}
    th2, b2, pr2, sse2 = model.fit(use)
    out["fullSample"] = {"tau_tot_h": round(float(th2[0]), 3), "tau_ip_h": round(float(th2[1]), 4), "r_Ci_over_Cp": round(float(th2[2]), 4), "alpha_C_per_A2h": round(float(b2[0]), 6), "offset_C": round(float(b2[1]), 3), "SSE": round(float(sse2), 2)}
    onb = {"tau_ip_h": [math.exp(LO[1]), math.exp(HI[1])], "r": [math.exp(LO[2]), math.exp(HI[2])]}
    interior = bool(onb["tau_ip_h"][0] * 1.05 < th2[1] < onb["tau_ip_h"][1] / 1.05 and onb["r"][0] * 1.05 < th2[2] < onb["r"][1] / 1.05)
    out["fullSample"]["boundsOfProfiledParameters"] = onb
    out["fullSample"]["interiorToBounds"] = interior
    # one-state comparison on the same pairs (M2, full sample SSE)
    F = D[use]
    th1 = PM.fit(F)
    sse1 = float(np.sum((PM.predict(F, *th1) - F["y"].values) ** 2))
    n = int(use.sum())
    out["fullSample"]["oneState"] = {"tau_h": round(float(th1[0]), 3), "offset_C": round(float(th1[1]), 3), "SSE": round(sse1, 2), "deltaAIC_twoMinusOne_nominal": round(n * math.log(sse2 / sse1) + 6, 2),
                                     "note": "nominal AIC overstates the evidence under day clustering; the held-out comparison is the test"}
    prof_ok = None
    if profile:
        rows_t, keep_t, rt = profile_width(th2, model, use, TAU_IP_GRID, 1)
        rows_r, keep_r, rr = profile_width(th2, model, use, R_GRID, 2)
        out["profile"] = {"tau_ip_h": {"grid": rows_t, "nominalSet": keep_t, "ratioMaxOverMin": rt}, "r_Ci_over_Cp": {"grid": rows_r, "nominalSet": keep_r, "ratioMaxOverMin": rr}, "note": "dev = n log(SSE/SSE_min); a nominal 95 % set is dev < 3.84 (too narrow under day clustering); the pre-registered rule asks for a set narrower than one decade for both parameters"}
        prof_ok = bool(rt is not None and rr is not None and rt < 10 and rr < 10)
    # hold-out: fit May-Aug, test Sep-Nov
    mon = D["month"].values
    tr, te = use & (mon <= 8), use & (mon >= 9)
    th2h, b2h, pr2h, _ = model.fit(tr)
    th1h = PM.fit(D[tr])
    y = D["y"].values
    p1 = PM.predict(D, *th1h)
    e1, e2 = np.abs(p1 - y), np.abs(pr2h - y)
    ok = te & np.isfinite(e2)
    gains = {}
    for cls in RC.GAP_LAB + ["<1 h", "all"]:
        m = ok & ((D["gc"] == cls).values if cls not in ("<1 h", "all") else (D["gc"].isin(RC.GAP_LAB[:2]).values if cls == "<1 h" else np.ones(len(D), bool)))
        m = m & np.isfinite(e1)
        if m.sum() < 5:
            continue
        r = RC.boot_mean(D["day"].values[m], (e1 - e2)[m])
        gains[cls] = {"est": r["est"], "lo": r["lo"], "hi": r["hi"], "n": r["n"], "nDays": r["nDays"], "MAE_oneState": float(e1[m].mean()), "MAE_twoState": float(e2[m].mean())}
    out["holdout_fitMayAug_testSepNov"] = {"nTrain": int(tr.sum()), "nTest": int(ok.sum()), "twoStateParams": {"tau_tot_h": round(float(th2h[0]), 3), "tau_ip_h": round(float(th2h[1]), 4), "r": round(float(th2h[2]), 4), "alpha": round(float(b2h[0]), 6), "offset_C": round(float(b2h[1]), 3)},
                                           "oneStateParams": {"tau_h": round(float(th1h[0]), 3), "offset_C": round(float(th1h[1]), 3)}, "gainOneMinusTwo_byClass": gains,
                                           "note": "gain = MAE(one-state M2) - MAE(two-state); positive = the two-state model is better; day-clustered percentile interval, seed 42, 4000 draws; the hold-out is not clean (spec M708 section 3)"}
    out["gate_P-R2"] = gate(gains, interior, prof_ok if prof_ok is not None else False)
    out["gate_P-R2"]["profileEvaluated"] = bool(profile)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "analyses", "M718"))
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--traces-cache", default=None)
    ap.add_argument("--no-profile", action="store_true")
    a = ap.parse_args(argv)
    os.makedirs(a.dir, exist_ok=True)
    E = RC.load_endpoints(a.raw_dir, a.workers)
    P = RC.build_pairs(E, RC.ambient_start_map())
    tr = load_traces(E, a.raw_dir, a.workers, a.traces_cache)
    res = evaluate(E, P, tr, profile=not a.no_profile)
    res.update({"milestone": "M718", "spec": "analyses/M708_spec.md", "specSha256": hashlib.sha256(open(os.path.join(ROOT, "analyses", "M708_spec.md"), "rb").read()).hexdigest(),
                "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "scriptSha256": hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest(), "nDrives": int(len(E)),
                "label": "two-state (interior / probe) park model: estimated, model-derived; logged probe readings; not justified is not 'two states do not exist'"})
    json.dump(res, open(os.path.join(a.dir, "park_two_state.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({"fullSample": res["fullSample"], "gate": res["gate_P-R2"]}, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
