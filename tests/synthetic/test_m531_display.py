"""M531 display step (analyses/M531_spec.md Rev 2 + Director): the motored share beside the RPM Distribution chart carries its day-clustered interval from S.motoredShare for the SHOWN cohort. Recomputes every displayed
value from summary_arrays.json and runs motoredShareText in node with real and patched payloads: interval shown only under the support rule, exploratory text otherwise, n/a guards, the rule, and the payload block itself
(support fields, escalation rule, post hoc sensitivity labelled)."""
import json, os, re, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import language_gate as G

A = json.load(open("summary_arrays.json", encoding="utf-8")); MS = A["motoredShare"]; RD = A["rpmDistribution"]; FLOOR = RD["params"]["fuelStateRpmMin"]
jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
fn = re.search(r"function motoredShareText\(rd, floor, ms, key\)\{.*?" + chr(10) + "}" + chr(10), jsx, re.S).group(0)
def run(rd, ms, key):
    js = fn + chr(10) + "console.log(motoredShareText(%s, %s, %s, %s));" % (json.dumps(rd), json.dumps(FLOOR), json.dumps(ms), json.dumps(key))
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()

# payload block
assert MS["faithfulness"]["passed"] and MS["descriptive"] is True and MS["displayed"] is False
P = MS["pooled"]
assert P["intervalShown"] and P["nDaysWithMotored"] >= 10 and P["zeroNumeratorDrawShare"] < 0.025 and P["ci95Pct"][0] < P["pct"] < P["ci95Pct"][1]
assert "gridOnlyFfillSensitivity_postHoc_auditorFound" in MS and "NOT the pipeline convention" in MS["gridOnlyFfillSensitivity_postHoc_auditorFound"]["note"]
assert MS["allMasterDaysResampling"]["nDays"] == 141      # M721: 130 at 665 drives; M608: 126 at 632 drives; M578: 124 days at 621 drives, 121 at 606 and "escalates to the Director" in MS["escalationRule"]
# M721: the cold interval is shown from the pre-registered 5-day floor (M608 owner decision), exploratory
assert MS["cohorts"]["cold"]["intervalShown"] == (MS["cohorts"]["cold"]["nDays"] >= 5) and (MS["cohorts"]["cold"]["ci95Pct"] is None) == (not MS["cohorts"]["cold"]["intervalShown"]) and MS["cohorts"]["warm"]["intervalShown"] and MS["cohorts"]["shoulder"]["intervalShown"]
# pooled display: the pooled hours of the real payload and the pooled block
txt = run(RD, MS, "all")
g = MS["gridOnlyFfillSensitivity_postHoc_auditorFound"]
exp = "95 %% CI %.1f–%.1f, day-clustered; %d of %d drives and %d of %d days with motored seconds; a rare, zero-inflated state; pooled share with a grid-only gap-fill convention %.1f %%" % (
    P["ci95Pct"][0], P["ci95Pct"][1], P["nDrivesWithMotored"], P["nDrivesWithClassified"], P["nDaysWithMotored"], P["nDays"], g["pct"])
assert exp in txt, txt
assert "descriptive, no interval" not in txt and "of boost-classified engine-on hours" in txt
# shown cohort: the interval follows the cohort block; cold is exploratory
W = MS["cohorts"]["warm"]
assert ("95 %% CI %.1f–%.1f" % (W["ci95Pct"][0], W["ci95Pct"][1])) in run(RD, MS, "warm")
cold = run(RD, MS, "cold")
_C = MS["cohorts"]["cold"]
if _C["intervalShown"]:        # M721: the cold block reached the support rule (exploratory cohort); the text follows the block
    assert ("95 %% CI %.1f–%.1f" % (_C["ci95Pct"][0], _C["ci95Pct"][1])) in cold and "exploratory, no interval" not in cold
else:
    assert "exploratory, no interval (%d of %d days with motored seconds)" % (_C["nDaysWithMotored"], _C["nDays"]) in cold and "95 % CI" not in cold
# negative controls: a patched interval changes the text; a failed support rule shows no interval; a missing block says n/a (never a literal)
MS2 = json.loads(json.dumps(MS)); MS2["pooled"]["ci95Pct"][1] += 1.0
assert run(RD, MS2, "all") != txt
MS3 = json.loads(json.dumps(MS)); MS3["pooled"]["intervalShown"] = False; MS3["pooled"]["ci95Pct"] = None
assert "exploratory, no interval" in run(RD, MS3, "all") and "95 % CI" not in run(RD, MS3, "all")
assert "interval n/a" in run(RD, None, "all") and "interval n/a" in run(RD, {}, "all") and "interval n/a" in run(RD, MS, "unknown-cohort")
# rule
R = {r.rid: r for r in G.RULES}["M531-motored-share-interval"]
assert R.hits("0.9 % of boost-classified engine-on hours (bins ≥ 1400 rpm; motored 0.75 h of 79.4 h; descriptive, no interval)") and not R.hits(txt)
print("OK test_m531_display: block, shown cohort, support rule, guards, rule")
