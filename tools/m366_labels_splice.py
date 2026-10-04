#!/usr/bin/env python3
"""M366 (Director ruling analyses/M366_spec.md Rev 2): additive/leaf splice after the raw/ replacement.
1. generatorTractionRecon.gtrClosure.basis + _staleness: computed on the FORMER raw/ re-exports (pre-M366), NOT refreshed on the originals; new additive key generatorTractionRecon.staleBlocks lists the five blocks (gtrClosure, sensitivity, simultaneity, crossval, speedSplit) that were written once by one-off tools and carried forward.
2. fuelAnalytics.fuel12.m366Shift (additive): previous published FUEL-12 figures (origin/main arrays) next to the current ones, the five estimates outside their previous CI (from the headline gate JSON), and the M337 read-only reference (re-exports raised the rate-integral totals and the counter totals by the stated shares; script-written).
Deep-diff asserts that nothing else in summary_arrays.json changes. Usage: python tools/m366_labels_splice.py PUBLISHED_ARRAYS.json"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
canon = lambda o: json.dumps(o, sort_keys=True, ensure_ascii=False, default=float)
A = json.load(open("summary_arrays.json", encoding="utf-8"))
pub = json.load(open(sys.argv[1], encoding="utf-8"))
gate = json.load(open("analyses/F03_originals/M366_headline_gate.json", encoding="utf-8"))
m337 = json.load(open("analyses/M337_f03_fuel_check.json", encoding="utf-8"))
old = copy.deepcopy(A)

G = A["generatorTractionRecon"]
STALE = "computed on the former raw/ re-exports (pre-M366); not refreshed on the originals"
Z = G["gtrClosure"]
Z["basis"] = f"fuel-PID subset, model-derived; {STALE}; not M299-reproducible"
Z["_staleness"] = Z["_staleness"].split(" | M366:")[0] + f" | M366: {STALE} (follow-up refresh milestone)"
G["staleBlocks"] = {"blocks": ["gtrClosure", "sensitivity", "simultaneity", "crossval", "speedSplit"], "note": STALE + "; written once by one-off tools and carried forward (follow-up refresh milestone)"}

F = A["fuelAnalytics"]["fuel12"]; P = pub["fuelAnalytics"]["fuel12"]
pick = lambda e: {"est": e["est"], "ci95": e["ci95"], "nTrips": e.get("nTrips"), "nDays": e.get("nDays")}
outside = [x for x in gate["ciOutside"] if x["path"].startswith("/fuelAnalytics/fuel12/")]
F["m366Shift"] = {
    "previous": {"aggregate": pick(P["aggregate"]), "hashFailStratum": pick(P["f03Sensitivity"]["hashFail"]), "hashPassStratum": pick(P["f03Sensitivity"]["hashPass"]),
                 "variants": {k: pick(P["integrationVariants"][k]) for k in ("cap10s", "gapFreeTripsBase", "trapezoid")}},
    "nOutsidePreviousCi": len(gate["ciOutside"]), "nCiChecked": gate["ciSummary"]["nChecked"],
    "outsidePaths": [x["path"] for x in outside],
    "m337Reference": {"rateIntegralRaisedByRawReexports": round(m337["V_int"]["aggRelDiff"], 5), "counterRaisedByRawReexports": round(m337["V_cnt"]["aggRelDiff"], 6), "nFiles": m337["V_int"]["n"]},
    "source": "tools/m366_labels_splice.py from the M366 headline gate (analyses/F03_originals/M366_headline_gate.json) and the M337 read-only check; previous = arrays at origin/main before M366"}
assert gate["ciSummary"]["nOutsideBaselineCi"] == len(gate["ciOutside"]) == len(outside), "all outside-CI estimates must be FUEL-12 (stop condition otherwise)"

ALLOW = ("/generatorTractionRecon/gtrClosure/basis", "/generatorTractionRecon/gtrClosure/_staleness", "/generatorTractionRecon/staleBlocks", "/fuelAnalytics/fuel12/m366Shift")


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                assert f"{path}/{k}" in ALLOW, f"{path}/{k}"
                continue
            walk(a[k], b[k], f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{i}]")
    elif a != b:
        assert path in ALLOW, (path, a, b)


walk(old, A)
with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(A, f, ensure_ascii=False, indent=1)
print("labels spliced; nOutside", len(gate["ciOutside"]), "of", gate["ciSummary"]["nChecked"])
