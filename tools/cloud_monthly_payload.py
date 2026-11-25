#!/usr/bin/env python3
"""M776 (spec analyses/M776_spec.md Rev 2): additive payload block `cloudMonthlyCoverage`: monthly OBD distance beside speed-supported cloud movement outside the OBD logs (auxiliary, not an article figure).
Reads ONLY the registered results analyses/M776_cloud_monthly.json and analyses/M739_unlogged_exposure.json, each pinned by file sha256 (PINS; recorded in the CHANGELOG entry); a mismatch or a missing file writes nothing and exits 3 (fails closed).
Every number is copied from a registered field; every string is written here. Aggregates only: no coordinates, no per-drive tracks. The M776 result is a snapshot of the registered corpus (717 drives); refreshing it is a re-run of
tools/cloud_monthly_coverage.py, a new pin and a CHANGELOG entry (open item for the next ingestion).
Writes only /cloudMonthlyCoverage in summary_arrays.json (deep-diff guarded). Idempotent.
Usage: python tools/cloud_monthly_payload.py [--splice] [--dry-run] [--check]   (no flag = print the block)"""
import copy, hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
A_DIR = os.path.join(ROOT, "analyses")
PINS = {
    "M776_cloud_monthly.json": "ed7c2c9b14c644bc421b549e2f05a98b569400660a5e314ebd8b6b4bbb0e3ec4",
    "M739_unlogged_exposure.json": "9bd34b87e06fe053f267d92ea7cb988db822814b54e650a73b95c1645f5fb07f",
}
REGISTERED_MASTER = "d514d6009d6d9a0a168ad4fb09b9bb98"
KEY = "cloudMonthlyCoverage"
MONTH_FIELDS = ("month", "partial", "obdKm", "obdDrives", "obdDays", "cloudOutsideKm", "cloudOutsideSteps", "cloudOutsideDays",
                "e2SensitivityMinKm", "e2SensitivityMaxKm", "e2SensitivityMinKmGap35Plus", "e2SensitivityMaxKmGap35Plus", "small",
                "g1Km", "g1N", "g2Km", "g2N", "definitionRangeKm", "cloudInsideLogsKm", "captureInsideLogs", "belowResolution")


class Stop(Exception):
    pass


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def load(a_dir=A_DIR, pins=PINS):
    out = {}
    for fn, want in pins.items():
        p = os.path.join(a_dir, fn)
        if not os.path.exists(p):
            raise Stop("missing registered source %s" % fn)
        if want != "TO_BE_PINNED" and sha256(p) != want:
            raise Stop("sha256 mismatch for %s" % fn)
        out[fn] = json.load(open(p, encoding="utf-8"))
    m = out["M776_cloud_monthly.json"]
    if m.get("masterMd5") != REGISTERED_MASTER or m.get("pinnedMd5") != REGISTERED_MASTER:
        raise Stop("registered result is not on the registered corpus")
    return out


def build(src):
    m, u = src["M776_cloud_monthly.json"], src["M739_unlogged_exposure.json"]
    rows = [{k: r[k] for k in MONTH_FIELDS} for r in m["months"] if r["month"] != "month unknown"]
    unknown = [r for r in m["months"] if r["month"] == "month unknown"]
    # headline month: the full (non-partial) month with the largest speed-supported cloud movement outside the logs; ties impossible in practice
    full = [r for r in rows if not r["partial"]]
    head = max(full, key=lambda r: r["cloudOutsideKm"])["month"] if full else None
    v1 = u["V1_reconstruction_error"]["distance"]
    short = u["V1_strata"]["strata"]
    shortest = {k: v for k, v in short.items() if k.startswith("0/") and v.get("supported")}
    block = {
        "label": "OBD-logged distance and speed-supported cloud movement outside the logs, by month",
        "status": "auxiliary; not an article figure; snapshot registered on 717 drives (master d514d600; %d start inside the export span %s to %s); not recomputed with later drives" % (
            sum(r["obdDrives"] for r in m["months"]), m["exportSpanKyiv"][0][:10], m["exportSpanKyiv"][1][:10]),
        "spec": "analyses/M776_spec.md Rev 2.1", "specSha256": m["specSha256"],
        "registeredMasterMd5": REGISTERED_MASTER,
        "sourceSha256": [fn for fn in PINS],
        "ruleLabel": "Cloud movement counted here: successive odometer samples at most 35 s apart, speed above 2 km/h within 25 s of the step midpoint, implied speed at most 180 km/h, and the whole step outside every OBD log padded by 45 s. A step is assigned to the Kyiv month of both its ends.",
        "headlineMonth": head,
        "months": rows,
        "monthUnknown": [{"cloudOutsideKm": r["cloudOutsideKm"], "g1Km": r["g1Km"], "g2Km": r["g2Km"]} for r in unknown],
        "totals": m["totals"],
        "crossReferenceM739": m["crossReferenceM739"],
        "d4": m["d4"],
        "rejectedSteps": m["rejected"],
        "gridCombinations": m["gridCombinations"],
        "gridNote": m["gridNote"],
        "daysWithoutObdWithCloudMovement": [d for d in m["days"] if d["obdKm"] == 0.0 and (d["e2Km"] > 0 or d["g1Km"] > 0)],
        "cloudReportingGapDates": m["cloudReportingGapDates"],
        "cloudHoles24h": m["cloudHoles24h"],
        "obdWindows": {"rawFiles": m["windows"]["rawFiles"], "notInMaster": len(m["windows"]["notInMaster"])},
        "m739Reference": {
            "aggregateSignedDifferenceRelative": v1["aggregate_signed_bias"], "aggregateInterval95Day": v1["bias_ci95_day"],
            "shortestTercileStrata": {k: {"nDrives": v["n_drives"], "nDays": v["n_days"], "aggregateSignedDifferenceRelative": v["agg_bias"]} for k, v in sorted(shortest.items())},
            "reading": "cloud step distance of logged drives, relative to their OBD distance",
        },
        "reading": [
            "Kilometres are OBD-logged distance and speed-supported cloud movement outside those logs; the cloud value is a lower value under the stated rule, not a total.",
            "Movement across long gaps is listed separately, with its timing unresolved, and is never added to the bars.",
            "The definition range (cloud movement plus unresolved gap movement) is not a bound or an interval: driving that the cloud did not register cannot be excluded.",
            "No percentage is computed across the two sources.",
        ],
    }
    return block


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from walk(a.get(k), b.get(k), path + "/" + k)
    elif a != b:
        yield path


def splice(block, dry=False, path=None):
    P = path or os.path.join(ROOT, "summary_arrays.json")
    raw = open(P, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    B = copy.deepcopy(A)
    B[KEY] = block
    if KEY not in (B.get("_artifactStamps") or {}):
        import datetime
        st = copy.deepcopy(B["_artifactStamps"]["cloudCrossChecks"])
        for k in ("declaredIdentity", "stampLineage", "carriedForward", "upstreamHashes"):
            st.pop(k, None)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        st.update(corpusHash=REGISTERED_MASTER, generatedAt=now, includedInReleaseAt=now, computedAt=now, computationStatus="computed",
                  computationStatusNote="M776: copied by tools/cloud_monthly_payload.py from the registered monthly cloud-movement result (auxiliary; spec analyses/M776_spec.md Rev 2)")
        B["_artifactStamps"][KEY] = st
    bad = [d for d in walk(A, B) if not d.startswith("/" + KEY) and not d.startswith("/_artifactStamps/" + KEY)]
    if bad:
        raise Stop("deep diff outside %s: %s" % (KEY, bad[:4]))
    if A.get(KEY) == block and KEY in (A.get("_artifactStamps") or {}):
        return False
    if not dry:
        with open(P, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return True


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        block = build(load())
        if "--check" in argv:
            A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
            ok = A.get(KEY) == block
            print("cloud_monthly_payload: block %s" % ("present and equal to the registered sources" if ok else "MISSING or different"))
            return 0 if ok else 1
        if "--splice" in argv:
            dry = "--dry-run" in argv
            ch = splice(block, dry)
            print("cloud_monthly_payload: %s" % (("would write" if dry else "written") if ch else "unchanged"))
        else:
            print(json.dumps(block, indent=1)[:3000])
        return 0
    except Stop as e:
        print("cloud_monthly_payload: STOP (%s); nothing written" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
