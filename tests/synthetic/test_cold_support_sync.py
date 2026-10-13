"""M426 known-answer tests for tools/cold_support_sync.py: the per-chart cold markers follow the live state once the cold cohort meets the support rule
('computed' where the chart's cold view is built, 'support_met_view_not_built' where a builder returned nothing), the natively computed charts are never touched,
the coverage frozen at an old basis is refreshed, no leaf is lost, the run is idempotent and follows later ingestions, and inconsistent inputs refuse. Synthetic arrays."""
import copy, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cold_support_sync as CS
import leaf_guard as LG

LIVE = {"all": {"n_drives": 578, "km": 9337.9, "independent_days": 117}, "warm": {"n_drives": 423, "km": 8279.4, "independent_days": 100},
        "shoulder": {"n_drives": 144, "km": 1042.3, "independent_days": 47}}


def arrays(supported=True):
    cold = {"n_drives": 11, "km": 16.2, "independent_days": 4, "date_range": ["2026-09-30", "2026-10-13"], "ambient_range_c": [3.0, 5.0]} if supported else {"n_drives": 0, "status": "no_observations"}
    return {
        "cohortMeta": {"cold": {"n": 11, "inferenceAvailable": True, "eligibleForCohortView": 11, "nDaysObserved": 4} if supported else
                       {"nObserved": 7, "inferenceAvailable": False, "eligibleForCohortView": 0, "nDaysObserved": 3}},
        "comparisonCube": {"_meta": {"minSupport": {"drives": 10, "days": 3}}},
        "seasonalCharts": {"_meta": {"cohortSuppressedBelowMinSupport": {"minDrivesForStatistics": 10, "nObserved": {} if supported else {"cold": 7}}}, "charts": {
            "EnergyIntensity": {"data": {"cold": {"value": 40.2}}, "coverage": {**copy.deepcopy(LIVE), "cold": cold}},
            "DriveTypeChart": {"data": {"cold": [{"key": "urban", "drives": 11}]}, "status": {"all": "computed", "cold": "unavailable"},
                               "coverage": {"all": {"n_drives": 410, "km": 8437.74, "independent_days": 90}, "warm": {"n_drives": 346, "km": 8033.3, "independent_days": 86},
                                            "shoulder": {"n_drives": 64, "km": 404.44, "independent_days": 22}, "cold": {"n_drives": 0, "status": "no_observations"}}},
            "EfficiencyBands": {"data": {"cold": [{"label": "Urban"}]}, "coldStatus": {"status": "unavailable", "n": 0, "reason": "no sub-5 C (cold) drives in the corpus; cohort requires >=10 for a view"}},
            "SpeedDist": {"data": {"cold": {"bins": [1]}}, "status": {"cold": "unavailable"}, "coverage": {"all": {"n_drives": 578, "km": 9337.9}, "cold": {"n_drives": 11, "km": 16.2}}},   # regen wrote cold without status
            "NotBuilt": {"data": {"cold": None}, "status": {"cold": "unavailable"}, "coverage": {"cold": {"n_drives": 0, "status": "no_observations"}}},
            "NoMarkers": {"data": {"cold": {"x": 1}}},
            "NoColdKey": {"data": {"all": {"x": 1}}, "status": {"cold": "unavailable"}}}}}      # a chart without a cold slot is not ours


A = arrays()
new, ch = CS.sync(A)
c = new["seasonalCharts"]["charts"]
want_cov = {"n_drives": 11, "km": 16.2, "independent_days": 4, "date_range": ["2026-09-30", "2026-10-13"], "ambient_range_c": [3.0, 5.0]}
assert c["DriveTypeChart"]["status"] == {"all": "computed", "cold": "computed"}
assert c["DriveTypeChart"]["coverage"]["cold"] == {**want_cov, "status": "computed"}
assert c["DriveTypeChart"]["coverage"]["all"] == {"n_drives": 578, "km": 9337.9, "independent_days": 117}          # refreshed from the frozen 410 basis
assert c["DriveTypeChart"]["coverage"]["shoulder"] == {"n_drives": 144, "km": 1042.3, "independent_days": 47}
assert c["SpeedDist"]["coverage"]["all"] == {"n_drives": 578, "km": 9337.9}                                          # no independent_days: left to the builder
assert c["SpeedDist"]["coverage"]["cold"] == {**want_cov, "status": "computed"} and c["SpeedDist"]["status"]["cold"] == "computed"
assert c["EfficiencyBands"]["coldStatus"]["status"] == "computed" and c["EfficiencyBands"]["coldStatus"]["n"] == 11 and "11 drives" in c["EfficiencyBands"]["coldStatus"]["reason"]
assert c["NotBuilt"]["status"]["cold"] == CS.NOT_BUILT and c["NotBuilt"]["coverage"]["cold"]["status"] == CS.NOT_BUILT and c["NotBuilt"]["coverage"]["cold"]["n_drives"] == 11
assert c["EnergyIntensity"] == A["seasonalCharts"]["charts"]["EnergyIntensity"] and c["NoMarkers"] == A["seasonalCharts"]["charts"]["NoMarkers"]
assert c["NoColdKey"] == A["seasonalCharts"]["charts"]["NoColdKey"]
assert all(c[k]["data"] == A["seasonalCharts"]["charts"][k]["data"] for k in c)                                       # no data value is ever written
assert LG.guard(A, new, [])["nLost"] == 0                                                                              # values change, no leaf is lost
new2, ch2 = CS.sync(new)
assert ch2 == [] and new2 == new                                                                                       # idempotent

# a later ingestion (cold 11 -> 15 drives): the markers written earlier follow the live counts; a chart whose builder now returns a view flips to 'computed'
L = copy.deepcopy(new)
L["cohortMeta"]["cold"].update({"n": 15, "eligibleForCohortView": 15, "nDaysObserved": 6})
L["seasonalCharts"]["charts"]["EnergyIntensity"]["coverage"]["cold"].update({"n_drives": 15, "independent_days": 6})
L["seasonalCharts"]["charts"]["NotBuilt"]["data"]["cold"] = {"y": 1}
l2, chl = CS.sync(L)
lc = l2["seasonalCharts"]["charts"]
assert lc["DriveTypeChart"]["coverage"]["cold"]["n_drives"] == 15 and lc["EfficiencyBands"]["coldStatus"]["n"] == 15
assert lc["NotBuilt"]["status"]["cold"] == "computed" and lc["NotBuilt"]["coverage"]["cold"]["status"] == "computed"
assert CS.sync(l2)[1] == []

# no support -> no change at all
B = arrays(supported=False)
nb, chb = CS.sync(B)
assert chb == [] and nb == B

# inconsistent inputs refuse (cohortMeta says supported, the native coverage disagrees)
for mut in (lambda a: a["seasonalCharts"]["charts"]["EnergyIntensity"]["coverage"]["cold"].__setitem__("n_drives", 10),
            lambda a: a["seasonalCharts"]["charts"]["EnergyIntensity"]["coverage"]["cold"].__setitem__("independent_days", 3),
            lambda a: a["cohortMeta"]["cold"].__setitem__("eligibleForCohortView", 9)):
    a = copy.deepcopy(A); mut(a)
    try:
        CS.sync(a)
    except SystemExit:
        continue
    raise AssertionError("inconsistent input accepted")
print("test_cold_support_sync: OK")
