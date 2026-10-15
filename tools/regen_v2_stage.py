#!/usr/bin/env python3
"""M441 ingestion stage `regen_v2` (spec analyses/M441_spec.md Rev 2.1, section 5): extracts only the new or invalidated drives into the per-drive cache (tools/regen_v2_cache.py), aggregates all cohorts
(tools/regen_v2_agg.py) and splices ONE additive top-level key, regenCaptureV2 (+ its artifact stamp), into summary_arrays.json. With --study the on-demand study block regenCaptureV2Study (sensitivities, cadence-invariance
study; produced by tools/m441_study.py into analyses/M441_result.json) is spliced as well; ingestion carries that block forward unchanged (tools/ingest_core.carry_forward) until the study is re-run.
The legacy keys (regenCaptureMeasured, regenByTempMeasured, regenByZone, ...) are NOT touched in this stage; nothing here changes a displayed figure.
Usage: python tools/regen_v2_stage.py [--dry-run] [--study]"""
import copy, datetime, hashlib, json, os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import regen_v2 as R
import regen_v2_agg as G
import m441_study as S

KEYS = ["regenCaptureV2", "regenCaptureV2Study", "regenCaptureV2H", "regenCaptureV2HStudy", "regenSocStandardized", "regenSocStandardizedStudy"]
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()


def build_block(res, A, md5, st):
    base = res["cohorts"]
    return {"milestone": "M441", "spec": "analyses/M441_spec.md", "specSha256": sha("analyses/M441_spec.md"), "masterMd5": md5, "extractorVersion": R.EXTRACTOR_VERSION, "policy": R.POLICY, "policyHash": R.POLICY_HASH,
            "codeHashes": st["codeHashes"], "offsetA": float(A["offsetUncertainty"]["pointEstimateA"]), "bootstrap": {"B": G.B_DRAWS, "seed": G.SEED, "cluster": "calendar day"}, "socEdges": G.SOC_EDGES,
            "support": {"minStrictIntervals": G.MIN_N, "minDrives": G.MIN_DRIVES, "minDays": G.MIN_DAYS, "unidentifiedDrawMax": G.UNID_MAX},
            "label": "raw/ = sha256-verified originals (M366); apparent battery-side KE recovery with assumed masses (observed, not SOC-standardized); interval-based extractor v2; not a correction of the legacy values",
            "reading": ("Ratio of sums of battery-side charge energy to kinetic energy lost over the same engine-off deceleration intervals (consecutive native speed samples, actual duration, current and voltage interpolated, "
                        "unknown RPM never engine-off). Cells are observed, not standardized for SOC: temperature and SOC are confounded in the logged data. Intervals are counted in every speed bin they touch; support counts strict-drop intervals. "
                        "A cell is 'supported' with at least 200 strict-drop intervals on at least 10 drives and 5 days, otherwise 'thin' (exploratory). The assumed-mass range is kept apart from the statistical interval. "
                        "The 300 rpm engine-off proxy, the assumed masses and the cadence regime are declared conventions; a nonzero legacy-versus-v2 difference is not a correction of the legacy values."),
            "refresh": "recomputed at every ingestion by the stage regen_v2 (per-drive cache; only new or invalidated drives are re-extracted)",
            "disclosures": ["exclusion reasons are first-match in the order speedGap, rpmUnknown, engineOn, currentOrVoltageUnsupported, notDecelOrFlat: per-reason counts depend on that order, the kept intervals, KE and charge do not",
                            "the estimator excludes the trimmed leading and trailing plateau intervals (their charge is reported per cohort as withTrimmedPlateaus, with the ratio when they are included)",
                            "cells above 100 % are flagged (flagAbove100) and never clipped; the number of drives above 100 % is reported per cohort",
                            "SOC and temperature contrasts are confounded with speed, demand, day and the cadence regime; no temperature, SOC, BMS-limit or health statement follows from these cells",
                            "engine off is the RPM <= 300 proxy; the field name eff is a label for the apparent KE recovery ratio (assumed mass), not an efficiency",
                            "the cadence-invariance study (regenCaptureV2Study) FAILED on the pre-registered rule; the observed layer is cadence-sensitive by about 1-2 pp, the order of the assumed-mass half-width; no display is bound to these cells (stage ME blocked, Director ruling M441 Rev 2.2)"],
            "cohorts": base, "legacyComparison": S.legacy_block(A, base["all"]), "sensitivityEnsClean": res.get("sensitivityEnsClean")}


def study_block(md5):
    R_ = json.load(open("analyses/M441_result.json", encoding="utf-8"))
    if R_["_provenance"]["masterMd5"] != md5:
        raise SystemExit("analyses/M441_result.json was computed on a different master: re-run tools/m441_study.py")
    return {"milestone": "M441", "result": "analyses/M441_result.json", "resultSha256": sha("analyses/M441_result.json"), "masterMd5": md5, "extractorVersion": R_["_provenance"]["extractorVersion"],
            "policyHash": R_["_provenance"]["policyHash"], "reading": "Sensitivities are ranges over declared conventions, not confidence intervals. Cadence-invariance study: paired difference between the full-rate and the per-channel half-rate extraction on fast-cadence drives (days clustered); "
                                                                 "a cell fails if its interval excludes zero and the difference exceeds the half-width of its assumed-mass range.",
            "refresh": "on demand: re-run tools/m441_study.py when the extractor, the gates or the polling regime change, or after about 14 calendar days of new drives; each ingestion carries this block forward unchanged",
            "verdict": "failed; stage ME blocked (%d of %d supported decision cells fail the pre-registered cadence-invariance rule; the strict-drop-only population is invariant, the plateau rule carries the residual)" % (len(R_["cadenceInvariance"]["decision"]["supportedCellsFailing"]), R_["cadenceInvariance"]["decision"]["nSupportedCells"]),
            "sensitivities": R_["sensitivities"], "cadenceInvariance": R_["cadenceInvariance"]}


def h_blocks(A, md5):
    """M442 (spec Rev 1.2): the harmonized levels (interp3, four phases, 3 s grid) and the confirm-run study. Produced ONLY after the confirm run exists (C9: no even-day harmonized aggregate before it)."""
    import m442_gate as MG
    R1 = json.load(open("analyses/M442_result.json", encoding="utf-8"))               # the first confirm output (kept untouched)
    rr = os.path.exists("analyses/M442_result_rerun.json")
    R2 = json.load(open("analyses/M442_result_rerun.json", encoding="utf-8")) if rr else R1      # recorded-deviation rerun (spec C9) supersedes contrasts, G2 and sensitivities
    if R1["_provenance"]["masterMd5"] != md5:
        raise SystemExit("analyses/M442_result.json was computed on a different master: re-run the study (needs a recorded deviation, spec C9)")
    res, st = G.run(stack=MG.HARM, oos_delta=MG.DELTA, ens_clean=False)
    lvl = {"milestone": "M442", "spec": "analyses/M442_spec.md", "specSha256": R1["_provenance"]["specSha256"], "specSha256Current": sha("analyses/M442_spec.md"), "masterMd5": md5, "primary": "interp3", "deltaS": MG.DELTA, "phases": MG.PH, "extractorVersion": R.EXTRACTOR_VERSION, "codeHashes": st["codeHashes"],
           "label": "apparent KE recovery at common sampling resolution (3 s grid, assumed mass); resolution-conditional; assumed masses; not a correction of the legacy values",
           "reading": ("Levels of the v2 cells after every channel is reduced to a common 3 s grid (speed, current and voltage interpolated to the grid nodes, other channels latest sample, four grid phases averaged). The level depends on the resolution; the continuous-time recovery is not identified. "
                       "Each level is shown with its day-clustered interval and assumed-mass range; the resolution bracket b is in the study block. Contrasts between adjacent bins are 'resolved' only under the rule of spec M442 Rev 1.2 (D5); otherwise 'not resolved at this resolution'."),
           "outOfSupport": res.get("outOfSupport"), "refresh": "recomputed at every ingestion by the stage regen_v2 (after the M442 confirm run exists)", "cohorts": res["cohorts"]}
    study = {"milestone": "M442", "result": "analyses/M442_result_rerun.json" if rr else "analyses/M442_result.json", "resultSha256": sha("analyses/M442_result_rerun.json" if rr else "analyses/M442_result.json"),
             "firstOutput": "analyses/M442_result.json", "firstOutputSha256": sha("analyses/M442_result.json"), "deviation": R2.get("deviation"), "masterMd5": md5, "specSha256": R1["_provenance"]["specSha256"], "primary": "interp3",
             "verdict": R2.get("verdict"), "G1": R2.get("G1"), "G2": R2.get("G2"), "G3": R2.get("G3"), "H1": R2.get("H1"), "H2": R2.get("H2"), "bracket": R2.get("bracket"), "contrasts": R2.get("contrasts"), "sensitivities": R2.get("sensitivities"),
             "reading": ("Gates G1-G3 and the resolution bracket b of spec M442 Rev 1.2; H1 and H2 are reported and do not block. A contrast between adjacent bins is labelled resolved only if its even-day interval excludes 0, it exceeds b(A) + b(B), it has the same sign at both ends of the assumed-mass range and on even, odd and all days; contrasts are unadjusted for multiplicity. "
                         "Sensitivities are ranges over declared conventions, not confidence intervals."),
             "refresh": "on demand (a re-run of the confirm run needs a recorded deviation and a Director decision); each ingestion carries this block forward unchanged"}
    return lvl, study


def std_blocks(A, md5, with_study):
    """M444 (spec analyses/M444_spec.md Rev 2): the SOC-standardized bars (refreshed at every ingestion, only after the first real run exists: the run-once lock) and, on demand, the study block (demand ladder, holdouts, sensitivities) read from analyses/M444_result.json."""
    import regen_std as RS
    prim, _ = RS.run(study=False)
    first = json.load(open("analyses/M444_result.json", encoding="utf-8"))
    if first["_provenance"]["masterMd5"] != md5:
        raise SystemExit("analyses/M444_result.json was computed on a different master: re-run the study (needs a recorded deviation, spec B5)")
    state = {c: {v: {"available": b[v]["availability"]["available"], "groups": sorted(b[v]["bars"]), "bands": b[v]["commonSupportBands"]} for v in ("temperature", "speed")} for c, b in prim["cohorts"].items()}
    sp = "analyses/regen_std_state.json"
    old = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else None
    flags = [] if old is None else ["%s/%s: %s changed" % (c, v, k) for c in state for v in state[c] for k in ("available", "groups", "bands") if (old.get("state", {}).get(c, {}).get(v, {}) or {}).get(k) != state[c][v][k]]
    if flags:
        print("FLAG regen_std (S*, group set or availability changed at this refresh): " + "; ".join(flags))
    if "--dry-run" not in sys.argv:
        with open(sp, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"state": state, "lastFlags": flags}, f, indent=1, sort_keys=True)
    blk = dict(prim, milestone="M444", spec="analyses/M444_spec.md", specSha256=first["_provenance"]["specSha256"], masterMd5=md5, label=first["_provenance"]["label"],
               reading=("SOC-standardized apparent KE recovery (assumed mass): each bar is the KE-weighted combination over the common-support SOC bands of the joint-cell recoveries, standardized to the all-cohort reference SOC mix; it adjusts for the SOC composition of the groups only. "
                        "It is not adjusted for speed, demand, season, day or the polling cadence regime (pooled bars are cadence-mixed: see the fast-polled KE share of each bar), it is not an effect of temperature and not an efficiency. "
                        "A group without support in every retained SOC band is shown as unsupported for the comparison, never imputed. The intervals are conditional on the reference weights and the retained bands."),
               speedViewPopulation="The speed view uses intervals with a valid SOC at the interval start (a valid pack temperature is not required); the reference weights come from intervals with a valid pack temperature and a valid SOC; the speed view is restricted to 10-70 km/h in the retained groups (spec M444 Rev 2.2 S9).",
               refresh="recomputed at every ingestion by the stage regen_v2 (after the first run of the M444 analysis exists)")
    study = None
    if with_study and first.get("study"):
        study = dict(first["study"], milestone="M444", result="analyses/M444_result.json", resultSha256=sha("analyses/M444_result.json"), specSha256=first["_provenance"]["specSha256"], masterMd5=md5,
                     redundantSensitivities=["ensCleanDrives: the ens-flagged drives hold almost no kept intervals, so it reproduces the primary (spec M444 Rev 2.2 S11)"],
                     reading="Braking-demand check (episode deceleration ladder), chronological holdouts and sensitivities of the SOC-standardized bars; descriptive, with no decision resting on them; ranges over declared conventions, never combined with the statistical interval.",
                     refresh="on demand: each ingestion carries this block forward unchanged")
    return blk, study


def stamp_for(A, key, blk, md5, note):
    old = (A.get("_artifactStamps") or {}).get(key)
    if old and A.get(key) == blk and old.get("corpusHash") == md5:
        return old
    st = copy.deepcopy(A["_artifactStamps"]["thermalSupportLedger"])
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5}, computationStatusNote=note)
    st["includedInReleaseAt"] = st["computedAt"] = now
    st.pop("carriedForward", None)
    return st


def diff(a, b, p=""):
    if type(a) is not type(b):
        return [p]
    if isinstance(a, dict):
        return [x for k in sorted(set(a) | set(b)) for x in diff(a.get(k), b.get(k), p + "/" + k)]
    if isinstance(a, list):
        return [x for i, (u, v) in enumerate(zip(a, b)) for x in diff(u, v, p + "/%d" % i)] if len(a) == len(b) else [p + " len"]
    return [p] if a != b else []


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    raw = open("summary_arrays.json", "rb").read().decode("utf-8")
    A = json.loads(raw)
    rt = json.dumps(A, ensure_ascii=False, indent=1)
    if rt != raw and rt + chr(10) != raw:
        raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    res, st = G.run()
    bad_rec = [(c, k, v) for c, b in res["cohorts"].items() for k, rr in b["reconciliation"].items() for kk, v in rr.items() if (kk.startswith("n") and v != 0) or (not kk.startswith("n") and v > 1e-9)]
    if bad_rec:
        raise SystemExit("reconciliation (G3) failed: %r" % bad_rec[:5])
    N = copy.deepcopy(A)
    blk = build_block(res, A, md5, st)
    N["regenCaptureV2"] = blk
    N["_artifactStamps"]["regenCaptureV2"] = stamp_for(A, "regenCaptureV2", blk, md5, "M441: derived by tools/regen_v2_stage.py from the per-drive cache of the interval extractor v2 and the frame cache; additive observed apparent KE recovery by pack temperature, speed and SOC band")
    if "--study" in argv:
        sb = study_block(md5)
        N["regenCaptureV2Study"] = sb
        N["_artifactStamps"]["regenCaptureV2Study"] = stamp_for(A, "regenCaptureV2Study", sb, md5, "M441: derived by tools/m441_study.py (on demand); sensitivities and cadence-invariance study of the interval extractor v2; carried forward at ingestion")
    if os.path.exists("analyses/M442_confirm.lock") and os.path.exists("analyses/M442_result.json"):
        lvl, hs = h_blocks(A, md5)
        N["regenCaptureV2H"] = lvl
        N["_artifactStamps"]["regenCaptureV2H"] = stamp_for(A, "regenCaptureV2H", lvl, md5, "M442: derived by tools/regen_v2_stage.py from the per-drive cache (interp3 variants); additive harmonized levels of the apparent KE recovery")
        N["regenCaptureV2HStudy"] = hs
        N["_artifactStamps"]["regenCaptureV2HStudy"] = stamp_for(A, "regenCaptureV2HStudy", hs, md5, "M442: derived by tools/m442_gate.py (confirm run); gates, resolution bracket, contrasts and sensitivities; carried forward at ingestion")
    if os.path.exists("analyses/M444_first.lock") and os.path.exists("analyses/M444_result.json"):
        sb, sstudy = std_blocks(A, md5, "--study" in argv)
        N["regenSocStandardized"] = sb
        N["_artifactStamps"]["regenSocStandardized"] = stamp_for(A, "regenSocStandardized", sb, md5, "M444: derived by tools/regen_std.py from the per-drive cache; additive SOC-standardized apparent KE recovery by pack temperature and speed")
        if sstudy:
            N["regenSocStandardizedStudy"] = sstudy
            N["_artifactStamps"]["regenSocStandardizedStudy"] = stamp_for(A, "regenSocStandardizedStudy", sstudy, md5, "M444: derived by tools/regen_std.py (on demand); demand-ladder check, chronological holdouts and sensitivities; carried forward at ingestion")
    ch = diff(A, N)
    stray = [x for x in ch if not any(x == "/" + k or x.startswith("/" + k + "/") or x.startswith("/_artifactStamps/" + k) for k in KEYS)]
    print(json.dumps({"nChanged": len(ch), "stray": stray[:10], "extraction": {k: v for k, v in st.items() if k in ("nFiles", "cacheHits", "extracted", "seconds")}}))
    if stray:
        return 1
    if "--dry-run" not in argv and ch:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(N, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("wrote summary_arrays.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
