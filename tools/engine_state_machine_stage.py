#!/usr/bin/env python3
"""M546 (analyses/M546_spec.md Rev 2): wave 4 of the engine-on migration: additive top-level payload block engineStateMachineRule (+ stamp): the engineStateMachine of the pipeline with the strict engine-on boundary ('off' = rpm <= 400, so a state-grid
second at exactly 400 rpm is 'off', not 'low'), all drives and the three season cohorts, next to the stored block (rpm >= 400 is 'low'), which is not touched. The block is the FULL block of compute_summary_arrays._engine_state_machine(strict_off=True) over the
same drives and the same state grid (_esm_grid: 1 s mean resample, hold 3 s); cohorts come from the same function over the cohort subsets (thermal_regime of seasonal_drive_master.csv). The pooled kW / dwell lists are not fixed-size, so the stage recomputes the
whole block and caches the WHOLE result: the cache key (sha256 of the sorted (file, raw sha256) list, the dates, the thermal_regime map, the loader mode, the source hashes of _esm_grid / _esm_classify / _engine_state_machine / _ft / _apply_speed_priority,
_ESM_COLS, _ESM_STATES and the edges) is stored in the block provenance; an equal key reuses the block in the payload.
Gates (STOP, nothing written): drive set equal to the stored block; conservation on the UNROUNDED transition-matrix row sums (Rule off = stored off + n(exactly 400, last classified sample of each drive excluded), Rule low = stored low - the same n, the other rows
equal; the matrices differ only in the rows / columns of off and low); the tripwire A3 on the unrounded pooled off share (flag, written to detail). Usage: python tools/engine_state_machine_stage.py [--dry-run] [--check] [--rebuild]"""
import copy, datetime, hashlib, inspect, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

KEY = "engineStateMachineRule"
SPEC = "analyses/M546_spec.md"
COHORTS = ("warm", "shoulder", "cold")
MIN_DAYS = 5
A3_PP = 0.01          # escalation tripwire on the unrounded pooled off share (percentage points)


def loaders():
    import drive_raw_cache as drc
    import ah_throughput as AH
    return drc.make_frame_loader(raw_dir=os.path.abspath(os.path.join(ROOT, "raw_only"))), AH.raw_loader()


def cache_key(dm, sdm):
    import compute_summary_arrays as C
    import drive_raw_cache as drc
    import ah_throughput as AH
    load = AH.raw_loader()
    files = [(f, hashlib.sha256(load(f) or b"").hexdigest()) for f in sorted(dm["file"])]
    src = "".join(inspect.getsource(x) for x in (C._esm_grid, C._esm_classify, C._engine_state_machine, drc.fast_time, C._apply_speed_priority))
    parts = {"files": files, "dates": sorted(zip(dm["file"], dm["date"].astype(str))), "regime": sorted((f, str(sdm.get(f))) for f in dm["file"]), "loaderMode": "frame_loader raw_only/ (pipeline)",
             "sourceSha256": hashlib.sha256(src.encode("utf-8")).hexdigest(), "esmCols": repr(sorted(C._ESM_COLS.items())), "esmStates": repr(C._ESM_STATES), "edges": repr(C._ESM_EDGES), "strictOff": True}
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def exactly_400(dm, fl, rl):
    """per drive, on the state grid: seconds with rpm exactly 400 (all, and excluding the last classified sample of the drive); same drive eligibility as _engine_state_machine"""
    import compute_summary_arrays as C
    out = {}
    for _, r in dm.iterrows():
        g = C._esm_grid(r["file"], rl, fl)
        if g is None or "rpm" not in g.columns:
            continue
        g = g.dropna(subset=["rpm"])
        if len(g) < 20:
            continue
        v = g["rpm"].values
        st = C._esm_classify(v)
        if (st >= 0).sum() < 20:
            continue
        out[r["file"]] = (int((v == 400.0).sum()), int((v[:-1] == 400.0).sum()), int(len(v)))
    return out


def shares(blk):
    c = np.array(blk["transitionMatrix"]["counts"], float)
    rows = c.sum(1)
    return rows, rows / rows.sum() * 100.0


def compute(dm, sdm, A):
    import compute_summary_arrays as C
    fl, rl = loaders()
    pooled = C._engine_state_machine(dm, rl, frame_loader=fl, strict_off=True)
    byc = {}
    for c in COHORTS:
        sub = dm[dm["file"].map(sdm) == c]
        byc[c] = C._engine_state_machine(sub, rl, frame_loader=fl, strict_off=True) if len(sub) else None
    n400 = exactly_400(dm, fl, rl)
    stored = A["engineStateMachine"]
    rows_s, sh_s = shares(stored)
    rows_r, sh_r = shares(pooled)
    n_all, n_ex = sum(v[0] for v in n400.values()), sum(v[1] for v in n400.values())
    cs, cr = np.array(stored["transitionMatrix"]["counts"], float), np.array(pooled["transitionMatrix"]["counts"], float)
    mask = np.ones((5, 5), bool); mask[:2, :] = False; mask[:, :2] = False
    gates = {"driveSetEqualsStored": bool(pooled["nDrivesCovered"] == stored["nDrivesCovered"] and pooled["nDays"] == stored["nDays"]),
             "conservationRowSums": {"nExactly400LastExcluded": n_ex, "offRuleMinusStored": float(rows_r[0] - rows_s[0]), "lowRuleMinusStored": float(rows_r[1] - rows_s[1]), "otherRowsEqual": bool(np.array_equal(rows_r[2:], rows_s[2:]))},
             "matrixOutsideOffLowEqual": bool(np.array_equal(cr[mask], cs[mask]))}
    gates["conservationRowSums"]["passed"] = bool(gates["conservationRowSums"]["offRuleMinusStored"] == n_ex and gates["conservationRowSums"]["lowRuleMinusStored"] == -n_ex and gates["conservationRowSums"]["otherRowsEqual"])
    detail = {"pooled": {"nDrives": pooled["nDrivesCovered"], "nDays": pooled["nDays"], "exploratory": bool(pooled["nDays"] < MIN_DAYS), "secondsExactly400OnStateGrid": n_all, "secondsExactly400LastClassifiedExcluded": n_ex,
                         "pooledOffShareUnroundedPct": {"stored": round(float(sh_s[0]), 6), "rule": round(float(sh_r[0]), 6), "movePp": round(float(sh_r[0] - sh_s[0]), 6)},
                         "classifiedSecondsPooled": {"stored": int(rows_s.sum()), "rule": int(rows_r.sum())}},
              "byCohort": {c: (None if b is None else {"nDrives": b["nDrivesCovered"], "nDays": b["nDays"], "exploratory": bool(b["nDays"] < MIN_DAYS)}) for c, b in byc.items()},
              "perDriveExactly400": {f: {"all": v[0], "lastExcluded": v[1], "classifiedSeconds": v[2]} for f, v in sorted(n400.items()) if v[0]}}
    a3 = {"tripwire": "unrounded pooled off share moves by >= %.2f percentage points" % A3_PP, "hit": bool(abs(detail["pooled"]["pooledOffShareUnroundedPct"]["movePp"]) >= A3_PP),
          "otherStatesDiffer": bool(not np.array_equal(rows_r[2:], rows_s[2:]))}
    gates["A3"] = a3
    gates["passed"] = bool(gates["driveSetEqualsStored"] and gates["conservationRowSums"]["passed"] and gates["matrixOutsideOffLowEqual"] and not a3["hit"] and not a3["otherStatesDiffer"])
    return pooled, byc, detail, gates


def build_block(dm, sdm, A, rebuild=False):
    key = cache_key(dm, sdm)
    old = A.get(KEY)
    sha = lambda p: hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest()
    if old and not rebuild and (old.get("provenance") or {}).get("cacheKey") == key:
        return old, {"cacheHit": True, "passed": True}
    pooled, byc, detail, gates = compute(dm, sdm, A)
    blk = {"estimand": "engine operating-point state machine on the state grid (1 s mean resample, hold 3 s) with the strict engine-on boundary: 'off' = rpm <= 400, so a second at exactly 400 rpm is 'off'; the stored block (rpm >= 400 is 'low') is unchanged",
           "basis": "rpm > 400 (strict) for leaving 'off'; the state limits 1400 / 2300 / 3200 are not engine-on gates and stay '>='; a deterministic re-definition on the same data, not a correction",
           "rule": {"thresholdRpm": 400, "boundary": "gt", "name": "engine-on (rpm > 400)", "storedKey": "engineStateMachine", "offState": "rpm <= 400"}, "descriptive": True, "displayed": False,
           "pooled": pooled, "byCohort": byc, "detail": detail,
           "limits": ["logged rpm is app-reported, not measured", "the state grid differs from the pipeline grid of engineOnRule (1 s mean resample, hold 3 s, no native forward fill), so shares are compared only within this block",
                      "the pooled off share is a share of classified state-grid time, not of engine time", "no stored-versus-Rule contrast or difference interval is drawn",
                      "fewer than %d calendar days: exploratory, no interval reading" % MIN_DAYS, "the day bootstrap does not capture serial day correlation; convenience sample",
                      "engineDwellSurvival keeps the stored boundary (rpm >= 400): stored basis"],
           "provenance": {"spec": SPEC, "specSha256": sha(SPEC), "toolSha256": sha("tools/engine_state_machine_stage.py"), "cacheKey": key, "gates": gates,
                          "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "cohortSource": "thermal_regime of seasonal_drive_master.csv"}}
    return blk, gates


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new[KEY] = blk
    old = (A.get("_artifactStamps") or {}).get(KEY)
    if old and A.get(KEY) == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"][KEY] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M546: derived by tools/engine_state_machine_stage.py (compute_summary_arrays._engine_state_machine with strict_off) from drive_master.csv and the raw drive files through the pipeline frame loader; gates: drive set, unrounded row-sum conservation",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        import stamp_common as _sc
        new["_artifactStamps"][KEY] = _sc.carry_declared(old, st)
    ch = [k for k in set(A) | set(new) if A.get(k) != new.get(k)]
    bad = [k for k in ch if k not in (KEY, "_artifactStamps")]
    st_bad = [k for k in set(A["_artifactStamps"]) | set(new["_artifactStamps"]) if A["_artifactStamps"].get(k) != new["_artifactStamps"].get(k) and k != KEY]
    return new, ch, bad + st_bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False, usecols=["file", "thermal_regime"]).set_index("file")["thermal_regime"]
    raw_txt = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A = json.loads(raw_txt)
    blk, gates = build_block(dm, sdm, A, rebuild="--rebuild" in argv)
    if not gates.get("passed"):
        print(json.dumps({"STOP": "state-machine gates failed", "gates": gates}, default=float)[:3000])
        return 1
    if "--check" in argv:
        keep = lambda b: {k: v for k, v in (b or {}).items() if k != "provenance"}
        ok = keep(A.get(KEY)) == keep(blk)
        print(json.dumps({"check": KEY, "matchesPayload": ok, "cacheHit": bool(gates.get("cacheHit"))}))
        return 0 if ok else 1
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, ch, bad = splice(A, blk, md5)
    print(json.dumps({"gates": gates, "nChanged": len(ch), "outsideAllowList": bad}, default=float)[:2500])
    if bad:
        return 1
    if "--dry-run" not in argv and ch:
        with open("summary_arrays.json", "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + (chr(10) if raw_txt.endswith(chr(10)) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
