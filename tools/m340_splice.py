#!/usr/bin/env python3
"""M340 (audit F05/F06/F07, spec analyses/M340_spec.md rev 2): recompute ONLY batteryDrawGross and the Records rows with the repaired builders, check them against
independent known answers and the pre-registered allow-list, and splice them additively into summary_arrays.json (no pipeline run, master untouched).
Allow-list: batteryDrawGross.floor.*; Records rows 'Longest sustained 130+ km/h discharge' (replaced by 'Longest contiguous 130+ km/h discharge run'), the NEW row
'Cumulative 130+ km/h discharge exposure (single drive)' (inserted directly after it) and 'Battery intake air temperature max' (replaced in place); their disclosure leaves;
the _artifactStamps entries of batteryDrawGross, records and recordsContract. floorWarmHwy must NOT change (else STOP). Every other leaf byte-identical.
Usage: python tools/m340_splice.py [--dry-run]"""
import copy, datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import compute_summary_arrays as cs
import records_disclosure as RD

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M340_result.json")
OLD_HS, NEW_HS, NEW_CUM, TIN = "Longest sustained 130+ km/h discharge", "Longest contiguous 130+ km/h discharge run", "Cumulative 130+ km/h discharge exposure (single drive)", "Battery intake air temperature max"


def j(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, default=float)


def stop(msg, **kw):
    print(json.dumps({"STOP": msg, **kw}, indent=1, default=float))
    sys.exit(2)


def main():
    dry = "--dry-run" in sys.argv
    dm = pd.read_csv("drive_master.csv")
    A = json.load(open(ARR, encoding="utf-8"))
    old = copy.deepcopy(A)
    bad = cs._canonical_bad(dm)
    # ---- F05 ----
    new_b = json.loads(json.dumps(cs._battery_draw_gross(dm)))
    if j(new_b["floorWarmHwy"]) != j(old["batteryDrawGross"]["floorWarmHwy"]):
        stop("floorWarmHwy changed (pre-registered expectation: unchanged)", old=old["batteryDrawGross"]["floorWarmHwy"], new=new_b["floorWarmHwy"])
    thr = dm.gross_throughput_kwh / dm.distance_km * 100
    pool = thr[(dm.distance_km > 0.5) & ~bad].dropna()
    ki = pool.idxmin()
    assert abs(new_b["floor"]["kwh100"] - round(float(pool.loc[ki]), 2)) < 1e-9 and new_b["floor"]["n"] == len(pool)          # independent known answer
    # ---- F06 / F07 rows ----
    new_recs = cs._records(dm)
    by_new = {r["metric"]: r for r in new_recs}
    for m in (NEW_HS, NEW_CUM, TIN):
        if m not in by_new:
            stop("repaired row missing from the builder output", metric=m)
    clean = dm[~bad]
    run_max, cum_max = float(clean.highspeed_discharge_longest_run_s_130p.max()), float(clean.highspeed_discharge_s_130p.max())
    assert by_new[NEW_HS]["value"] == f"{run_max:.1f} s" and by_new[NEW_CUM]["value"] == f"{cum_max:.0f} s"
    te = pd.read_csv("battery_temp_extremes.csv")
    te_clean = te[te.file.isin(clean.file)]
    assert by_new[TIN]["value"] == f"{float(te_clean.intake_max.max()):.1f}°C"
    wf = te_clean.loc[te_clean.intake_max.idxmax(), "file"]
    mean_w = float(dm.loc[dm.file == wf, "T_intake"].iloc[0])
    assert mean_w <= float(te_clean.intake_max.max()) + 1e-9                                                                      # per-drive mean <= native max
    # ---- build the new records list (other rows must equal the builder output) ----
    stored = old["records"]
    new_list, seen = [], set()
    for r in stored:
        m = r["metric"]
        if m in (OLD_HS, NEW_HS):          # idempotent: also matches the already-spliced row
            new_list += [by_new[NEW_HS], by_new[NEW_CUM]]; seen |= {NEW_HS, NEW_CUM}
        elif m == NEW_CUM:
            continue
        elif m == TIN:
            new_list.append(by_new[TIN]); seen.add(TIN)
        else:
            new_list.append(r); seen.add(m)       # untouched rows are carried as stored (some are written by post-passes, e.g. rainflow rows, not by _records)
    extra = [m for m in by_new if m not in seen]
    if extra:
        stop("builder emits rows not in the stored list", rows=extra)
    # ---- apply ----
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    A["batteryDrawGross"] = new_b
    A["records"] = new_list
    for key, note in (("batteryDrawGross", "M340: floor recomputed with the shared canonical mask inside the builder (audit F05); floorWarmHwy unchanged; drive, n and context from the same pool."),
                      ("records", "M340: contiguous 130+ km/h run row, new cumulative-exposure row and native-sample intake-air maximum row (audit F06/F07); other rows unchanged.")):
        st = copy.deepcopy(A["_artifactStamps"][key]); st.update(generatedAt=now, computationStatus="computed", computationStatusNote=note); st.pop("carriedForward", None)
        A["_artifactStamps"][key] = st
    RD.apply(A, dm)
    # ---- deep-diff against the allow-list ----
    rest_old = {k: v for k, v in old.items() if k not in ("batteryDrawGross", "records", "_artifactStamps")}
    rest_new = {k: v for k, v in A.items() if k not in ("batteryDrawGross", "records", "_artifactStamps")}
    if j(rest_old) != j(rest_new):
        stop("a key outside the allow-list changed", keys=[k for k in rest_old if j(rest_old[k]) != j(rest_new.get(k))])
    so, sn = old["_artifactStamps"], A["_artifactStamps"]
    ch_st = [k for k in set(so) | set(sn) if j(so.get(k)) != j(sn.get(k))]
    if not set(ch_st) <= {"batteryDrawGross", "records", "recordsContract"}:
        stop("artifact stamps outside the allow-list changed", keys=ch_st)
    old_by, new_by = {r["metric"]: r for r in stored}, {r["metric"]: r for r in A["records"]}
    changed_rows = sorted(m for m in new_by if m not in old_by or j(new_by[m]) != j(old_by[m]))
    if set(changed_rows) - {NEW_HS, NEW_CUM, TIN}:
        stop("record rows outside the allow-list changed (including disclosure)", rows=changed_rows)
    order_old = [m for m in old_by if m not in (OLD_HS, NEW_HS, NEW_CUM)]
    order_new = [m for m in new_by if m not in (NEW_HS, NEW_CUM)]
    assert [m for m in order_old if m != TIN] == [m for m in order_new if m != TIN]                                              # preserved order of every other row
    hs_pos = list(new_by).index(NEW_HS)
    assert list(new_by)[hs_pos + 1] == NEW_CUM
    # F07 cap check (Director): the in-range maxima of the drives excluded whole by the 80 C cap must not exceed the winner
    ex_files = list(te.loc[te.intake_max_raw > 80, "file"])
    ch = "[BMS] HV Battery Intake Air Temperature (℃)"
    ex_max = {}
    for fx in ex_files:
        sx = pd.read_csv(os.path.join("raw_only", fx), usecols=lambda c: c == ch)[ch]
        sx = sx[(sx >= -40) & (sx <= 80)]
        ex_max[fx] = float(sx.max()) if sx.notna().any() else None
    win_val = float(te_clean.intake_max.max())
    if any(v is not None and v > win_val for v in ex_max.values()):
        stop("an in-range maximum of a cap-excluded drive exceeds the winner (definition question for the Director)", exMax=ex_max)
    import subprocess
    try:        # the committed baseline (git HEAD) is the stable 'before' for the result file, whatever number of re-runs
        head = json.loads(subprocess.check_output(["git", "show", "HEAD:summary_arrays.json"], cwd=ROOT).decode("utf-8"))
    except Exception:
        head = None
    prev = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    if head is not None and any(r["metric"] == OLD_HS for r in head["records"]):
        h_by = {r["metric"]: r for r in head["records"]}
        old_floor = head["batteryDrawGross"]["floor"]; old_hs_row = {k: v for k, v in h_by[OLD_HS].items() if k != "disclosure"}
        old_tin_row = {k: v for k, v in h_by[TIN].items() if k != "disclosure"}
        rows_vs_head = sorted(m for m in new_by if m not in h_by or {k: v for k, v in new_by[m].items() if k != "disclosure"} != {k: v for k, v in h_by[m].items() if k != "disclosure"})
        rows_vs_head += [OLD_HS + " (replaced by " + NEW_HS + ")"]
    else:
        rows_vs_head = None
    first = OLD_HS in old_by                      # on a re-run the 'before' values come from the first run's result file
    if rows_vs_head is None:
        old_floor = old["batteryDrawGross"]["floor"] if first else prev["F05"]["old"]
        old_hs_row = {k: v for k, v in old_by[OLD_HS].items() if k != "disclosure"} if first else prev["F06"]["oldRow"]
        old_tin_row = {k: v for k, v in old_by[TIN].items() if k != "disclosure"} if first else prev["F07"]["old"]
    census130 = next(b for b in A["highSpeedCensus"]["bands"] if b["kmh"] == 130)
    res = {"milestone": "M340", "audit": ["F05", "F06", "F07"], "controls": "unchanged builders reproduced the stored batteryDrawGross and the three stored rows leaf-for-leaf; highspeed_130_runlength_check.csv equals the master columns on its 26 files (max diff 0)",
           "mask": "canonical-clean = not (ens_invalid or ens_outlier_v2 is True); missing flag not excluded",
           "F05": {"old": old_floor, "new": new_b["floor"], "floorWarmHwy": "unchanged", "oldPoolN": 467, "consumers": "no jsx/summary_config consumer of batteryDrawGross.floor"},
           "F06": {"oldRow": old_hs_row, "newRun": {k: v for k, v in new_by[NEW_HS].items() if k != "disclosure"},
                   "newCumulative": {k: v for k, v in new_by[NEW_CUM].items() if k != "disclosure"},
                   "definitionComparison": {"masterRunColumnMaxS": run_max, "csvCheckMax": float(pd.read_csv("highspeed_130_runlength_check.csv").longest_run_s.max()),
                                            "highSpeedCensus130": {"maxStreakS": census130["maxStreakS"], "drive": census130["maxStreakDrive"], "definition": "longest continuous streak above 130 km/h irrespective of discharge state"},
                                            "note": "three definitions disagree by construction (run column: net-discharge only, capped steps summed across gaps; census: any state); reported, not tuned"}},
           "F07": {"old": old_tin_row, "new": {k: v for k, v in new_by[TIN].items() if k != "disclosure"},
                   "newDisclosure": new_by[TIN]["disclosure"], "winnerFile": wf, "winnerPerDriveMeanC": mean_w, "archive": "raw/ via raw_only (primary); originals not read",
                   "minRowControl": next(r["value"] for r in A["records"] if r["metric"] == "Battery intake air temperature min")},
           "deepDiff": {"otherTopLevelKeysChanged": 0, "otherStampsChanged": 0, "otherRecordRowsChanged": 0, "recordRowOrderPreserved": True, "newRowDirectlyAfterRun": True},
           "capCheck": {"nExcludedDrives": len(ex_files), "inRangeMaxOfExcludedDrives": {"min": min(v for v in ex_max.values() if v is not None), "max": max(v for v in ex_max.values() if v is not None)}, "winner": win_val},
           "changedRows": rows_vs_head if rows_vs_head is not None else changed_rows, "changedRowsThisRun": changed_rows, "changedStamps": sorted(ch_st), "limits": "master run column is not recomputed (v6 pipeline not run): capped steps are summed across log gaps; native intake maximum is from raw/ (F03 provenance-sensitive)"}
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, ensure_ascii=False, default=float); f.write("\n")
    status = "unchanged" if j(old) == j(A) else "spliced"
    if not dry and status != "unchanged":
        with open(ARR, "w", encoding="utf-8", newline="\n") as f:
            json.dump(A, f, ensure_ascii=False, indent=1)
    print(json.dumps({"status": status, "changedRows": changed_rows, "floor": [old_floor, new_b["floor"]], "run": new_by[NEW_HS]["value"], "cum": new_by[NEW_CUM]["value"],
                      "tin": [old_tin_row["value"], new_by[TIN]["value"]], "tinDrive": new_by[TIN]["drive"], "census130": census130["maxStreakS"]}, default=float))


if __name__ == "__main__":
    main()
