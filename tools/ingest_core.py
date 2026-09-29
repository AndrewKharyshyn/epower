#!/usr/bin/env python3
"""Ingestion core (protocol steps 1-5, spec: analyses/M300_ingest_core_spec.md).

Additive, idempotent ingestion of NEW raw drive CSVs. Never calls run_pipeline() (no full reprocess, no ML refit drift).

Usage: python tools/ingest_core.py [--dry-run] [--recompute-m119v2]      (run from anywhere; works in the repo root)
Exit codes: 0 ok / no-op, 1 gate failed (nothing written, backups restored), 2 usage/setup error.
Writes (only on success): drive_master.csv, raw_manifest.json (append-only), summary_config.json (determinism block),
summary_arrays.json, tools/ingest_core_report.json. Backups of every file it touches: runs/ingest_core_<ts>/backup/.

Order (differs from the docstring of the stub on purpose; each step depends only on earlier ones):
 1. new-file detection; analyze_bytes per NEW file; append+sort; postprocess_master; restore the 16 ML/domain columns for
    pre-existing rows; GATE: ML16 0/16 diffs AND every pre-existing row unchanged in every column.
 2. raw_manifest.json: APPEND records for the new files (existing records/hashes untouched - owner decision 2026-09-29,
    raw/ treated as original; a full corpus_manifest.build() would overwrite them with this checkout's hashes).
 3. determinism_check.build(new master) -> summary_config.json auditMetadata.determinism AND summary_arrays.json determinism.
 4. build_summary_arrays(dm, loader, with_raw=True, raw_dir=<raw_only staging>, prev_arrays=<current>,
    recompute_energy_mc=True, recompute_m119v2=<flag, default False>, config forwarded exactly as run_pipeline does).
 5. crosscheck_vehicles.inject() + crosscheck_events.inject() (both MD5-assert drive_master.csv unchanged).
Downstream stages (post_steps, seasonal, cohort_arrays, build_html, jsdom, release_check) are separate stages in
tools/ingest_stages.json.

Raw staging: the code base loads raw files by the drive_master 'file' key, but this checkout stores 'YYYY-MM-DD HH-MM-SS.csv'
(space). A git-ignored raw_only/ directory of symlinks named by the master keys bridges the two."""
import argparse, datetime as dt, glob, hashlib, json, os, re, shutil, sys, traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

ML16 = ['drive_cluster_k3', 'iso_outlier', 'iso_score', 'lof_score', 'f_iso', 'f_lof', 'f_mad', 'f_domain', 'ens_outlier',
        'f_domain_2p', 'f_iso_i', 'f_lof_i', 'f_mad_i', 'ens_invalid', 'ens_extreme', 'ens_outlier_v2']
OUT_FILES = ["drive_master.csv", "raw_manifest.json", "summary_config.json", "summary_arrays.json"]
STAGING = os.path.join(ROOT, "raw_only")


class Gate(Exception):
    pass


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def digits(name):
    return re.sub(r"\D", "", os.path.basename(name).rsplit(".", 1)[0])


def master_key(basename):
    """'file' key for a NEW drive, following the latest master rows: archive-native names keep the dash form with '_'."""
    if re.match(r"^\d{4}-\d{2}-\d{2}[ _]\d{2}-\d{2}-\d{2}\.csv$", basename):
        return basename.replace(" ", "_")
    return basename.replace(" ", "_")


def raw_index(raw_dir):
    return {digits(f): os.path.join(raw_dir, f) for f in os.listdir(raw_dir) if f.lower().endswith(".csv")}


def stage_raw(dm_files, new_map, raw_dir, e4_files):
    """Symlink raw_only/<master key> -> real raw file. Returns the staging dir."""
    if os.path.isdir(STAGING):
        shutil.rmtree(STAGING)
    os.makedirs(STAGING)
    idx = raw_index(raw_dir)
    for f in dm_files:
        real = idx.get(digits(f))
        if real is None:
            raise Gate(f"raw file for master row {f} not found in {raw_dir}")
        os.symlink(real, os.path.join(STAGING, f))
    for key, real in new_map.items():
        os.symlink(real, os.path.join(STAGING, key))
    for f in e4_files:                                  # e-4ORCE / comparison files keep their raw names
        if os.path.exists(os.path.join(raw_dir, f)):
            os.symlink(os.path.join(raw_dir, f), os.path.join(STAGING, f))
    for f in os.listdir(raw_dir):
        if "_comparison" in f.lower() and not os.path.exists(os.path.join(STAGING, f)):
            os.symlink(os.path.join(raw_dir, f), os.path.join(STAGING, f))
    shutil.copy(os.path.join(ROOT, "raw_manifest.json"), os.path.join(STAGING, "raw_manifest.json"))
    return STAGING


def detect_new(dm, raw_dir):
    import compute_drive_summary_v6 as v6
    import corpus_manifest as cm
    files = sorted(glob.glob(os.path.join(raw_dir, "2026*.csv")))
    kept = v6._select_canonical_cohort(files, raw_dir, manifest_path=os.path.join(ROOT, "raw_manifest.json"),
                                       strict=False, verbose=False)
    have = {cm._canonical(f) for f in dm["file"].astype(str)}
    return [f for f in kept if cm._canonical(os.path.basename(f)) not in have]


def step1_master(dm_old, new_paths):
    import pandas as pd
    import compute_drive_summary_v6 as v6
    rows = []
    for p in new_paths:
        r = v6.analyze_bytes(open(p, "rb").read(), master_key(os.path.basename(p)))
        d, tm = v6._date_from_name(p)
        r.setdefault("date", d)
        r.setdefault("time_start", r.get("time_start") or tm)
        rows.append(r)
    new_df = pd.DataFrame(rows)
    merged = pd.concat([dm_old, new_df], ignore_index=True, sort=False)
    merged = merged.sort_values(["date", "time_start"], kind="stable").reset_index(drop=True)
    out = v6.postprocess_master(merged, verbose=False)
    dm_new = out[0] if isinstance(out, tuple) else out
    # ---- restore ML16 for pre-existing rows (archived values preferred), keyed by file
    old = dm_old.set_index("file")
    is_old = dm_new["file"].isin(old.index)
    for c in ML16:
        if c in dm_new.columns and c in old.columns:
            dm_new.loc[is_old, c] = old[c].reindex(dm_new.loc[is_old, "file"]).values
    # ---- GATES (compare through CSV text, exactly what lands on disk)
    tmp = os.path.join(ROOT, "runs", "_ingest_core_tmp_master.csv")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    dm_new.to_csv(tmp, index=False)
    chk = pd.read_csv(tmp, low_memory=False, dtype=str, keep_default_na=False)
    ref = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False, dtype=str, keep_default_na=False)
    chk_old = chk[chk["file"].isin(ref["file"])].reset_index(drop=True)
    ref = ref.set_index("file").loc[chk_old["file"]].reset_index()
    cols = [c for c in ref.columns if c in chk_old.columns]
    diffs = {c: int((ref[c] != chk_old[c]).sum()) for c in cols if (ref[c] != chk_old[c]).any()}
    ml_diffs = {c: n for c, n in diffs.items() if c in ML16}
    missing_cols = [c for c in ref.columns if c not in chk.columns]
    if len(chk_old) != len(ref) or missing_cols:
        raise Gate(f"pre-existing rows lost or columns dropped: rows {len(chk_old)}/{len(ref)}, missing {missing_cols}")
    if ml_diffs:
        raise Gate(f"ML16 restore not byte-exact: {ml_diffs}")
    if diffs:
        raise Gate(f"pre-existing rows changed by the new corpus (non-ML columns): {diffs}")
    os.remove(tmp)
    return dm_new, {"ml16_diffs": f"{len(ml_diffs)}/16", "preexisting_row_diffs": 0}


def step2_manifest(new_paths, dm_files_all):
    import corpus_manifest as cm
    man = json.load(open(os.path.join(ROOT, "raw_manifest.json"), encoding="utf-8"))
    have = {r["record_id"] for r in man["files"]}
    added = []
    for p in new_paths:
        base = os.path.basename(p)
        role, mode, reason = cm._classify(base)
        canon = cm._canonical(base)
        if role != "canonical" or canon in have:
            continue
        sha, nbytes, rows = cm._sha256_and_rows(p)
        added.append({"record_id": canon, "raw_name": master_key(base), "canonical": canon, "sha256": sha,
                      "normHash": cm._norm_hash(p), "bytes": nbytes, "rows": rows, "role": "canonical", "mode": mode,
                      "exclusion_reason": ""})
    man["files"].extend(added)
    recs = man["files"]
    canon = [r for r in recs if r["role"] == "canonical"]
    roles = {}
    for r in recs:
        roles[r["role"]] = roles.get(r["role"], 0) + 1
    man["corpusHash"] = hashlib.sha256("".join(sorted(r["sha256"] for r in canon)).encode()).hexdigest()
    man["contentHash"] = hashlib.sha256("".join(sorted(r["normHash"] for r in canon)).encode()).hexdigest()
    man["roles"] = roles
    integ = man["integrity"]
    integ.update({"nCanonical": roles.get("canonical", 0), "nMasterRows": len(dm_files_all),
                  "nFilesOnDisk": integ.get("nFilesOnDisk", 0) + len(added)})
    integ["oneToOneCanonical"] = integ["clean"] = (integ["nCanonical"] == integ["nMasterRows"]
                                                   and not roles.get("orphan") and not roles.get("missing"))
    snap = dt.datetime.now(dt.timezone.utc)
    man["parentSnapshot"] = man.get("snapshotId")
    man["snapshotId"] = f"{snap.strftime('%Y-%m-%d')}_{man['corpusHash'][:16]}"
    man["generatedUtc"] = snap.isoformat()
    man["appendOnlyNote"] = ("M301 ingest_core: records appended for new files only; existing records and hashes untouched "
                             "(raw/ treated as original by owner decision 2026-09-29).")
    if not integ["clean"]:
        raise Gate(f"manifest not 1:1 with master after append: {integ}")
    return man, [r["record_id"] for r in added]


def step3_determinism(master_path):
    import determinism_check as dc
    block, full = dc.build(master_path)
    return block, full


def step4_arrays(dm, raw_stage, recompute_m119v2):
    import compute_summary_arrays as csa
    import drive_raw_cache as drc
    cfg = json.load(open(os.path.join(ROOT, "summary_config.json")))
    prev = json.load(open(os.path.join(ROOT, "summary_arrays.json")))

    def loader(fn):
        with open(os.path.join(raw_stage, fn), "rb") as f:
            return f.read()
    drc.add_missing(list(dm["file"].astype(str)), raw_stage, verbose=False)
    arrays = csa.build_summary_arrays(
        dm, loader, with_raw=True, odometer_km=cfg.get("vehicle", {}).get("odometerKm"),
        seasonal_cfg=cfg.get("seasonalAssumptions"), ambient_by_drive=cfg.get("ambientByDrive"),
        frame_loader=drc.make_frame_loader(), session_cfg=cfg, raw_dir=raw_stage,
        recompute_m119v2=recompute_m119v2, prev_arrays=prev, recompute_energy_mc=True)
    if (arrays.get("energyUncertaintyMC") or {}).get("recomputeMode") != "fresh":
        raise Gate("energyUncertaintyMC.recomputeMode != 'fresh' (recompute_energy_mc must run on every ingestion)")
    if (cfg.get("sessions") or cfg.get("sessionGroups")) and not arrays.get("sessionLedgerAudit"):
        raise Gate("sessionLedgerAudit is null although config declares sessions (P0-14)")
    return arrays


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--recompute-m119v2", action="store_true")
    a = ap.parse_args()
    import pandas as pd
    report = {"tool": "ingest_core", "started": dt.datetime.now(dt.timezone.utc).isoformat(), "raw_dir": a.raw_dir}
    dm_old = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    report["rows_before"], report["md5_before"] = len(dm_old), md5(os.path.join(ROOT, "drive_master.csv"))
    new_paths = detect_new(dm_old, a.raw_dir)
    report["new_files"] = [os.path.basename(p) for p in new_paths]
    rpath = os.path.join(ROOT, "tools", "ingest_core_report.json")
    if not new_paths:
        report.update(status="noop", rows_after=len(dm_old), md5_after=report["md5_before"])
        json.dump(report, open(rpath, "w"), indent=1)
        print(json.dumps(report, indent=1)); return 0
    if a.dry_run:
        report["status"] = "dry_run"
        print(json.dumps(report, indent=1)); return 0

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bdir = os.path.join(ROOT, "runs", f"ingest_core_{ts}", "backup")
    os.makedirs(bdir)
    for f in OUT_FILES:
        shutil.copy2(os.path.join(ROOT, f), bdir)
    try:
        dm_new, g1 = step1_master(dm_old, new_paths)
        report.update(g1)
        new_map = {master_key(os.path.basename(p)): p for p in new_paths}
        e4 = [f for f in os.listdir(a.raw_dir) if f.lower().startswith("e4orce_") and f.lower() not in ("e4orce_master.csv", "e4orce_ambient.csv")]
        stage = stage_raw(list(dm_old["file"].astype(str)), new_map, a.raw_dir, e4)
        man, added = step2_manifest(new_paths, dm_new["file"])
        report["manifest_records_added"] = added
        # master written first (determinism + arrays + crosschecks read it from disk)
        dm_new.to_csv(os.path.join(ROOT, "drive_master.csv"), index=False)
        json.dump(man, open(os.path.join(ROOT, "raw_manifest.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        block, _ = step3_determinism(os.path.join(ROOT, "drive_master.csv"))
        cfg = json.load(open(os.path.join(ROOT, "summary_config.json")))
        cfg.setdefault("auditMetadata", {})["determinism"] = block
        json.dump(cfg, open(os.path.join(ROOT, "summary_config.json"), "w"), ensure_ascii=False, indent=1)
        dm_disk = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
        arrays = step4_arrays(dm_disk, stage, a.recompute_m119v2)
        arrays["determinism"] = block
        json.dump(arrays, open(os.path.join(ROOT, "summary_arrays.json"), "w"), ensure_ascii=False, indent=1)
        import crosscheck_vehicles as cv, crosscheck_events as ce
        m0 = md5(os.path.join(ROOT, "drive_master.csv"))
        cv.inject(arrays_path=os.path.join(ROOT, "summary_arrays.json"), master_csv=os.path.join(ROOT, "drive_master.csv"),
                  e4_master=os.path.join(ROOT, "e4orce_master.csv"), verbose=False)
        ce.inject(arrays_path=os.path.join(ROOT, "summary_arrays.json"), master_csv=os.path.join(ROOT, "drive_master.csv"),
                  e4_master=os.path.join(ROOT, "e4orce_master.csv"), raw_dir=stage, verbose=False)
        if md5(os.path.join(ROOT, "drive_master.csv")) != m0:
            raise Gate("crosscheck inject changed drive_master.csv")
        report.update(status="ok", rows_after=len(dm_disk), md5_after=m0, backup=os.path.relpath(bdir, ROOT))
        rc = 0
    except Exception as ex:
        for f in OUT_FILES:
            shutil.copy2(os.path.join(bdir, f), os.path.join(ROOT, f))
        report.update(status="gate_failed" if isinstance(ex, Gate) else "error", error=str(ex),
                      trace=None if isinstance(ex, Gate) else traceback.format_exc()[-1500:], restored_from=os.path.relpath(bdir, ROOT))
        rc = 1
    finally:
        shutil.rmtree(STAGING, ignore_errors=True)
    json.dump(report, open(rpath, "w"), indent=1)
    print(json.dumps({k: v for k, v in report.items() if k != "trace"}, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
