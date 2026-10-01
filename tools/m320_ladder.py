#!/usr/bin/env python3
"""M320 (spec: analyses/M320_spec.md rev 2): support-gated, data-driven pack-temperature ladder for the M119-v2 surfaces.
The fitted model is NOT changed: the final fit is refit from the M318 tables and must reproduce the stored M318 surfaces (known-answer check).
  python tools/m320_ladder.py run   --tables TABLES489.pkl [--tables410 TABLES410.pkl] --out DIR [--draws 4000] [--workers 11] [--sides start stop]
  python tools/m320_ladder.py apply --out DIR            # splice DIR/tempLadder_{side}.json into summary_arrays.json (isolation-checked, LF)
TABLES*.pkl come from `tools/m318_run.py tables`. Pure functions (weighted_quantile, rms_contrast, support_stats, select_levels, decide_levels)
are importable for tests/synthetic/test_m320_ladder.py. Bootstrap: day-clustered, 4000 draws, per-draw seed = SeedSequence(42, spawn_key=(k,)),
each draw refits the whole pipeline (knots, standardisation, GLM) with the levels held fixed (selection is conditional; quantiles do not depend on the outcome)."""
import argparse, hashlib, json, math, os, pickle, subprocess, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
import numpy as np
import pandas as pd

STEP, T_RANGE, BAND = 2.5, (-25.0, 50.0), 2.5
GATE_EVENTS, GATE_DAYS, MIN_N = 100, 10, 20
DELTA = math.log(1.25)
QUANTILES = (("P5", 0.05), ("P50", 0.50), ("P95", 0.95))
SOC_EDGES = np.arange(37.5, 87.6, 5.0)       # = _support_mask windows of m119v2_model.SURF_SOC (40..85 step 5, +/-2.5)
SPD_EDGES = np.arange(-5.0, 135.1, 10.0)     # = SURF_SPEED (0..130 step 10, +/-5)
NC = (len(SOC_EDGES) - 1) * (len(SPD_EDGES) - 1)
SEC_CELLS = (("demandLow", 0, 15.0), ("demandHigh", 2, 15.0), ("dur2s", 1, 2.0), ("dur60s", 1, 60.0))   # (name, demand idx 0/1/2, duration s)
LEGACY = (20.0, 28.0, 35.0)
UNIFORM_SPREAD = 0.02    # a contrast whose spread across the supported SoC x speed cells is below this (log units) is shown as one hazard-ratio card


def annotate_block(block):
    """Data-derived disclosure strings and config for the dashboard (nothing is typed in the JSX). Director wording, M320."""
    m = _model()
    notes = []
    pr = {(r["a"], r["b"]): r for r in block["pairs"]}
    g = lambda v: f"{v:g}"
    r2028 = pr.get((20.0, 28.0))
    if r2028:
        st = r2028["primary"]["status"]
        notes.append(f"legacy premise not supported: {g(r2028['a'])} vs {g(r2028['b'])} C differ" if st == "distinct" else
                     f"legacy {g(r2028['a'])} vs {g(r2028['b'])} C {'not distinct (premise holds)' if st == 'indistinct' else st}")
        hi = block["levels"][-1]["value"]
        r_hi = pr.get((28.0, hi))
        if st == "distinct" and r_hi and r_hi["primary"]["status"] == "indistinct":
            notes.append(f"no further change established between 28 and {g(hi)} C")
    for l in block["levels"]:
        if block["fewDaysFlag"].get(l["name"]):
            notes.append(f"{g(l['value'])} C level rests on events from {l['nDays']} calendar days (<20: limited day support; few clusters for the day bootstrap); "
                         f"hot-band days are seasonally clustered")
        if l["value"] > block["linearTailAboveC"] or l["value"] < block["linearTailBelowC"]:
            kn = block["linearTailAboveC"] if l["value"] > block["linearTailAboveC"] else block["linearTailBelowC"]
            notes.append(f"{g(l['value'])} C lies beyond the boundary knot ({g(kn)} C): linear tail (spline-constrained)")
    dw = [f"{c['name']} {g(c['snapped'])} vs {g(c['dayWeightedSnapped'])} C" for c in block["candidates"] if c["snapped"] != c["dayWeightedSnapped"]]
    if dw:
        notes.append("day-weighted quantile levels differ (method disagreement; at-risk-seconds weighting pre-registered): " + "; ".join(dw))
    for c in block.get("stability410") or []:
        if c["value410"] != c["value489"]:
            notes.append(f"{c['name']} level changed between the 410- and 489-drive corpora ({g(c['value410'])} -> {g(c['value489'])} C)")
    sel = pr.get((block["levels"][0]["value"], block["levels"][-1]["value"])) if len(block["levels"]) > 1 else None
    if sel:
        for k in ("demandLow", "demandHigh", "dur2s", "dur60s"):
            if sel[k]["status"] != sel["primary"]["status"]:
                notes.append(f"secondary cell {k}: {sel[k]['status']} (primary: {sel['primary']['status']}); reported as method disagreement")
    block["notes"] = notes
    inter = sorted({b if a == "tpack" else a for a, b in m.INTERACTIONS if "tpack" in (a, b)})
    block["uniformityNote"] = ("the fitted model has pack temperature interacting only with " + " and ".join(inter) +
                               " (no interaction with SoC or speed), so this uniformity is a model property, not an observation")
    block["config"] = {"uniformSpreadThreshold": UNIFORM_SPREAD, "step": STEP, "band": BAND, "gateEvents": GATE_EVENTS, "gateDays": GATE_DAYS,
                       "minCellSeconds": MIN_N, "delta": round(DELTA, 6), "contrastCell": "median demand, 15 s duration"}
    block["coreSupportDiagnostic"] = "uninformative under a cell-uniform model; not robustness evidence"
    return block


def snap(x):
    return round(float(x) / STEP) * STEP


def weighted_quantile(x, w, q):
    """Inverted-CDF weighted quantile: smallest x whose cumulative weight fraction >= q."""
    x, w = np.asarray(x, float), np.asarray(w, float)
    o = np.argsort(x, kind="mergesort")
    x, w = x[o], w[o]
    c = np.cumsum(w) / w.sum()
    return float(x[min(int(np.searchsorted(c, q - 1e-12, side="left")), len(x) - 1)])


def rms_contrast(eta_a, eta_b, n_a, n_b, min_n=MIN_N):
    """D = at-risk-weighted RMS of eta_a - eta_b over cells supported at BOTH levels (weights = pooled at-risk seconds of the two bands)."""
    n_a, n_b = np.asarray(n_a), np.asarray(n_b)
    ok = (n_a >= min_n) & (n_b >= min_n)
    if not ok.any():
        return float("nan")
    w = (n_a + n_b)[ok].astype(float)
    d = (np.asarray(eta_a, float) - np.asarray(eta_b, float))[ok]
    return float(np.sqrt(np.sum(w * d * d) / np.sum(w)))


def band_mask(tp, level):
    return (tp >= level - BAND) & (tp <= level + BAND)


def support_stats(cc, level):
    m = band_mask(cc["tpack"].values, level)
    ev = m & (cc["y"].values > 0)
    return {"nEvents": int(ev.sum()), "nDays": int(pd.unique(cc["day"].values[ev]).size), "nAtRiskS": int(m.sum()),
            "admissible": bool(ev.sum() >= GATE_EVENTS and pd.unique(cc["day"].values[ev]).size >= GATE_DAYS)}


def select_levels(cc, prev=None):
    """Candidate levels per side: seconds-weighted P5/P50/P95 of pack temperature snapped to the grid; day-weighted sensitivity;
    hysteresis (keep the previous value unless the quantile moved >= 1 grid step)."""
    tp, day = cc["tpack"].values, cc["day"].values
    nd = pd.Series(day).map(pd.Series(day).value_counts()).values.astype(float)
    out = []
    for name, q in QUANTILES:
        qv = weighted_quantile(tp, np.ones(len(tp)), q)
        dq = weighted_quantile(tp, 1.0 / nd, q)
        raw = snap(qv)
        pv = (prev or {}).get(name)
        val = pv if (pv is not None and abs(qv - pv) < STEP) else raw
        out.append({"name": name, "quantile": q, "quantileValue": round(qv, 3), "snapped": raw, "value": val,
                    "dayWeightedQuantileValue": round(dq, 3), "dayWeightedSnapped": snap(dq), **support_stats(cc, val)})
    return out


def pair_status(d, lo_pct, lo_basic, failed, n):
    if n and failed / n > 0.01 or not np.isfinite(d):
        return "inconclusive"
    a, b = lo_pct >= DELTA, lo_basic >= DELTA
    return "distinct" if (a and b) else ("borderline" if (a or b) else "indistinct")


def decide_levels(cands, pairs):
    """Merge rule (fixed sequence): {P5,P95} first; P50 added only if distinct from BOTH (intersection-union). Reference = P50, else the lower
    level. `pairs` maps frozenset({a,b}) -> status. Inadmissible candidates are dropped."""
    by = {c["name"]: c for c in cands}
    adm = {k: v for k, v in by.items() if v["admissible"]}
    lo, mid, hi = adm.get("P5"), adm.get("P50"), adm.get("P95")
    director, stmt = False, None
    st = lambda a, b: pairs.get(frozenset((a["value"], b["value"])), "inconclusive")
    if lo and hi and lo["value"] != hi["value"]:
        s = st(lo, hi)
        if s == "distinct":
            levels = [lo, hi]
            if mid and mid["value"] not in (lo["value"], hi["value"]) and st(mid, lo) == "distinct" and st(mid, hi) == "distinct":
                levels = [lo, mid, hi]
            ref = mid if len(levels) == 3 else lo
            return levels, ref, False, None
        director = s in ("borderline", "inconclusive")
    ref = mid or lo or hi
    stmt = "pack-temperature effect not established at this resolution"
    return ([ref] if ref else []), ref, director, stmt


# ---------------------------------------------------------------- model helpers
def _model():
    sys.path.insert(0, ROOT)
    import m119v2_model as m
    return m


def cell_frame(m, soc_ax=None, spd_ax=None):
    soc_ax, spd_ax = soc_ax if soc_ax is not None else m.SURF_SOC, spd_ax if spd_ax is not None else m.SURF_SPEED
    SS, VV = np.meshgrid(soc_ax, spd_ax, indexing="ij")
    return SS.ravel(), VV.ravel()


def eta_block(m, spec, params, levels, dem, cells_soc, cells_spd, sec=True, prof=None):
    """Linear predictors on the SoC x speed cells for each level at the primary cell (median demand, 15 s) and the secondary cells."""
    rows = []
    combos = [("primary", 1, 15.0)] + (list(SEC_CELLS) if sec else [])
    for _, di, du in combos:
        for lv in levels:
            rows.append(pd.DataFrame({"soc": cells_soc, "speed": cells_spd, "tpack": float(lv), "demand": dem[di], "durationS": du}))
    if prof is not None:
        rows.append(prof)
    d = pd.concat(rows, ignore_index=True)
    X, _ = spec.transform(d)
    return X @ np.asarray(params, float), len(combos)


def day_cell_counts(cc, levels, day_codes, nd):
    """(L, nd, NC) at-risk-second counts per day and SoC x speed cell inside each level's +/-2.5 C band."""
    out = np.zeros((len(levels), nd, NC), np.float32)
    si = np.digitize(cc["soc"].values, SOC_EDGES) - 1
    vi = np.digitize(cc["speed"].values, SPD_EDGES) - 1
    ok = (si >= 0) & (si < len(SOC_EDGES) - 1) & (vi >= 0) & (vi < len(SPD_EDGES) - 1)
    cell = si * (len(SPD_EDGES) - 1) + vi
    tp = cc["tpack"].values
    for li, lv in enumerate(levels):
        mk = ok & band_mask(tp, lv)
        np.add.at(out[li], (day_codes[mk], cell[mk]), 1.0)
    return out


G = {}


def _init(payload):
    G.update(payload)


def _draw(k):
    m = G["m"] if "m" in G else _model()
    G["m"] = m
    rng = np.random.default_rng(np.random.SeedSequence(entropy=42, spawn_key=(k,)))
    nd = G["nd"]
    pick = rng.integers(0, nd, nd)
    mult = np.bincount(pick, minlength=nd).astype(np.float32)
    try:
        idx = np.concatenate([G["day_rows"][d] for d in pick])
        df = pd.DataFrame({c: G["cols"][c][idx] for c in G["cols"]})
        spec = m.DesignSpec(['soc', 'speed', 'tpack', 'demand', 'logdur'], m.INTERACTIONS).fit(df)
        X, _ = spec.transform(df)
        res = m.fit_glm(X, df["y"].values.astype(float))
        if hasattr(res, "converged") and not res.converged:
            return k, None
        L, cs, cv = G["levels"], G["cs"], G["cv"]
        prof = pd.DataFrame({"soc": G["prof_soc"], "speed": G["prof_spd"], "tpack": G["tgrid"], "demand": G["dem"][1], "durationS": 15.0})
        eta, nc = eta_block(m, spec, res.params, L, G["dem"], cs, cv, prof=prof)
        nL = len(L)
        etas = eta[: nc * nL * NC].reshape(nc, nL, NC)
        pr = m._predict(res, spec.transform(prof)[0])
        n = np.tensordot(mult, G["counts"], axes=([0], [1]))          # (L, NC) resampled conditional counts
        D = np.full((len(G["pairs"]), nc), np.nan)
        for pi, (a, b) in enumerate(G["pairs"]):
            for ci in range(nc):
                D[pi, ci] = rms_contrast(etas[ci, a], etas[ci, b], n[a], n[b])
        return k, {"D": D, "eta": etas[0].astype(np.float32), "prof": np.asarray(pr, np.float32)}
    except Exception:
        return k, None


def _logistic_p(eta):
    return 1.0 - np.exp(-np.exp(eta))


def run_side(side, tbl, prev, a, tbl410=None):
    m = _model()
    t0 = time.time()
    res, spec, cc, _names = m._final_fit(tbl)
    cc = cc.reset_index(drop=True)
    # known-answer: refit reproduces the stored M318 surfaces at the legacy levels
    A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["socHysteresisV2"]
    legacy = m._surfaces(res, spec, cc)
    kat = max(abs(np.array(legacy["grids"][k], float) - np.array(A["surfaces"][side]["grids"][k], float)).max() for k in legacy["grids"])
    if kat > 1e-6:
        raise SystemExit(f"{side}: known-answer check failed: max |stored - refit| = {kat}")
    cands = select_levels(cc, prev)
    levels = sorted({c["value"] for c in cands} | set(LEGACY))
    dem = [float(x) for x in np.round(np.nanpercentile(cc["demand"], [25, 50, 90]), 2)]
    cs, cv = cell_frame(m)
    days, day_codes = np.unique(cc["day"].values, return_inverse=True)
    nd = len(days)
    counts = day_cell_counts(cc, levels, day_codes, nd)
    n_pt = counts.sum(axis=1)
    pairs = [(i, j) for i in range(len(levels)) for j in range(i + 1, len(levels))]
    tmin, tmax = float(cc["tpack"].min()), float(cc["tpack"].max())
    tgrid = np.arange(math.ceil(tmin), math.floor(tmax) + 1, 1.0)
    med = {c: float(np.nanmedian(cc[c])) for c in ("soc", "speed")}
    prof_pt = pd.DataFrame({"soc": med["soc"], "speed": med["speed"], "tpack": tgrid, "demand": dem[1], "durationS": 15.0})
    eta_pt, nc = eta_block(m, spec, res.params, levels, dem, cs, cv, prof=prof_pt)
    nL = len(levels)
    etas_pt = eta_pt[: nc * nL * NC].reshape(nc, nL, NC)
    D_pt = np.array([[rms_contrast(etas_pt[ci, i], etas_pt[ci, j], n_pt[i], n_pt[j]) for ci in range(nc)] for i, j in pairs])
    prof_p = _logistic_p(eta_pt[nc * nL * NC:])
    print(f"[{side}] point stage done {round(time.time() - t0)}s, levels {levels}, KAT max diff {kat:.2e}", flush=True)
    # bootstrap
    cols = {c: cc[c].values.astype(float) for c in ("soc", "speed", "tpack", "demand", "durationS", "y")}
    day_rows = [np.where(day_codes == d)[0] for d in range(nd)]
    payload = {"cols": cols, "day_rows": day_rows, "nd": nd, "levels": levels, "cs": cs, "cv": cv, "dem": dem, "pairs": pairs, "counts": counts,
               "tgrid": tgrid, "prof_soc": med["soc"], "prof_spd": med["speed"]}
    import multiprocessing as mp
    draws, res_list = a.draws, {}
    with mp.get_context("spawn").Pool(a.workers, initializer=_init, initargs=(payload,)) as pool:
        for k, r in pool.imap_unordered(_draw, range(draws), chunksize=4):
            res_list[k] = r
            if len(res_list) % 200 == 0:
                print(f"[{side}] {len(res_list)}/{draws} draws, {round(time.time() - t0)}s", flush=True)
    ok = [k for k in range(draws) if res_list[k] is not None]
    failed = draws - len(ok)
    Dd = np.stack([res_list[k]["D"] for k in ok])            # (ok, pairs, nc)
    Ed = np.stack([res_list[k]["eta"] for k in ok])          # (ok, L, NC)
    Pd = np.stack([res_list[k]["prof"] for k in ok])         # (ok, P)
    np.savez_compressed(os.path.join(a.out, f"draws_{side}.npz"), D=Dd, eta=Ed, prof=Pd, levels=levels)
    pair_rows, status = [], {}
    for pi, (i, j) in enumerate(pairs):
        row = {"a": levels[i], "b": levels[j]}
        for ci, nm in enumerate(["primary"] + [s[0] for s in SEC_CELLS]):
            x = Dd[:, pi, ci]
            fin = np.isfinite(x)
            f = int(draws - fin.sum())
            d0 = float(D_pt[pi, ci])
            if fin.sum() > 10:
                lo, hi = np.percentile(x[fin], [2.5, 97.5])
                basic_lo = 2 * d0 - hi
                row[nm] = {"D": round(d0, 5), "ci95Pct": [round(float(lo), 5), round(float(hi), 5)], "basicLower": round(float(basic_lo), 5),
                           "bias": round(float(np.mean(x[fin]) - d0), 5), "failedDraws": f,
                           "status": pair_status(d0, lo, basic_lo, f, draws)}
            else:
                row[nm] = {"D": round(d0, 5), "failedDraws": f, "status": "inconclusive"}
        status[frozenset((levels[i], levels[j]))] = row["primary"]["status"]
        pair_rows.append(row)
    final, ref, needs_dir, stmt = decide_levels(cands, status)
    if not final:
        raise SystemExit(f"{side}: no admissible level")
    # surfaces at the final levels from the SAME fit; conditional masks from the point data
    lab = {"P5": "low (P5)", "P50": "reference (P50)", "P95": "high (P95)"}
    tl = [{"label": f"{lab[c['name']] if len(final) > 1 else 'single (P50)'} ~{c['value']:g}C", "value": float(c["value"])} for c in final]
    surf = m._surfaces(res, spec, cc, temp_levels=tl)
    li = {lv: i for i, lv in enumerate(levels)}
    masks = [(n_pt[li[c["value"]]] >= MIN_N).reshape(len(SOC_EDGES) - 1, len(SPD_EDGES) - 1).astype(int).tolist() for c in final]
    surf["supportMaskMarginal"] = surf["supportMask"]
    surf["supportMaskByLevel"] = masks
    # maps and profile
    rI = li[ref["value"]]
    maps = []
    for c in final:
        if c["value"] == ref["value"]:
            continue
        j = li[c["value"]]
        diff = Ed[:, j, :] - Ed[:, rI, :]
        lo, hi = np.percentile(diff, [2.5, 97.5], axis=0)
        pt = etas_pt[0, j] - etas_pt[0, rI]
        sup = (n_pt[j] >= MIN_N) & (n_pt[rI] >= MIN_N)
        r = lambda v: np.round(v, 4).reshape(len(SOC_EDGES) - 1, len(SPD_EDGES) - 1).tolist()
        maps.append({"value": c["value"], "reference": ref["value"], "logHr": r(pt), "lo": r(lo), "hi": r(hi), "supported": sup.reshape(len(SOC_EDGES) - 1, len(SPD_EDGES) - 1).astype(int).tolist(),
                     "ciIncludesZero": ((lo <= 0) & (hi >= 0)).reshape(len(SOC_EDGES) - 1, len(SPD_EDGES) - 1).astype(int).tolist()})
    plo, phi = np.percentile(Pd, [2.5, 97.5], axis=0)
    mu, sd = spec.scale["tpack"]
    kn = spec.knots["tpack"]
    edges = np.arange(math.floor(tmin / STEP) * STEP, tmax + STEP, STEP)
    tp, yy = cc["tpack"].values, cc["y"].values
    rug = [{"binLowC": float(e), "nAtRiskS": int(((tp >= e) & (tp < e + STEP)).sum()), "nEvents": int((((tp >= e) & (tp < e + STEP)) & (yy > 0)).sum())} for e in edges]
    block = {"side": side, "basisNDrives": int(a.n_drives), "tpackMinC": round(tmin, 2), "tpackMaxC": round(tmax, 2),
             "linearTailBelowC": round(float(mu + sd * kn[0]), 2), "linearTailAboveC": round(float(mu + sd * kn[-1]), 2),
             "candidates": cands, "levels": [{**c, "role": ("reference" if c["value"] == ref["value"] else ("low" if c["value"] == final[0]["value"] else "high"))} for c in final],
             "referenceValue": ref["value"], "statement": stmt, "needsDirector": needs_dir, "pairs": pair_rows,
             "legacyPairs": [r for r in pair_rows if r["a"] in LEGACY and r["b"] in LEGACY],
             "profile": {"x": tgrid.tolist(), "hazard": np.round(prof_p, 6).tolist(), "lo": np.round(plo, 6).tolist(), "hi": np.round(phi, 6).tolist(),
                         "demandLevel": dem[1], "durationS": 15.0, "socMedian": round(med["soc"], 2), "speedMedian": round(med["speed"], 2)},
             "diffMaps": maps, "rug": rug,
             "bootstrap": {"draws": draws, "seed": 42, "failedDraws": failed, "failedRate": round(failed / draws, 5), "type": "day-clustered percentile, whole-pipeline refit per draw, levels held fixed",
                           "delta": round(DELTA, 6), "decision": "primary cell only (median demand, 15 s); distinct = percentile AND basic lower bound >= delta"},
             "nDaysWithEvents": {c["name"]: c["nDays"] for c in cands},
             "fewDaysFlag": {c["name"]: bool(c["nDays"] < 20) for c in cands},
             "katMaxAbsDiffVsM318": kat, "label": "model-derived, associational; not M299-reproducible (F03); not article-eligible",
             "provenance": {"master_md5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(),
                            "script_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "spec": "analyses/M320_spec.md",
                            "secs": round(time.time() - t0)}}
    if tbl410 is not None:
        c410 = tbl410.dropna(subset=m.CORE5).reset_index(drop=True)
        block["stability410"] = [{"name": c["name"], "value410": c["snapped"], "value489": next(x["snapped"] for x in cands if x["name"] == c["name"])} for c in select_levels(c410)]
    json.dump({"block": block, "surfaces": surf}, open(os.path.join(a.out, f"tempLadder_{side}.json"), "w", encoding="utf-8"), default=str)
    print(f"[{side}] DONE {round(time.time() - t0)}s final levels {[c['value'] for c in final]} failed {failed}", flush=True)


def cmd_run(a):
    os.makedirs(a.out, exist_ok=True)
    sys.path.insert(0, ROOT)
    P = pickle.load(open(a.tables, "rb"))
    a.n_drives = len(P["files"])
    P410 = pickle.load(open(a.tables410, "rb")) if a.tables410 else None
    for side in a.sides:
        tbl = P["tables"][0 if side == "start" else 1]
        t410 = (P410["tables"][0 if side == "start" else 1] if P410 else None)
        prev = None
        run_side(side, tbl, prev, a, t410)


def cmd_apply(a):
    p = os.path.join(ROOT, "summary_arrays.json")
    A = json.load(open(p, encoding="utf-8"))
    head = json.loads(subprocess.check_output(["git", "show", "HEAD:summary_arrays.json"], cwd=ROOT).decode("utf-8"))
    v2 = A["socHysteresisV2"]
    ladder = {}
    for side in ("start", "stop"):
        R = json.load(open(os.path.join(a.out, f"tempLadder_{side}.json"), encoding="utf-8"))
        ladder[side] = annotate_block(R["block"])
        v2["surfaces"][side] = R["surfaces"]
    v2["tempLadder"] = ladder
    st = A["_artifactStamps"]["socHysteresisV2"]
    note = st.get("computationStatusNote") or ""
    if "M320" not in note:
        st["computationStatusNote"] = (note + " | M320: surfaces re-levelled and tempLadder added (support-gated data-driven pack-temperature ladder; fitted model unchanged).").lstrip(" |")
    open(p, "w", encoding="utf-8", newline="\n").write(json.dumps(A, ensure_ascii=False, indent=1))
    A2 = json.load(open(p, encoding="utf-8"))
    diff = sorted(k for k in set(A2) | set(head) if A2.get(k) != head.get(k))
    assert set(diff) <= {"socHysteresisV2", "_artifactStamps"}, f"unexpected arrays keys changed: {diff}"
    sub = sorted(k for k in set(A2["socHysteresisV2"]) | set(head["socHysteresisV2"]) if A2["socHysteresisV2"].get(k) != head["socHysteresisV2"].get(k))
    assert set(sub) <= {"surfaces", "tempLadder"}, f"unexpected socHysteresisV2 keys changed: {sub}"
    sd = sorted(k for k in A2["_artifactStamps"] if A2["_artifactStamps"][k] != head["_artifactStamps"].get(k))
    assert set(sd) <= {"socHysteresisV2"}, f"stamps changed outside the intended set: {sd}"
    print(json.dumps({"arrays_keys_changed": diff, "socHysteresisV2_keys_changed": sub, "stamps_changed": sd}))


def main():
    ap = argparse.ArgumentParser(); sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("--tables", required=True); r.add_argument("--tables410"); r.add_argument("--out", required=True)
    r.add_argument("--draws", type=int, default=4000); r.add_argument("--workers", type=int, default=11); r.add_argument("--sides", nargs="+", default=["start", "stop"])
    r.set_defaults(f=cmd_run)
    p = sp.add_parser("apply"); p.add_argument("--out", required=True); p.set_defaults(f=cmd_apply)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
