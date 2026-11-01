"""M556 (analyses/M556_spec.md Rev 2): known-answer tests for the signal-validity reader contract and the registry."""
import os, sys, re, json
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import signal_validity as SV

reg = SV.load_registry()
E12 = "bms_12v_supply"

# KA1: an all-zero vector of the declared channel -> unavailable (values withheld); one non-zero value -> not holding (values returned unchanged, escalate); empty and all-missing -> not testable
r = SV.status(E12, [0.0, 0, "0", "0.0", "-0", -0.0], reg)
assert r["status"] == "rule_holds_unavailable" and r["values"] is None and not r["escalate"]
v = [0.0, 0.0, 12.6]
r = SV.status(E12, v, reg)
assert r["status"] == "rule_not_holding" and r["values"] is v and r["escalate"]
assert SV.status(E12, [], reg)["status"] == "not_testable" and SV.status(E12, [np.nan, None, ""], reg)["status"] == "not_testable"
assert SV.status(E12, None, reg)["status"] == "not_testable"

# KA2: no mutation, raw zeros preserved
z = [0.0, 0.0, 0.0]; z2 = list(z)
SV.status(E12, z, reg)
assert z == z2
arr = np.zeros(5); a2 = arr.copy()
SV.status(E12, arr, reg)
assert np.array_equal(arr, a2)

# a declared sparse channel has no per-file unavailable verdict
assert SV.status("elm327_supply", [0.0, 0.0], reg)["status"] == "not_testable"

# KA5: schema: every required field is present; sparse supply channels forbid ageing, rest-state SoC and DC/DC statements; the unavailable channel forbids any physical statement
for e in reg["entries"]:
    for k in SV.REQUIRED:
        assert k in e and (e[k] or k == "consumers"), (e["id"], k)
    if e["status"] in ("sparse_location_specific", "unavailable_when_rule_holds"):
        txt = " ".join(e["impermissibleAnalyses"]).lower()
        assert "12 v ageing" in txt and "rest-state soc" in txt and "dc/dc" in txt, e["id"]
assert "any physical statement" in " ".join(next(e for e in reg["entries"] if e["id"] == E12)["impermissibleAnalyses"])
assert "unknown" in next(e for e in reg["entries"] if e["id"] == E12)["physicalJustification"] and "fault" not in next(e for e in reg["entries"] if e["id"] == E12)["physicalJustification"]

# consumers: no code module other than the registry tool references the BMS 12 V column
col = next(e for e in reg["entries"] if e["id"] == E12)["column"]
hits = []
for base in (".", "tools", "tests/synthetic"):
    for f in os.listdir(base):
        if f.endswith((".py", ".jsx", ".js")) and os.path.join(base, f).replace("\\", "/").lstrip("./") not in ("tools/signal_validity.py", "tests/synthetic/test_signal_validity.py"):
            if "12V Battery Supply" in open(os.path.join(base, f), encoding="utf-8", errors="replace").read():
                hits.append(os.path.join(base, f))
assert hits == [] and next(e for e in reg["entries"] if e["id"] == E12)["consumers"] == [], hits

# extractor on a synthetic file: equality parse, second text route, -100 and out-of-bound counts
txt = "time,[BMS] 12V Battery Supply Voltage (V),[BMS] HV Battery Intake Air Temperature (\u2103)\n1,0,20\n2,0.0,-100\n3,-0,95\n4,,\n5,0,-100\n"
rec = SV.file_record(txt.encode("utf-8"), [e["column"] for e in reg["entries"]])
d12 = rec["declared"][col]; da = rec["declared"][next(e for e in reg["entries"] if e["id"] == "intake_air_minus100")["column"]]
assert d12["nNumeric"] == 4 and d12["nZero"] == 4 and d12["nText"] == 4
assert da["nMinus100"] == 2 and da["nOutOfBoundNotMinus100"] == 1 and da["nNumeric"] == 4

# stored block (after the splice): partition identity, no non-zero BMS 12 V value, inventory labelled
A = json.load(open("summary_arrays.json", encoding="utf-8"))
B = A["signalValidity"]
e12 = next(x for x in B["entries"] if x["id"] == E12)
assert e12["filesRuleHolds"] + e12["filesRuleNotHolding"] == e12["filesWithSamples"] and e12["nonZeroValuesInDeclaredChannel"] == 0
assert "not a validity declaration" in B["inventory"]["label"] and B["reconciliation"]["rawNotInMasterByRole"]["unexplained"] == 0
assert not any(B["knownAnswer"]["misses"].values())
print("test_signal_validity OK")
