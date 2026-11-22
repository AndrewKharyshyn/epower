#!/usr/bin/env python3
"""M731 (analyses/M731_spec.md Rev 2, section 2): extractor of the observed quantity of the M717 winter prediction P6 (peak charge C-rate below 0 C versus the BMS charge-limit map).
Two pure parts. (1) `p6_row(grid)`: per drive, on the production 1 Hz grid of the VENDORED `scenario_frame.extract_drive` (analyses/M731_frozen_engine/root/tools, git blobs of the M717 commit), over the CHARGE seconds (native per-second Imax > 0)
with the coldest probe `Tlo` below 0 C and a finite SoC: the maximum over those seconds of (Imax / 5 Ah minus the limit-map C-rate at that second's Tlo and SoC), and at the attaining second the peak C-rate, Tlo, SoC and limit. The limit map is the frozen one
(b0 33.9221 kW at 0 C and SoC 60, bT 1.5529 kW per C, bS -1.0097 kW per SoC point; extrapolated below the observed range; kW x 1000 / 360 V / 5 Ah, rated basis, verified:false).
(2) `extract_p6(df, tol)`: the cell, the literal-rule count, the maximum margin, the stated-deviation share with a zero-event-safe upper bound, the by-Tlo-region split and the reading. BMS-reported register, not delivered power; logged current, never measured.
`build_sidecar` writes analyses/M731/p6_events.csv (additive, never touches the exposure frame). Usage: python tools/winter_p6.py [--build [--raw-dir DIR]]"""
import importlib.util, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
VENDOR_TOOLS = os.path.join(ROOT, "analyses", "M731_frozen_engine", "root", "tools")
SEED, NB = 42, 4000
VERSION = 1
CAP_AH = 5.0
V_NOM = 360.0
B0, BT, BS = 33.9221, 1.5529, -1.0097                       # frozen limit map (M717 params.limitMap)
SUPPORT_DRIVES, SUPPORT_DAYS = 10, 5
COLUMNS = {"P6": ["day", "p6_n_s", "p6_margin_c", "p6_peak_c", "p6_Tlo", "p6_soc", "p6_limit_c"]}
SIDECAR = os.path.join(ROOT, "analyses", "M731", "p6_events.csv")


def vendored_frame_module():
    """The vendored scenario_frame (unique module name; its own ROOT is the vendored mini-root, so nothing live is read)."""
    if "m731_scenario_frame" in sys.modules:
        return sys.modules["m731_scenario_frame"]
    sys.path.insert(0, VENDOR_TOOLS)
    try:
        spec = importlib.util.spec_from_file_location("m731_scenario_frame", os.path.join(VENDOR_TOOLS, "scenario_frame.py"))
        m = importlib.util.module_from_spec(spec)
        sys.modules["m731_scenario_frame"] = m
        spec.loader.exec_module(m)
    finally:
        sys.path.remove(VENDOR_TOOLS)
    return m


def limit_c(tlo, soc):
    """Limit-map C-rate (frozen map, not clipped) at the given probe temperature and SoC."""
    return (B0 + BT * np.asarray(tlo, float) + BS * (np.asarray(soc, float) - 60.0)) * 1000.0 / V_NOM / CAP_AH


def cmax_series(d):
    """Per-second charge C-rate as in the exposure frame: native Imax where finite, else the mean current, 0 where neither."""
    I = d["I"].values.astype(float)
    okI = np.isfinite(I)
    return np.where(np.isfinite(d["Imax"].values), d["Imax"].values, np.where(okI, I, 0)) / CAP_AH


def p6_row(d, tlo_lt=0.0):
    """Per-drive P6 statistics on a 1 Hz grid DataFrame (columns I, Imax, Tmin, soc). `tlo_lt` is the probe-temperature ceiling of the cell (0.0 for P6; 10.0 only for the descriptive reference of C-P6c)."""
    d = d.reset_index(drop=True)
    cm = cmax_series(d)
    Tlo = d["Tmin"].ffill().bfill(limit=180).values.astype(float)
    soc = d["soc"].ffill().bfill(limit=60).values.astype(float)
    r = {"p6_all_peak_c": float(np.nanmax(cm)) if len(d) else np.nan}
    lo = -np.inf if tlo_lt == 0.0 else 0.0
    m = np.isfinite(Tlo) & np.isfinite(soc) & (Tlo < tlo_lt) & (Tlo >= lo) & (cm > 0)
    r["p6_n_s"] = int(m.sum())
    if m.sum() == 0:
        r.update(p6_margin_c=np.nan, p6_peak_c=np.nan, p6_Tlo=np.nan, p6_soc=np.nan, p6_limit_c=np.nan)          # every column is always present
        return r
    marg = np.where(m, cm - limit_c(np.where(m, Tlo, 0.0), np.where(m, soc, 60.0)), -np.inf)
    i = int(np.argmax(marg))
    r.update(p6_margin_c=float(marg[i]), p6_peak_c=float(cm[i]), p6_Tlo=float(Tlo[i]), p6_soc=float(soc[i]), p6_limit_c=float(limit_c(Tlo[i], soc[i])))
    return r


def _cp_upper(k, n, conf=0.975):
    from scipy.stats import beta
    return 1.0 if k >= n else float(beta.ppf(conf, k + 1, n - k))


def extract_p6(df, tol, nb=NB, seed=SEED):
    """Spec 2.2 / 2.3 on a scoring frame with the columns of COLUMNS['P6']. `tol` is the frozen tolerance of C-P6c. Returns a dict."""
    d = df[df["p6_n_s"] > 0].copy()
    nd, ndays = len(d), int(d["day"].nunique()) if len(d) else 0
    out = {"nDrives": nd, "nDays": ndays, "tolC": tol, "kind": "BMS-reported register (input possible power) extrapolated linearly; logged current; not delivered power; rated 5 Ah verified:false"}
    if nd < SUPPORT_DRIVES or ndays < SUPPORT_DAYS:
        out.update(status="not evaluable", reason="cell below support (%d drives on %d days; needs %d on %d)" % (nd, ndays, SUPPORT_DRIVES, SUPPORT_DAYS))
        return out
    exc = d["p6_margin_c"].values > tol
    k = int(exc.sum())
    days = sorted(d["day"].unique())
    exc_days = int(d.loc[exc, "day"].nunique()) if k else 0
    g = d.assign(_e=exc.astype(float), _n=1.0).groupby("day")[["_e", "_n"]].sum().loc[days]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(days), size=(nb, len(days)))
    se, sn = g["_e"].values[idx].sum(axis=1), g["_n"].values[idx].sum(axis=1)
    share_b = se / sn
    boot_hi = float(np.percentile(share_b, 97.5))
    cp_hi = _cp_upper(k, nd)
    out.update(status="fitted", exceedCount=k, exceedDays=exc_days, maxMarginC=float(d["p6_margin_c"].max()), medianMarginC=float(d["p6_margin_c"].median()),
               share=k / nd, shareUpperBootstrap=boot_hi, shareUpperClopperPearson=cp_hi, shareUpperSafe=max(boot_hi, cp_hi),
               byTloRegion={"below -5 C": int((d["p6_Tlo"] < -5).sum()), "-5..0 C": int(((d["p6_Tlo"] >= -5) & (d["p6_Tlo"] < 0)).sum())},
               reading=("within the map" if k == 0 else ("outside the map" if exc_days >= 2 else "inconclusive (exceedance on a single day)")))
    return out


def build_sidecar(raw_dir, keys=None, out=None, tlo_lt=0.0):
    """Per-drive sidecar over the raw drives of `keys` (default: the keys of analyses/M713/exposure_drives.csv)."""
    SF = vendored_frame_module()
    fr = pd.read_csv(os.path.join(ROOT, "analyses", "M713", "exposure_drives.csv"), dtype={"key": str}, usecols=["key", "day", "peak_c_chg"], low_memory=False)
    if keys is not None:
        fr = fr[fr["key"].isin(keys)]
    import raw_resolver as RR  # noqa: F401  (vendored copy is on the module path only inside vendored_frame_module; the live resolver is used for paths)
    res = RR.resolve(raw_dir, os.path.join(ROOT, "raw_manifest.json"))
    rows = []
    for _, r in fr.iterrows():
        path = res.index.get(r["key"])
        if path is None:
            rows.append({"key": r["key"], "day": r["day"], "error": "raw file not found"})
            continue
        grid = SF.extract_drive(path)
        row = p6_row(grid, tlo_lt)
        row.update(key=r["key"], day=r["day"], frame_peak_c_chg=r["peak_c_chg"])
        rows.append(row)
    df = pd.DataFrame(rows)
    if out:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        df.to_csv(out, index=False, lineterminator="\n")
    return df


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--build" in a:
        rd = a[a.index("--raw-dir") + 1] if "--raw-dir" in a else os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
        df = build_sidecar(rd, out=SIDECAR)
        print(len(df), "drives;", int((df.get("p6_n_s", pd.Series(dtype=float)) > 0).sum()), "with sub-zero charge seconds")
