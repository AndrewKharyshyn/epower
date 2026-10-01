#!/usr/bin/env python3
"""M321 validation evidence (spec analyses/M321_spec.md rev 3, items (b)-(d)): writes analyses/M321_result.json (all numbers script-written).
Read-only on summary_arrays.json and the cache. Usage: python tools/m321_validate.py [--skip-path]"""
import argparse, copy, hashlib, json, os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.chdir(ROOT)
import numpy as np
import pandas as pd
import m320_ladder as L
import m321_ladder_monitor as M

ap = argparse.ArgumentParser(); ap.add_argument("--skip-path", action="store_true"); a = ap.parse_args()
A = json.load(open("summary_arrays.json", encoding="utf-8"))
v2 = A["socHysteresisV2"]; lad = v2["tempLadder"]
cache = M.load_cache()
dm = pd.read_csv("drive_master.csv", usecols=["file"], low_memory=False)
files = list(dm["file"])
md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
out = {"spec": "analyses/M321_spec.md", "spec_rev": 3, "master_md5": md5, "cache_sha256": M.sha256_bytes(open(M.CACHE, "rb").read()),
       "selection_code_sha256": M.code_sha(), "cache_stats": cache.get("stats"), "labels": "model-derived monitoring statistics; F03 label of the V2 block applies"}

# (c) equivalence with the M320 candidates, exact
eq = {}
for s in M.SIDES:
    cur = M.rows_frame(cache["entries"], files, s)
    qs = M.quantile_set(cur)
    rows = []
    for c in lad[s]["candidates"]:
        sup = M.band_support(cur, c["value"])
        ok = (qs[c["name"]]["quantileValue"] == c["quantileValue"] and qs[c["name"]]["snapped"] == c["snapped"] and qs[c["name"]]["dayWeightedSnapped"] == c["dayWeightedSnapped"]
              and sup["nEvents"] == c["nEvents"] and sup["nDays"] == c["nDays"] and sup["nAtRiskS"] == c["nAtRiskS"] and sup["admissible"] == c["admissible"])
        rows.append({"name": c["name"], "exact": bool(ok)})
    rng = (float(cur[cur["n"] > 0]["v"].min()), float(cur[cur["n"] > 0]["v"].max()))
    eq[s] = {"candidates": rows, "rangeFromCache": rng, "rangeInArrays": [lad[s]["tpackMinC"], lad[s]["tpackMaxC"]], "rangeConsistent": bool(abs(rng[0] - lad[s]["tpackMinC"]) < 0.0051 and abs(rng[1] - lad[s]["tpackMaxC"]) < 0.0051)}
out["equivalenceWithM320"] = eq
assert all(r["exact"] for s in M.SIDES for r in eq[s]["candidates"]), "cache statistics are not the M320 population"

# (b) incremental path == tables path
if not a.skip_path:
    p = subprocess.run([sys.executable, "tools/m321_ladder_monitor.py", "check-path", "--n", "30"], capture_output=True, text=True)
    out["pathEquivalence"] = json.loads(p.stdout.strip().splitlines()[-1])
    assert not out["pathEquivalence"]["mismatches"], out["pathEquivalence"]

# zero drift and rev 2 vs rev 3 W2 side by side
mon0 = M.build_monitor(A, cache, files, md5)
out["currentCorpus"] = {"status": mon0["status"], "warningCodes": mon0["warningCodes"], "information": mon0["information"]}
sbs = {}
for s in M.SIDES:
    cur = M.rows_frame(cache["entries"], files, s)
    fin = [l["value"] for l in lad[s]["levels"]]
    sbs[s] = {"lowestFinalLevel": min(fin), "rev2LiteralW2": M.w2_rev2_literal(cur, fin), "rev3W2": M.w2_candidates(cur, fin),
              "bandAtBound": {"level": min(fin) - 2 * L.BAND, **M.band_support(cur, min(fin) - 2 * L.BAND)}}
out["w2Rev2VsRev3"] = sbs
assert mon0["status"] == "ok" and not mon0["warningCodes"], "a warning on the zero-drift corpus is a monitor defect (spec falsification clause)"


def monitor_with(extra_entries=None, basis_files=None, raw_sha_now=None, code_stale=False, cur_files=None):
    c = copy.deepcopy(cache)
    fl = list(cur_files or files)
    for f, e in (extra_entries or {}).items():
        c["entries"][f] = e; fl.append(f)
    if basis_files is not None:
        c["basis"]["files"] = list(basis_files)
    if code_stale:
        c["basis"]["selectionCodeSha256"] = "0" * 64
    return M.build_monitor(A, c, fl, md5, raw_sha_now=raw_sha_now)


def summarize(b):
    return {"status": b["status"], "codes": b["warningCodes"], "warnings": b["warnings"], "information": b["information"]}


def syn(i, side_vals):
    return {"day": f"2026-12-{i + 1:02d}", "rawSha256": "synthetic", "start": {f"{v:.4f}": [n, ev] for v, (n, ev) in side_vals.items()}, "stop": {f"{v:.4f}": [n, ev] for v, (n, ev) in side_vals.items()}}


sc = {}
# forward replay: the ladder selection from the first 410 drives, monitored on the 489 corpus (diagnostic, not tuned)
b410 = files[:410]
lad410 = copy.deepcopy(lad)
for s in M.SIDES:
    d410 = M.rows_frame(cache["entries"], b410, s)
    qs = M.quantile_set(d410)
    for c in lad410[s]["candidates"]:
        c["quantileValue"] = qs[c["name"]]["quantileValue"]
    lad410[s]["levels"] = [{"value": qs["P5"]["snapped"]}, {"value": qs["P95"]["snapped"]}]
A410 = copy.deepcopy(A); A410["socHysteresisV2"]["tempLadder"] = lad410
c410 = copy.deepcopy(cache); c410["basis"]["files"] = b410
fr = M.build_monitor(A410, c410, files, md5)
sc["forwardReplay410"] = {**summarize(fr), "ladder410FinalLevels": {s: [l["value"] for l in lad410[s]["levels"]] for s in M.SIDES},
                          "rev2LiteralW2OnReplay": {s: M.w2_rev2_literal(M.rows_frame(cache["entries"], files, s), [l["value"] for l in lad410[s]["levels"]]) for s in M.SIDES}}
# injected cold drives (12 days, 12 events each at -5 C)
cold = {f"SYN_cold_{i}": syn(i, {-5.0: (2000, 12)}) for i in range(12)}
sc["injectedColdDrives"] = summarize(monitor_with(cold))
# injected 0.25 C creep below the fit-basis minimum (start 11.0, stop 11.5)
sc["injectedCreep0p25"] = summarize(monitor_with({"SYN_creep": {"day": "2026-12-01", "rawSha256": "synthetic", "start": {"10.7500": [100, 0]}, "stop": {"11.2500": [100, 0]}}}))
# exact gate boundary at L = lowest final level - 2*BAND: events needed to reach 100 / 99 in the closed band, injected at bound+0.5 (inside the band, not on an edge)
bnd = {}
for s in M.SIDES:
    cur = M.rows_frame(cache["entries"], files, s)
    lv = min(l["value"] for l in lad[s]["levels"]) - 2 * L.BAND
    have = M.band_support(cur, lv)
    bnd[s] = {"level": lv, "haveEvents": have["nEvents"], "haveDays": have["nDays"]}
for target, label in ((100, "passes_100"), (99, "fails_99")):
    ent = {}
    for s in M.SIDES:
        need = target - bnd[s]["haveEvents"]
        ent[s] = {f"{bnd[s]['level'] + 0.5:.4f}": [500, need]}
    b = monitor_with({"SYN_boundary": {"day": "2026-12-01", "rawSha256": "synthetic", "start": ent["start"], "stop": ent["stop"]}})
    sc["boundary_" + label] = {**summarize(b), "w2Candidates": {s: [c["level"] for c in b["sides"][s]["coldCandidates"]] for s in M.SIDES}}
sc["boundaryBase"] = bnd
# F03: a basis drive's raw sha256 changed -> separate flag, no drift
sha_now = dict(cache["basis"]["rawSha256"]); sha_now[files[0]] = "f" * 64
fb = monitor_with(raw_sha_now=sha_now)
sc["f03HashChange"] = {**summarize(fb), "flag": fb["f03ProvenanceFlag"]["basisFilesWithChangedRawSha256"]}
# selection-code change -> cache-invalid and the gate FAILs
cb = monitor_with(code_stale=True)
Ag = copy.deepcopy(A); Ag["socHysteresisV2"]["tempLadderMonitor"] = {**cb, "cacheSha256": out["cache_sha256"]}
sc["selectionCodeChange"] = {**summarize(cb), "gateFails": M.gate(Ag, ROOT)[0]}
out["scenarios"] = sc
json.dump(out, open("analyses/M321_result.json", "w", encoding="utf-8", newline="\n"), indent=1, default=str)
print(json.dumps({k: (v["status"] if isinstance(v, dict) and "status" in v else None) for k, v in sc.items() if isinstance(v, dict)}))
print("path:", out.get("pathEquivalence"))
