#!/usr/bin/env python3
"""M768 (spec analyses/M768_spec.md Rev 3): energy flows and fuel BY estimated grade class (three classes primary: downhill below -1 pp, flat, uphill above 1 pp). Auxiliary, report-only, offline.

Quantities (per step of the frozen M762 primary step set, OBD window +16 s): Q1a battery CHARGE energy (all steps; the master's per-interval directional integral, charge = the negative part of the discharge-positive battery power), Q1b the part with the engine off
(300 rpm proxy, primary; the master's 400 rpm engine-off charge is a sensitivity), Q2 exploratory apparent recovery (ratio of sums, assumed mass, steps with at least 100 kJ released), Q3 traction energy (reconstruction, fuel basis), Q4 net battery energy, SOC change and
the engine-on share of the charge, Q5 fuel (app-calculated, fuel basis). Day-clustered bootstrap (seed 42, 4000 draws); only Q1a downhill minus flat is confirmatory; every placebo (displaced DEM) result is reported beside the primary.
Control R1: the step set equals the M762 result; the per-drive full-drive charge integrals reproduce the master columns within the tolerances fixed in the spec. Aggregates only: no per-step or per-drive output, no coordinates.

Usage: python tools/grade_energy_flows.py [--run] [--cache FILE] [--nb 4000]   Exit codes: 0 done or skipped, 1 master pin, 3 control or manifest failure."""
import argparse, io, json, math, os, re, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import dem_step_grade as dsg
import dem_crosscheck as X
import odometer_jump_audit as J

SEED, NB_DEFAULT = 42, 4000
G = 9.80665
MASS = 1950.0
CLASS_EDGES = (-1.0, 1.0)                                   # three classes: downhill, flat, uphill (pp)
CLASS_NAMES = ("downhill", "flat", "uphill")
BAND_EDGES = (50.0, 90.0)                                   # speed bands by the mean step speed (km/h): urban, mixed, highway
BAND_NAMES = ("urban", "mixed", "highway")
A_MIN_KJ = 100.0                                            # Q2: released energy threshold (spec 7.5)
FLOORS = {"days": 30, "km": 100.0, "steps": 1000}
Q2_FLOORS = {"steps": 20, "days": 10}
TOL_GROSS = (0.005, 0.01)                                   # relative, kWh (spec 8.2)
TOL_OFF_REGEN = (0.01, 0.01)
MAX_DRIVE_FAIL_SHARE = 0.02
ENG_OFF_RPM = 300.0
ENG_ON_RPM = 400.0


class Stop(Exception):
    pass


# ------------------------------------------------------------------ steps with their windows (copy of dsg.build_steps plus the window times; equality tested)
def build_steps_win(obd, ft, flat, flon, dem, shift=dsg.PRIMARY_SHIFT):
    """dsg.build_steps with the step window (a, b) recorded: same selection, same values. Returns (rows, dropped)."""
    t, v, dt, P = (np.asarray(obd[k], float) for k in ("t", "v", "dt", "P"))
    cD, cV2, cV3 = np.cumsum(v * dt), np.cumsum(v * v * dt), np.cumsum(v ** 3 * dt)
    Pn = np.nan_to_num(P)
    cE, cEn, cEp = np.cumsum(Pn * dt), np.cumsum(np.minimum(Pn, 0.0) * dt), np.cumsum(np.maximum(Pn, 0.0) * dt)
    ft, flat, flon = np.asarray(ft, float), np.asarray(flat, float), np.asarray(flon, float)
    rows, dropped = [], {"gap": 0, "short": 0, "long": 0, "outside_obd": 0}
    n = len(ft)
    h = dem.height(flat, flon) if n else np.zeros(0)
    pairs = [(k, k + 1) for k in range(n - 1)]
    ia = lambda c, x: np.interp(x, t, c)
    in_obd = [(ft[k] + shift >= t[0]) and (ft[k + 1] + shift <= t[-1]) for k, _ in pairs]
    cand = [k for (k, _), ok in zip(pairs, in_obd) if ok]
    first_k, last_k = (cand[0], cand[-1]) if cand else (None, None)
    for (k, k2), ok in zip(pairs, in_obd):
        if not ok:
            dropped["outside_obd"] += 1
            continue
        if ft[k2] - ft[k] > dsg.GAP_MAX_S or ft[k2] <= ft[k]:
            dropped["gap"] += 1
            continue
        a, b = ft[k] + shift, ft[k2] + shift
        d = float(ia(cD, b) - ia(cD, a))
        if d < dsg.STEP_MIN_M:
            dropped["short"] += 1
            continue
        if d > dsg.STEP_MAX_M:
            dropped["long"] += 1
            continue
        i0, i1 = np.searchsorted(t, a, "left"), np.searchsorted(t, b, "right")
        vmin = float(v[i0:i1].min()) if i1 > i0 else float(min(ia(v, a), ia(v, b)))
        rows.append({"a": float(a), "b": float(b), "d_m": d, "T_s": float(b - a), "E_kJ": float(ia(cE, b) - ia(cE, a)), "Eneg_kJ": float(ia(cEn, b) - ia(cEn, a)), "Epos_kJ": float(ia(cEp, b) - ia(cEp, a)),
                     "V2": float(ia(cV2, b) - ia(cV2, a)), "V3": float(ia(cV3, b) - ia(cV3, a)), "vs": float(ia(v, a)), "ve": float(ia(v, b)),
                     "vmin_kmh": vmin * 3.6, "vmean_kmh": d / (b - a) * 3.6, "first": k == first_k, "last": k == last_k, "dh": float(h[k2] - h[k]), "dh_pl": np.nan, "dh_pr": np.nan})
        for side, name in ((1.0, "dh_pl"), (-1.0, "dh_pr")):
            la1, lo1, la2, lo2 = dsg.displace(flat[k], flon[k], flat[k2], flon[k2], dsg.PLACEBO_M, side)
            hh = dem.height([la1, la2], [lo1, lo2])
            rows[-1][name] = float(hh[1] - hh[0]) if np.all(np.isfinite(hh)) else np.nan
    return rows, dropped


# ------------------------------------------------------------------ battery charge arrays: the master's per-interval integral (known-answer tested against a planted drive)
def directional_integrals(t_s, p_kw, dt_cap=5.0):
    """The master's F01 zero-crossing-aware directional integration (compute_drive_summary_v6, M229): per interval the discharge and charge energy (kWh) from the piecewise-linear power p (kW, discharge positive)."""
    t_s, p = np.asarray(t_s, float), np.asarray(p_kw, float)
    dt_h = np.clip(np.diff(t_s, prepend=t_s[0]), 0.0, dt_cap) / 3600.0
    p0 = np.nan_to_num(np.concatenate([[np.nan], p[:-1]]), nan=0.0)
    cross = (p0 * p) < 0
    ab = np.abs(p0) + np.abs(p)
    den = np.where(ab > 0, 2.0 * ab, 1.0)
    disc_c = dt_h * ((p0 > 0) * p0 ** 2 + (p > 0) * p ** 2) / den
    chg_c = dt_h * ((p0 < 0) * p0 ** 2 + (p < 0) * p ** 2) / den
    signed = dt_h * (p0 + p) / 2.0
    disc = np.where(cross, disc_c, np.where(signed > 0, signed, 0.0))
    chg = np.where(cross, chg_c, np.where(signed < 0, -signed, 0.0))
    return disc, chg, dt_h


def charge_arrays(csv_bytes):
    """Replicates the master's energy block for one drive from the raw CSV: returns the I time base (seconds since the first row), per-interval charge and discharge energy (kWh), the engine speed and the master's pure-regeneration mask; None without usable I and V."""
    import compute_drive_summary_v6 as cds
    df, t = cds._prep_bytes(csv_bytes)
    I = cds._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900]
    V = cds._series(df, t, "V", lo=200, hi=450)
    eng = cds._series(df, t, "eng_rpm", lo=0)
    soc = cds._series(df, t, "soc")
    if I is None or V is None or len(I) <= 2:
        return None
    e = cds._asof(I.copy(), V, "V", cds.V_ALIGN_TOL).dropna(subset=["V"])
    e = cds._asof(e, eng, "eng_rpm", cds.ENG_ALIGN_TOL)
    e["Id"] = -e["v"]                                         # the BMS current is charge-positive (M11, M265); discharge-positive = -I
    e["P"] = e["Id"] * e["V"] / 1000.0
    if len(e) < 2:
        return None
    t0 = t.iloc[0]
    ts = (e["t"] - t0).dt.total_seconds().to_numpy()
    disc, chg, _ = directional_integrals(ts, e["P"].to_numpy(), cds.DT_CAP_S)
    rpm = e["eng_rpm"].fillna(0).to_numpy()
    tq = cds._series(df, t, "target_torque")
    pure = None
    if tq is not None:
        e2 = cds._asof(e.copy(), tq, "tq", "1500ms")
        pure = ((e2["tq"].fillna(0) < -15).to_numpy()) & ~(rpm > ENG_ON_RPM)
    out = {"ts": ts, "disc": disc, "chg": chg, "rpm": rpm, "pure": pure, "soc_t": None, "soc_v": None}
    if soc is not None:
        out["soc_t"] = (soc["t"] - t0).dt.total_seconds().to_numpy()
        out["soc_v"] = soc["v"].to_numpy()
    return out


def cum_at(ts, arr, x):
    """Cumulative sum of per-interval values attributed to the interval end times, interpolated at x."""
    return np.interp(x, ts, np.cumsum(arr))


def step_charge(ca, a_rel, b_rel):
    """Per-step integrals from the charge arrays (a_rel, b_rel in seconds since the first row)."""
    ts = ca["ts"]
    off300 = (ca["rpm"] <= ENG_OFF_RPM)
    off400 = ~(ca["rpm"] > ENG_ON_RPM)
    out = {"q1a": cum_at(ts, ca["chg"], b_rel) - cum_at(ts, ca["chg"], a_rel), "q1b": cum_at(ts, ca["chg"] * off300, b_rel) - cum_at(ts, ca["chg"] * off300, a_rel),
           "q1b_400": cum_at(ts, ca["chg"] * off400, b_rel) - cum_at(ts, ca["chg"] * off400, a_rel), "disc": cum_at(ts, ca["disc"], b_rel) - cum_at(ts, ca["disc"], a_rel)}
    out["q1a_on400"] = out["q1a"] - out["q1b_400"]
    if ca["soc_t"] is not None and len(ca["soc_t"]) > 1:
        out["dsoc"] = float(np.interp(b_rel, ca["soc_t"], ca["soc_v"]) - np.interp(a_rel, ca["soc_t"], ca["soc_v"]))
    else:
        out["dsoc"] = float("nan")
    return out


def drive_reconciliation(ca, mrow):
    """Per-drive full-drive sums against the master columns: gross charge, engine-off charge (400 rpm) and pure regeneration; True when within the spec tolerances."""
    res = {}
    gc = float(ca["chg"].sum())
    off400 = ~(ca["rpm"] > ENG_ON_RPM)
    eo = float(ca["chg"][off400].sum())
    pr = float(ca["chg"][ca["pure"]].sum()) if ca["pure"] is not None else None
    for key, val, col, tol in (("gross", gc, "gross_charge_kwh", TOL_GROSS), ("eng_off", eo, "charge_eng_off_kwh", TOL_OFF_REGEN), ("pure_regen", pr, "charge_pure_regen_kwh", TOL_OFF_REGEN)):
        m = mrow.get(col)
        if val is None or m is None or pd.isna(m):
            res[key] = None
            continue
        diff = abs(val - float(m))
        res[key] = bool(diff <= max(tol[0] * abs(float(m)), tol[1]))
    return res


# ------------------------------------------------------------------ classes and estimators (known-answer tested)
def class3(g):
    g = np.asarray(g, float)
    return np.where(np.isfinite(g), np.digitize(g, CLASS_EDGES), -1)


def band3(v):
    return np.digitize(np.asarray(v, float), BAND_EDGES)


def day_arrays(num, den, cls, band, days, nd_index):
    """Per-day sums of the numerator and the denominator by class and speed band: arrays [nd, 3, 3]."""
    nd = int(nd_index.max()) + 1 if len(nd_index) else 0
    N, D = np.zeros((nd, 3, 3)), np.zeros((nd, 3, 3))
    ok = (cls >= 0) & np.isfinite(num) & np.isfinite(den)
    np.add.at(N, (nd_index[ok], cls[ok], band[ok]), num[ok])
    np.add.at(D, (nd_index[ok], cls[ok], band[ok]), den[ok])
    return N, D


def class_means(N, D, W):
    """Raw and speed-standardised class means (numerator over denominator) at the point and under the day weights W (nb x nd): returns dicts of arrays [3] and [nb, 3]."""
    def one(w):
        Nw, Dw = np.einsum("...d,dcs->...cs", w, N), np.einsum("...d,dcs->...cs", w, D)
        with np.errstate(divide="ignore", invalid="ignore"):
            raw = Nw.sum(-1) / Dw.sum(-1)
            rat = Nw / Dw
            share = D.sum((0, 1))
            share = share / share.sum()
            ok = np.isfinite(rat).all(axis=-2)                        # a band is used only if every class has data in it
            wts = np.where(ok, share, 0.0)
            wts = wts / wts.sum(-1, keepdims=True) if wts.ndim > 1 else wts / wts.sum()
            std = (np.where(np.isfinite(rat), rat, 0.0) * wts[..., None, :]).sum(-1)
        return raw, std
    nd = N.shape[0]
    raw_p, std_p = one(np.ones(nd))
    raw_b, std_b = one(W)
    return raw_p, std_p, raw_b, std_b


def pct_ci(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))] if len(x) > 20 else [None, None]


def contrast_block(pt, draws, scale=1.0):
    """Class means and the contrasts downhill minus flat and uphill minus flat with day-clustered intervals and the minimum detectable difference (2.8 standard errors)."""
    out = {"means": {CLASS_NAMES[c]: {"est": float(scale * pt[c]) if np.isfinite(pt[c]) else None, "ci95": [None if v is None else float(scale * v) for v in pct_ci(draws[:, c])]} for c in range(3)}}
    for c, nm in ((0, "downhill_minus_flat"), (2, "uphill_minus_flat")):
        d = draws[:, c] - draws[:, 1]
        est = pt[c] - pt[1]
        se = float(np.nanstd(d))
        out[nm] = {"est": float(scale * est) if np.isfinite(est) else None, "ci95": [None if v is None else float(scale * v) for v in pct_ci(d)], "se": float(scale * se), "mdd": float(scale * 2.8 * se)}
    return out


def support(cls, days, km, c):
    m = cls == c
    return {"steps": int(m.sum()), "days": int(len(set(np.asarray(days)[m]))), "km": float(np.asarray(km)[m].sum()),
            "floors_met": bool(m.sum() >= FLOORS["steps"] and len(set(np.asarray(days)[m])) >= FLOORS["days"] and np.asarray(km)[m].sum() >= FLOORS["km"])}


def slope_fit(y, w, grade, band, cohort, days, W, nb):
    """Weighted least squares of y (per-km quantity) on the grade (pp) with speed-band and cohort fixed effects; day-clustered bootstrap of the slope per percentage point."""
    ok = np.isfinite(y) & np.isfinite(grade) & np.isfinite(w) & (w > 0)
    if ok.sum() < 50:
        return None
    y, w, grade, band, cohort, days = y[ok], w[ok], grade[ok], band[ok], np.asarray(cohort)[ok], np.asarray(days)[ok]
    cols = [grade]
    for b in (1, 2):
        cols.append((band == b).astype(float))
    for ch in sorted(set(cohort))[1:]:
        cols.append((cohort == ch).astype(float))
    Xm = np.column_stack([np.ones(len(y))] + cols)
    ud, di = X.day_index(days)
    sw = np.sqrt(w)
    A, c, _, _ = dsg.day_sums(Xm * sw[:, None], y * sw, di, len(ud))
    cols_idx = list(range(Xm.shape[1]))
    sc = np.sqrt((Xm ** 2).mean(0)) + 1e-12
    A, c, _, _ = dsg.day_sums((Xm / sc) * sw[:, None], y * sw, di, len(ud))
    pt = dsg.solve_w(A, c, None, cols_idx)[1] / sc[1]
    if W is None or W.shape[1] != len(ud):
        W = X.boot_weights(len(ud), nb)
    bs = dsg.solve_w(A, c, W, cols_idx)[:, 1] / sc[1]
    return {"slope_per_pp": float(pt), "ci95": pct_ci(bs), "se": float(np.nanstd(bs)), "mdd": float(2.8 * np.nanstd(bs)), "n_steps": int(len(y)), "n_days": int(len(ud))}


def reading(primary, placebo, consensus_same_sign):
    """Spec R3: 'differs from flat' only if the interval excludes zero AND the consensus-class sensitivity has the same sign AND the placebo is not (same sign, interval excluding zero, at least 0.5 times the primary), else 'inconclusive' / 'not distinguishable'."""
    lo, hi = primary["ci95"]
    if lo is None or hi is None:
        return "not testable"
    excl = lo > 0 or hi < 0
    if not excl:
        return "not distinguishable"
    plo, phi = placebo["ci95"]
    pe = placebo["est"]
    if plo is not None and (plo > 0 or phi < 0) and pe is not None and primary["est"] is not None and np.sign(pe) == np.sign(primary["est"]) and abs(pe) >= 0.5 * abs(primary["est"]):
        return "inconclusive (placebo of comparable size)"
    if not consensus_same_sign:
        return "inconclusive (consensus class disagrees)"
    return "differs from flat"


# ------------------------------------------------------------------ the run (needs the DEM folders, the cloud store, the raw files; optional stage)
def fuel_arrays_full(raw_dir, fname, mrow, t0):
    """dsg.drive_arrays plus the fuel flow (L/h) and the engine speed on the same epoch axis (fuel-instrumented drives only)."""
    import recon_engine as RE
    import model_constants as MC
    RE.BASE = raw_dir.rstrip("/\\") + "/"
    off = float(mrow.get("I_offset_A_applied", 0.0) or 0.0)
    g = RE.load_drive(os.path.basename(fname), off)
    if g is None:
        return None
    pc = RE.precompute(g)
    agg, ps = RE.central_estimate_v2_persample(pc, mrow, "central")
    first = pd.read_csv(os.path.join(raw_dir, os.path.basename(fname)), usecols=["time"], nrows=1)["time"].iloc[0]
    tod = lambda ts: ts.hour * 3600 + ts.minute * 60 + ts.second + ts.microsecond / 1e6
    tod0 = tod(pd.to_datetime(str(first), format="mixed"))
    tg = (g["t"] - g["t"].iloc[0]).dt.total_seconds().values
    tod_g0 = tod(g["t"].iloc[0])
    t = t0 + ((tod_g0 - tod0) % 86400.0) + tg
    v = pd.Series(g["speed"].values, dtype=float).interpolate(limit=5, limit_area="inside").fillna(0.0).values / 3.6
    return {"t": t, "v": v, "dt": g["dt"].values, "P": ps["Ptrac"], "flow": np.nan_to_num(pd.to_numeric(g["flow"], errors="coerce").values), "rpm": np.nan_to_num(pd.to_numeric(g["rpm"], errors="coerce").values)}


def collect_energy(args, dems):
    """Steps of the registered corpus with the window times, the charge integrals (all steps) and, on the fuel basis, the fuel and engine-on time per step."""
    import bisect
    mi, mc, mg = dsg.mi, dsg.mc, dsg.mg
    master = mc.load_master(args.master)
    dmaster = pd.read_csv(args.master)
    regime = {}
    if os.path.exists(args.seasonal):
        sd = pd.read_csv(args.seasonal, usecols=["file", "thermal_regime"])
        regime = dict(zip(sd["file"], sd["thermal_regime"]))
    geo = mi.load_stream(args.store, "Geolocation")
    cpos = [(t, mc.fnum(x["LocationLatitude"]), mc.fnum(x["LocationLongitude"])) for t, x in geo]
    cpos = [(t, la, lo) for t, la, lo in cpos if la is not None and lo is not None and not (la == 0 and lo == 0) and mc.BOX[0] <= la <= mc.BOX[1] and mc.BOX[2] <= lo <= mc.BOX[3]]
    ct, cla, clo = np.array([c[0] for c in cpos]), np.array([c[1] for c in cpos]), np.array([c[2] for c in cpos])
    idx = mg.raw_index(args.raw_dir)
    mrows = {r["file"]: r for _, r in dmaster.iterrows()}
    out, recon = [], []
    for m in master:
        key = re.sub(r"\D", "", os.path.basename(m["file"]))
        path = idx.get(key)
        mrow = mrows.get(m["file"])
        if not path or mrow is None:
            continue
        ca = None
        try:
            ca = charge_arrays(open(path, "rb").read())
        except Exception:
            ca = None
        if ca is not None:
            recon.append(drive_reconciliation(ca, mrow))
        i0, i1 = bisect.bisect_left(ct, m["t0"] - 60.0), bisect.bisect_right(ct, m["t1"] + 60.0)
        if i1 - i0 < 2:
            continue
        arr = fuel_arrays_full(args.raw_dir, path, mrow, m["t0"])
        fuel = arr is not None
        if arr is None:
            arr = dsg.speed_only_arrays(path, m["t0"])
            if arr is None:
                continue
        base, _ = build_steps_win(arr, ct[i0:i1], cla[i0:i1], clo[i0:i1], dems["F"])
        if not base:
            continue
        for k, d in dems.items():
            if k == "F":
                continue
            rk, _ = dsg.build_steps(arr, ct[i0:i1], cla[i0:i1], clo[i0:i1], d, dsg.PRIMARY_SHIFT)
            if len(rk) != len(base):
                raise Stop("step sets differ between sources (internal error)")
            for r0, r1 in zip(base, rk):
                r0["dh_" + k] = r1["dh"]
                if k in ("N", "A", "G"):
                    r0["dhpl_" + k], r0["dhpr_" + k] = r1["dh_pl"], r1["dh_pr"]
        if fuel:
            tF = arr["t"]
            cumfuel = np.cumsum(arr["flow"] * arr["dt"] / 3600.0)
            cumon = np.cumsum((arr["rpm"] > ENG_ON_RPM) * arr["dt"])
        for r in base:
            r.update({"day": m["date"], "drive": m["file"], "cohort": regime.get(m["file"], "unknown"), "fuel": fuel})
            if ca is not None:
                r.update(step_charge(ca, r["a"] - m["t0"], r["b"] - m["t0"]))
            else:
                r.update({"q1a": np.nan, "q1b": np.nan, "q1b_400": np.nan, "disc": np.nan, "q1a_on400": np.nan, "dsoc": np.nan})
            if fuel:
                r["fuel_L"] = float(np.interp(r["b"], tF, cumfuel) - np.interp(r["a"], tF, cumfuel))
                r["eng_on_s"] = float(np.interp(r["b"], tF, cumon) - np.interp(r["a"], tF, cumon))
            else:
                r["fuel_L"], r["eng_on_s"] = np.nan, np.nan
        out.extend(base)
    return pd.DataFrame(out), recon


def reconciliation_summary(recon):
    s = {"drives_with_arrays": int(len(recon))}
    for k in ("gross", "eng_off", "pure_regen"):
        vals = [r[k] for r in recon if r.get(k) is not None]
        s[k] = {"compared": int(len(vals)), "outside_tolerance": int(sum(1 for v in vals if not v)), "share_outside": float(sum(1 for v in vals if not v) / len(vals)) if vals else None}
    s["tolerances"] = {"gross_charge": {"relative": TOL_GROSS[0], "kwh": TOL_GROSS[1]}, "engine_off_and_pure_regen": {"relative": TOL_OFF_REGEN[0], "kwh": TOL_OFF_REGEN[1]}, "stop_if_share_outside_above": MAX_DRIVE_FAIL_SHARE}
    s["stop"] = bool(any((s[k]["share_outside"] or 0.0) > MAX_DRIVE_FAIL_SHARE for k in ("gross", "eng_off", "pure_regen")))
    return s


QUANTITIES = [
    # name, basis, numerator column (or a callable name), denominator, scale, label
    ("Q1a_charge_kwh_per_100km", "all", "q1a", "km", 100.0, "battery charge energy, kWh per 100 km (confirmatory contrast: downhill minus flat)"),
    ("Q1b_engine_off_charge_300rpm_kwh_per_100km", "all", "q1b", "km", 100.0, "engine-off (300 rpm proxy) charge energy, kWh per 100 km"),
    ("Q1b_engine_off_charge_400rpm_kwh_per_100km", "all", "q1b_400", "km", 100.0, "sensitivity: the master's engine-off threshold (400 rpm)"),
    ("Q4_net_battery_energy_kwh_per_100km", "all", "net", "km", 100.0, "net battery energy (charge minus discharge), kWh per 100 km"),
    ("Q4_soc_change_pp_per_100km", "all", "dsoc", "km", 100.0, "SOC change, percentage points per 100 km"),
    ("Q4_engine_on_share_of_charge_pct", "all", "q1a_on400", "q1a", 100.0, "share of the charge energy recorded with the engine on (above 400 rpm), percent"),
    ("Q3_positive_traction_kwh_per_100km", "fuel", "epos", "km", 100.0, "positive traction energy (reconstruction, model-derived), kWh per 100 km"),
    ("Q3_negative_traction_kwh_per_100km", "fuel", "eneg", "km", 100.0, "negative traction energy (reconstruction, model-derived), kWh per 100 km"),
    ("Q5_fuel_l_per_100km", "fuel", "fuel_L", "km", 100.0, "fuel (app-calculated), litres per 100 km"),
    ("Q5_engine_on_time_share_pct", "fuel", "eng_on_s", "T_s", 100.0, "engine-on time share, percent"),
]


def _prepare(df):
    df = df.copy()
    df["km"] = df["d_m"] / 1000.0
    for k in ("F", "N", "A", "G"):
        col = "dh" if k == "F" else "dh_" + k
        df["g" + k] = 100.0 * df[col] / df["d_m"]
    for k in ("N", "A", "G"):
        df["gp" + k] = 100.0 * df["dhpl_" + k] / df["d_m"]
    df["gpF"] = 100.0 * df["dh_pl"] / df["d_m"]
    df["net"] = df["q1a"] - df["disc"]
    df["epos"] = df["Epos_kJ"] / 3600.0
    df["eneg"] = -df["Eneg_kJ"] / 3600.0
    df["band"] = band3(df["vmean_kmh"])
    return df


def _quantity_stats(sub, spec, grade_col, cls_override, W_cache, nb, standardised=True):
    name, basis, num_col, den_col, scale, label = spec
    d = sub[np.isfinite(sub[num_col]) & np.isfinite(sub[den_col])] if num_col in sub and den_col in sub else sub.iloc[0:0]
    if len(d) < 50:
        return None
    cls = cls_override(d) if cls_override is not None else class3(d[grade_col].values)
    ud, di = X.day_index(d["day"].values)
    key = len(ud)
    if key not in W_cache:
        W_cache[key] = X.boot_weights(len(ud), nb)
    N, D = day_arrays(d[num_col].values, d[den_col].values, cls, d["band"].values, d["day"].values, di)
    raw_p, std_p, raw_b, std_b = class_means(N, D, W_cache[key])
    out = {"n_steps": int(len(d)), "n_days": int(len(ud)), "support": {CLASS_NAMES[c]: support(cls, d["day"].values, d["km"].values, c) for c in range(3)},
           "raw": contrast_block(raw_p, raw_b, scale), "speed_standardised": contrast_block(std_p, std_b, scale)}
    return out, d, cls


def analyse(df, nb, m762):
    df = _prepare(df)
    stages = {"all_steps_before_exclusions": int(len(df))}
    base = df[~df["first"] & ~df["last"] & (df["vmin_kmh"] >= dsg.V_MIN_KMH)]
    stages["after_first_last_speed"] = int(len(base))
    cs = base[np.isfinite(base["gF"]) & np.isfinite(base["gN"]) & np.isfinite(base["gA"])]
    stages["common_support_F_N_A_finite"] = int(len(cs))
    nasok = cs[np.isfinite(cs["dh_num"])]
    stages["after_nasadem_num_srtm_mask"] = int(len(nasok))
    gloOK = nasok[np.isfinite(nasok["dh_glo"])]
    stages["after_glo30_unflagged_mask"] = int(len(gloOK))
    prim = gloOK[gloOK["gF"].abs() <= dsg.GRADE_EXCL_PP]
    stages["after_fabdem_grade_8pp_exclusion"] = int(len(prim))
    if stages != m762["C1_step_stages"]:
        raise Stop("control R1: the step stages differ from the M762 result: %s" % stages)
    res = {"R1_step_stages_equal_M762": True, "C1_step_stages": stages}
    cl = class3(prim["gF"].values)
    fuelm = prim["fuel"].values.astype(bool)
    g0 = {"all_steps": {CLASS_NAMES[c]: support(cl, prim["day"].values, prim["km"].values, c) for c in range(3)},
          "fuel_basis": {CLASS_NAMES[c]: support(cl[fuelm], prim["day"].values[fuelm], prim["km"].values[fuelm], c) for c in range(3)}}
    # five-class counts, exploratory
    cl5 = np.digitize(prim["gF"].values, dsg.CLASS_EDGES)
    g0["five_class_steps_all"] = [int((cl5 == i).sum()) for i in range(5)]
    g0["five_class_steps_fuel_basis"] = [int(((cl5 == i) & fuelm).sum()) for i in range(5)]
    res["G0"] = g0
    # misclassification of the three-class label per source
    res["three_class_misclassification_vs_fabdem"] = {k: float(np.mean(class3(prim["gF"].values) != class3(prim["g" + k].values))) for k in ("N", "A", "G")}
    W_cache = {}
    results = {}
    escal = []
    for spec in QUANTITIES:
        name, basis = spec[0], spec[1]
        sub = prim[prim["fuel"]] if basis == "fuel" else prim
        r = _quantity_stats(sub, spec, "gF", None, W_cache, nb)
        if r is None:
            results[name] = {"status": "not estimable (too few steps)"}
            continue
        blk, d, cls = r
        blk["basis"] = basis
        blk["label"] = spec[5]
        # placebo (displaced DEM), sources and consensus
        pl = _quantity_stats(sub, spec, "gpF", None, W_cache, nb)
        blk["placebo_displaced_dem"] = pl[0]["raw"] if pl else None
        blk["by_source"] = {}
        for k in ("N", "A", "G"):
            sr = _quantity_stats(sub, spec, "g" + k, None, W_cache, nb)
            blk["by_source"][k] = sr[0]["raw"] if sr else None
        cons = sub[(class3(sub["gF"].values) == class3(sub["gN"].values)) & (class3(sub["gF"].values) == class3(sub["gA"].values))]
        cr = _quantity_stats(cons, spec, "gF", None, W_cache, nb)
        blk["consensus_class_selected_subset"] = {"n_steps": cr[0]["n_steps"], "raw": cr[0]["raw"]} if cr else None
        # reading per contrast (R3; Q2 is exempt, handled separately)
        blk["reading"] = {}
        for cn in ("downhill_minus_flat", "uphill_minus_flat"):
            prim_c = blk["raw"][cn]
            plc = blk["placebo_displaced_dem"][cn] if blk["placebo_displaced_dem"] else {"est": None, "ci95": [None, None]}
            same = bool(cr and cr[0]["raw"][cn]["est"] is not None and prim_c["est"] is not None and np.sign(cr[0]["raw"][cn]["est"]) == np.sign(prim_c["est"]))
            floors = all(blk["support"][c]["floors_met"] for c in ("flat", cn.split("_")[0]))
            word = reading(prim_c, plc, same)
            blk["reading"][cn] = word if floors else "not testable (below the support floors); counts only"
        # continuous slope with the placebo slope (per-km quantities only)
        if spec[3] == "km":
            y = d[spec[2]].values / d["km"].values * spec[4]
            ud, di = X.day_index(d["day"].values)
            W = W_cache.setdefault(len(ud), X.boot_weights(len(ud), nb))
            blk["slope_per_pp"] = slope_fit(y, d["km"].values, d["gF"].values, d["band"].values, d["cohort"].values, d["day"].values, W, nb)
            blk["placebo_slope_per_pp"] = slope_fit(y, d["km"].values, d["gpF"].values, d["band"].values, d["cohort"].values, d["day"].values, W, nb)
        results[name] = blk
        # R5 physical-sign escalations
        if name.startswith("Q1a") and blk["raw"]["uphill_minus_flat"]["est"] is not None and blk["raw"]["uphill_minus_flat"]["est"] > 0:
            escal.append("Q1a: more battery charge per km uphill than flat")
        if name.startswith("Q5_fuel") and blk["raw"]["downhill_minus_flat"]["est"] is not None and blk["raw"]["downhill_minus_flat"]["est"] > 0:
            escal.append("Q5: more fuel per km downhill than flat")
    res["quantities"] = results
    # Q2 exploratory: ratio of sums over the steps with at least 100 kJ released (assumed mass bracket)
    q2 = {}
    for mass in (MASS - 100.0, MASS, MASS + 100.0):
        kin = mass * (prim["ve"] ** 2 - prim["vs"] ** 2) / 2.0 / 1000.0
        A = np.maximum(0.0, -kin - mass * G * prim["dh"] / 1000.0)
        d = prim[(A >= A_MIN_KJ) & np.isfinite(prim["q1b"])].copy()
        d["a_kj"], d["q1b_kj"] = A[d.index], d["q1b"] * 3600.0
        spec = ("Q2", "all", "q1b_kj", "a_kj", 1.0, "exploratory")
        r = _quantity_stats(d, spec, "gF", None, W_cache, nb)
        q2[str(int(mass))] = None if r is None else {"n_steps": r[0]["n_steps"], "n_days": r[0]["n_days"], "support": r[0]["support"], "ratio_of_sums_by_class": r[0]["raw"]["means"]}
        if r is not None and any((v["est"] or 0) > 1 for v in r[0]["raw"]["means"].values()):
            escal.append("Q2 above 1 (mass %d kg)" % mass)
    res["Q2_exploratory_apparent_recovery_ratio_of_sums"] = {"label": "EXPLORATORY: step-based, kinetic plus potential, assumed mass bracket +-100 kg (NOT the M753 scenarios); never compared with regenDisplayV2; no R3 or R4 verdict", "by_mass_kg": q2, "release_threshold_kj": A_MIN_KJ}
    # R4 falsification (Q1a downhill minus flat)
    q1a = results.get("Q1a_charge_kwh_per_100km")
    if q1a and "raw" in q1a:
        c = q1a["raw"]["downhill_minus_flat"]
        flat = q1a["raw"]["means"]["flat"]["est"]
        lo, hi = c["ci95"]
        res["R4_confirmatory_Q1a_downhill_minus_flat"] = {"estimate": c["est"], "ci95": c["ci95"], "mdd": c["mdd"], "flat_mean": flat,
                                                           "falsified": bool(lo is not None and lo <= 0 <= hi and flat and c["mdd"] < 0.15 * abs(flat)), "reading": q1a["reading"]["downhill_minus_flat"]}
    res["R5_escalations_to_the_director"] = escal
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dem-dir", default=os.environ.get("XT_DEM_DIR") or "")
    ap.add_argument("--store", default=None)
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or "")
    ap.add_argument("--out-dir", default=os.path.join(HERE, "..", "analyses"))
    ap.add_argument("--master", default=os.path.join(HERE, "..", "drive_master.csv"))
    ap.add_argument("--seasonal", default=os.path.join(HERE, "..", "seasonal_drive_master.csv"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    ap.add_argument("--cache", default="")
    a = ap.parse_args(argv)
    for sub in ("fabdem", "nasadem", "aw3d30", "glo30"):
        if not a.dem_dir or not os.path.isdir(os.path.join(a.dem_dir, sub)):
            print("grade_energy_flows: DEM directories missing, skipped (optional)")
            return 0
    if not a.run:
        print(__doc__)
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    t_start = time.time()
    try:
        a.store = a.store or dsg.mi.default_store()
        if not os.path.exists(os.path.join(a.store, "manifest.json")) or not os.path.isdir(a.raw_dir):
            print("grade_energy_flows: no cloud store or raw directory, skipped (optional)")
            return 0
        X.verify_manifest(a.dem_dir, os.path.join(HERE, "..", "analyses", "M762_dem_manifest.json"))
        if dsg.mc.md5(a.master) != dsg.PINNED_MD5:
            print("grade_energy_flows: master pin failed")
            return 1
        m762_path = os.path.join(HERE, "..", "analyses", "M762_dem_crosscheck.json")
        m762 = json.load(open(m762_path, encoding="utf-8"))
        c0 = X.integrity_stage(a.dem_dir)
        sf, sn, sa, sg, numS, edm, flm, tmp = X.build_surfaces(a.dem_dir)
        try:
            dems = {"F": sf, "N": sn, "A": sa, "G": sg, "num": X.num_mask(numS),
                    "glo": X.glo_unflagged_mask(edm, flm, c0["glo30_masks"]["EDM"]["unflagged_code"], c0["glo30_masks"]["FLM"]["unflagged_code"])}
            if a.cache and os.path.exists(a.cache):
                import pickle
                df, recon = pickle.load(open(a.cache, "rb"))
            else:
                df, recon = collect_energy(a, dems)
                if a.cache:
                    import pickle
                    pickle.dump((df, recon), open(a.cache, "wb"))
        finally:
            import shutil
            getattr(sa.loader, "close", lambda: None)()
            shutil.rmtree(tmp, ignore_errors=True)
        rec = reconciliation_summary(recon)
        if rec["stop"]:
            raise Stop("control R1: more than %.0f %% of the drives lie outside the charge tolerances: %s" % (100 * MAX_DRIVE_FAIL_SHARE, rec))
        res = analyse(df, a.nb, m762)
        res.update({"milestone": "M768", "spec": "analyses/M768_spec.md Rev 3", "masterMd5": dsg.PINNED_MD5, "m762ResultSha256": X.sha256_file(m762_path), "m762ManifestSha256": X.sha256_file(os.path.join(HERE, "..", "analyses", "M762_dem_manifest.json")),
                    "toolSha256": X.sha256_file(os.path.abspath(__file__)), "seed": SEED, "nBoot": a.nb, "R1_per_drive_charge_reconciliation": rec,
                    "conventions": {"battery_current": "the raw BMS current is charge-positive (M11, M265); the discharge-positive current is its negative; charge energy = the negative part of the discharge-positive power integrated per interval with the master's zero-crossing-aware directional rule (M229); the master's gross charge is NOT offset-corrected (the M13/M24 offset is a net-draw correction), so the tool follows the master and the offset is a stated limit (about -0.4 A)",
                                    "engine_off": "primary classifier: engine speed at or below 300 rpm (missing speed counts as off, as in the master); the master's 400 rpm engine-off charge is the sensitivity and the C1 target",
                                    "speed_bands_kmh": {"urban_below": BAND_EDGES[0], "highway_from": BAND_EDGES[1]}, "classes_pp": {"downhill_below": CLASS_EDGES[0], "uphill_above": CLASS_EDGES[1]}},
                    "limits": ["grade is an estimate (inter-product error 0.36 pp; about 15 % of steps change the three-class label between products): between-class contrasts are attenuated toward zero",
                               "the displaced-DEM placebo is nonzero for every source in M757 and M762 (cause not identified): every placebo result is reported beside the primary",
                               "reconstruction quantities (Q3) are model-derived; fuel is app-calculated; none is measured",
                               "thermal cohort strata carry no thermal-contrast reading; no winter-frozen file is read or written"],
                    "deviations_from_spec": ["the master's gross charge is not offset-corrected, so the offset is not applied to Q1a (spec 7.9 said the tool applies i_off): the tool follows the master to reconcile per drive; stated as a limit",
                                             "the C1 engine-off reconciliation target is the master's charge_eng_off_kwh (400 rpm) and charge_pure_regen_kwh (400 rpm and torque below -15); the primary Q1b classifier is the 300 rpm proxy (spec 8.1), so the two differ by definition and the difference is reported",
                                             "the Q2 mass sensitivity is a global bracket of +-100 kg, not the per-drive M753 scenarios"],
                    "seconds": round(time.time() - t_start, 1)})
        bad = J.scan_privacy(res)
        if bad:
            raise Stop("privacy scan failed: %s" % bad[:3])
        if dsg.mc.md5(a.master) != dsg.PINNED_MD5:
            raise Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        with open(os.path.join(a.out_dir, "M768_grade_energy_flows.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, default=lambda o: None if o != o else str(o))
        q1 = res["quantities"].get("Q1a_charge_kwh_per_100km", {})
        print("grade_energy_flows: R1 ok | escalations %s | Q1a downhill-minus-flat %s" % (res["R5_escalations_to_the_director"], q1.get("reading", {}).get("downhill_minus_flat")))
        return 0
    except (Stop, X.Stop) as e:
        print("grade_energy_flows: STOP (%s)" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
