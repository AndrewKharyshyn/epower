"""M525 display step (analyses/M525_spec.md Rev 2 + Director): the best-point list item is bound to S.rpmOptBand. Recomputes every displayed value from summary_arrays.json and checks the rendered fuel dumps
(all / warm / shoulder / cold; the item is corpus-wide), the dropped wording, and the rule."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

A = json.load(open("summary_arrays.json", encoding="utf-8"))
O = A["rpmOptBand"]; P = O["primary"]
assert O["faithfulness"]["passed"] and O["descriptive"] is True
ev = [P["pct"]] + list(O["edgeSensitivity"].values())
exp = [
    "%.1f%% of engine-on time (95 %% CI %.1f–%.1f, day-clustered bootstrap; %d drives, %d days with engine-on time (%d resampled), %.1f engine-on h)" % (P["pct"], P["ci95Pct"][0], P["ci95Pct"][1], P["nDrives"], P["nDaysWithEngineOn"], P["nDays"], P["engineOnSeconds"] / 3600),
    "gives %.1f–%.1f%%, a band-definition range, not an interval" % (min(ev), max(ev)),
    "observed occupancy of logged engine rpm (rpm ≥ 300, 1 Hz grid, duration-weighted)",
]
jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
assert "steady cruise" not in jsx.split("The best-point (OPT) band")[1][:2500] and "empiricalLoad" not in jsx
R = {r.rid: r for r in G.RULES}["M525-opt-band-wording"]
assert R.hits("falls (steady cruise / generator-charging load)") and R.hits("this block was computed once on 397 of 410 drives")
assert not R.hits(" ".join(exp))
# superseded label on the old block, numeric leaves byte-unchanged
rf = A["generatorTractionRecon"]["rpmFinding"]
assert rf["supersededBy"] == "rpmOptBand" and rf["empiricalPct"] == 63.4 and rf["empiricalDrives"] == 397 and rf["corpusWideDrives"] == 410 and rf["empiricalN"] == 284260
if os.path.isdir("tabtext"):
    n = 0
    for mode in ("all", "warm", "shoulder", "cold"):
        t = " ".join(open(os.path.join("tabtext", "fuel__%s.txt" % mode), encoding="utf-8").read().split())
        for e in exp:
            assert e in t, (mode, e)
        assert "steady cruise / generator-charging load" not in t and "not refreshed to the current corpus" not in t, mode
        n += 1
    assert n == 4
print("OK test_m525_display: displayed values equal the payload, dropped wording absent, old block labelled")
