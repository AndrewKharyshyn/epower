#!/usr/bin/env python3
"""M440 splice (analyses/M440_spec.md Rev 2.1, gate G2): adds ONE additive top-level key, regenLegacySensitivity (+ its artifact stamp), to summary_arrays.json from the script-written
analyses/M440_result.json (tools/m440_regen_sens.py, which also passed gate G1 = exact reproduction of the published bins). Top-level keys the arrays build does not produce are carried forward by
tools/ingest_core.carry_forward, so the block stays until the study is re-run (on demand: when the extractor, the gates or the polling regime change, or after about 14 calendar days of new drives).
Every number is read from the result file (nothing typed). The deep diff against the current payload must show exactly this key and its stamp. Idempotent.
Usage: python tools/m440_splice.py [--dry-run]     |     python tools/m440_splice.py --verify RESULT2.json   (gate G3: a second run gives a byte-identical block)"""
import copy, datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
DRY = "--dry-run" in sys.argv
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
KEEP_BIN = ("n0", "n", "days0", "days", "eff0", "eff", "delta", "deltaCi95", "massHalfWidth", "retainedKeShare", "retainedDayShare", "effRemoved", "validLegacy", "decision", "offsetShiftPp")


def build(R, spec_sha, script_sha, result_sha):
    out = {"milestone": "M440", "spec": R["_provenance"]["spec"], "specSha256": spec_sha, "result": "analyses/M440_result.json", "resultSha256": result_sha, "scriptSha256": script_sha,
           "masterMd5": R["_provenance"]["masterMd5"], "label": R["_provenance"]["label"], "offsetA": R["_provenance"]["offsetA"], "bootstrap": R["_provenance"]["bootstrap"],
           "reproduction": {"ok": R["G1"]["ok"], "nStepsReproduced": R["G1"]["nStepsReproduced"], "note": "every published temperature and speed bin (n and eff) is reproduced exactly by the study's extractor before any variant is read"},
           "reading": ("Sensitivity of the legacy apparent KE recovery (assumed masses) to the extraction rule: each variant changes one declared rule and is compared with the legacy bar on the same drives. "
                       "Delta is a range over declared conventions, not a confidence interval and not a correction of the legacy values; a nonzero Delta does not show which rule is closer to the truth. "
                       "A defect is 'material' if |Delta| exceeds the half-width of the bin's published mass-uncertainty range and its 95 % day-clustered interval excludes zero in at least one valid legacy bin; "
                       "'notMaterial' is not evidence of harmlessness."),
           "refresh": "on demand: re-run when the extractor, the gates or the polling regime change, or after about 14 calendar days of new drives; each ingestion carries this block forward unchanged",
           "variantsDeclared": {"V1_rpmKnown": "exclude steps with a missing RPM grid value (legacy: missing = engine-off)", "V2_age2/5/10": "exclude steps whose speed, current, voltage or RPM native sample is older than k s",
                                "V3_contiguous": "exclude steps whose previous kept row is not exactly 1 s earlier", "V4_startSpeedBin": "bin the speed view by the step start speed (legacy: end speed)",
                                "V5_fullProbe": "temperature view: all four probes present", "V6_offset": "apply the declared current offset (logged current + i_off)",
                                "VCa_combined": "V1 + V2(5) + V3 (+ V5 on the temperature view, + V4 on the speed view)", "VCb_combinedOffset": "VCa + V6"},
           "cohorts": {}}
    for coh, c in R["cohorts"].items():
        cc = {"nSteps": c["nSteps"], "nDrives": c["nDrives"], "nDays": c["nDays"], "ageMaxShare": c["ageMaxShare"], "ageStrata": c["ageStrata"], "legacyByCadence": c["legacyByCadence"], "flagShare": c["flagShare"], "variants": {}}
        for vn, v in c["variants"].items():
            x = {"retained": v["retained"], "materialDefect": v["materialDefect"], "materialBins": v["materialBins"]}
            if "binMigration" in v:
                x["binMigration"] = v["binMigration"]
            for kind in ("temp", "speed"):
                if kind in v:
                    x[kind] = {b: {k: r[k] for k in KEEP_BIN if k in r} for b, r in v[kind].items()}
            cc["variants"][vn] = x
        out["cohorts"][coh] = cc
    return out


def main():
    R = json.load(open("analyses/M440_result.json", encoding="utf-8"))
    if "--verify" in sys.argv:
        R2 = json.load(open(sys.argv[sys.argv.index("--verify") + 1], encoding="utf-8"))
        same = json.dumps(build(R, "x", "x", "x"), sort_keys=True) == json.dumps(build(R2, "x", "x", "x"), sort_keys=True)
        print(json.dumps({"G3_identical_block": same}))
        raise SystemExit(0 if same else 1)
    raw = open("summary_arrays.json", "rb").read().decode("utf-8")
    A = json.loads(raw)
    if json.dumps(A, ensure_ascii=False, indent=1) != raw:
        raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    if R["_provenance"]["masterMd5"] != md5:
        raise SystemExit("M440_result.json was computed on a different master")
    if not R["G1"]["ok"]:
        raise SystemExit("gate G1 did not pass in the result file")
    blk = build(R, sha("analyses/M440_spec.md"), sha("tools/m440_regen_sens.py") + "+" + sha("tools/m440_analyse.py")[:16], sha("analyses/M440_result.json"))
    N = copy.deepcopy(A)
    changed = N.get("regenLegacySensitivity") != blk
    N["regenLegacySensitivity"] = blk
    old = (A.get("_artifactStamps") or {}).get("regenLegacySensitivity")
    if old and not changed and old.get("corpusHash") == md5:
        N["_artifactStamps"]["regenLegacySensitivity"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["thermalSupportLedger"])
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
                  computationStatusNote="M440: derived by tools/m440_regen_sens.py from the frame cache and the raw files; additive sensitivity of the legacy apparent KE recovery to the extraction rule; on demand, carried forward at ingestion")
        st["includedInReleaseAt"] = st["computedAt"] = now
        st.pop("carriedForward", None)
        N["_artifactStamps"]["regenLegacySensitivity"] = st

    def diff(a, b, p=""):
        if type(a) is not type(b):
            return [p]
        if isinstance(a, dict):
            return [x for k in sorted(set(a) | set(b)) for x in diff(a.get(k), b.get(k), p + "/" + k)]
        if isinstance(a, list):
            return [x for i, (u, v) in enumerate(zip(a, b)) for x in diff(u, v, p + "/%d" % i)] if len(a) == len(b) else [p + " len"]
        return [p] if a != b else []

    d = diff(A, N)
    stray = [x for x in d if not (x.startswith("/regenLegacySensitivity") or x.startswith("/_artifactStamps/regenLegacySensitivity"))]
    if stray:
        raise SystemExit("unexpected changed leaves: %r" % stray[:10])
    print(json.dumps({"changed": changed, "nChangedLeaves": len(d)}, indent=1))
    if not DRY and (changed or not old):
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(N, ensure_ascii=False, indent=1))
        print("wrote summary_arrays.json")


main()
