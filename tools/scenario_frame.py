#!/usr/bin/env python3
"""M713a (spec analyses/M712_spec.md Rev 1.1): per-drive exposure frame for the scenario model, built from the raw drive CSVs (read-only) under tools/ (fresh code, nothing imported from analyses/).

Stage 1  extract_drive(path) -> 1 Hz grid of one drive: I and V = mean in the clock second, other channels = last in the second; forward-fill limits I/V/speed/rpm/torque/accel 5 s, SoC 30 s,
         temperature and power-limit PIDs 120 s; native per-second current extremes Imax/Imin kept; sentinels masked (probe > 70 C, I outside +-900 A, ...). Raw BMS current is charge-positive.
Stage 2  drive_row(key, grid) -> one row of per-drive exposure statistics: Ah and kWh (charge / discharge, zero-order hold on the 1 Hz grid: the PROTOTYPE rule, about 4.4 % above the project's linear
         sign-aware rule; the project rule is the master column `gross_throughput_kwh` / the Ah sidecar and is carried beside it, spec Rev 1.1 C2), Ah / hours by pack-temperature bin (probe mean) and SoC bin,
         Arrhenius-weighted hours and Ah (Ea 40 / 50 / 60 kJ/mol), speed bins, engine starts, C-rate episodes, cold-charge Ah and Ah x C by coldest probe, hot-tail Ah (>= 35 / 40 / 45 C).
Stage 3  slices(grid) -> K = 16 equal-duration slices per drive (i2, ahc, ahd, soc, observed temperature, speed, engine share, charge Ah by C-rate bin) for the state model and the day-replay engine.
Capacity bases: 5 Ah rated (Article 10) and 2.1 kWh legacy, both verified:false. Pack temperature = mean of the available probes (>= 2).
Usage: python tools/scenario_frame.py [--out DIR] [--workers N]    writes <out>/exposure_drives.csv, exposure_slices.npz, exposure_frame_check.json (default out = analyses/M713/)"""
import argparse, hashlib, json, os, re, sys
from multiprocessing import Pool
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import raw_resolver as RR

CAP_AH_RATED, CAP_KWH_LEGACY = 5.0, 2.1                      # both verified:false
RGAS = 8.314462618
K = 16
CB = [0, 2, 5, 10, 15, 20, 30, np.inf]                       # charge C-rate bins on the 5 Ah basis
TBINS = [-np.inf, 0, 5, 10, 15, 20, 25, 30, 35, 40, 45, np.inf]
TLAB = ["<0", "0-5", "5-10", "10-15", "15-20", "20-25", "25-30", "30-35", "35-40", "40-45", ">=45"]
SOCBINS = [0, 45, 50, 55, 60, 65, 70, 75, 101]
SOCLAB = ["<45", "45-50", "50-55", "55-60", "60-65", "65-70", "70-75", ">=75"]
SPB = [0, 1, 20, 40, 60, 90, 120, 400]
SPL = ["stop", "1-20", "20-40", "40-60", "60-90", "90-120", "120+"]
C = {"I": "[BMS] HV Battery Current (A)", "V": "[BMS] HV Battery voltage (V)", "soc": "[BMS] HV State of charge (%)",
     "T1": "[BMS] HV Battery Temperature Sensor 1 (℃)", "T2": "[BMS] HV Battery Temperature Sensor 2 (℃)",
     "T3": "[BMS] HV Battery Temperature Sensor 3 (℃)", "T4": "[BMS] HV Battery Temperature Sensor 4 (℃)",
     "Tbin": "[BMS] HV Battery Intake Air Temperature (℃)",
     "Pin_hp": "[BMS] Input possible power (hp)", "Pin_kw": "[BMS] Input possible power (kW)",
     "Pout_hp": "[BMS] Output possible power (hp)", "Pout_kw": "[BMS] Output possible power (kW)",
     "Thvc": "[VCM] HV Coolant Temperature (℃)", "Tmot": "[VCM] Traction motor temperature (℃)",
     "vmax": "[BMS] Max Cell Voltage (V)", "vmin": "[BMS] Min Cell Voltage (V)",
     "spd_vcm": "[VCM] Vehicle Speed (km/h)", "spd_obd": "Швидкість автомобіля (km/h)",
     "tq": "[VCM] Motor Torque (N⋅m)", "tqt": "[VCM] Target Motor Torque (N⋅m)",
     "rpm": "Оберти двигуна (rpm)", "acc": "Прискорення (g)",
     "iat": "Температура повітря, що всмоктується (℃)",
     "Tcool": "Температура охолодної рідини (℃)",
     "alt": "Висота (GPS) (m)", "lat": "Latitude", "lon": "Longtitude"}
FAST = ["I", "V", "spd", "rpm", "tq", "tqt", "acc"]
MEAN = ["I", "V"]
COLS = ["I", "V", "soc", "T1", "T2", "T3", "T4", "Tbin", "Pin", "Pout", "Thvc", "Tmot", "vmax", "vmin", "spd", "tq", "tqt", "rpm", "acc", "iat", "Tcool", "alt", "lat", "lon"]


def key14(name):
    return re.sub(r"\D", "", os.path.basename(str(name)).rsplit(".", 1)[0])[:14]


def arrh(Tc, Ea_kj=50.0, Tref=25.0):
    """Arrhenius acceleration factor relative to Tref (dimensionless). ASSUMPTION: Ea 40-60 kJ/mol."""
    T = np.asarray(Tc, dtype=float) + 273.15
    return np.exp(Ea_kj * 1000.0 / RGAS * (1.0 / (Tref + 273.15) - 1.0 / T))


# ----------------------------------------------------------------------------------- stage 1 -----------------------------------------------------
def extract_drive(path):
    """1 Hz grid DataFrame of one raw drive (columns COLS + nI, Imax, Imin, sec, key), or raises."""
    hdr = pd.read_csv(path, nrows=0, encoding="utf-8").columns
    use = ["time"] + [v for v in C.values() if v in hdr]
    d = pd.read_csv(path, usecols=use, low_memory=False, encoding="utf-8")
    t = pd.to_datetime(d["time"], format="%H:%M:%S.%f", errors="coerce")
    ok = t.notna().values
    d = d[ok].copy()
    sec = (t[ok] - pd.Timestamp("1900-01-01")).dt.total_seconds().values
    sec = sec + np.concatenate([[0], np.cumsum(np.diff(sec) < -12 * 3600)]) * 86400.0
    inv = {v: k for k, v in C.items()}
    d = d.rename(columns=inv).drop(columns=["time"])
    for k in list(d.columns):
        d[k] = pd.to_numeric(d[k], errors="coerce")
    if "spd_vcm" in d and d["spd_vcm"].notna().sum() >= 20:
        d["spd"] = d["spd_vcm"]
    elif "spd_obd" in d:
        d["spd"] = d["spd_obd"]
    else:
        d["spd"] = np.nan
    if "Pin_hp" in d:
        d["Pin"] = d["Pin_hp"] * 0.7457
        d["Pout"] = d["Pout_hp"] * 0.7457 if "Pout_hp" in d else np.nan
    elif "Pin_kw" in d:
        d["Pin"] = d["Pin_kw"]
        d["Pout"] = d["Pout_kw"] if "Pout_kw" in d else np.nan

    def mask(c, lo, hi):
        if c in d:
            d.loc[(d[c] < lo) | (d[c] > hi), c] = np.nan
    mask("I", -900, 900); mask("V", 200, 450); mask("soc", 0, 100)
    for c in ["T1", "T2", "T3", "T4", "Tbin", "Thvc", "Tmot", "iat", "Tcool"]:
        mask(c, -40, 130)
    mask("spd", 0, 260); mask("rpm", 0, 9000); mask("vmax", 2, 5); mask("vmin", 2, 5)
    for c in COLS:
        if c not in d:
            d[c] = np.nan
    s0 = np.floor(sec).astype(np.int64)
    d["s"] = s0
    g = d.groupby("s")
    out = pd.DataFrame(index=np.arange(s0.min(), s0.max() + 1))
    out = out.join(g[MEAN].mean()).join(g[[c for c in COLS if c not in MEAN]].last())
    out["nI"] = g["I"].count().reindex(out.index).fillna(0)
    out["Imax"] = g["I"].max().reindex(out.index)
    out["Imin"] = g["I"].min().reindex(out.index)
    for c in COLS:
        out[c] = out[c].ffill(limit=5 if c in FAST else (30 if c == "soc" else 120))
    out = out.astype(np.float32)
    out["sec"] = out.index.values.astype(np.float64)
    out.insert(0, "key", key14(path))
    for c in ["T1", "T2", "T3", "T4"]:
        out[c] = out[c].where(out[c] <= 70)                  # the logger's 107 C sentinel
    tp = out[["T1", "T2", "T3", "T4"]]
    out["Tm"] = tp.mean(axis=1, skipna=True).where(tp.notna().sum(axis=1) >= 2)
    out["Tmin"], out["Tmax"] = tp.min(axis=1), tp.max(axis=1)
    return out.reset_index(drop=True)


def _read(path):
    try:
        return extract_drive(path), None
    except Exception as ex:
        return None, {"path": os.path.basename(path), "error": repr(ex)}


# ----------------------------------------------------------------------------------- stage 2 -----------------------------------------------------
def drive_row(key, d):
    """Per-drive exposure statistics of one 1 Hz grid (see module doc)."""
    d = d.reset_index(drop=True)
    n = len(d)
    I = d["I"].values.astype(float)
    V = d["V"].values.astype(float)
    okI = np.isfinite(I)
    Tm = d["Tm"].ffill().bfill(limit=180).values.astype(float)
    Tlo = d["Tmin"].ffill().bfill(limit=180).values.astype(float)
    T1 = d["T1"].ffill().bfill(limit=180).values.astype(float)
    soc = d["soc"].ffill().bfill(limit=60).values.astype(float)
    spd = d["spd"].values.astype(float)
    rpm = d["rpm"].values.astype(float)
    ch = np.where(okI, np.clip(I, 0, None), 0.0)
    di = np.where(okI, np.clip(-I, 0, None), 0.0)
    r = {"key": key, "n_s": n, "I_s": int(okI.sum()), "ah_chg": ch.sum() / 3600, "ah_dis": di.sum() / 3600}
    P = np.where(okI & np.isfinite(V), I * V / 1000.0, 0.0)
    r["kwh_chg"] = np.clip(P, 0, None).sum() / 3600
    r["kwh_dis"] = np.clip(-P, 0, None).sum() / 3600
    r["i2_a2h"] = np.where(okI, I * I, 0).sum() / 3600
    r["V_med"] = np.nanmedian(V) if np.isfinite(V).any() else np.nan
    tb = np.digitize(Tm, TBINS[1:-1]); tv = np.isfinite(Tm)
    for i, lab in enumerate(TLAB):
        mk = tv & (tb == i)
        r[f"h_T_{lab}"] = mk.sum() / 3600
        r[f"ahc_T_{lab}"] = ch[mk].sum() / 3600
        r[f"ahd_T_{lab}"] = di[mk].sum() / 3600
    r["ah_noT"] = (ch + di)[~tv].sum() / 3600
    sb = np.digitize(soc, SOCBINS[1:-1]); sv = np.isfinite(soc)
    for i, lab in enumerate(SOCLAB):
        mk = sv & (sb == i)
        r[f"h_S_{lab}"] = mk.sum() / 3600
        r[f"ah_S_{lab}"] = (ch + di)[mk].sum() / 3600
    for ea in (40, 50, 60):
        af = arrh(Tm, ea)
        r[f"afh_{ea}"] = np.nansum(af) / 3600
        r[f"afah_{ea}"] = np.nansum(af * (ch + di)) / 3600
    r["T_valid_h"] = tv.sum() / 3600
    fv = np.flatnonzero(np.isfinite(d["Tm"].values))
    if len(fv):
        r["T_start"] = d["Tm"].values[fv[0]]; r["T_start_lag_s"] = int(fv[0]); r["T_end"] = d["Tm"].values[fv[-1]]
        r["T_max"] = np.nanmax(Tm); r["T_mean"] = np.nanmean(Tm); r["T1_max"] = np.nanmax(T1)
        r["T1_start"] = T1[fv[0]]; r["Tlo_start"] = Tlo[fv[0]]; r["Tlo_min"] = np.nanmin(Tlo)
    if sv.any():
        fs = np.flatnonzero(sv)
        r["soc_start"], r["soc_end"], r["soc_mean"] = soc[fs[0]], soc[fs[-1]], np.nanmean(soc)
        r["soc_min"], r["soc_max"] = np.nanmin(soc), np.nanmax(soc)
    sp = np.where(np.isfinite(spd), spd, 0.0)
    r["km"] = sp.sum() / 3600
    r["spd_s"] = int(np.isfinite(spd).sum())
    r["moving_s"] = int((sp > 1).sum())
    spb = np.digitize(sp, SPB[1:-1])
    for i, lab in enumerate(SPL):
        mk = np.isfinite(spd) & (spb == i)
        r[f"s_v_{lab}"] = int(mk.sum()); r[f"km_v_{lab}"] = sp[mk].sum() / 3600
        r[f"ah_v_{lab}"] = (ch + di)[mk].sum() / 3600
    on = np.where(np.isfinite(rpm), rpm > 400, False)
    r["rpm_s"] = int(np.isfinite(rpm).sum()); r["eng_on_s"] = int(on.sum())
    st = np.flatnonzero(on[1:] & ~on[:-1]) + 1
    st = [s for s in st if on[s:s + 2].all()]
    r["eng_starts"] = len(st)
    r["charge_eng_on_ah"] = ch[on].sum() / 3600
    r["charge_eng_off_ah"] = ch[~on].sum() / 3600
    cmax = np.where(np.isfinite(d["Imax"].values), d["Imax"].values, np.where(okI, I, 0)) / CAP_AH_RATED
    dmax = -np.where(np.isfinite(d["Imin"].values), d["Imin"].values, np.where(okI, I, 0)) / CAP_AH_RATED
    r["peak_c_chg"] = float(np.nanmax(cmax)) if n else np.nan
    r["peak_c_dis"] = float(np.nanmax(dmax)) if n else np.nan
    for nm, arr in (("chg", cmax), ("dis", dmax)):
        for thr in (10, 15, 20, 30):
            m = arr > thr
            r[f"ep_{nm}_{thr}"] = int((m & ~np.r_[False, m[:-1]]).sum()); r[f"eps_{nm}_{thr}"] = int(m.sum())
    for thr in (15, 10, 5, 0):
        mk = np.isfinite(Tlo) & (Tlo < thr)
        r[f"ahc_lt{thr}"] = ch[mk].sum() / 3600
        r[f"ccs_lt{thr}"] = (ch[mk] * ch[mk] / CAP_AH_RATED).sum() / 3600            # Ah x C-rate
        r[f"h_lt{thr}"] = mk.sum() / 3600
    for thr in (35, 40, 45):
        mk = np.isfinite(Tm) & (Tm >= thr)
        r[f"ahc_ge{thr}"] = ch[mk].sum() / 3600; r[f"ah_ge{thr}"] = (ch + di)[mk].sum() / 3600; r[f"h_ge{thr}"] = mk.sum() / 3600
    # pulse-resistance proxy (M713b): slope of dV on dI between consecutive seconds with |dI| >= 20 A (reconstructed, not a DCIR measurement) -> R(T) activation energy of the heating model
    dI, dV, nI = np.diff(I), np.diff(V), d["nI"].values
    okp = np.isfinite(dI) & np.isfinite(dV) & (np.abs(dI) >= 20) & (nI[1:] > 0) & (nI[:-1] > 0)
    if okp.sum() >= 30:
        x, y = dI[okp], dV[okp]
        Tpf = d["Tm"].ffill().bfill().values[1:][okp]
        Spf = d["soc"].ffill().bfill().values[1:][okp]
        up = x > 0
        r["R_pulse_mohm"] = float(np.sum(x * y) / np.sum(x * x)) * 1000.0
        r["R_up_mohm"] = float(np.sum(x[up] * y[up]) / np.sum(x[up] ** 2)) * 1000 if up.sum() >= 15 else np.nan
        r["R_down_mohm"] = float(np.sum(x[~up] * y[~up]) / np.sum(x[~up] ** 2)) * 1000 if (~up).sum() >= 15 else np.nan
        r["pulse_n_pairs"] = int(okp.sum()); r["T_pulse"] = float(np.nanmean(Tpf)); r["soc_pulse"] = float(np.nanmean(Spf)); r["dI_med"] = float(np.median(np.abs(x)))
    # BMS charge-limit register ("input possible power", kW) vs coldest probe and SoC: per-drive normal-equation sufficient statistics of Pin ~ 1 + Tmin + (SoC - 60) over seconds with Tmin < 20 C
    pin, tmin, sc = d["Pin"].values.astype(float), d["Tmin"].values.astype(float), d["soc"].values.astype(float)
    mp = np.isfinite(pin) & np.isfinite(tmin) & (tmin < 20) & np.isfinite(sc)
    r["pin_n"] = int(mp.sum())
    if mp.any():
        X = np.column_stack([np.ones(mp.sum()), tmin[mp], sc[mp] - 60.0])
        XtX, Xty = X.T @ X, X.T @ pin[mp]
        for i in range(3):
            r["pin_xty_%d" % i] = float(Xty[i])
            for j in range(3):
                r["pin_xtx_%d%d" % (i, j)] = float(XtX[i, j])
    r["t0_s"], r["t1_s"] = float(d["sec"].iloc[0]), float(d["sec"].iloc[-1])
    return r


# ----------------------------------------------------------------------------------- stage 3 -----------------------------------------------------
def slices(d):
    """K equal-duration slices of one 1 Hz grid; dict of arrays (see module doc)."""
    m = len(d)
    I = d["I"].values.astype(float); ok = np.isfinite(I)
    ch = np.where(ok, np.clip(I, 0, None), 0.0); di = np.where(ok, np.clip(-I, 0, None), 0.0)
    Tm = d["Tm"].ffill().bfill(limit=180).values.astype(float)
    Tlo = d["Tmin"].ffill().bfill(limit=180).values.astype(float)
    soc = d["soc"].ffill().bfill(limit=60).values.astype(float)
    spd = d["spd"].values.astype(float); rpm = d["rpm"].values.astype(float)
    cmax = np.where(np.isfinite(d["Imax"].values), d["Imax"].values, ch) / CAP_AH_RATED
    dmax = -np.where(np.isfinite(d["Imin"].values), d["Imin"].values, -di) / CAP_AH_RATED
    sl = np.minimum((np.arange(m) * K) // m, K - 1)
    cb = np.digitize(ch / CAP_AH_RATED, CB[1:-1])
    A = {k: np.full(K, np.nan) for k in ["i2", "ahc", "ahd", "soc", "Tobs", "Tlo", "spd", "engon"]}
    A["ahc_cb"] = np.zeros((K, len(CB) - 1)); A["ahcC_cb"] = np.zeros((K, len(CB) - 1))
    for nm in ("ep10c", "ep20c", "ep10d", "ep20d"):
        A[nm] = np.zeros(K)
    A["icov"] = float(ok.mean())
    for k in range(K):
        mk = sl == k
        if not mk.any():
            continue
        A["i2"][k] = np.mean(np.where(ok[mk], I[mk] ** 2, np.nan)) if ok[mk].any() else np.nan
        A["ahc"][k] = ch[mk].sum() / 3600; A["ahd"][k] = di[mk].sum() / 3600
        with np.errstate(all="ignore"):
            for nm, arr in (("soc", soc), ("Tobs", Tm), ("Tlo", Tlo), ("spd", spd)):
                A[nm][k] = np.nanmean(arr[mk]) if np.isfinite(arr[mk]).any() else np.nan
            A["engon"][k] = np.nanmean(rpm[mk] > 400) if np.isfinite(rpm[mk]).any() else np.nan
        for b in range(len(CB) - 1):
            mb = mk & (cb == b) & (ch > 0)
            A["ahc_cb"][k, b] = ch[mb].sum() / 3600
            A["ahcC_cb"][k, b] = (ch[mb] ** 2).sum() / 3600 / CAP_AH_RATED
        for nm, arr, thr in (("ep10c", cmax, 10), ("ep20c", cmax, 20), ("ep10d", dmax, 10), ("ep20d", dmax, 20)):
            mm = arr > thr
            A[nm][k] = ((mm & ~np.r_[False, mm[:-1]]) & mk).sum()
    return A


CACHE_DIR = os.environ.get("XT_SCENARIO_CACHE_DIR") or os.path.join(ROOT, "scenario_cache")      # M720: git-ignored per-drive cache; an environment override reaches the pool workers
_EXTRACTOR_SRC = None


def extractor_hash():
    """SHA-256 of the extraction source (grid, per-drive row, slices) and its constants: any change invalidates every cache entry."""
    global _EXTRACTOR_SRC
    if _EXTRACTOR_SRC is None:
        import inspect
        parts = [inspect.getsource(f) for f in (extract_drive, _read, drive_row, slices, key14, arrh)]
        parts.append(repr((CAP_AH_RATED, CAP_KWH_LEGACY, K, CB, TBINS, SOCBINS, SPB, sorted(C.items()), FAST, MEAN, COLS)))
        _EXTRACTOR_SRC = hashlib.sha256(chr(10).join(parts).encode("utf-8")).hexdigest()
    return _EXTRACTOR_SRC


def _cache_path(path):
    return os.path.join(CACHE_DIR, key14(path) + ".pkl")


def _file_sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _all(path):
    """One drive: (row, slices, error). With the cache on (XT_SCENARIO_CACHE != 0) an entry is reused only if the raw-file SHA-256 and the extractor hash both match; a miss computes and stores it."""
    use = os.environ.get("XT_SCENARIO_CACHE", "1") != "0"
    if use:
        import pickle
        cp, fs, eh = _cache_path(path), _file_sha(path), extractor_hash()
        if os.path.exists(cp):
            try:
                e = pickle.load(open(cp, "rb"))
                if e.get("sha256") == fs and e.get("extractor") == eh:
                    return e["row"], e["slices"], None
            except Exception:
                pass
    g, err = _read(path)
    if g is None:
        return None, None, err
    key = key14(path)
    row, sl = drive_row(key, g), slices(g)
    if use:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = cp + ".tmp%d" % os.getpid()
        pickle.dump({"sha256": fs, "extractor": eh, "row": row, "slices": sl}, open(tmp, "wb"))
        os.replace(tmp, cp)
    return row, sl, None


def build(raw_dir, workers=1):
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file"], low_memory=False)
    keys = [key14(f) for f in dm["file"]]
    res = RR.resolve(raw_dir, os.path.join(ROOT, "raw_manifest.json"))
    paths = [res.index[k] for k in keys if k in res.index]
    if workers > 1:
        with Pool(workers) as p:
            out = p.map(_all, paths, chunksize=4)
    else:
        out = [_all(p) for p in paths]
    errs = [o[2] for o in out if o[2]]
    if errs:
        raise RuntimeError("unreadable drives: %s" % errs[:5])
    rows = [o[0] for o in out]
    sls = [o[1] for o in out]
    D = pd.DataFrame(rows)
    D["day"] = D["key"].map(lambda k: "%s-%s-%s" % (k[:4], k[4:6], k[6:8]))
    D["start"] = pd.to_datetime(D["day"]) + pd.to_timedelta(D["t0_s"], unit="s")
    D["end"] = pd.to_datetime(D["day"]) + pd.to_timedelta(D["t1_s"], unit="s")
    order = D.sort_values("start").index.values
    D = D.loc[order].reset_index(drop=True)
    sls = [sls[i] for i in order]
    D["dur_h"] = (D["t1_s"] - D["t0_s"]) / 3600
    D["gap_before_h"] = (D["start"] - D["end"].shift(1)).dt.total_seconds() / 3600
    D["month"] = D["start"].dt.month
    D["hour"] = D["start"].dt.hour + D["start"].dt.minute / 60
    D["ah"] = D["ah_chg"] + D["ah_dis"]
    D["kwh"] = D["kwh_chg"] + D["kwh_dis"]
    D["gtc_5ah"] = D["ah"] / CAP_AH_RATED
    D["gtc_2p1"] = D["kwh"] / CAP_KWH_LEGACY
    Z = {k: np.stack([s[k] for s in sls]) for k in sls[0] if k not in ("icov",)}
    Z["icov"] = np.array([s["icov"] for s in sls])
    return D, Z


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M713"))
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    D, Z = build(a.raw_dir, a.workers)
    D.to_csv(os.path.join(a.out, "exposure_drives.csv"), index=False)
    np.savez_compressed(os.path.join(a.out, "exposure_slices.npz"), keys=D["key"].values.astype(str), K=K, CB=np.array(CB), **Z)
    m = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    m["key"] = m["file"].map(key14)
    J = D.merge(m[["key", "distance_km", "gross_throughput_kwh"]], on="key", how="left")
    v = J[J["I_s"] > 0]
    rel = (v["kwh"] - v["gross_throughput_kwh"]) / v["gross_throughput_kwh"]
    chk = {"nDrives": int(len(D)), "nDays": int(D["day"].nunique()), "ahTotal_zohGrid": round(float(D["ah"].sum()), 2), "kwhTotal_zohGrid": round(float(D["kwh"].sum()), 2),
           "kmTotal_speedIntegral": round(float(D["km"].sum()), 2), "kmTotal_master": round(float(m["distance_km"].sum()), 2),
           "kwhPerDrive_vs_masterProjectRule_medianRelDiff": round(float(rel.median()), 4), "kwhPerDrive_vs_masterProjectRule_p95AbsRelDiff": round(float(rel.abs().quantile(0.95)), 4),
           "sliceAhConservation_maxAbsDiff": float(np.nanmax(np.abs((np.nansum(Z["ahc"], 1) + np.nansum(Z["ahd"], 1)) - D["ah"].values))),
           "sliceChargeBinConservation_maxAbsDiff": float(np.nanmax(np.abs(Z["ahc_cb"].sum((1, 2)) - np.nansum(Z["ahc"], 1)))),
           "scriptSha256": hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest(), "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(),
           "rule": "zero-order-hold 1 Hz grid (prototype rule), about 4.4 % above the project linear sign-aware rule; the project rule is gross_throughput_kwh of the master (spec M712 Rev 1.1 C2)"}
    json.dump(chk, open(os.path.join(a.out, "exposure_frame_check.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps(chk, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
