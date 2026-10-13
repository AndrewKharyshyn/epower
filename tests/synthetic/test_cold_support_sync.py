"""M426 known-answer tests for tools/cold_support_sync.py: the per-chart cold markers are rewritten only when the cold cohort meets the support rule, only for
charts whose cold view is not built, never for the natively computed charts, with no lost leaf, idempotently; inconsistent inputs refuse. Synthetic arrays."""
import copy, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cold_support_sync as CS
import leaf_guard as LG


def arrays(supported=True):
    cov = {"n_drives": 12, "km": 143.6, "independent_days": 5, "date_range": ["2026-09-30", "2026-10-13"], "ambient_range_c": [3.0, 5.0]} if supported else {"n_drives": 0, "status": "no_observations"}
    return {
        "cohortMeta": {"cold": {"n": 12, "inferenceAvailable": True, "eligibleForCohortView": 12, "nDaysObserved": 5} if supported else
                       {"nObserved": 7, "inferenceAvailable": False, "eligibleForCohortView": 0, "nDaysObserved": 3}},
        "comparisonCube": {"_meta": {"minSupport": {"drives": 10, "days": 3}}},
        "seasonalCharts": {"_meta": {"cohortSuppressedBelowMinSupport": {"minDrivesForStatistics": 10, "nObserved": {} if supported else {"cold": 7}}}, "charts": {
            "EnergyIntensity": {"data": {"cold": {"value": 17.7}}, "coverage": {"cold": cov}},
            "DriveTypeChart": {"data": {"cold": None}, "status": {"all": "computed", "cold": "unavailable"},
                               "coverage": {"all": {"n_drives": 410}, "cold": {"n_drives": 0, "status": "no_observations"}}},
            "EfficiencyBands": {"data": {"cold": None}, "coldStatus": {"status": "unavailable", "n": 0, "reason": "no sub-5 C (cold) drives in the corpus; cohort requires >=10 for a view"}},
            "SpeedDist": {"data": {"cold": None}, "status": {"cold": "unavailable"}},
            "BuiltChart": {"data": {"cold": {"x": 1}}, "status": {"cold": "computed"}},          # a built cold view must stay untouched
            "NoMarkers": {"data": {"cold": None}}}}}


A = arrays()
new, ch = CS.sync(A)
assert sorted(ch) == sorted(["/seasonalCharts/charts/DriveTypeChart/status/cold", "/seasonalCharts/charts/DriveTypeChart/coverage/cold",
                             "/seasonalCharts/charts/EfficiencyBands/coldStatus", "/seasonalCharts/charts/SpeedDist/status/cold"]), ch
c = new["seasonalCharts"]["charts"]
assert c["DriveTypeChart"]["status"]["cold"] == CS.NOT_BUILT and c["DriveTypeChart"]["status"]["all"] == "computed"
assert c["DriveTypeChart"]["coverage"]["cold"] == {"n_drives": 12, "km": 143.6, "independent_days": 5, "date_range": ["2026-09-30", "2026-10-13"], "ambient_range_c": [3.0, 5.0], "status": CS.NOT_BUILT}
assert c["DriveTypeChart"]["coverage"]["all"] == {"n_drives": 410}                                  # other cohorts are not touched
assert c["EfficiencyBands"]["coldStatus"]["status"] == CS.NOT_BUILT and c["EfficiencyBands"]["coldStatus"]["n"] == 12 and "12 drives" in c["EfficiencyBands"]["coldStatus"]["reason"]
assert c["BuiltChart"] == A["seasonalCharts"]["charts"]["BuiltChart"] and c["EnergyIntensity"] == A["seasonalCharts"]["charts"]["EnergyIntensity"]
assert all(c[k]["data"]["cold"] is None for k in ("DriveTypeChart", "EfficiencyBands", "SpeedDist", "NoMarkers"))        # no cold view is built
assert LG.guard(A, new, [])["nLost"] == 0                                                          # values change, no leaf is lost
new2, ch2 = CS.sync(new)
assert ch2 == [] and new2 == new                                                                    # idempotent

# a later ingestion (cold 12 -> 15 drives): the markers written earlier are refreshed to the live counts, idempotently
L = copy.deepcopy(new)
L["cohortMeta"]["cold"].update({"n": 15, "eligibleForCohortView": 15, "nDaysObserved": 6})
L["seasonalCharts"]["charts"]["EnergyIntensity"]["coverage"]["cold"].update({"n_drives": 15, "independent_days": 6})
l2, chl = CS.sync(L)
assert l2["seasonalCharts"]["charts"]["DriveTypeChart"]["coverage"]["cold"]["n_drives"] == 15 and l2["seasonalCharts"]["charts"]["EfficiencyBands"]["coldStatus"]["n"] == 15
assert sorted(chl) == sorted(["/seasonalCharts/charts/DriveTypeChart/coverage/cold", "/seasonalCharts/charts/EfficiencyBands/coldStatus"]), chl
assert CS.sync(l2)[1] == []

# no support -> no change at all
B = arrays(supported=False)
nb, chb = CS.sync(B)
assert chb == [] and nb == B

# inconsistent inputs refuse (cohortMeta says supported, the native coverage disagrees)
for mut in (lambda a: a["seasonalCharts"]["charts"]["EnergyIntensity"]["coverage"]["cold"].__setitem__("n_drives", 11),
            lambda a: a["seasonalCharts"]["charts"]["EnergyIntensity"]["coverage"]["cold"].__setitem__("independent_days", 4),
            lambda a: a["cohortMeta"]["cold"].__setitem__("eligibleForCohortView", 9)):
    a = copy.deepcopy(A); mut(a)
    try:
        CS.sync(a)
    except SystemExit:
        continue
    raise AssertionError("inconsistent input accepted")
print("test_cold_support_sync: OK")
