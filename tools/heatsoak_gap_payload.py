#!/usr/bin/env python3
"""M758 (spec analyses/M758_spec.md Rev 2): additive CARRIED payload block `heatSoakGapSensitivity` (display of the registered M756 rerun of the M751 heat-soak gap sensitivity).

Reads ONLY the registered result analyses/M756_rerun/M751_heatsoak_gap_sensitivity.json, pinned by sha256 (a mismatch or a missing file writes nothing and exits 3).
Every number is copied from a registered field (tolerance 0); every string is written here except the registered overall wording (copied, spec 7.5/R2) and the registered verdict words.
Single displayed basis (spec 7.1): the M756 rerun on the M755 ambient basis. Sets shown: B and C, C first; C1 is left out (spec 7.3).
The block is computed on the registered corpus (master d514d600..., 717 drives) and is NOT refreshed by ingestion (carried; spec 7.2). It never fails a gate on a stale basis.
R1 (spec 7.6): the displayed set-A 6-12 h median must equal the live heatSoakCarryover 6-12 h median in summary_arrays.json while the live master is the registered one.
Writes only /heatSoakGapSensitivity and its artifact stamp in summary_arrays.json (deep-diff guarded). Idempotent.
Usage: python tools/heatsoak_gap_payload.py [--splice] [--dry-run] [--check]   (no flag = print the block)"""
import copy, hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC_REL = "analyses/M756_rerun/M751_heatsoak_gap_sensitivity.json"
SRC_SHA = "2ea781c96575569d89d7733c8931c9fcdc8eb0d90866a31e31e587b603b23c8c"
REGISTERED_MASTER = "d514d6009d6d9a0a168ad4fb09b9bb98"
GAP_TABLE_SHA = "d1d3f8e9da732e7c58212c3bcf5718e05304a186df4f45e567d8799c704d159f"
KEY = "heatSoakGapSensitivity"
BOUNDARY = "not distinguishable (interval lower bound at 0.0; boundary case, not evidence of no shift)"
SETS = ("C", "B")           # C first (spec 7.3)


class Stop(Exception):
    pass


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load(root=ROOT, rel=SRC_REL, pin=SRC_SHA):
    p = os.path.join(root, rel)
    if not os.path.exists(p):
        raise Stop("missing registered source %s" % rel)
    if sha256(p) != pin:
        raise Stop("registered source %s differs from its pinned sha256" % rel)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def verdict_word(cell):
    """Registered verdict word; a 'not distinguishable' cell whose interval lower bound is exactly 0.0 with a positive point shift gets the Director boundary wording (spec 7.5)."""
    v = cell["verdict"]
    if v == "not distinguishable" and cell.get("ci95Pp") and cell["ci95Pp"][0] == 0.0 and cell.get("shiftPp", 0) > 0:
        return BOUNDARY
    return v


def bin_label(lo, hi):
    return "%g h and longer" % lo if hi is None else "%g-%g h" % (lo, hi)


def build(res, pin=SRC_SHA):
    if res.get("masterMd5") != REGISTERED_MASTER or res.get("registeredMasterMd5") != REGISTERED_MASTER:
        raise Stop("the registered result was not computed on the registered master")
    if res.get("m729GapsSha256") != GAP_TABLE_SHA:
        raise Stop("the registered result does not carry the pinned M729 gap table sha256")
    if res["control_V0"]["status"] != "reproduced":
        raise Stop("control V0 is not reproduced in the registered result")
    shifts = res["E2_retained_fraction_shift"]["primaryArrivalDay"]
    comp = res["E1_composition_by_gap_bin"]
    rows = []
    for b in shifts:
        lo, hi = b["gapLoH"], b["gapHiH"]
        key = "%s-%s" % (lo, "" if hi is None else hi)
        c = comp[key]
        row = {"gapLoH": lo, "gapHiH": hi, "label": bin_label(lo, hi), "allPairs": {"nAmb": b["nAmbA"], "med": b["medA"]},
               "pairsInBin": c["n"], "pairsStationaryConsistent": c["S"], "pairsWithMovementOrUnknown": c["n"] - c["S"]}
        for s in SETS:
            cell = b[s]
            out = {"nAmb": cell["nAmb"], "days": cell["days"], "med": cell["med"], "supported": bool(cell["supported"])}
            if cell["supported"]:
                out.update(shiftPp=cell["shiftPp"], ci95Pp=list(cell["ci95Pp"]), mdePp=cell["mdePp"])
            out["verdict"] = verdict_word(cell)
            row[s] = out
        rows.append(row)
    tau = {}
    for s in ("A",) + SETS:
        t = res["E3_tau"][s]
        d = {"nPairsWithAmbient": t["nAmbBeforeFilter"], "nFit": t["nFit"], "tauH": t["tauH"], "tauCI": list(t["tauCI"]),
             "decayRateK": t["decayRateK"], "decayRateKCI": list(t["decayRateKCI"])}
        if s != "A":
            d.update(kShiftVsA=t["kShiftVsA"], kShiftCI95=list(t["kShiftCI95"]), verdictK=t["verdictK"])
        tau[s] = d
    n_pairs = sum(r["pairsInBin"] for r in rows)
    basis = ("computed on the registered corpus of %d drives (master MD5 %s...; all pairs, set A), cloud gap table M729 sha256 %s..., ambient read through the shared reader (M755 basis); "
             "later drives are not included" % (717, REGISTERED_MASTER[:8], GAP_TABLE_SHA[:8]))
    block = {
        "basis": basis, "registeredMasterMd5": REGISTERED_MASTER, "corpusDrives": 717, "pairsRegistered": res["reconciliation"]["pairs"],
        "sourceFile": SRC_REL, "sourceSha256": pin, "resultToolSha256": res["toolSha256"], "seed": res["seed"], "nBoot": res["nBoot"],
        "status": "carried sensitivity block, auxiliary; not an article figure; not refreshed by ingestion",
        "staleness": {"carried": True, "corpusDrives": 717, "refreshedAt": None},
        "setLabels": {"A": "all pairs, registered corpus", "C": "pairs without definite estimated unlogged movement (set C)",
                      "B": "stationary-consistent pairs only (set B)"},
        "bins": rows, "tau": tau, "overall": res["overall"], "unloggedPairCounts": {k: int(v) for k, v in res["unlogged_shares"].items()},
        "pairsTotal": n_pairs,
        "notes": {
            "lead": "Sensitivity of the retained-heat medians in the gap bins above to estimated unlogged driving between logged drives (estimated, lower bound). The explanation above is unchanged.",
            "unlogged": "Unlogged means no OBD record. The classes come from the cloud odometer and geolocation gap table (estimated, not an OBD record); undetected unlogged driving stays in the subsets, so the shifts are lower bounds.",
            "setB": "Set B also selects on cloud coverage; B and C do not bracket the truth (cloud recall is below 1), so both are lower bounds.",
            "ambient": "Ambient is the hand-entered driving-time value, as in the table above.",
            "sensitivity": "A sensitivity of the registered-corpus median, not a replacement of any displayed figure.",
            "audit": "The blind reproduction reproduced these cells within construction differences, not leaf-exactly (6-12 h A-C 6.52 vs 7.19 pp; tau B 9.79 vs 9.53 h; 12-24 h point estimates differ). The tau fit conditions on the outcome (residual excess above 0.5 C).",
            "days": "Day counts are the calendar days of the arrival clusters in the registered result.",
            "unsupported": "not estimable at this support",
        },
    }
    return block


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from walk(a.get(k), b.get(k), path + "/" + k)
    elif a != b:
        yield path


def r1_check(arrays, block):
    """Spec 7.6: displayed set-A 6-12 h median equals the live heatSoakCarryover value while the live master is the registered one."""
    live_md5 = ((arrays.get("_artifactStamps") or {}).get("heatSoakCarryover") or {}).get("corpusHash")
    if live_md5 != REGISTERED_MASTER:
        return True, "live master differs from the registered one (carried block disclosed; R1 not applicable)"
    live = next(b for b in arrays["heatSoakCarryover"]["gapBins"] if b["gapLoH"] == 6 and b["gapHiH"] == 12)["medRetainedFrac"]
    shown = next(r for r in block["bins"] if r["gapLoH"] == 6 and r["gapHiH"] == 12)["allPairs"]["med"]
    return live == shown, "live %s vs shown %s" % (live, shown)


def splice(block, dry=False, path=None):
    P = path or os.path.join(ROOT, "summary_arrays.json")
    with open(P, encoding="utf-8", newline="") as f:
        raw = f.read()
    A = json.loads(raw)
    ok, msg = r1_check(A, block)
    if not ok:
        raise Stop("R1: displayed set-A 6-12 h median differs from the live heatSoakCarryover (%s)" % msg)
    B = copy.deepcopy(A)
    B[KEY] = block
    if KEY not in (B.get("_artifactStamps") or {}):
        import datetime
        st = copy.deepcopy(B["_artifactStamps"]["powerFadeTemperatureSpecs"])
        for k in ("declaredIdentity", "stampLineage", "carriedForward", "upstreamHashes"):
            st.pop(k, None)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        st.update(corpusHash=REGISTERED_MASTER, generatedAt=now, includedInReleaseAt=now, computedAt=now, computationStatus="computed",
                  computationStatusNote="M758: copied by tools/heatsoak_gap_payload.py from the registered M756 rerun result (carried; spec analyses/M758_spec.md Rev 2)")
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
            with open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8") as f:
                A = json.load(f)
            ok = A.get(KEY) == block
            print("heatsoak_gap_payload: block %s" % ("present and equal to the registered result" if ok else "MISSING or different"))
            return 0 if ok else 1
        if "--splice" in argv:
            dry = "--dry-run" in argv
            ch = splice(block, dry)
            print("heatsoak_gap_payload: %s" % (("would write" if dry else "written") if ch else "unchanged"))
        else:
            print(json.dumps(block, indent=1)[:4000])
        return 0
    except Stop as e:
        print("heatsoak_gap_payload: STOP (%s); nothing written" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
