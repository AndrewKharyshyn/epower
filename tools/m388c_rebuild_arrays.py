#!/usr/bin/env python3
"""M388c (Director option (b), step 4/5): fresh arrays build from the corrected master, i.e. the arrays tail of tools/ingest_core.main() replayed on the live
master WITHOUT new-file detection (ingest_core is a no-op once the files are in the master). Same calls in the same order as ingest_core: determinism block
(summary_config.json auditMetadata.determinism), battery_temp_extremes.csv, step4_arrays (build_summary_arrays with prev_arrays = current payload,
recompute_energy_mc=True, estimator gate, carry-forward), determinism into the payload, crosscheck_vehicles / crosscheck_events inject, master MD5 unchanged.
Needed because the one-row master resplice changes rf_* / soc_* / vreg_* columns read in many payload blocks; key-by-key splicing is not reliable. The stages after
ingest_core (stage_raw ... release_check) must be re-run afterwards (run_ingest.py --from stage_raw), and the stamp notes re-issued.
Backs up the OUT_FILES first and restores them on any failure. Never writes drive_master.csv or raw files.
Usage (LF-preserving shim): PYTHONPATH=tools/eol_shim python tools/m388c_rebuild_arrays.py"""
import datetime as dt, json, os, shutil, sys, traceback
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import ingest_core as IC


def main():
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bdir = os.path.join(ROOT, "runs", f"m388c_rebuild_{ts}", "backup")
    os.makedirs(bdir)
    for f in IC.OUT_FILES:
        shutil.copy2(os.path.join(ROOT, f), bdir)
    IC.ACK["recal"] = os.environ.get("XT_ACK_RECALIBRATION") or None
    master = os.path.join(ROOT, "drive_master.csv")
    m0 = IC.md5(master)
    stage = IC.STAGING
    try:
        assert os.path.isdir(stage), "raw_only/ missing: run tools/stage_raw.py first"
        block, _ = IC.step3_determinism(master)
        cfg = json.load(open(os.path.join(ROOT, "summary_config.json")))
        cfg.setdefault("auditMetadata", {})["determinism"] = block
        IC.write_json(os.path.join(ROOT, "summary_config.json"), cfg, ensure_ascii=False, indent=1)
        dm_disk = pd.read_csv(master, low_memory=False)
        import battery_temp_extremes as bte
        IC._atomic(os.path.join(ROOT, "battery_temp_extremes.csv"), lambda t: bte.raw_pass(dm_disk, stage).to_csv(t, index=False))
        arrays = IC.step4_arrays(dm_disk, stage, False)
        arrays["determinism"] = block
        IC.write_json(os.path.join(ROOT, "summary_arrays.json"), arrays, ensure_ascii=False, indent=1)
        import crosscheck_vehicles as cv, crosscheck_events as ce
        cv.inject(arrays_path=os.path.join(ROOT, "summary_arrays.json"), master_csv=master,
                  e4_master=os.path.join(ROOT, "e4orce_master.csv"), verbose=False)
        ce.inject(arrays_path=os.path.join(ROOT, "summary_arrays.json"), master_csv=master,
                  e4_master=os.path.join(ROOT, "e4orce_master.csv"), raw_dir=stage, verbose=False)
        if IC.md5(master) != m0:
            raise IC.Gate("crosscheck inject changed drive_master.csv")
        print(json.dumps({"status": "ok", "rows": len(dm_disk), "masterMd5": m0, "estimatorChanges": list(IC.EST_CHANGES), "backup": os.path.relpath(bdir, ROOT)}, default=str))
        return 0
    except BaseException as ex:
        for f in IC.OUT_FILES:
            shutil.copy2(os.path.join(bdir, f), os.path.join(ROOT, f))
        print(json.dumps({"status": "failed", "error": repr(ex), "trace": traceback.format_exc()[-1500:], "restored_from": os.path.relpath(bdir, ROOT)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
