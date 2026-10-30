#!/usr/bin/env python3
"""M536 phase 1 (analyses/M536_spec.md Rev 2): evidence for ONE project-wide engine-on / engine-off definition. Evidence only: NO payload key, NO ingest stage, NO change to rpmDistribution edges or to the regeneration proxy.

Per-drive sidecar engine_on_evidence_sidecar.csv (tracked; keyed by the raw-file SHA-256 AND by engine_on_evidence_sidecar.meta.json: source hash of evidence_row + thresholds; a mismatch rebuilds all):
- 1 Hz grid of the pipeline (byte-faithful to rpm_opt_band.grid_rpm / _RawAccum.add, but the NaN seconds are kept): seconds with rpm >= T for T in 250..500 (step 50), > 300, > 400, the 300-400 band and its start/stop-adjacent seconds,
  the app-calculated engine load in the band and above (corroboration), hysteresis (on >= 400, off < 300) with minimum hold 1/2/3/5 s, minimum ON-run filters (3/5 s) of the plain rules, the engineStartRate detector rule (NaN -> off, > 300, run >= 2 s);
- interval integration of the production helpers (compute_drive_summary_v6._prep_bytes / _series / _tw_stats; the M512 engineRuntime basis): supported seconds and seconds with rpm >= 300, > 300, >= 400, > 400.
Aggregation reads the sidecar only: totals in hours, threshold table, B1-B2 gap decomposition in both orders, strata by cadence regime, day-clustered intervals (seed 42, 4000 draws), tripwires. Output analyses/M536_evidence.json (first output kept).
`--inventory` writes analyses/M536_inventory_grep.json (grep-based list of rpm threshold sites; the annotated producer table is analyses/M536_inventory.json).
Usage: python tools/engine_on_evidence.py [--build] [--inventory] [--rebuild]"""
import hashlib, inspect, io, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

SIDECAR = os.path.join(ROOT, "engine_on_evidence_sidecar.csv")
META = os.path.join(ROOT, "engine_on_evidence_sidecar.meta.json")
OUT = os.path.join(ROOT, "analyses", "M536_evidence.json")
SPEC = "analyses/M536_spec.md"
TS = (250, 300, 350, 400, 450, 500)
HOLDS = (1, 2, 3, 5)
RUNS = (3, 5)
NB, SEED = 4000, 42
INT_T = (("ge300", 300, True), ("gt300", 300, False), ("ge400", 400, True), ("gt400", 400, False))


def _runs(on):
    """run-length encode a boolean array: list of (start, length, value)"""
    out, i, n = [], 0, len(on)
    while i < n:
        j = i
        while j < n and on[j] == on[i]:
            j += 1
        out.append((i, j - i, bool(on[i])))
        i = j
    return out


def hysteresis(r, on_t=400.0, off_t=300.0):
    """on when rpm >= on_t, off when rpm < off_t (a NaN second turns the state off)"""
    s = np.zeros(len(r), dtype=bool); cur = False
    for i, v in enumerate(r):
        if v != v:
            cur = False
        elif cur and v < off_t:
            cur = False
        elif (not cur) and v >= on_t:
            cur = True
        s[i] = cur
    return s


def min_hold(state, h):
    """remove ON runs shorter than h seconds, then fill OFF gaps (between ON runs) shorter than h seconds"""
    s = state.copy()
    for st, ln, v in _runs(s):
        if v and ln < h:
            s[st:st + ln] = False
    rr = _runs(s)
    for k, (st, ln, v) in enumerate(rr):
        if (not v) and ln < h and 0 < k < len(rr) - 1:
            s[st:st + ln] = True
    return s


def drop_short_on(on, h):
    s = on.copy()
    for st, ln, v in _runs(s):
        if v and ln < h:
            s[st:st + ln] = False
    return s


def evidence_row(csv_bytes, cs, D):
    """one drive -> dict of integer counts, or None when the drive has no time / rpm column"""
    df = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    df = df.rename(columns={k: v for k, v in cs.RAW_MAP.items() if k in df.columns})
    if "time" not in df or "eng_rpm" not in df:
        return None
    t = cs._ft(df["time"], mixed=True)
    rpm = pd.to_numeric(df["eng_rpm"], errors="coerce").ffill(limit=15)
    rpm = rpm.where(rpm >= 0)
    ld = pd.to_numeric(df["eng_load_calc"], errors="coerce").ffill(limit=15) if "eng_load_calc" in df else pd.Series(np.nan, index=df.index)
    g1 = pd.DataFrame({"t": t, "eng_rpm": rpm.values, "load": ld.values}).dropna(subset=["t"]).set_index("t")
    hz = g1.resample("1s").mean().ffill(limit=15)
    r = hz["eng_rpm"].values.astype(float); lo = hz["load"].values.astype(float)
    ok = ~np.isnan(r)
    if not ok.any():
        return None
    row = {"grid_total_s": int(len(r)), "grid_valid_s": int(ok.sum()), "grid_zero_s": int((r == 0).sum())}
    rz = np.nan_to_num(r, nan=-1.0)
    for T in TS:
        row["g_ge%d" % T] = int((rz >= T).sum())
    row["g_gt300"] = int((rz > 300).sum()); row["g_gt400"] = int((rz > 400).sum())
    band = (rz >= 300) & (rz < 400)
    prev = np.concatenate([[-1.0], rz[:-1]]); nxt = np.concatenate([rz[1:], [-1.0]])
    adj = band & (((prev >= 0) & (prev < 300)) | ((nxt >= 0) & (nxt < 300)))
    row["band_300_400_s"] = int(band.sum()); row["band_adjacent_off_s"] = int(adj.sum())
    lv = ~np.isnan(lo)
    row["band_load_valid_s"] = int((band & lv).sum()); row["band_load_pos_s"] = int((band & lv & (lo > 0)).sum())
    hi = rz >= 400
    row["ge400_load_valid_s"] = int((hi & lv).sum()); row["ge400_load_pos_s"] = int((hi & lv & (lo > 0)).sum())
    hs = hysteresis(r)
    for h in HOLDS:
        row["hyst_hold%d_s" % h] = int(min_hold(hs, h).sum())
    for h in RUNS:
        row["run%d_ge300_s" % h] = int(drop_short_on(rz >= 300, h).sum()); row["run%d_gt400_s" % h] = int(drop_short_on(rz > 400, h).sum())
    on6 = np.nan_to_num(r, nan=0.0) > 300
    s6 = [ln for st, ln, v in _runs(on6) if v and ln >= cs.MIN_ENGINE_START_S]
    row["b6_on_s"] = int(sum(s6)); row["b6_runs"] = int(len(s6))
    # interval integration of the production helpers (M512 basis)
    df2, t2 = D._prep_bytes(csv_bytes)
    eng = D._series(df2, t2, "eng_rpm", lo=0)
    if eng is None or len(eng) <= 2:
        row.update({"int_sup_s": np.nan, **{"int_" + n: np.nan for n, _, _ in INT_T}})
    else:
        w = D._tw_stats(eng).values; v = eng["v"].values
        row["int_sup_s"] = float(w.sum())
        for n, T, ge in INT_T:
            row["int_" + n] = float(w[(v >= T) if ge else (v > T)].sum())
    return row


def _src_hash():
    import compute_summary_arrays as cs
    return hashlib.sha256((inspect.getsource(evidence_row) + inspect.getsource(hysteresis) + inspect.getsource(min_hold) + inspect.getsource(drop_short_on) + inspect.getsource(_runs)
                           + repr((TS, HOLDS, RUNS, cs.MIN_ENGINE_START_S))).encode()).hexdigest()


def build_sidecar(dm, rebuild=False):
    import compute_summary_arrays as cs
    import compute_drive_summary_v6 as D
    import ah_throughput as AH
    load = AH.raw_loader()
    src = _src_hash()
    meta = json.load(open(META)) if os.path.exists(META) else {}
    old = {}
    if not rebuild and os.path.exists(SIDECAR) and meta.get("rowFnSha256") == src:
        old = pd.read_csv(SIDECAR, dtype={"sha256": str}).set_index("file").to_dict("index")
    rows, reparsed = [], 0
    for f, d in zip(dm["file"], dm["date"]):
        raw = load(f)
        if raw is None:
            continue
        sha = hashlib.sha256(raw).hexdigest(); prev = old.get(f)
        if prev and prev["sha256"] == sha:
            rows.append({"file": f, **prev}); continue
        r = evidence_row(raw, cs, D)
        if r is None:
            continue
        rows.append({"file": f, "sha256": sha, "date": d, **r}); reparsed += 1
    sc = pd.DataFrame(rows)
    sc.to_csv(SIDECAR, index=False, lineterminator="\n")
    json.dump({"rowFnSha256": src, "thresholds": list(TS), "holds": list(HOLDS), "runs": list(RUNS), "note": "evidence only (M536 phase 1); raw/ = sha256-verified originals (M366)"}, open(META, "w", newline="\n"), indent=1)
    return sc, reparsed


def ratio_ci(num, den, days, nb=NB, seed=SEED):
    ud, inv = np.unique(np.asarray(days), return_inverse=True)
    dn = np.bincount(inv, weights=num, minlength=len(ud)); dd = np.bincount(inv, weights=den, minlength=len(ud))
    pt = float(dn.sum() / dd.sum()) if dd.sum() > 0 else float("nan")
    idx = np.random.default_rng(seed).integers(0, len(ud), (nb, len(ud)))
    ds = dd[idx].sum(1); ok = ds > 0
    r = dn[idx].sum(1)[ok] / ds[ok]
    lo, hi = np.percentile(r, [2.5, 97.5])
    return {"pct": round(100 * pt, 4), "ci95Pct": [round(100 * float(lo), 4), round(100 * float(hi), 4)], "nDays": int(len(ud))}


def compute(sc, A, reg):
    H = lambda col, m=None: float((sc[col] if m is None else sc.loc[m, col]).sum()) / 3600.0
    sc = sc.copy(); sc["regime"] = sc["file"].map(reg).fillna("unknown")
    rd = A["rpmDistribution"]
    out = {"nDrives": int(len(sc)), "nDays": int(sc["date"].nunique())}
    out["gridded_h"] = round(H("grid_valid_s"), 4)
    b1_on = H("g_ge300")
    out["storedRpmDistribution"] = {"onHours": rd.get("engineOnHours", None), "note": "A1 compares g_ge300 hours with the stored B1 on-hours (99.867 h in M521) and gridded hours (230.506 h)"}
    out["thresholdTable"] = {"ge%d" % T: {"hours": round(H("g_ge%d" % T), 4), "pctOfGriddedValid": ratio_ci(sc["g_ge%d" % T].values.astype(float), sc["grid_valid_s"].values.astype(float), sc["date"].values)} for T in TS}
    out["thresholdTable"]["gt300"] = {"hours": round(H("g_gt300"), 4)}; out["thresholdTable"]["gt400"] = {"hours": round(H("g_gt400"), 4), "pctOfGriddedValid": ratio_ci(sc["g_gt400"].values.astype(float), sc["grid_valid_s"].values.astype(float), sc["date"].values)}
    out["hysteresis"] = {"hold%d" % h: round(H("hyst_hold%d_s" % h), 4) for h in HOLDS}
    out["minRunFilters"] = {"run%d_ge300" % h: round(H("run%d_ge300_s" % h), 4) for h in RUNS}; out["minRunFilters"].update({"run%d_gt400" % h: round(H("run%d_gt400_s" % h), 4) for h in RUNS})
    out["b6Rule"] = {"onHours": round(H("b6_on_s"), 4), "runs": int(sc["b6_runs"].sum())}
    # B1 -> B2 gap (hours), both orders. B1 = grid >= 300; B2 numerator = interval > 400.
    gi = sc.dropna(subset=["int_gt400"]); Hh = lambda c: float(gi[c].sum()) / 3600.0
    B1, B2 = Hh("g_ge300"), Hh("int_gt400")
    T_grid, I_400 = Hh("g_ge300") - Hh("g_gt400"), Hh("g_gt400") - Hh("int_gt400")          # order 1: threshold first (on the grid), then integration
    I_300, T_int = Hh("g_ge300") - Hh("int_ge300"), Hh("int_ge300") - Hh("int_gt400")        # order 2: integration first (at 300), then threshold (on the intervals)
    out["gapDecomposition"] = {"population": "drives with an interval series (the M512 basis)", "nDrives": int(len(gi)), "B1_grid_ge300_h": round(B1, 4), "B2_interval_gt400_h": round(B2, 4), "gap_h": round(B1 - B2, 4),
                               "order1": {"threshold_h": round(T_grid, 4), "integration_h": round(I_400, 4)}, "order2": {"integration_h": round(I_300, 4), "threshold_h": round(T_int, 4)},
                               "average": {"threshold_h": round((T_grid + T_int) / 2, 4), "integration_h": round((I_400 + I_300) / 2, 4)},
                               "residual_h": round((B1 - B2) - (T_grid + I_400), 4), "note": "order1 and order2 each sum to the gap by construction; the residual is 0 unless the populations differ; the supported-time denominator term concerns shares, not hours"}
    out["denominators"] = {"gridded_valid_h": round(Hh("grid_valid_s"), 4), "interval_supported_h": round(Hh("int_sup_s"), 4)}
    band = float(sc["band_300_400_s"].sum()); on300 = float(sc["g_ge300"].sum())
    out["band300_400"] = {"hours": round(band / 3600, 4), "pctOfGe300": ratio_ci(sc["band_300_400_s"].values.astype(float), sc["g_ge300"].values.astype(float), sc["date"].values),
                          "adjacentToOffPctOfBand": round(100 * float(sc["band_adjacent_off_s"].sum()) / band, 3) if band else None,
                          "loadPositivePctOfBandValidLoad": round(100 * float(sc["band_load_pos_s"].sum()) / max(1.0, float(sc["band_load_valid_s"].sum())), 3),
                          "loadPositivePctAbove400ValidLoad": round(100 * float(sc["ge400_load_pos_s"].sum()) / max(1.0, float(sc["ge400_load_valid_s"].sum())), 3)}
    strata = {}
    for g, s in sc.groupby("regime"):
        strata[g] = {"nDrives": int(len(s)), "ge300_h": round(float(s["g_ge300"].sum()) / 3600, 3), "bandPctOfGe300": round(100 * float(s["band_300_400_s"].sum()) / max(1.0, float(s["g_ge300"].sum())), 3),
                     "adjacentToOffPctOfBand": round(100 * float(s["band_adjacent_off_s"].sum()) / max(1.0, float(s["band_300_400_s"].sum())), 3)}
    out["byCadenceRegime"] = strata
    d300 = {T: abs(H("g_ge%d" % T) - b1_on) / b1_on * 100 for T in TS}
    sp = [strata[g]["bandPctOfGe300"] for g in ("fast", "slow") if g in strata]
    out["tripwires"] = {"thresholdChangesOnHoursOver3PctOfB1": {str(T): bool(v > 3) for T, v in d300.items()}, "thresholdChangePctOfB1": {str(T): round(v, 3) for T, v in d300.items()},
                        "band300_400OverOnePctOfEngineOn": bool(band / max(1.0, on300) > 0.01), "bandPctOfEngineOn": round(100 * band / max(1.0, on300), 3),
                        "decompositionResidualOver0.5h": bool(abs(out["gapDecomposition"]["residual_h"]) > 0.5),
                        "bandDiffersMoreThan2xBetweenCadenceStrata": bool(len(sp) == 2 and min(sp) > 0 and max(sp) / min(sp) > 2),
                        "hysteresisVsPlainOver1PctOfB1": {("hold%d" % h): bool(abs(H("hyst_hold%d_s" % h) - H("g_ge300")) / b1_on * 100 > 1) for h in HOLDS},
                        "xBasisProducersUnresolved": ["rpmFinding (M521 row 5428)", "simultaneity (rows 5518, 5521)", "engineStateMachine (row 10874)"]}
    return out


def inventory():
    pat = re.compile(r"(eng_rpm|\brpm\b|ENG_ON|RPM_ON|_RSYNC_ENG_ON|engineOnThresholdRpm)[^\n]{0,60}?(>=|<=|>|<)\s*(\d{3,4})\b|(RPM_ON|_RSYNC_ENG_ON|ENGINE_ON_RPM)\s*=\s*(\d{3,4})")
    files = ["compute_summary_arrays.py", "compute_drive_summary_v6.py"] + sorted("tools/" + f for f in os.listdir(os.path.join(ROOT, "tools")) if f.endswith(".py"))
    rows = []
    for f in files:
        for i, line in enumerate(open(os.path.join(ROOT, f), encoding="utf-8", errors="replace"), 1):
            m = pat.search(line)
            if m and not line.lstrip().startswith("#"):
                rows.append({"file": f, "line": i, "text": line.strip()[:200]})
    json.dump({"method": "grep (regex on rpm threshold comparisons and constants); the annotated producer table is analyses/M536_inventory.json", "n": len(rows), "rows": rows}, open(os.path.join(ROOT, "analyses", "M536_inventory_grep.json"), "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    return len(rows)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    if "--inventory" in argv:
        print("inventory rows", inventory()); return 0
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    if "--build" in argv or not os.path.exists(SIDECAR):
        sc, rep = build_sidecar(dm, rebuild="--rebuild" in argv); print("sidecar rows", len(sc), "reparsed", rep)
    sc = pd.read_csv(SIDECAR, dtype={"sha256": str})
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    reg = pd.read_csv("cadence_regime.csv").set_index("file")["regime"]
    res = compute(sc, A, reg)
    res["provenance"] = {"spec": SPEC, "specSha256": hashlib.sha256(open(SPEC, "rb").read()).hexdigest(), "toolSha256": hashlib.sha256(open("tools/engine_on_evidence.py", "rb").read()).hexdigest(),
                         "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "sidecar": "engine_on_evidence_sidecar.csv"}
    if not os.path.exists(OUT):                                   # run-once lock: the first output is kept
        json.dump(res, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    print(json.dumps({k: res[k] for k in ("gapDecomposition", "band300_400", "tripwires", "byCadenceRegime")}, default=float)[:3500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
