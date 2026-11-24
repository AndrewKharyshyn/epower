#!/usr/bin/env python3
"""M749 (spec analyses/M749_spec.md Rev 4): additive payload block `cloudCrossChecks`: short cross-check notes (X1 logged distance, X2 between-drive logging, X3 ambient, X4 timestamps) shown beside the OBD figures they verify (AUXILIARY; OBD stays primary; not an article figure). X1 (M760, replaced by M766) reads the registered M766 result under the revised jump rule P and the Director sentence of M765.

Reads ONLY the registered results (never the M746 retests): analyses/M730_clock_offset.json, M734_thermal_forcing.json, M739_unlogged_exposure.json.
Each file is pinned by its sha256 (PINS below, recorded in the CHANGELOG entry of M749); a mismatch or a missing file writes nothing and exits 3 (fails closed). Every number is copied from a registered field,
every string is written here (no source string is copied; the M739 'measurement error' wording becomes 'export reconstruction error'). Not displayed by design: the absolute cloud odometer, the V1 km bracket, the
M734 numbers (status line only), tyre values (status line only), per-drive or coordinate items.
Writes only /cloudAuxiliary in summary_arrays.json (deep-diff guarded); the stamp comes from the declared-dependency stage (tools/stamp_dependencies.json). Idempotent: a second run is byte-identical.
Usage: python tools/cloud_payload.py [--splice] [--dry-run] [--check]   (no flag = print the block)"""
import copy, hashlib, json, os, sys
from decimal import Decimal, ROUND_HALF_UP

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
A_DIR = os.path.join(ROOT, "analyses")
PINS = {
    "M730_clock_offset.json": "930a54ee4a18e8577322d209086cad80cdf2aaca76e47a89dbd43b3fa761b3bf",
    "M734_thermal_forcing.json": "3df29a57a5246d029cb6d7778ce1bd0bcaac9080fade286ae8ee4aa8372fb6b6",
    "M739_unlogged_exposure.json": "9bd34b87e06fe053f267d92ea7cb988db822814b54e650a73b95c1645f5fb07f",
    "M766_odometer_agreement_P.json": "516ab32b55978edac91967f1be391abf517263d4667fb1cbc23bd71079c19dc4",
    "M765_director_decision.json": "38e9e94b847e57ede2e97e5a4905ea4d2f0ab4beb516383d3d57ddab9a59082d",
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


def pct2(x):
    """M760 frozen rounding rule (spec Rev 2 7.8a): the fraction x as a percent with two decimals, round half up on the decimal repr of the registered float (0.01195 -> 1.20)."""
    return float((Decimal(repr(float(x))) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def km2(x):
    return float(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def short_word(word):
    """The verdict phrase without the repeated numbers: 'aggregate relative difference ...: the interval includes 1 %' -> 'the interval includes 1 %'."""
    return word.split(": ", 1)[1] if ": " in word else word


def build_x1(res, dec):
    """Note X1 (spec analyses/M766_spec.md Rev 2): logged distance versus the cloud-reported, interpolated odometer under the REVISED jump rule P (M765). Copies the registered M766 result and the Director's disclosure sentence;
    carries NO absolute cloud odometer, no cloud km, no 'reading' string and no B (M752 window rule) number."""
    if res["masterMd5"] != REGISTERED_MASTER or res.get("rule") != "P (revised rule, M765)":
        raise Stop("the registered M766 result was not computed on the registered master under rule P")
    if not res["control_R0"]["reproduced_leaf_by_leaf"] or not res["consistency_R2"]["equals_M765_P"]:
        raise Stop("the M766 result does not carry a passed control and M765 consistency")
    P = res["P1_agreement"]
    prim = P["E_int"]["primary_identity_ge2km"]
    for k in ("nDrives", "nDays"):
        if not prim.get(k):
            raise Stop("X1 source carries no %s" % k)
    words = res["P1_verdict_wording"]["primary_E_int_identity_ge2km"]
    cov = res["P0_coverage"]["E_int"]
    sel = res["P0_selection_check"]
    sens = res["excursionSensitivity"]
    if "disclosure_sentence" not in dec:
        raise Stop("the M765 decision carries no disclosure sentence")

    def rel(c):
        return {"est": pct2(c["relative"]["est"]), "ci95": [pct2(c["relative"]["ci95"][0]), pct2(c["relative"]["ci95"][1])], "nDrives": c["nDrives"], "nDays": c["nDays"],
                "rawFraction": {"est": c["relative"]["est"], "ci95": list(c["relative"]["ci95"])}}

    def sens_block(v):
        s_ = v["primary_identity_ge2km"]
        return {"drivesDropped": int(v["drives_with_an_endpoint_inside_an_excursion"]), **rel(s_), "verdict": {"within1pct": short_word(v["verdict_words"]["within1pct"]), "within3pct": short_word(v["verdict_words"]["within3pct"])}}

    both_positive = P["E_int"]["primary_identity_ge2km"]["relative"]["est"] > 0 and P["E_br"]["primary_identity_ge2km"]["relative"]["est"] > 0
    lo, hi = prim["relative"]["ci95"]
    x1 = {
        "label": "Independent cross-check (auxiliary): cloud-reported, interpolated odometer at both ends of a drive compared with the logged (app-calculated) drive distance",
        "ruleLabel": "revised rule P (the earlier note used the M752 window rule)",
        "nDrives": int(prim["nDrives"]), "nDays": int(prim["nDays"]), "available": int(cov["available"]), "drivesInCorpus": int(res["P0_coverage"]["drives"]),
        "medianDifferenceKm": {"est": km2(prim["median"]["est"]), "ci95": [km2(prim["median"]["ci95"][0]), km2(prim["median"]["ci95"][1])], "raw": {"est": prim["median"]["est"], "ci95": list(prim["median"]["ci95"])}},
        "relativeDifferencePercent": rel(prim),
        "verdict": {"within1pct": short_word(words["within1pct"]), "within3pct": short_word(words["within3pct"]), "size": "small difference, cloud larger" if prim["relative"]["est"] > 0 else "small difference"},
        "aggregateDefinition": "aggregate = sum of per-drive differences over the sum of logged kilometres (km-weighted), so long drives dominate; day-clustered bootstrap, seed %d, %d draws" % (res["seed"], res["nBoot"]),
        "strata": {k: rel(P["E_int"]["strata"][k]) for k in ("2to10km", "10kmplus")},
        "sensitivity": {"bracketedEndpoints": rel(P["E_br"]["primary_identity_ge2km"]), "shift16s": rel(P["E_int_shift16"]["primary_identity_ge2km"]),
                        "note": "the +16 s shift changes the sample (more drives have a bracket inside the cap), not only the offset"},
        "excursionSensitivity": {"S1_strict": sens_block(sens["S1_strict"]), "S2_wide": sens_block(sens["S2_wide"]),
                                 "note": "strict = an endpoint between the first and the last row of a recorded level excursion; wide = between the row before and the row after it"},
        "coverage": {"unavailableByReason": dict(cov["unavailableByReason"]), "byStratum": sel["byStratum"], "byMonth": sel["byMonth"]},
        "integrity": {"negativeSteps": int(res["negative_steps"]), "levelExcursions": int(res["level_excursions"]), "maxExcursionKm": res["maxExcursionKm"], "jumpExcluded": int(cov["unavailableByReason"].get("odometer_jump", 0))},
        "anchor": {"differenceKm": km2(res["P3_anchor"]["differenceKm"]), "rawDifferenceKm": res["P3_anchor"]["differenceKm"], "n": int(res["P3_anchor"]["n"])},
        "disclosures": [
            "Both counters rest on the same wheel-speed scale, so this checks logging completeness, not distance accuracy; a shared scale offset cannot be detected.",
            "The earlier note used the M752 window rule; it is replaced by the revised rule P (a jump counts only between the last row at or before the drive start and the first row at or after its end).",
            dec["disclosure_sentence"],
            "Jump-excluded drives under the revised rule: %d; drives with a cloud odometer: %d of %d." % (cov["unavailableByReason"].get("odometer_jump", 0), cov["available"], res["P0_coverage"]["drives"]),
            "Availability is selected by month and by drive length (counts in the payload); a selection effect on the aggregate is not excluded.",
            "The cloud odometer stream has %d negative steps and %d level excursions (largest %s km); the rule can miss an excursion that starts before the first endpoint row, which is why the sensitivity with those drives dropped (%d strict, %d wide) is shown." % (res["negative_steps"], res["level_excursions"], res["maxExcursionKm"], sens["S1_strict"]["drives_with_an_endpoint_inside_an_excursion"], sens["S2_wide"]["drives_with_an_endpoint_inside_an_excursion"]),
        ] + (["Both interpolation variants (interpolated and bracketed endpoints) give a positive difference, so the parked-edge model of the design is not confirmed."] if both_positive else []) + [
            "The end-of-record anchor is one point (n = %d), one-sided and not a known answer." % res["P3_anchor"]["n"],
            "Cause wording: consistent with logger edge losses (a hypothesis); per-sample speed quantisation in the app integral is an untested alternative; the positive sign argues against a parked-edge interpolation artefact.",
            "Nothing is replaced or corrected: no cloud kilometre or odometer value is shown and the logged distance and logged-share KPI are unchanged.",
        ],
    }
    return x1

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
    x1 = build_x1(src["M766_odometer_agreement_P.json"], src["M765_director_decision.json"])
    block = {
        "basis": basis, "registeredMasterMd5": REGISTERED_MASTER, "sourceSha256": dict(pins), "status": tail,
        "x1LoggedDistance": x1,
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
