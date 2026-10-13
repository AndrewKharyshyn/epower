#!/usr/bin/env python3
"""M426: keep the per-chart cold-cohort METADATA consistent with the cohort support rule (analyses/M426_spec.md, Director ruling 2026-10-13, owner decision
'open all Cold data' 2026-10-13).

The cohort views (cohortMeta, EnergyIntensity, StartsPer100km, fuelStates) are built natively from the data and open when a cohort reaches the pre-registered
support rule (cohortMeta[c].inferenceAvailable, >= minDrivesForStatistics drives and >= minSupport.days days). The other seasonalCharts entries are built per
cohort by m296_refresh_master_seasonal.py / tools/regen_seasonal_raw.py (cold included once the seasonal master labels the cohort 'cold') and carry status /
coverage / coldStatus markers that are not written by those builders. This tool (stage after engine_start_rate) sets ONLY those markers from the live state, for
charts that carry a `data.cold` key, when the cold cohort meets the support rule:
  status.cold      'unavailable' | 'support_met_view_not_built' -> 'computed' when data.cold is built, else 'support_met_view_not_built' (a builder returned nothing)
  coverage.cold    the live cohort counts (copied from EnergyIntensity.coverage.cold) + status 'computed' / 'support_met_view_not_built'
  coverage.{all,warm,shoulder} of the charts that carry independent_days: refreshed to the live counts (they were frozen at the 410-drive basis)
  coldStatus       (EfficiencyBands) status 'computed' / 'support_met_view_not_built' with n and reason
It builds NO cold view and adds NO figure. Idempotent; a no-op while the cold cohort lacks support.
Usage: python tools/cold_support_sync.py [--dry-run]"""
import copy, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
NOT_BUILT = "support_met_view_not_built"
NATIVE = ("EnergyIntensity", "StartsPer100km")      # cold views computed natively by the cohort stages
COV_KEYS = ("n_drives", "km", "independent_days", "date_range", "ambient_range_c")
OLD = ("unavailable", NOT_BUILT, "computed")


def sync(A, cohort="cold"):
    """Pure: arrays dict -> (new arrays, list of changed paths)."""
    new, changes = copy.deepcopy(A), []
    cm = (A.get("cohortMeta") or {}).get(cohort)
    if not cm or cm.get("inferenceAvailable") is not True:
        return new, changes
    m = A["seasonalCharts"]["_meta"]["cohortSuppressedBelowMinSupport"]["minDrivesForStatistics"]
    dmin = A["comparisonCube"]["_meta"]["minSupport"]["days"]
    n, days = cm["eligibleForCohortView"], cm["nDaysObserved"]
    live = A["seasonalCharts"]["charts"]["EnergyIntensity"]["coverage"]
    cov = live[cohort]
    if n < m or days < dmin or cov.get("n_drives") != cm.get("n") or cov.get("independent_days") != days:
        raise SystemExit("cold_support_sync: cohortMeta and the EnergyIntensity coverage disagree (%r vs %r); nothing changed" % (cm, cov))
    reason = ("the %s cohort meets the support rule (n=%d drives, %d days; rule: >= %d drives and >= %d days)" % (cohort, n, days, m, dmin))
    for cid, ch in new["seasonalCharts"]["charts"].items():
        d = ch.get("data")
        if cid in NATIVE or not isinstance(d, dict) or cohort not in d:
            continue
        status = "computed" if d[cohort] is not None else NOT_BUILT
        st = ch.get("status")
        if isinstance(st, dict) and st.get(cohort) in OLD and st[cohort] != status:
            st[cohort] = status
            changes.append("/seasonalCharts/charts/%s/status/%s" % (cid, cohort))
        cv = ch.get("coverage")
        if isinstance(cv, dict):
            if isinstance(cv.get(cohort), dict):
                want = {k: copy.deepcopy(cov[k]) for k in COV_KEYS if k in cov}
                want["status"] = status
                if cv[cohort] != want:
                    cv[cohort] = want
                    changes.append("/seasonalCharts/charts/%s/coverage/%s" % (cid, cohort))
            for c in ("all", "warm", "shoulder"):          # frozen at an old basis in the charts that carry independent_days
                e, lv = cv.get(c), live.get(c)
                if isinstance(e, dict) and isinstance(lv, dict) and "independent_days" in e and "n_drives" in lv:
                    w = {k: lv[k] for k in ("n_drives", "km", "independent_days") if k in lv}
                    if any(e.get(k) != w[k] for k in w):
                        cv[c] = {**e, **w}
                        changes.append("/seasonalCharts/charts/%s/coverage/%s" % (cid, c))
        cs = ch.get("coldStatus")
        want = {"status": status, "n": n, "reason": reason + ("" if status == "computed" else "; the per-class view of this chart is not built for it (not zero, not 'no observations')")}
        if cohort == "cold" and isinstance(cs, dict) and cs.get("status") in OLD and cs != want:
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
