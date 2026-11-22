#!/usr/bin/env python3
"""M709 (spec analyses/M708_spec.md Rev 2): restart / post-drive pack-temperature census (E1, E2-inputs, E5) from the raw drive CSVs.

Reads every canonical raw drive (read-only), builds the per-drive endpoints by the frozen rule, the adjacent-pair table with exclusions and unlogged-use flags, the E1 restart-change
table by gap class (day-clustered percentile bootstrap, seed 42, 4000 draws) and the E5 ledger-vs-native start comparison. Fresh code: nothing is imported from analyses/.
Endpoint rule (spec section 2): start reading of a probe = EARLIEST native reading at or before first movement (speed > 0.5 km/h) and within 60 s of log start; if none before movement, the
first reading within 30 s (flag start_after_move). End reading = LAST native reading within 60 s of log end. No forward fill, no averaging in time. Probes T1-T4 report whole degrees.
Usage: python tools/restart_census.py [--raw-dir DIR] [--out DIR] [--workers N] [--drives-cache FILE]
Writes <out>/restart_endpoints.csv, restart_pairs.csv, restart_census.json (default out = analyses/M709/). No payload splice (stage `restart_census`, M711)."""
import argparse, hashlib, json, os, re, sys
from multiprocessing import Pool
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import raw_resolver as RR

PROBES = ("T1", "T2", "T3", "T4")
COLS = {"T1": "[BMS] HV Battery Temperature Sensor 1 (℃)", "T2": "[BMS] HV Battery Temperature Sensor 2 (℃)",
        "T3": "[BMS] HV Battery Temperature Sensor 3 (℃)", "T4": "[BMS] HV Battery Temperature Sensor 4 (℃)",
        "Tcool": "Температура охолодної рідини (℃)",
        "soc": "[BMS] HV State of charge (%)", "spd_vcm": "[VCM] Vehicle Speed (km/h)",
        "spd_obd": "Швидкість автомобіля (km/h)"}
START_WIN, START_WIN_MOVING, END_WIN, MOVE_KMH = 60.0, 30.0, 60.0, 0.5
SEED, NBOOT = 42, 4000
GAP_EDGES = [0, 1 / 6, 1, 4, 12, 1e6]
GAP_LAB = ["<10 min", "10-60 min", "1-4 h", "4-12 h", ">=12 h"]
SOC_RISE_PTS, COOL_HOT_C, COOL_HOT_GAP_H, COOL_UP_C, COOL_UP_GAP_H, ODO_STEP_KM, GAP_MAX_H = 3.0, 15.0, 6.0, 5.0, 1.0, 1.0, 168.0


def key14(name):
    return re.sub(r"\D", "", os.path.basename(str(name)).rsplit(".", 1)[0])[:14]


def _utc0(key, first_clock_s):
    """UTC epoch of the first row: local date from the file name, local clock from the first row (Europe/Kyiv); a file name just before midnight with a first row after it moves to the next day."""
    from zoneinfo import ZoneInfo
    fdt = pd.Timestamp("%s-%s-%s %s:%s:%s" % (key[:4], key[4:6], key[6:8], key[8:10], key[10:12], key[12:14]))
    day0 = fdt.normalize()
    if first_clock_s < (fdt - day0).total_seconds() - 6 * 3600:
        day0 += pd.Timedelta(days=1)
    loc = (day0 + pd.Timedelta(microseconds=int(round(float(first_clock_s) * 1e6)))).to_pydatetime().replace(tzinfo=ZoneInfo("Europe/Kyiv"))
    return loc.timestamp(), str(loc.replace(tzinfo=None))


def read_drive(path):
    """Per-drive endpoint record (dict) from one raw CSV; never raises (an error is returned in the record)."""
    key = key14(path)
    try:
        hdr = pd.read_csv(path, nrows=0, encoding="utf-8").columns
        use = ["time"] + [v for v in COLS.values() if v in hdr]
        d = pd.read_csv(path, usecols=use, low_memory=False, encoding="utf-8")
        t = pd.to_datetime(d["time"], format="%H:%M:%S.%f", errors="coerce")
        ok = t.notna().values
        d = d[ok].reset_index(drop=True)
        sec = (t[ok] - pd.Timestamp("1900-01-01")).dt.total_seconds().values
        sec = sec + np.concatenate([[0], np.cumsum(np.diff(sec) < -12 * 3600)]) * 86400.0
        d = d.rename(columns={v: k for k, v in COLS.items()})
        for k in d.columns:
            if k != "time":
                d[k] = pd.to_numeric(d[k], errors="coerce")
        rel = sec - sec[0]
        dur = float(rel[-1])
        utc0, local0 = _utc0(key, sec[0])
        if "spd_vcm" in d and d["spd_vcm"].notna().sum() >= 20:
            spd = d["spd_vcm"].where(d["spd_vcm"].notna(), d["spd_obd"]) if "spd_obd" in d else d["spd_vcm"]
        else:
            spd = d["spd_obd"] if "spd_obd" in d else pd.Series(np.nan, index=d.index)
        spd = spd.where((spd >= 0) & (spd <= 260))
        mv = np.flatnonzero(spd.values > MOVE_KMH)
        tm0 = float(rel[mv[0]]) if len(mv) else np.nan
        r = {"key": key, "path": os.path.basename(path), "utc0": utc0, "utc1": utc0 + dur, "dur_s": dur, "local0": local0, "t_move0": tm0}
        for ch in PROBES + ("Tcool",):
            if ch not in d:
                continue
            v = d[ch].values
            m = np.isfinite(v) & ((v <= 70) & (v >= -40) if ch in PROBES else (v <= 150) & (v >= -40))
            tt, vv = rel[m], v[m]
            if len(tt) == 0:
                continue
            r[ch + "_n"] = int(len(tt))
            r[ch + "_dt_med"] = float(np.median(np.diff(tt))) if len(tt) > 2 else np.nan
            pre = (tt <= (tm0 if np.isfinite(tm0) else np.inf)) & (tt <= START_WIN)
            if pre.any():
                i0 = int(np.flatnonzero(pre)[0]); r[ch + "_s"], r[ch + "_s_lag"], r[ch + "_s_am"] = float(vv[i0]), float(tt[i0]), 0
            elif tt[0] <= START_WIN_MOVING:
                r[ch + "_s"], r[ch + "_s_lag"], r[ch + "_s_am"] = float(vv[0]), float(tt[0]), 1
            if dur - tt[-1] <= END_WIN:
                r[ch + "_e"], r[ch + "_e_lag"] = float(vv[-1]), float(dur - tt[-1])
        soc = d["soc"].where((d["soc"] > 0) & (d["soc"] <= 100)).dropna() if "soc" in d else pd.Series(dtype=float)
        r["soc_first"] = float(soc.iloc[0]) if len(soc) else np.nan
        r["soc_last"] = float(soc.iloc[-1]) if len(soc) else np.nan
        return r
    except Exception as ex:                                   # one unreadable drive is reported, never a silent drop
        return {"key": key, "path": os.path.basename(path), "error": repr(ex)}


def load_endpoints(raw_dir, workers=1, cache=None):
    """Endpoints for every drive of drive_master.csv (file key = digits); raw files through the typed resolver (M707 B3)."""
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file", "date", "odo_start", "odo_end"], low_memory=False)
    dm["key"] = dm["file"].map(key14)
    res = RR.resolve(raw_dir, os.path.join(ROOT, "raw_manifest.json"))
    paths = [res.index[k] for k in dm["key"] if k in res.index]
    if cache and os.path.exists(cache):
        recs = pd.read_pickle(cache)
    else:
        if workers > 1:
            with Pool(workers) as p:
                recs = p.map(read_drive, paths, chunksize=4)
        else:
            recs = [read_drive(p) for p in paths]
        if cache:
            pd.to_pickle(recs, cache)
    bad = [r for r in recs if "error" in r]
    if bad:
        raise RuntimeError("unreadable drives: %s" % [(b["path"], b["error"]) for b in bad[:5]])
    E = pd.DataFrame(recs).merge(dm[["key", "file", "date", "odo_start", "odo_end"]], on="key", how="left")
    E["local0"] = pd.to_datetime(E["local0"], format="ISO8601")
    E["day"] = E["local0"].dt.strftime("%Y-%m-%d")
    E = E.sort_values("utc0").reset_index(drop=True)
    for p in PROBES:
        for sfx in ("_s", "_e"):
            if p + sfx not in E:
                E[p + sfx] = np.nan
    for sfx in ("_s", "_e"):
        if "Tcool" + sfx not in E:
            E["Tcool" + sfx] = np.nan
    return E


def build_pairs(E, ambient_start):
    """Adjacent pairs with exclusions (counted in first-match order: odo, no probe, long gap), unlogged-use flags and the same-probe-mean change.
    ambient_start: {key14: ambient reading at the drive start} (vehicle-sensor ambient from summary_config ambientByDrive; uncalibrated)."""
    a = E.iloc[:-1].reset_index(drop=True).add_prefix("p_")
    b = E.iloc[1:].reset_index(drop=True).add_prefix("n_")
    P = pd.concat([a, b], axis=1)
    P["gap_h"] = (P["n_utc0"] - P["p_utc1"]) / 3600
    P["day"] = P["n_day"]
    S = P[["n_%s_s" % p for p in PROBES]].values
    Ev = P[["p_%s_e" % p for p in PROBES]].values
    both = np.isfinite(S) & np.isfinite(Ev)
    P["n_same"] = both.sum(1)
    P["d_same"] = np.where(both.sum(1) >= 2, np.nansum(np.where(both, S - Ev, 0), 1) / np.maximum(both.sum(1), 1), np.nan)
    P["d_T1"] = P["n_T1_s"] - P["p_T1_e"]
    P["d_Tcool"] = P["n_Tcool_s"] - P["p_Tcool_e"]
    P["dsoc"] = P["n_soc_first"] - P["p_soc_last"]
    P["odo_step"] = P["n_odo_start"] - P["p_odo_end"]
    P["n_amb_s"] = P["n_key"].map(ambient_start)
    P["flag_overlap"] = P["gap_h"] < 0
    P["flag_dup"] = P["n_utc0"] == P["p_utc0"]
    P["flag_odo"] = P["odo_step"].abs() > ODO_STEP_KM
    P["flag_noprobe"] = P["d_T1"].isna() | P["d_same"].isna()
    P["flag_long"] = P["gap_h"] > GAP_MAX_H
    P["elig"] = ~(P["flag_overlap"] | P["flag_dup"] | P["flag_odo"] | P["flag_noprobe"] | P["flag_long"])
    P["mp_soc"] = P["dsoc"] >= SOC_RISE_PTS
    P["mp_coolHot"] = (P["gap_h"] >= COOL_HOT_GAP_H) & ((P["n_Tcool_s"] - P["n_amb_s"]) >= COOL_HOT_C)
    P["mp_coolUp"] = (P["gap_h"] >= COOL_UP_GAP_H) & (P["d_Tcool"] >= COOL_UP_C)
    P["flagged"] = P[["mp_soc", "mp_coolHot", "mp_coolUp"]].any(axis=1)
    P["gc"] = pd.cut(P["gap_h"], GAP_EDGES, labels=GAP_LAB, right=False).astype(str)
    P["pair_id"] = P["p_key"] + "|" + P["n_key"]
    return P


def exclusion_counts(P):
    """First-match partition of the 664 pairs: overlap, duplicate, odo step, no fresh probe, long gap; plus eligible and flagged."""
    ov, du = P["flag_overlap"], P["flag_dup"]
    od = P["flag_odo"] & ~ov & ~du
    npb = P["flag_noprobe"] & ~(ov | du | P["flag_odo"])
    lg = P["flag_long"] & ~(ov | du | P["flag_odo"] | P["flag_noprobe"])
    el = P["elig"]
    return {"pairsTotal": int(len(P)), "overlap_gapNegative": int(ov.sum()), "duplicateStart": int(du.sum()), "odoStepAbsGt1km_appCounter": int(od.sum()),
            "noFreshProbeAtAnEndpoint": int(npb.sum()), "gapOver168h": int(lg.sum()), "eligible": int(el.sum()), "eligibleDays": int(P.loc[el, "day"].nunique()),
            "flaggedUnloggedUseAmongEligible": int((el & P["flagged"]).sum()),
            "flagBreakdownAmongEligible": {k: int((el & P[k]).sum()) for k in ("mp_soc", "mp_coolHot", "mp_coolUp")},
            "longGapPairIds": P.loc[lg, "pair_id"].tolist()}


# ---------------------------------------------------------------- day-clustered bootstrap (spec section 3) ----------------------------------
def _weights(n, nboot=NBOOT, seed=SEED):
    return np.random.default_rng(seed).multinomial(n, np.ones(n) / n, size=nboot).astype(float)


def boot_mean(day, x, nboot=NBOOT, seed=SEED, cluster=None):
    """Mean of x with whole clusters resampled (default cluster = the given day labels). Returns est, lo, hi, n, nDays."""
    x = np.asarray(x, float)
    day = np.asarray(day)
    ok = np.isfinite(x)
    d = pd.DataFrame({"c": day[ok], "a": x[ok]})
    if len(d) == 0:
        return {"est": None, "lo": None, "hi": None, "n": 0, "nDays": 0}
    g = d.groupby("c")["a"].agg(["sum", "count"])
    W = _weights(len(g), nboot, seed)
    rr = (W @ g["sum"].values) / (W @ g["count"].values)
    lo, hi = np.nanpercentile(rr, [2.5, 97.5])
    return {"est": float(g["sum"].sum() / g["count"].sum()), "lo": float(lo), "hi": float(hi), "n": int(len(d)), "nDays": int(len(g))}


def boot_share(day, cond, nboot=NBOOT, seed=SEED):
    c = np.asarray(cond, float)
    r = boot_mean(day, c, nboot, seed)
    return {k: (None if r[k] is None else (round(100 * r[k], 2) if k in ("est", "lo", "hi") else r[k])) for k in r}


def e1_table(P, rows_mask=None, cluster_col="day"):
    """E1: mean restart change (same-probe mean) per gap class and pooled <1 h, with shares and day-clustered intervals."""
    out = {}
    sel = P[P["elig"] if rows_mask is None else rows_mask]
    groups = {lab: sel[sel["gc"] == lab] for lab in GAP_LAB}
    groups["<1 h"] = sel[sel["gc"].isin(GAP_LAB[:2])]
    groups["all gaps"] = sel
    for lab, g in groups.items():
        d, c = g["d_same"].values, g[cluster_col].values
        out[lab] = {"meanChange": boot_mean(c, d), "T1meanChange": boot_mean(c, g["d_T1"].values),
                    "shareGt0": boot_share(c, d > 0), "shareGe1": boot_share(c, d >= 1), "shareGe2": boot_share(c, d >= 2),
                    "nGe2Pairs": int((d >= 2).sum())}
    return out


SUPPORT_MIN_PAIRS, SUPPORT_MIN_DAYS = 10, 5


def supported(n, days):
    """Support floor of the winter protocol (spec M708 section 9): at least 10 pairs on at least 5 days, else the cell is 'not evaluable' (never pooled across thermal classes to reach it)."""
    return bool(n >= SUPPORT_MIN_PAIRS and days >= SUPPORT_MIN_DAYS)


def condition_table(P, mask, label):
    """E1 per gap class under a condition mask over the pair frame (flagged pairs kept; the without-flags version beside it). Cells below the support floor are reported as not evaluable without numbers."""
    out = {"condition": label}
    for name, m in (("flaggedKept", mask & P["elig"]), ("flaggedDropped", mask & P["elig"] & ~P["flagged"])):
        t = e1_table(P, m)
        res = {}
        for cls, v in t.items():
            n, dd = v["meanChange"]["n"], v["meanChange"]["nDays"]
            res[cls] = v if supported(n, dd) else {"notEvaluable": True, "n": int(n), "nDays": int(dd), "floor": "%d pairs on %d days" % (SUPPORT_MIN_PAIRS, SUPPORT_MIN_DAYS)}
        out[name] = res
    return out


def e5_start_bias(E, ledger_path, seed=SEED):
    """E5: ledger pack_temp_start_c minus the native 4-probe start, per drive, by regime (per-drive T2-T4 median period > 10 s = slow-polled; calendar rule and 8-12 s as sensitivities)."""
    L = pd.read_csv(ledger_path, usecols=["file", "pack_temp_start_c"], low_memory=False)
    L["key"] = L["file"].map(key14)
    D = E.merge(L[["key", "pack_temp_start_c"]], on="key", how="left")
    S = D[["%s_s" % p for p in PROBES]].values
    D["native4"] = np.where(np.isfinite(S).all(1), S.mean(1), np.nan)
    D["diff"] = D["pack_temp_start_c"] - D["native4"]
    per = D[["T2_dt_med", "T3_dt_med", "T4_dt_med"]].median(axis=1)
    D["slow"] = per > 10.0
    D["slow_calendar"] = D["day"] >= "2026-09-06"
    D["near10"] = (per >= 8.0) & (per <= 12.0)
    res = {"rule": "slow-polled = per-drive median T2-T4 polling period strictly above 10 s", "perDrivePeriodMedianS": {"all": float(per.median())}}
    for lab, m in (("slowPerDrive", D["slow"]), ("fastPerDrive", ~D["slow"]), ("slowCalendar>=2026-09-06", D["slow_calendar"]), ("beforeCalendar", ~D["slow_calendar"]), ("period8to12s", D["near10"])):
        g = D[m & D["diff"].notna()]
        r = boot_mean(g["day"].values, g["diff"].values, seed=seed)
        r.update({"shareGe1C": round(float((g["diff"] >= 1).mean()), 4) if len(g) else None, "max": float(g["diff"].max()) if len(g) else None})
        res[lab] = r
    return res, D[["key", "file", "day", "pack_temp_start_c", "native4", "diff", "slow", "T1_dt_med", "T2_dt_med", "T3_dt_med", "T4_dt_med", "T1_n", "T2_n", "T3_n", "T4_n"]]


def ambient_start_map():
    cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))
    out = {}
    for f, v in cfg.get("ambientByDrive", {}).items():
        val = v[0] if isinstance(v, list) and v else v
        if val is not None:
            out[key14(f)] = float(val)
    return out


def build_result(E, P):
    """The census result dict (exclusions, E1 tables, E5) and the E5 per-drive frame, from the endpoints and the pair table."""
    e5, E5 = e5_start_bias(E, os.path.join(ROOT, "seasonal_drive_master.csv"))
    res = {"milestone": "M709", "spec": "analyses/M708_spec.md", "specSha256": hashlib.sha256(open(os.path.join(ROOT, "analyses", "M708_spec.md"), "rb").read()).hexdigest(),
           "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "scriptSha256": hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest(),
           "bootstrap": {"B": NBOOT, "seed": SEED, "cluster": "calendar day of the next drive"}, "nDrives": int(len(E)),
           "exclusions": exclusion_counts(P),
           "E1_primary_flaggedKept": e1_table(P), "E1_secondary_flaggedDropped": e1_table(P, P["elig"] & ~P["flagged"]),
           "E1_sensitivity_previousDayCluster": e1_table(P, None, "p_day"), "E5": e5,
           "label": "logged BMS probe readings (whole degrees); same-probe mean of next start minus previous end; rise shares are a resolution artefact, not an event rate"}
    return res, E5


def write_outputs(out, E, P, res, E5):
    os.makedirs(out, exist_ok=True)
    E.to_csv(os.path.join(out, "restart_endpoints.csv"), index=False)
    P.drop(columns=[c for c in P.columns if c.startswith(("p_", "n_")) and c not in ("p_key", "n_key", "p_day", "n_day", "n_amb_s")]).to_csv(os.path.join(out, "restart_pairs.csv"), index=False)
    E5.to_csv(os.path.join(out, "restart_e5_start.csv"), index=False)
    json.dump(res, open(os.path.join(out, "restart_census.json"), "w", encoding="utf-8"), indent=1)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M709"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--drives-cache", default=None, help="pickle of the per-drive records (development speed-up; delete when raw or code changes)")
    a = ap.parse_args(argv)
    E = load_endpoints(a.raw_dir, a.workers, a.drives_cache)
    P = build_pairs(E, ambient_start_map())
    res, E5 = build_result(E, P)
    write_outputs(a.out, E, P, res, E5)
    print(json.dumps({"nDrives": res["nDrives"], "exclusions": res["exclusions"], "lt1h": res["E1_primary_flaggedKept"]["<1 h"]["meanChange"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
