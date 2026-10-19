#!/usr/bin/env python3
"""M460 splice (analyses/M460_spec.md Rev 1.1, gate G3): adds ONE additive key, evTraction.zeroFuelVariant, to summary_arrays.json from the script-written analyses/M460_result.json (tools/zero_fuel.py, run once under the lock).
Every number is read from the result file (nothing typed). The deep diff against the current payload must show exactly this key and the re-issued evTraction stamp; nothing else. Idempotent.
Usage: python tools/m460_splice.py [--dry-run]"""
import copy
import datetime
import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
DRY = "--dry-run" in sys.argv
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()


def build(R):
    prov = R["_provenance"]
    blk = {
        "milestone": "M460", "spec": prov["spec"], "specSha256": prov["specSha256"], "result": "analyses/M460_result.json", "resultSha256": sha("analyses/M460_result.json"), "masterMd5": prov["masterMd5"],
        "label": prov["label"], "rawBasis": prov["rawBasis"], "status": R["status"],
        "reading": ("Share of the logged distance with a zero logged fuel rate, set beside the RPM-defined engine-off share on the SAME drives (those that carry the logged, app-calculated fuel-rate channel; this population is not the one of the "
                    "released engine-off share, so the two levels are never mixed). Four states per second: A engine off and no fuel, B engine turning and no fuel, C engine off and fuel logged (an inconsistency flag), D fuelled. "
                    "Day-clustered 95 % intervals; sensitivities are ranges over declared conventions, never combined with the interval. Descriptive: no physical claim about injection or the controller."),
        "population": R["populationDescription"], "nSkippedOrExcluded": R["nSkipped"], "G1": R["G1"], "constructValidity": R["constructValidity"],
    }
    cv = blk["constructValidity"]
    if cv.get("motoredSeconds"):                                                     # Director ruling (M461): the gate basis is small; the binomial interval is script-computed
        n_, k_ = cv["motoredSeconds"], cv["motoredSecondsWithZeroFuelState"]
        z = 1.96
        ph = k_ / n_
        den = 1 + z * z / n_
        ctr = (ph + z * z / (2 * n_)) / den
        hw = z * ((ph * (1 - ph) / n_ + z * z / (4 * n_ * n_)) ** 0.5) / den
        cv["wilson95"] = [round(ctr - hw, 4), round(ctr + hw, 4)]
        cv["weaklyIdentified"] = bool(ctr - hw < cv["minShare"])
        cv["note"] = "motored state weakly identified (%d s basis; the interval %s the %d %% minimum)" % (n_, "spans" if cv["weaklyIdentified"] else "lies above", int(100 * cv["minShare"]))
    if R["status"] == "computed":
        blk.update({k: R[k] for k in ("primary", "decomposition", "inconsistencyFlag", "sensitivities", "strata", "crosstabUndebouncedSeconds")})
        blk["readingRule"] = R["reading"]
        crow = blk["sensitivities"]["counterConsistencyRow"]
        share0 = crow["fuelledSecondsWithZeroCounterIncrementShare"]
        crow["label"] = "resolution check failed (%.1f %% of fuelled seconds have a zero counter increment): non-informative, same app calculation; never corroboration" % (100 * share0)
        for key, v in blk["strata"].items():
            n_dr = v["shareRpm"]["nDrives"]
            n_dy = v["shareRpm"]["nDays"]
            if n_dr < 10 or n_dy < 5:
                v["belowSupport"] = True
                v["belowSupportNote"] = "below the support floors (%d drives, %d days): exploratory" % (n_dr, n_dy)
        dg = json.load(open("analyses/M460_diag.json", encoding="utf-8"))
        if dg["nPF"] != R["nPF"] or not dg["gate"]["nPFMatchesResult"]:
            raise SystemExit("analyses/M460_diag.json does not match the result file")
        blk["motoredKmByConvention"] = dg["motoredKmByConvention"]
        blk["motoredKmRange"] = dg["motoredKmRange"]
        blk["pollStrataNote"] = ("the RPM polling stratum and the fuel polling stratum coincide on P_F (%s; identical partition: %s), because both channels are polled in the same logging generation; they are one stratification, not two" % (json.dumps(dg["pollCrossTab"]), dg["identicalPartition"]))
        blk["diagnostics"] = {"file": "analyses/M460_diag.json", "sha256": sha("analyses/M460_diag.json"), "note": "post-run read-only diagnostics required by the Director ruling; the first-run result is unchanged"}
    blk["limits"] = ["the fuel rate is a logged / app-calculated, discrete channel; the counter row shares its calculation and its quantisation (consistency row only)",
                     "the population is the fuel-instrumented subset (Aug-Oct 2026 drives) and is not the released population; levels are not comparable across populations",
                     "the classifier-motored seconds that identify the construct are few (see constructValidity); the motored state is a small share of the distance",
                     "one vehicle, one driver; descriptive"]
    blk["refresh"] = "on demand: re-run tools/zero_fuel.py under a recorded deviation when the detector, the gates or the fuel channel change; each ingestion carries this block forward unchanged (tools/ingest_core.NESTED_CARRIED)"
    return blk


def main():
    R = json.load(open("analyses/M460_result.json", encoding="utf-8"))
    raw = open("summary_arrays.json", "rb").read().decode("utf-8")
    A = json.loads(raw)
    if json.dumps(A, ensure_ascii=False, indent=1) != raw and json.dumps(A, ensure_ascii=False, indent=1) + "\n" != raw:
        raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
    if R["_provenance"]["masterMd5"] != hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest():
        raise SystemExit("M460_result.json was computed on a different master")
    if not R["G1"]["pass"]:
        raise SystemExit("gate G1 did not pass in the result file")
    blk = build(R)
    N = copy.deepcopy(A)
    changed = N["evTraction"].get("zeroFuelVariant") != blk
    N["evTraction"]["zeroFuelVariant"] = blk
    st = N["_artifactStamps"]["evTraction"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if changed:
        st["generatedAt"] = st["includedInReleaseAt"] = st["computedAt"] = now
        st["computationStatusNote"] = "M460: additive evTraction.zeroFuelVariant spliced by tools/m460_splice.py from analyses/M460_result.json; the released engine-off figures are unchanged"

    def diff(a, b, p=""):
        if type(a) is not type(b):
            return [p]
        if isinstance(a, dict):
            return [x for k in sorted(set(a) | set(b)) for x in diff(a.get(k), b.get(k), p + "/" + k)]
        if isinstance(a, list):
            return [x for i, (u, v) in enumerate(zip(a, b)) for x in diff(u, v, p + "/%d" % i)] if len(a) == len(b) else [p + " len"]
        return [p] if a != b else []

    d = diff(A, N)
    stray = [x for x in d if not (x.startswith("/evTraction/zeroFuelVariant") or x.startswith("/_artifactStamps/evTraction"))]
    if stray:
        raise SystemExit("unexpected changed leaves: %r" % stray[:10])
    print(json.dumps({"changed": changed, "nChangedLeaves": len(d), "keys": sorted(blk)}, indent=1))
    if not DRY and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(N, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("wrote summary_arrays.json")


main()
