#!/usr/bin/env python3
"""M307 F3 (spec Amendment 1, item 5): which property of today's raw copies separates the drives whose cell spread differs between the
published master (P) and a fresh rebuild (A)? Diagnostic only; cannot identify the true original.
Usage: python tools/f03_f3_inspect.py PUBLISHED_MASTER.csv MASTER_A.csv OUT.json   (XT_RAW_DIR = raw dir)
D = drives with |P-A| > 1e-9 in cell_spread_loaded_p95_mv; C = hash-failing drives with identical spread matched by calendar month
(seed 42, without replacement, up to 1:1 per month); hash-verified drives (H) are reported separately, never pooled into C.
12 pre-listed features; AUC per feature vs a permutation null of the MAX AUC (1000 permutations, seed 42). Wording of any explanation:
'candidate mechanism (hypothesis)'."""
import hashlib, io, json, os, re, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
import compute_drive_summary_v6 as v6

Y = "cell_spread_loaded_p95_mv"
FEATS = ["f01_max_decimals", "f02_distinct_cellV", "f03_quant_step_V", "f04_nan_frac_cellV", "f05_dup_timestamps",
         "f06_nonmonotonic_time", "f07_rows_minus_manifest", "f08_spike_count_z6", "f09_p95_loaded_pipeline",
         "f10_p95_loaded_median3", "f11_zero_spread_frac", "f12_bytes_per_row"]
I_COL = "[BMS] HV Battery Current (A)"


def decimals(s):
    s = s.dropna().astype(str)
    if s.empty:
        return 0
    return int(s.str.extract(r"\.(\d+)")[0].dropna().str.len().max() or 0)


def spread_p95(t, vmax, vmin, cur, med3=False):
    if med3:
        vmax = vmax.rolling(3, center=True, min_periods=1).median()
        vmin = vmin.rolling(3, center=True, min_periods=1).median()
    a = pd.DataFrame({"t": t, "v": vmax}).dropna().sort_values("t")
    b = pd.DataFrame({"t": t, "v": vmin}).dropna().sort_values("t")
    if a.empty or b.empty:
        return np.nan, np.nan, np.nan
    p = pd.merge_asof(a.rename(columns={"v": "vmax"}), b.rename(columns={"v": "vmin"}), on="t", direction="nearest",
                      tolerance=pd.Timedelta(v6.SPREAD_TOL)).dropna().reset_index(drop=True)
    if p.empty:
        return np.nan, np.nan, np.nan
    p["spread_mv"] = (p["vmax"] - p["vmin"]) * 1000.0
    I = pd.DataFrame({"t": t, "I": cur}).dropna().sort_values("t")
    p2 = v6._asof(p, I, "I", v6.V_ALIGN_TOL)
    loaded = p2.loc[p2["I"].abs() > 50, "spread_mv"]
    zero = float((p["spread_mv"] == 0).mean())
    z = (p["spread_mv"] - p["spread_mv"].mean()) / (p["spread_mv"].std() or 1.0)
    return (float(loaded.quantile(0.95)) if len(loaded) else np.nan), zero, int((z.abs() > 6).sum())


def features(path, man_rows):
    raw = open(path, "rb").read()
    txt = raw.decode("utf-8", "replace")
    hdr = pd.read_csv(io.StringIO(txt), nrows=0).columns
    cv_cols = [c for c in hdr if "Cell Voltage" in c]
    icols = [c for c in hdr if "HV Battery Current" in c and "High" not in c]     # naming varies across exports
    icol = icols[0] if icols else None
    use = ["time"] + ([icol] if icol else []) + cv_cols
    s = pd.read_csv(io.StringIO(txt), usecols=[c for c in use if c in hdr], dtype=str)
    d = pd.read_csv(io.StringIO(txt), usecols=[c for c in use if c in hdr], low_memory=False)
    t = pd.to_datetime(d["time"], errors="coerce")
    cvs = [pd.to_numeric(d[c], errors="coerce") for c in cv_cols]
    vmax = pd.to_numeric(d[[c for c in cv_cols if "Max" in c][0]], errors="coerce")
    vmin = pd.to_numeric(d[[c for c in cv_cols if "Min" in c][0]], errors="coerce")
    cur = pd.to_numeric(d[icol], errors="coerce") if icol else pd.Series(np.nan, index=d.index)
    allv = pd.concat(cvs).dropna()
    dist = np.sort(allv.unique())
    step = float(np.diff(dist).min()) if len(dist) > 1 else np.nan
    p95, zero, spikes = spread_p95(t, vmax, vmin, cur)
    p95m, _, _ = spread_p95(t, vmax, vmin, cur, med3=True)
    tt = t.dropna()
    return {
        "f01_max_decimals": max(decimals(s[c]) for c in cv_cols),
        "f02_distinct_cellV": int(len(dist)),
        "f03_quant_step_V": step,
        "f04_nan_frac_cellV": float(np.mean([x.isna().mean() for x in cvs])),
        "f05_dup_timestamps": int(tt.duplicated().sum()),
        "f06_nonmonotonic_time": int((tt.diff().dt.total_seconds() < 0).sum()),
        "f07_rows_minus_manifest": int(len(d) - man_rows) if man_rows is not None else np.nan,
        "f08_spike_count_z6": spikes,
        "f09_p95_loaded_pipeline": p95,
        "f10_p95_loaded_median3": p95m,
        "f11_zero_spread_frac": zero,
        "f12_bytes_per_row": len(raw) / max(len(d), 1)}


def auc(x, y):
    """AUC of feature x for label y (1 = D), ties = 0.5; NaN dropped; returns max(auc, 1-auc) (direction-free)."""
    x = np.asarray(x, float); y = np.asarray(y, int); m = ~np.isnan(x); x, y = x[m], y[m]
    pos, neg = x[y == 1], x[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    gt = (pos[:, None] > neg[None, :]).mean(); eq = (pos[:, None] == neg[None, :]).mean()
    a = gt + 0.5 * eq
    return float(max(a, 1 - a))


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    P = pd.read_csv(a[0], low_memory=False); A = pd.read_csv(a[1], low_memory=False)
    raw_dir = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
    man = {re.sub(r"\D", "", r["raw_name"].rsplit(".", 1)[0]): r for r in json.load(open(os.path.join(ROOT, "raw_manifest.json")))["files"]
           if r["raw_name"] and r["role"] == "canonical"}
    idx = {re.sub(r"\D", "", f.rsplit(".", 1)[0]): f for f in os.listdir(raw_dir) if f.lower().endswith(".csv")}
    key = lambda f: re.sub(r"\D", "", f.rsplit(".", 1)[0])
    P["hash_ok"] = [hashlib.sha256(open(os.path.join(raw_dir, idx[key(f)]), "rb").read()).hexdigest() == man[key(f)]["sha256"] for f in P["file"]]
    P["month"] = P["date"].astype(str).str[:7]
    diff = ((P[Y].astype(float) - A[Y].astype(float)).abs() > 1e-9) | (P[Y].isna() != A[Y].isna())
    P["D"] = diff.values
    rng = np.random.default_rng(42)
    D = P[P["D"]]
    pool = P[(~P["D"]) & (~P["hash_ok"]) & P[Y].notna()]      # drives without cell-voltage channels (7 early files) have no spread: not comparable
    C_idx = []
    for mo, g in D.groupby("month"):
        cand = pool[pool["month"] == mo].index.to_numpy()
        n = min(len(g), len(cand))
        if n:
            C_idx += list(rng.choice(cand, n, replace=False))
    C = P.loc[C_idx]
    H = P[P["hash_ok"] & P[Y].notna()]
    rows = []
    for grp, df in (("D", D), ("C", C), ("H", H)):
        for _, r in df.iterrows():
            f = features(os.path.join(raw_dir, idx[key(r["file"])]), man[key(r["file"])]["rows"])
            rows.append({"group": grp, "file": r["file"], "month": r["month"], **f})
    F = pd.DataFrame(rows)
    DC = F[F["group"].isin(["D", "C"])].reset_index(drop=True)
    y = (DC["group"] == "D").astype(int).values
    aucs = {f: auc(DC[f].values, y) for f in FEATS}
    obs_max = max(v for v in aucs.values() if not np.isnan(v))
    null = []
    for _ in range(1000):
        yp = rng.permutation(y)
        null.append(max(v for v in (auc(DC[f].values, yp) for f in FEATS) if not np.isnan(v)))
    p_perm = float((np.array(null) >= obs_max).mean())
    best = max(aucs, key=lambda k: -1 if np.isnan(aucs[k]) else aucs[k])
    summ = {g: {f: (None if F[F.group == g][f].dropna().empty else round(float(F[F.group == g][f].median()), 6)) for f in FEATS} for g in ("D", "C", "H")}
    out = {"nD": int(len(D)), "nC": int(len(C)), "nH": int(len(H)), "features": FEATS, "aucPerFeature": aucs, "bestFeature": best,
           "bestAUC": obs_max, "permutationNullMaxAUC": {"n": 1000, "seed": 42, "p": p_perm, "null95": float(np.quantile(null, 0.95))},
           "explains": bool(obs_max >= 0.9 and p_perm < 0.05), "medianByGroup": summ,
           "matching": "C = hash-failing identical-spread drives, matched by calendar month (seed 42); H = hash-verified reported separately",
           "wording": "any mechanism is a 'candidate mechanism (hypothesis)'; originals unavailable"}
    F.to_csv(os.path.join(os.path.dirname(a[2]) or ".", "f3_features.csv"), index=False)
    json.dump(out, open(a[2], "w"), indent=1)
    print(json.dumps({k: out[k] for k in ("nD", "nC", "nH", "bestFeature", "bestAUC", "permutationNullMaxAUC", "explains")}, indent=1))
    print({f: (None if np.isnan(v) else round(v, 3)) for f, v in aucs.items()})


if __name__ == "__main__":
    main()
