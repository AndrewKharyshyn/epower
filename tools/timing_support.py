#!/usr/bin/env python3
"""M479 (analyses/M479_spec.md, external cell-spread / cadence recheck 2026-10-22; Director: sidecar, diagnostics and flags only): per-drive, per-PID logged-timestamp
timing, max/min cell pair offset and loaded-support descriptors. The PID series, value bands, current artifact filter and the max/min and loaded pairing replicate
compute_drive_summary_v6.py (same helpers _prep_bytes / _series / _asof, SPREAD_TOL, V_ALIGN_TOL), so n_loaded equals the master n_loaded_spread_samples. Nothing here is
an estimate, a filter or a quality verdict: offsets and gaps are logged timestamp differences between reported values (not acquisition latency), flags are report-only
descriptors with exploratory thresholds fixed in the spec, and negative max/min pairs are counted, never clamped or removed.
Sidecar timing_support.csv + timing_support_summary.json are written ONLY by this tool; drive_master.csv is read-only. Incremental by content: a drive is recomputed only when its
raw sha256 (raw_manifest.json, else hashed bytes) or METHOD_VERSION changed. Values are unrounded in memory; the sidecar rounds at export only (6 decimals).
Usage: python tools/timing_support.py [--rebuild] [--check]    (--check is read-only and needs no raw files)"""
import hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)          # compute_drive_summary_v6 lives at the repo root
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
SIDECAR = os.path.join(ROOT, "timing_support.csv")
SUMMARY = os.path.join(ROOT, "timing_support_summary.json")
METHOD_VERSION = 1
FAST_SLOW_S = 1.05                    # tools/cadence_regime.py THRESHOLD_S (declared midpoint of the empty gap)
WIN_S, WIN_MIN_INTERVALS = 60.0, 5    # regime-stability windows (spec item 3)
EPISODE_BREAK_S = 10.0                # descriptive grouping of loaded pairs into episodes (spec item 5)
LOADED_A = 50.0                       # production loaded threshold |I| > 50 A
FLAG_SKEW_MS, FLAG_LT20, FLAG_LT30, FLAG_EPISODES = 50.0, 20, 30, 3
# (prefix, internal column name, value band) in the order of the sidecar columns
PIDS = [("i", "I", (None, None)), ("v", "V", (200, 450)), ("soc", "soc", (None, None)), ("vmax", "Vcell_max", (2.0, 5.0)),
        ("vmin", "Vcell_min", (2.0, 5.0)), ("t1", "T1", (-40, 90)), ("spd", "speed", (0, 260))]
PID_FIELDS = ["n", "row_cov", "rate_hz", "dt_q05", "dt_q50", "dt_q95", "dt_iqr_ratio", "frac_dt_gt3s", "n_dup", "n_gap20", "gap20_s", "max_gap_s"]
WIN_FIELDS = ["n_win", "win_dt_min", "win_dt_max", "regime_cross"]
PAIR_FIELDS = ["n_pairs", "off_med_ms", "off_p05_ms", "off_p95_ms", "off_abs_p95_ms", "frac_off_gt50ms", "n_neg", "frac_neg"]
LOAD_FIELDS = ["n_loaded", "n_loaded_dis", "n_loaded_chg", "n_episodes", "episode_max_share", "cur_age_p50_ms", "cur_age_p95_ms", "i_abs_med", "i_abs_p95",
               "soc_med", "n_neg_loaded", "frac_neg_loaded"]
FLAGS = ["flag_support_lt20", "flag_support_lt30", "flag_one_episode", "flag_skew_gt50ms", "flag_neg_loaded", "flag_regime_cross_i", "flag_regime_cross_vmax", "flag_gap20_i"]
COLS = (["file", "date", "raw_sha256", "method_version", "reason"]
        + [f"{p}_{f}" for p, _, _ in PIDS for f in PID_FIELDS]
        + [f"i_{f}" for f in WIN_FIELDS] + [f"vmax_{f}" for f in WIN_FIELDS]
        + PAIR_FIELDS + LOAD_FIELDS + FLAGS)
NUM = [c for c in COLS if c not in ("file", "date", "raw_sha256", "method_version", "reason") and c not in FLAGS and not c.endswith("regime_cross")]
BOOL = FLAGS + ["i_regime_cross", "vmax_regime_cross"]


def _intervals(s):
    """Seconds between consecutive samples of a (t, v) frame (sorted), all of them (no truncation)."""
    return np.diff(s["t"].to_numpy(dtype="datetime64[ns]")).astype("timedelta64[ns]").astype(np.int64) / 1e9


def _pid_block(prefix, s, df, col):
    """Timing descriptors of one PID series s (the production-cleaned (t, v) frame, or None)."""
    out = {f"{prefix}_{f}": None for f in PID_FIELDS}
    out[f"{prefix}_row_cov"] = float(df[col].notna().mean()) if col in df.columns and len(df) else None
    if s is None:
        out[f"{prefix}_n"] = 0
        return out
    out[f"{prefix}_n"] = int(len(s))
    if len(s) < 2:
        return out
    dt = _intervals(s)
    pos = dt[dt > 0]
    out[f"{prefix}_n_dup"] = int((dt == 0).sum())
    span = float(dt.sum())
    out[f"{prefix}_rate_hz"] = float(len(np.unique(s["t"].to_numpy())) / span) if span > 0 else None
    out[f"{prefix}_n_gap20"] = int((dt >= 20).sum())
    out[f"{prefix}_gap20_s"] = float(dt[dt >= 20].sum())
    out[f"{prefix}_max_gap_s"] = float(dt.max())
    if len(pos):
        q05, q25, q50, q75, q95 = np.quantile(pos, [0.05, 0.25, 0.5, 0.75, 0.95])
        out.update({f"{prefix}_dt_q05": float(q05), f"{prefix}_dt_q50": float(q50), f"{prefix}_dt_q95": float(q95),
                    f"{prefix}_dt_iqr_ratio": float((q75 - q25) / q50) if q50 > 0 else None, f"{prefix}_frac_dt_gt3s": float((pos > 3).mean())})
    return out


def _win_block(prefix, s):
    """Regime stability: median interval in fixed 60 s windows of PID time; regime_cross = window medians on both sides of the declared fast/slow gap."""
    out = {f"{prefix}_{f}": None for f in WIN_FIELDS}
    if s is None or len(s) < 2:
        return out
    ns = s["t"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    dt = np.diff(ns) / 1e9                       # differences taken in integer nanoseconds (absolute clock seconds would lose ~1e-7 s in float64)
    keep = dt > 0
    w = np.floor((ns[1:] - ns[0]) / 1e9 / WIN_S).astype(int)[keep]
    dtp = dt[keep]
    meds = [float(np.median(dtp[w == k])) for k in np.unique(w) if (w == k).sum() >= WIN_MIN_INTERVALS]
    out[f"{prefix}_n_win"] = len(meds)
    if meds:
        out[f"{prefix}_win_dt_min"], out[f"{prefix}_win_dt_max"] = min(meds), max(meds)
        out[f"{prefix}_regime_cross"] = bool(min(meds) < FAST_SLOW_S <= max(meds))
    return out


def _flags(r):
    """Report-only flags from the numeric columns of a row (also used by --check)."""
    def num(k):
        v = r.get(k)
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else v
    nl, ne, sk, nn = num("n_loaded"), num("n_episodes"), num("off_abs_p95_ms"), num("n_neg_loaded")
    return {"flag_support_lt20": None if nl is None else bool(nl < FLAG_LT20), "flag_support_lt30": None if nl is None else bool(nl < FLAG_LT30),
            "flag_one_episode": None if ne is None else bool(ne < FLAG_EPISODES), "flag_skew_gt50ms": None if sk is None else bool(sk > FLAG_SKEW_MS),
            "flag_neg_loaded": None if nn is None else bool(nn > 0),
            "flag_regime_cross_i": r.get("i_regime_cross"), "flag_regime_cross_vmax": r.get("vmax_regime_cross"),
            "flag_gap20_i": None if num("i_n_gap20") is None else bool(num("i_n_gap20") > 0)}


def timing_from_bytes(csv_bytes):
    """All descriptors of one drive CSV. Unparseable file -> reason 'parse_error' (nulls)."""
    import compute_drive_summary_v6 as D
    out = {c: None for c in COLS}
    try:
        df, t = D._prep_bytes(csv_bytes)
    except Exception:
        out["reason"] = "parse_error"
        return out
    S = {}
    for prefix, col, (lo, hi) in PIDS:
        s = D._series(df, t, col, lo=lo, hi=hi)
        if col == "I" and s is not None:
            s = s[s["v"].abs() < 900].reset_index(drop=True)          # production artifact filter
            s = s if len(s) else None
        S[prefix] = s
        out.update(_pid_block(prefix, s, df, col))
    out.update(_win_block("i", S["i"]))
    out.update(_win_block("vmax", S["vmax"]))
    vmax, vmin, I = S["vmax"], S["vmin"], S["i"]
    if vmax is None or vmin is None:
        out["reason"] = "no_cell_voltage"
        out.update(_flags(out))
        return out
    vmin2 = vmin.rename(columns={"v": "vmin"}).copy()
    vmin2["t_min"] = vmin2["t"]
    p = pd.merge_asof(vmax.rename(columns={"v": "vmax"}), vmin2, on="t", direction="nearest", tolerance=pd.Timedelta(D.SPREAD_TOL)).dropna()
    out["n_pairs"] = int(len(p))
    if not len(p):
        out["reason"] = "no_cell_pairs"
        out.update(_flags(out))
        return out
    p = p.reset_index(drop=True)
    off = (p["t_min"] - p["t"]).dt.total_seconds().to_numpy() * 1000.0
    spread = ((p["vmax"] - p["vmin"]) * 1000.0).to_numpy()
    out.update(off_med_ms=float(np.median(off)), off_p05_ms=float(np.quantile(off, 0.05)), off_p95_ms=float(np.quantile(off, 0.95)),
               off_abs_p95_ms=float(np.quantile(np.abs(off), 0.95)), frac_off_gt50ms=float((np.abs(off) > FLAG_SKEW_MS).mean()),
               n_neg=int((spread < 0).sum()), frac_neg=float((spread < 0).mean()))
    if I is None:
        out["reason"] = "no_current_series"
        out.update(_flags(out))
        return out
    I2 = I.copy()
    I2["t_I"] = I2["t"]
    p2 = D._asof(p, I2, "I", D.V_ALIGN_TOL)
    ld = (p2["I"].abs() > LOADED_A).to_numpy()
    out["n_loaded"] = int(ld.sum())
    if ld.any():
        q = p2.loc[ld].reset_index(drop=True)
        cur = q["I"].to_numpy(dtype=float)
        age = np.abs((q["t_I"] - q["t"]).dt.total_seconds().to_numpy()) * 1000.0
        gaps = np.diff(q["t"].to_numpy(dtype="datetime64[ns]").astype(np.int64)) / 1e9
        ep = np.concatenate([[0], np.cumsum(gaps > EPISODE_BREAK_S)])
        sizes = np.bincount(ep)
        soc = S["soc"]
        socm = D._asof(q[["t"]].copy(), soc, "soc", D.V_ALIGN_TOL)["soc"] if soc is not None else None
        sp_l = spread[ld]
        out.update(n_loaded_dis=int((cur < -LOADED_A).sum()), n_loaded_chg=int((cur > LOADED_A).sum()), n_episodes=int(len(sizes)),
                   episode_max_share=float(sizes.max() / sizes.sum()), cur_age_p50_ms=float(np.median(age)), cur_age_p95_ms=float(np.quantile(age, 0.95)),
                   i_abs_med=float(np.median(np.abs(cur))), i_abs_p95=float(np.quantile(np.abs(cur), 0.95)),
                   soc_med=float(np.nanmedian(socm)) if socm is not None and socm.notna().any() else None,
                   n_neg_loaded=int((sp_l < 0).sum()), frac_neg_loaded=float((sp_l < 0).mean()))
    else:
        out.update(n_loaded_dis=0, n_loaded_chg=0, n_episodes=0, n_neg_loaded=0)
    out.update(_flags(out))
    return out


def _row(f, date, res, sha):
    r = {k: None for k in COLS}
    r.update({k: res.get(k) for k in COLS if k in res})
    r.update(file=f, date=date, raw_sha256=sha, method_version=METHOD_VERSION)
    return r


def _clean(prev):
    return {k: (None if (isinstance(prev.get(k), float) and np.isnan(prev.get(k))) else prev.get(k)) for k in COLS}


def _read(path):
    return pd.read_csv(path, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])


def build_sidecar(master, loader, path=SIDECAR, sha_lookup=None, rebuild=False):
    """One row per master drive (master order). Reuses a stored row when its raw sha256 and method_version are unchanged; otherwise recomputes it."""
    old = {}
    if os.path.exists(path) and not rebuild:
        old = {r["file"]: r for r in _read(path).to_dict("records")}
    rows = []
    for _, m in master.iterrows():
        f, date = str(m["file"]), str(m["date"])
        prev = old.get(f)
        reusable = prev is not None and prev.get("method_version") == METHOD_VERSION and prev.get("reason") != "raw_file_missing"
        sha = sha_lookup(f) if sha_lookup else None
        if reusable and sha and prev.get("raw_sha256") == sha:
            rows.append(_clean(prev))
            continue
        b = loader(f)
        if b is None:
            rows.append(_row(f, date, {"reason": "raw_file_missing"}, None))
            continue
        h = hashlib.sha256(b).hexdigest()
        if reusable and prev.get("raw_sha256") == h:
            rows.append(_clean(prev))
            continue
        rows.append(_row(f, date, timing_from_bytes(b), h))
    out = pd.DataFrame(rows, columns=COLS)
    for c in NUM:
        out[c] = pd.to_numeric(out[c], errors="coerce").round(6)
    out.to_csv(path, index=False, lineterminator="\n")
    return _read(path)


def matched_support(side, master):
    """Pre-registered check: one row per master drive, n_loaded equals the master n_loaded_spread_samples (null pattern included), flags follow their numbers."""
    bad = []
    mm = master.set_index("file")
    s = side.set_index("file")
    if list(side["file"]) != list(master["file"]):
        bad.append("rows differ from the master drive list")
    for f in master["file"]:
        if f not in s.index:
            continue
        r = s.loc[f]
        if r.get("reason") == "raw_file_missing":
            bad.append(f"{f}: raw file missing")
            continue
        mv = mm.loc[f].get("n_loaded_spread_samples")
        nl = r.get("n_loaded")
        nl = 0 if pd.isna(nl) else int(nl)
        if (pd.isna(mv) and nl != 0) or (not pd.isna(mv) and nl != int(mv)):
            bad.append(f"{f}: n_loaded {nl} != master {mv}")
        fl = _flags({k: (None if pd.isna(v) else v) for k, v in r.items()})
        for k in FLAGS[:5] + ["flag_gap20_i"]:
            sv = r.get(k)
            sv = None if pd.isna(sv) else (str(sv) == "True")
            if fl[k] != sv:
                bad.append(f"{f}: {k} inconsistent with its numbers")
    return bad


def summarize(side, master):
    """Descriptive table: flag counts and quantiles of the main columns, overall and by the declared drive-level regime. No test, no interval."""
    d = side.merge(master[["file", "I_sample_period_s"]], on="file", how="left").copy()
    d["regime"] = np.where(d["I_sample_period_s"].isna(), "unknown", np.where(d["I_sample_period_s"] < FAST_SLOW_S, "fast", "slow"))
    cols = ["i_dt_q50", "i_dt_iqr_ratio", "i_frac_dt_gt3s", "i_gap20_s", "off_med_ms", "off_abs_p95_ms", "n_loaded", "n_episodes", "cur_age_p95_ms", "frac_neg_loaded"]

    def qt(x):
        x = pd.to_numeric(x, errors="coerce").dropna()
        return None if not len(x) else {"n": int(len(x)), **{k: round(float(np.quantile(x, q)), 4) for k, q in (("q05", .05), ("q50", .5), ("q95", .95))}}
    flags = {k: {"true": int((d[k].astype(str) == "True").sum()), "false": int((d[k].astype(str) == "False").sum()), "null": int(d[k].isna().sum())} for k in BOOL if k in d}
    noninf = sorted(k for k, v in flags.items() if v["true"] + v["false"] and v["true"] / (v["true"] + v["false"]) > 0.9)      # spec: a flag raised on more than 90 % of drives is non-informative, reported and not tuned
    return {"methodVersion": METHOD_VERSION, "nDrives": int(len(d)), "nonInformativeFlags": noninf, "reasons": {str(k): int(v) for k, v in d["reason"].fillna("ok").value_counts().items()},
            "flags": flags, "byRegime": {g: {"nDrives": int(len(x)), **{c: qt(x[c]) for c in cols}} for g, x in d.groupby("regime")},
            "all": {c: qt(d[c]) for c in cols},
            "thresholds": {"fastSlowS": FAST_SLOW_S, "windowS": WIN_S, "windowMinIntervals": WIN_MIN_INTERVALS, "episodeBreakS": EPISODE_BREAK_S, "loadedA": LOADED_A,
                           "skewMs": FLAG_SKEW_MS, "supportLt": [FLAG_LT20, FLAG_LT30], "episodesLt": FLAG_EPISODES, "status": "exploratory, fixed in analyses/M479_spec.md"},
            "statement": "report-only descriptors of logged timestamps and loaded support; offsets and gaps are logged timestamp differences between reported values, not acquisition latency; "
                         "no flag is a quality verdict, a filter or a degradation indicator"}


def main():
    import ah_throughput as AH       # raw loader and manifest lookup of the M402 sidecar tool
    master = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    if "--check" in sys.argv:
        if not os.path.exists(SIDECAR):
            raise SystemExit("FAIL: timing_support.csv missing")
        bad = matched_support(_read(SIDECAR), master)
        for b in bad[:20]:
            print("FAIL", b)
        print("timing_support check: %d problem(s)" % len(bad))
        sys.exit(1 if bad else 0)
    side = build_sidecar(master, AH.raw_loader(), sha_lookup=AH.manifest_sha_lookup(), rebuild="--rebuild" in sys.argv)
    bad = matched_support(side, master)
    with open(SUMMARY, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summarize(side, master), fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    for b in bad[:20]:
        print("FAIL", b)
    print(json.dumps({"rows": int(len(side)), "problems": len(bad)}))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
