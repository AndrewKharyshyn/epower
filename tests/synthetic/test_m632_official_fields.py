"""M632 (W1-09): the M114 life-year retraction keeps the manufacturer's source facts (official.expectedLifeYr, official.capacityFadeConditionYr) and still nulls every modelled year output."""
import json, os
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
A = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
cfg = json.load(open(os.path.join(REPO, "summary_config.json"), encoding="utf-8"))["officialDisclosure"]
off = A["officialDisclosureCorrelation"]["official"]
assert off["expectedLifeYr"] == cfg["expectedLifeYr"] == 14 and off["capacityFadeConditionYr"] == cfg["capacityFadeConditionYr"] == 14
assert off["expectedLifeKm"] == off["capacityFadeConditionKm"] == 190000
LIFE = {"yearsTotal", "yearsRemain", "yearsBand", "calendarLifeYrShaded", "matrixSpanYr", "thresholdSpanYr", "workloadSpanYr", "crossingYr", "yrPer1kGtc", "afWeightedYearsTotal",
        "yearsToOfficialLifeKm", "expectedLifeYr", "capacityFadeConditionYr", "observedCrossingYr", "selectedCrossingYr", "thresholdSensitivity"}
bad = []
def walk(o, path, in_official):
    if isinstance(o, dict):
        for k, v in o.items():
            p = path + "/" + k
            if k in LIFE and v is not None and not (in_official and k in ("expectedLifeYr", "capacityFadeConditionYr")):
                bad.append(p)
            walk(v, p, in_official)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, path + "[%d]" % i, in_official)
for blk in ("cycleLife", "fadeModes", "seasonalLife", "observedMix", "realisticBlend"):
    if isinstance(A.get(blk), dict):
        walk(A[blk], blk, False)
for k, v in A["officialDisclosureCorrelation"].items():
    walk({k: v}, "officialDisclosureCorrelation", k == "official")
assert not bad, "modelled year outputs not retracted: %s" % bad[:5]
src = open(os.path.join(REPO, "compute_summary_arrays.py"), encoding="utf-8").read()
assert "if _k2 != 'official'" in src and "M632 (self-audit W1-09)" in src
print("PASS test_m632_official_fields")
