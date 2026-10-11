"""M372 helpers shared by the gtrClosure producers (analyses/M372_spec.md Rev 2). Read-only; imports nothing with side effects (never wire_gtr_seasonal).

check_raw_originals(): every raw file of the closure drives must match raw_manifest.json sha256 BEFORE a run may carry the M366 basis label.
assert_baseline_set(): the eligible set must equal the published M336 set (IDs, days, km) BEFORE any estimate is computed or written.
M372_BASIS is a parameter set only after those checks pass; it is never edited after a run."""
import hashlib, json, os
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE_DIR = os.path.join(ROOT, "analyses", "M372_baseline")
BASE_CSV = os.path.join(BASE_DIR, "M336_closure_perdrive.csv")
M372_BASIS = "raw/ = sha256-verified originals (M366)"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def check_raw_originals(canon_to_rawname):
    """canon_to_rawname: {canonical key (YYYYMMDD_HHMMSS.csv): file name in raw/}. Raises on any missing manifest record or sha256 mismatch."""
    man = {r["canonical"]: r for r in json.load(open(os.path.join(ROOT, "raw_manifest.json"), encoding="utf-8"))["files"] if r.get("role") == "canonical"}
    bad = []
    for canon, raw in canon_to_rawname.items():
        rec = man.get(canon)
        if rec is None:
            bad.append((canon, "no manifest record"))
        elif sha256(os.path.join(ROOT, "raw", raw)) != rec["sha256"]:
            bad.append((canon, "sha256 differs"))
    if bad:
        raise SystemExit("raw originals check FAILED (%d of %d): %s" % (len(bad), len(canon_to_rawname), bad[:5]))
    return {"nChecked": len(canon_to_rawname), "nMismatch": 0}


def assert_baseline_set(files, dm):
    """files: eligible drive keys of this run; dm: drive_master DataFrame. Raises unless IDs, n days and km equal the published M336 set."""
    base = pd.read_csv(BASE_CSV)
    pub = set(base["file"])
    got = set(files)
    if got != pub:
        raise SystemExit("ID-set mismatch vs published M336 set: only-new %s, only-published %s" % (sorted(got - pub)[:5], sorted(pub - got)[:5]))
    sub = dm[dm["file"].isin(got)]
    n_days, km = int(sub["date"].astype(str).nunique()), round(float(sub["distance_km"].sum()), 1)
    if n_days != int(base["date"].nunique()) or km != round(float(base["km"].sum()), 1):
        raise SystemExit("n days / km mismatch: %s / %s vs published %s / %s" % (n_days, km, int(base["date"].nunique()), round(float(base["km"].sum()), 1)))
    return {"nDrives": len(got), "nDays": n_days, "km": km}


# ---- M377c (analyses/M377c_spec.md Rev 2): ingestion mode ----
RECORD = os.path.join(ROOT, "analyses", "gtr_closure_record.json")     # pins the previous per-drive file (path + sha256) of the closure refresh


def load_record():
    return json.load(open(RECORD, encoding="utf-8"))


def previous_perdrive():
    """The previous per-drive closure file, pinned by sha256 in the committed run record. A missing or mismatching file is a STOP."""
    rec = load_record()["previousPerDrive"]
    p = os.path.join(ROOT, rec["path"])
    if not os.path.exists(p):
        raise SystemExit("STOP: previous closure per-drive file missing: " + rec["path"])
    if sha256(p) != rec["sha256"]:
        raise SystemExit("STOP: previous closure per-drive file sha256 differs from the record: " + rec["path"])
    return pd.read_csv(p), rec


def assert_flags_equal(dm):
    """ens_outlier_v2 == ens_invalid wherever both exist (the closure diagnostic checks only ens_outlier_v2); STOP on any divergence."""
    both = dm[["ens_outlier_v2", "ens_invalid"]].dropna()
    bad = both[both["ens_outlier_v2"].astype(str) != both["ens_invalid"].astype(str)]
    if len(bad):
        raise SystemExit("STOP: ens_outlier_v2 and ens_invalid diverge on %d drives" % len(bad))
    return {"nCompared": int(len(both)), "nDiverging": 0}


def assert_expected_set(files, dm):
    """Expected-set rule (replaces the published-baseline equality): the eligible set must CONTAIN every previous closure drive; the new IDs (drives added since)
    are listed. A previous ID missing from the eligible set is a STOP (it would silently drop a drive from the block)."""
    prev, rec = previous_perdrive()
    got, pub = set(files), set(prev["file"])
    missing = sorted(pub - got)
    if missing:
        raise SystemExit("STOP: previous closure drives no longer eligible: %s" % missing[:5])
    new = sorted(got - pub)
    flagged = dm[dm["file"].isin(new) & ((dm["ens_outlier_v2"].astype(str) == "True") | (dm["ens_invalid"].astype(str) == "True"))]
    if len(flagged):
        raise SystemExit("STOP: new closure drives are canonical-flagged (ineligible): %s" % flagged["file"].tolist()[:5])
    sub = dm[dm["file"].isin(got)]
    ndays, km = int(sub["date"].astype(str).nunique()), round(float(sub["distance_km"].sum()), 1)
    newrows = dm[dm["file"].isin(new)][["file", "date", "distance_km", "drive_type"]]
    return {"nDrives": len(got), "nDays": ndays, "km": km, "nPrevious": len(pub), "nNew": len(new),
            "newIds": [{"file": r.file, "date": str(r.date), "km": round(float(r.distance_km), 3), "type": r.drive_type} for r in newrows.itertuples()],
            "previousPerDrive": rec}


def repin_previous(d, prev, rec, reason, evidence=None):      # rec = the previous pin ({"path", "sha256", ...}) as returned by previous_perdrive(); evidence = M398 attribution block (automatic variant)
    """One-time re-pin (M377c Director ruling, a stated deviation from spec Rev 2 item 1): after an acknowledged recalibration AND a passing attribution test
    (analyses/M377c_attribution_scratch.py; recorded in the CHANGELOG), the previous IDs' outputs on the new master become the pinned previous per-drive file.
    Identity stays exact for later runs; this is not a tolerance. Writes the subset file and moves the pin in analyses/gtr_closure_record.json."""
    cur = d.round(5).set_index("file")
    sub = cur.loc[prev["file"], [c for c in prev.columns if c != "file" and c in cur.columns]].reset_index()
    if evidence is None:
        dest = os.path.join("analyses", "closure_baselines", "perdrive_%ddrives_recal.csv" % len(sub))
    else:                                                                     # M398: unique per master, so no earlier pin file is ever overwritten
        mm = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()[:8]
        dest = os.path.join("analyses", "closure_baselines", "perdrive_%ddrives_recal_%s.csv" % (len(sub), mm))
    os.makedirs(os.path.join(ROOT, "analyses", "closure_baselines"), exist_ok=True)
    sub.to_csv(os.path.join(ROOT, dest), index=False, lineterminator="\n")
    rec_new = {"previousPerDrive": {"path": dest.replace(os.sep, "/"), "sha256": sha256(os.path.join(ROOT, dest)), "nDrives": int(len(sub))},
               "repinnedFrom": rec, "repinReason": reason,
               "note": ("re-pinned once after the acknowledged M376 offset recalibration; identity stays exact (1e-5) for later runs" if evidence is None else
                        "re-pinned automatically (M398): closure drift attributed to the recalibrated offset columns, hybrid run reproduces the previous pin exactly; identity stays exact (1e-5) for later runs")}
    if evidence is not None:
        rec_new["attribution"] = evidence
        try:
            rec_new["originalPin"] = load_record().get("originalPin") or rec          # first pin of the chain; later auto re-pins are bounded against it
        except Exception:
            rec_new["originalPin"] = rec
        rec_new["previousPerDrive"]["master"] = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    with open(RECORD, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec_new, indent=1) + "\n")
    return rec_new


def identity_drift(d, prev):
    """The identity rule of the pin, without raising (M398 refactor of assert_previous_identity): returns ([(column, n drives changed)], {column: magnitude}, [previous IDs missing from d]).
    Rule unchanged: the per-drive outputs of every previous ID must equal the pinned file (as written: rounded to 5 decimals; numeric columns within 1e-5, others as text)."""
    cur = d.round(5).set_index("file")
    old = prev.set_index("file")
    missing = [f for f in old.index if f not in cur.index]
    old = old.loc[[f for f in old.index if f in cur.index]]
    cols = [c for c in old.columns if c in cur.columns]
    diff, mag = [], {}
    for c in cols:
        a, b = cur.loc[old.index, c], old[c]
        if pd.api.types.is_numeric_dtype(b):
            bad = ((a - b).abs() > 1e-5) & ~(a.isna() & b.isna())
        else:
            bad = a.astype(str) != b.astype(str)
        if bad.any():
            diff.append((c, int(bad.sum())))
            if pd.api.types.is_numeric_dtype(b):
                dd = (a - b).abs()
                mag[c] = {"nDrivesChanged": int(bad.sum()), "maxAbs": round(float(dd.max()), 6), "medianAbsAmongChanged": round(float(dd[dd > 1e-5].median()), 6),
                          "colSumPrevious": round(float(b.sum()), 5), "colSumNew": round(float(a.sum()), 5),
                          "colSumRelChange": round(float(abs(a.sum() - b.sum()) / (abs(b.sum()) or 1.0)), 8)}
            else:
                mag[c] = {"nDrivesChanged": int(bad.sum())}
    return diff, mag, missing, len(old), len(cols)


def write_drift_report(d, prev, attribution=None):
    """analyses/M377c_identity_drift.json: written BEFORE a STOP so the size of the differences is visible to the Director (and, since M398, with the attribution evidence)."""
    diff, mag, missing, n_old, _ = identity_drift(d, prev)
    rep = {"nPrevious": int(n_old), "columns": mag}
    if missing:
        rep["missingPreviousIds"] = missing[:20]
    if attribution is not None:
        rep["attribution"] = attribution
    with open(os.path.join(ROOT, "analyses", "M377c_identity_drift.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rep, indent=1) + "\n")
    return diff


def assert_previous_identity(d, prev):
    """The per-drive outputs of every previous ID must equal the pinned previous per-drive file (as written: rounded to 5 decimals). Otherwise STOP:
    code / provenance drift is separated from new data."""
    diff, mag, missing, n_old, n_cols = identity_drift(d, prev)
    if diff or missing:
        write_drift_report(d, prev)
        raise SystemExit("STOP: per-drive outputs of previous closure IDs differ from the pinned file: %s (analyses/M377c_identity_drift.json)" % (diff[:5] or ["missing previous IDs: %s" % missing[:3]]))
    return {"nIdentical": int(n_old), "columns": n_cols}


# ---- M398 (analyses/M398_spec.md): attributed re-pin after recalibration drift ----
TOL_MAX_ABS, TOL_COLSUM_REL = 1e-3, 1e-3


def attribute_recalibration_drift(d, prev, rec, d_hybrid, old_master, new_master, recal_cols, head_master_md5, orig=None):
    """All four conditions of M398 must hold, otherwise STOP (nothing is written). d: closure rows of the run (current master); d_hybrid: the same rows recomputed from the PRE-ingestion master rows;
    old_master / new_master: the pre-ingestion and current master as TEXT frames (dtype=str); recal_cols: the columns a recalibration may change on pre-existing rows.
    Returns the evidence block (also stored in the drift report and the pin record)."""
    ids = list(prev["file"])
    if rec.get("master") != head_master_md5:
        raise SystemExit("STOP (M398): the pin was made on a master (%s) that is not the committed pre-ingestion master (%s): drift cannot be attributed" % (rec.get("master"), head_master_md5))
    om, nm = old_master.set_index("file"), new_master.set_index("file")
    miss = [f for f in ids if f not in om.index or f not in nm.index]
    if miss:
        raise SystemExit("STOP (M398): previous IDs missing from the pre-ingestion or current master: %s" % miss[:3])
    om, nm = om.loc[ids], nm.loc[ids]
    cols = [c for c in om.columns if c in nm.columns]
    changed = sorted(c for c in cols if (om[c] != nm[c]).any())
    other = [c for c in changed if c not in set(recal_cols)]
    if other:
        raise SystemExit("STOP (M398): master columns other than the recalibration columns changed on previous IDs: %s" % other[:6])
    hd, _, hmiss, _, _ = identity_drift(d_hybrid, prev)
    if hd or hmiss:
        raise SystemExit("STOP (M398): the hybrid run (pre-ingestion master rows, current code) does NOT reproduce the pinned file exactly (%s): code, raw or provenance drift, not recalibration drift" % (hd[:5] or hmiss[:3]))
    diff, mag, missing, _, _ = identity_drift(d, prev)
    if missing:
        raise SystemExit("STOP (M398): previous IDs missing from the current closure rows: %s" % missing[:3])
    nonnum = sorted(c for c, m in mag.items() if "maxAbs" not in m)
    if nonnum:                                                              # Director (M398): a non-numeric closure column cannot be a recalibration effect
        raise SystemExit("STOP (M398): non-numeric closure columns differ from the pin: %s" % nonnum[:6])
    big = {c: m for c, m in mag.items() if m.get("maxAbs", 0) > TOL_MAX_ABS or m.get("colSumRelChange", 0) > TOL_COLSUM_REL}
    if big:
        raise SystemExit("STOP (M398): recalibration drift exceeds the pre-registered tolerance (maxAbs %g, column-sum relative %g): %s" % (TOL_MAX_ABS, TOL_COLSUM_REL, sorted(big)))
    cum = None
    if orig is not None:                                                    # Director (M398): cumulative drift against the ORIGINAL pin is bounded by the same tolerance
        _, cmag, cmiss, _, _ = identity_drift(d, orig)
        cbig = {c: m for c, m in cmag.items() if "maxAbs" not in m or m.get("maxAbs", 0) > TOL_MAX_ABS or m.get("colSumRelChange", 0) > TOL_COLSUM_REL}
        if cmiss or cbig:
            raise SystemExit("STOP (M398): cumulative drift against the original pin exceeds the tolerance (Director ruling needed): %s" % (sorted(cbig) or cmiss[:3]))
        cum = {c: {k: m[k] for k in ("maxAbs", "colSumRelChange")} for c, m in cmag.items()}
    return {"rule": "M398", "pinMasterEqualsCommittedMaster": True, "masterColumnsChangedOnPreviousIds": changed, "allWithinRecalibrationColumns": True,
            "hybridRunIdentityExact": True, "nPrevious": len(ids), "tolerance": {"maxAbs": TOL_MAX_ABS, "colSumRelChange": TOL_COLSUM_REL},
            "driftColumns": {c: {k: m[k] for k in ("nDrivesChanged", "maxAbs", "colSumRelChange") if k in m} for c, m in mag.items()},
            "nDrivesChangedConvention": "at >1e-5 on 5-dp rounded values (descriptive only; the decision uses maxAbs and colSumRelChange)",
            "cumulativeVsOriginalPin": cum}
