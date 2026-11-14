"""M648 (UI-04 / UI-06, spec analyses/M648_spec.md Rev 1): the time-to-threshold block carries a Cold cohort under the M435 definitions (exploratory below 10 effective days: no reading class, no median),
the partition holds, warm / shoulder / all keep their cells, the extended fill rows sit in a separate sub-block and the Compare view shows the observed share instead of a median."""
import json, os, re, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
import language_gate as LG
A = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
T = A["thermalSupportLedger"]["timeToThreshold"]
assert set(T["cohorts"]) == {"all", "warm", "shoulder", "cold"} and T["partitionCheck"]["unassignedDrives"] == 0
for k, ns in T["partitionCheck"]["cells"].items():
    assert ns["all"] == ns["warm"] + ns["shoulder"] + ns["cold"], k
for fl in ("coolant", "oil"):
    for thr, c in T["cohorts"]["cold"][fl].items():
        assert "exploratory" in c and "rmst" in c
        if c["exploratory"]:
            assert c["median"]["shown"] is False and all("reading" not in h and "readingClasses" not in h for h in c["horizons"]), (fl, thr)
assert T["reconciliation"]["allEqual"] and any(k.startswith("cold/") for k in T["reconciliation"]["checks"])
E = T["fillSensitivity"]["extendedFills"]
assert E["fills"] == [3, 15, 30] and E["checks"]["allOk"] and "not a confidence interval" in E["label"] and E["cohort"] == "all"
assert set(T["fillSensitivity"]["settings"]) == {"0", "3", "6"}, "the 0 / 3 / 6 leaves are unchanged"
assert "0-6 s" in " ".join(T["fillSensitivity"]["limits"])
J = open(os.path.join(REPO, "xtrail_summary.jsx"), encoding="utf-8").read().replace("\r\n", "\n")
i = J.index("  ThermalWarmupLag:{kind:\"kpi\""); spec = J[i:J.index("  ThermalFuelPenalty:{kind", i)]
assert "cmpTteShare(" in spec and "Kaplan-Meier" not in spec.split("note:")[0] and "No median is drawn here" in spec
assert "<TteSupportNote series={series}/>" in J and "noContrast:true" in J and 'data-m648="extended-fills"' in J and "m.ci(data[o.s.key],o.s.key)" in J
r = [x for x in LG.RULES if x.rid == "M648-tte-cold-wording"][0]
for bad in ("the fill range is a confidence interval", "cold starts warm up faster than warm", "winter warm-up", "median time to threshold of the cold cohort"):
    assert r.hits(bad), bad
for good in ("range over declared conventions, not a confidence interval", "Cold is descriptive"):
    assert not r.hits(good), good
print("PASS test_m648_tte_cold")
