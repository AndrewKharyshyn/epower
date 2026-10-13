#!/usr/bin/env python3
"""M426: keep the per-chart cold-cohort METADATA consistent with the cohort support rule (analyses/M426_spec.md, Director ruling 2026-10-13).

The cohort views (cohortMeta, EnergyIntensity, StartsPer100km, fuelStates) are built natively from the data and open when a cohort reaches the pre-registered
support rule (cohortMeta[c].inferenceAvailable, >= minDrivesForStatistics drives and >= minSupport.days days). The other seasonalCharts entries are written by
m296_refresh_master_seasonal.py / tools/regen_seasonal_raw.py with `data.cold = None` and carry hand-written cold markers ('unavailable', coverage
'no_observations', EfficiencyBands.coldStatus 'no sub-5 C drives in the corpus'). Once the cold cohort meets the support rule those markers are FALSE.
This tool rewrites ONLY those markers, only for charts whose `data.cold` is None, and only when the cold cohort meets the rule:
  status.cold                    'unavailable'            -> 'support_met_view_not_built'
  coverage.cold                  {'n_drives': 0, 'status': 'no_observations'} -> the live cohort counts (copied from EnergyIntensity.coverage.cold) + the same status
  coldStatus (EfficiencyBands)   status 'unavailable'      -> 'support_met_view_not_built' with n and reason
It builds NO cold view and adds NO figure: 'view not built' is not 'no observations' and not zero. Idempotent; a no-op while the cold cohort lacks support.
Usage: python tools/cold_support_sync.py [--dry-run]"""
import copy, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
NOT_BUILT = "support_met_view_not_built"
NATIVE = ("EnergyIntensity", "StartsPer100km")      # cold views computed natively by the cohort stages
COV_KEYS = ("n_drives", "km", "independent_days", "date_range", "ambient_range_c")


def sync(A, cohort="cold"):
    """Pure: arrays dict -> (new arrays, list of changed paths)."""
    new, changes = copy.deepcopy(A), []
    cm = (A.get("cohortMeta") or {}).get(cohort)
    if not cm or cm.get("inferenceAvailable") is not True:
        return new, changes
    m = A["seasonalCharts"]["_meta"]["cohortSuppressedBelowMinSupport"]["minDrivesForStatistics"]
    dmin = A["comparisonCube"]["_meta"]["minSupport"]["days"]
    n, days = cm["eligibleForCohortView"], cm["nDaysObserved"]
    cov = A["seasonalCharts"]["charts"]["EnergyIntensity"]["coverage"][cohort]
    if n < m or days < dmin or cov.get("n_drives") != cm.get("n") or cov.get("independent_days") != days:
        raise SystemExit("cold_support_sync: cohortMeta and the EnergyIntensity coverage disagree (%r vs %r); nothing changed" % (cm, cov))
    blk = {k: copy.deepcopy(cov[k]) for k in COV_KEYS if k in cov}
    blk["status"] = NOT_BUILT
    reason = ("the %s cohort meets the support rule (n=%d drives, %d days; rule: >= %d drives and >= %d days); the per-class view of this chart is not built "
              "for it yet (not zero, not 'no observations')" % (cohort, n, days, m, dmin))
    for cid, ch in new["seasonalCharts"]["charts"].items():
        d = ch.get("data")
        if cid in NATIVE or not isinstance(d, dict) or d.get(cohort, "x") is not None:
            continue
        # a marker is (re)written while it is in the old state OR in the state this tool wrote earlier, so later ingestions refresh the live counts
        st = ch.get("status")
        if isinstance(st, dict) and st.get(cohort) in ("unavailable", NOT_BUILT) and st[cohort] != NOT_BUILT:
            st[cohort] = NOT_BUILT
            changes.append("/seasonalCharts/charts/%s/status/%s" % (cid, cohort))
        cv = ch.get("coverage")
        if isinstance(cv, dict) and isinstance(cv.get(cohort), dict) and cv[cohort].get("status") in ("no_observations", NOT_BUILT) and cv[cohort] != blk:
            cv[cohort] = copy.deepcopy(blk)
            changes.append("/seasonalCharts/charts/%s/coverage/%s" % (cid, cohort))
        cs = ch.get("coldStatus")
        want = {"status": NOT_BUILT, "n": n, "reason": reason}
        if cohort == "cold" and isinstance(cs, dict) and cs.get("status") in ("unavailable", NOT_BUILT) and cs != want:
            ch["coldStatus"] = want
            changes.append("/seasonalCharts/charts/%s/coldStatus" % cid)
    return new, changes


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    new, ch = sync(json.loads(raw))
    print(json.dumps({"changed": len(ch), "paths": ch[:60]}))
    if ch and "--dry-run" not in argv:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
