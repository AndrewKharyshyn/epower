#!/usr/bin/env python3
"""M749 (spec analyses/M749_spec.md Rev 4): additive payload block `cloudCrossChecks`: short cross-check notes (X2 between-drive logging, X3 ambient, X4 timestamps) shown beside the OBD figures they verify (AUXILIARY; OBD stays primary; not an article figure). X1 (logged distance) is held back.

Reads ONLY the registered results (never the M746 retests): analyses/M730_clock_offset.json, M734_thermal_forcing.json, M739_unlogged_exposure.json.
Each file is pinned by its sha256 (PINS below, recorded in the CHANGELOG entry of M749); a mismatch or a missing file writes nothing and exits 3 (fails closed). Every number is copied from a registered field,
every string is written here (no source string is copied; the M739 'measurement error' wording becomes 'export reconstruction error'). Not displayed by design: the absolute cloud odometer, the V1 km bracket, the
M734 numbers (status line only), tyre values (status line only), per-drive or coordinate items.
Writes only /cloudAuxiliary in summary_arrays.json (deep-diff guarded); the stamp comes from the declared-dependency stage (tools/stamp_dependencies.json). Idempotent: a second run is byte-identical.
Usage: python tools/cloud_payload.py [--splice] [--dry-run] [--check]   (no flag = print the block)"""
import copy, hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
A_DIR = os.path.join(ROOT, "analyses")
PINS = {
    "M730_clock_offset.json": "930a54ee4a18e8577322d209086cad80cdf2aaca76e47a89dbd43b3fa761b3bf",
    "M734_thermal_forcing.json": "3df29a57a5246d029cb6d7778ce1bd0bcaac9080fade286ae8ee4aa8372fb6b6",
    "M739_unlogged_exposure.json": "9bd34b87e06fe053f267d92ea7cb988db822814b54e650a73b95c1645f5fb07f",
}
REGISTERED_MASTER = "d514d6009d6d9a0a168ad4fb09b9bb98"
KEY = "cloudCrossChecks"
U2_CLASSES = ("below30", "30to80", "above80", "length_t1", "length_t2", "length_t3", "weekend", "night")


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
        if sha256(p) != want:
            raise Stop("registered source %s differs from its pinned sha256" % fn)
        out[fn] = json.load(open(p, encoding="utf-8"))
    return out


def r(x, n=4):
    return None if x is None else round(float(x), n)


def direction(c):
    """Direction word of a registered U2 class from its sign and day interval (never typed): 'larger' / 'smaller' only when the day interval excludes zero."""
    lo, hi = c["ci95_day"]
    if lo > 0:
        return "larger"
    if hi < 0:
        return "smaller"
    return "not distinguishable"


def build(src, pins=PINS):
    m30, m34, m39 = (src[k] for k in ("M730_clock_offset.json", "M734_thermal_forcing.json", "M739_unlogged_exposure.json"))
    if m39["masterMd5"] != REGISTERED_MASTER or m34["masterMd5"] != REGISTERED_MASTER:
        raise Stop("a registered source was not computed on the registered master")
    n_master = int(m39["alignment"]["drives_in_master"])
    span = m39["alignment"]["export_range_kyiv"]
    basis = "snapshot registered on %d drives (master d514d600, export span %s to %s); not recomputed with later drives" % (n_master, span[0][:10], span[1][:10])
    tail = "auxiliary; not an article figure"
    u1, v1, u2 = m39["U1_unlogged"], m39["V1_reconstruction_error"], m39["U2_representativeness"]["km_weighted_primary"]
    t1 = m34["T1_ambient"]["screened_minus_manual"]
    if m30.get("n_days") is None or t1.get("n_days") is None or u1.get("days") is None:
        raise Stop("a note source carries no n_days: that note is dropped by rule")
    block = {
        "basis": basis, "registeredMasterMd5": REGISTERED_MASTER, "sourceSha256": dict(pins), "status": tail,
        "x1LoggedDistance": None,
        "x1HeldBack": "not shown: the registered source has 431 drives and no day count or day-bootstrap interval; shown only after a registered addendum supplies them",
        "x2BetweenDriveLogging": {
            "label": "Independent cross-check (auxiliary): the cloud export shows %d strict movement units on %d days outside logged drives (units are odometer-step bursts, not trips)." % (int(u1["strict_units"]), int(u1["days"])),
            "strictUnits": int(u1["strict_units"]), "days": int(u1["days"]),
            "direction": {"timeBelow30": direction(u2["below30"]), "timeAbove80": direction(u2["above80"]), "longUnits": direction(u2["length_t3"])},
            "exportReconstructionErrorTimeShares": {"medianTotalVariation": r(v1["time_shares"]["median_tv"]), "ci95Day": [r(x) for x in v1["time_shares"]["ci95_day"]], "validationDrives": int(m39["V1_n"]["validation_drives"]), "validationDays": int(m39["V1_n"]["days"])},
            "note": "Descriptive; not an effect. The cloud export comes from the same vehicle, so this checks what was recorded, not sensor accuracy. The gap kilometres above are not replaced or corrected, and no cloud kilometres or hours are shown here",
        },
        "x3Ambient": {
            "label": "Independent cross-check (auxiliary): screened cloud ambient minus driver-recorded ambient",
            "nDrives": int(t1["n_drives"]), "nDays": int(t1["n_days"]), "median": r(t1["median"], 3), "ci95Day": [r(x, 3) for x in t1["ci95_day_bootstrap"]],
            "medianAbs": r(t1["median_abs"], 2), "p90Abs": r(t1["p90_abs"], 2),
            "caveat": "In-sample: the screening was tuned on these drives; likely the same vehicle sensor, so it checks recording, not sensor accuracy; no ambient value is replaced",
        },
        "x4Timestamps": {
            "label": "Estimated cloud-to-OBD clock offset (auxiliary)",
            "medianPerDriveBestS": r(m30["per_drive_best"]["median"], 1), "pooledS": m30["pooled_best_offset_s"], "dayBootstrapCi95S": [float(x) for x in m30["median_best_offset_ci95_day_bootstrap"]],
            "nDrives": int(m30["n_drives"]), "nDays": int(m30["n_days"]), "adoptGlobalOffset": bool(m30["decision_rule"]["adopt_global_offset"]),
            "convention": "a positive offset compares a cloud value at time t with the OBD value at t + offset",
            "note": "Not adopted as a correction (held-out rule not met); no displayed figure uses it",
        },
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
    if KEY not in (B.get("_artifactStamps") or {}):                 # first write: seed the stamp from a declared sibling; tools/stamp_dependencies_apply.py then derives it from the declaration
        import datetime
        st = copy.deepcopy(B["_artifactStamps"]["powerFadeTemperatureSpecs"])
        for k in ("declaredIdentity", "stampLineage", "carriedForward", "upstreamHashes"):
            st.pop(k, None)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        st.update(corpusHash=REGISTERED_MASTER, generatedAt=now, includedInReleaseAt=now, computedAt=now, computationStatus="computed",
                  computationStatusNote="M749: copied by tools/cloud_payload.py from the registered MyNISSAN cloud-export results (auxiliary; spec analyses/M749_spec.md Rev 2)")
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
            print("cloud_payload: block %s" % ("present and equal to the registered sources" if ok else "MISSING or different"))
            return 0 if ok else 1
        if "--splice" in argv:
            dry = "--dry-run" in argv
            ch = splice(block, dry)
            print("cloud_payload: %s" % (("would write" if dry else "written") if ch else "unchanged"))
        else:
            print(json.dumps(block, indent=1)[:3000])
        return 0
    except Stop as e:
        print("cloud_payload: STOP (%s); nothing written" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
