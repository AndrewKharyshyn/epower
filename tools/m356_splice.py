#!/usr/bin/env python3
"""M356 (spec analyses/M356_spec.md Rev 2): compute crawlStopGo.phaseEnergy per thermal cohort and splice it additively.
CONTROL (always): the fresh released composition (_crawl_stop_go + _crawl_stop_go_two_part) on all rows must equal the stored top-level crawlStopGo byte-for-byte (canonical JSON),
so the new cycle-dict key `ph` cannot have leaked; the new launch discharge / approach regen / cycle net quantiles must equal the stored whLaunchOut / whApproachIn / whCycleNet
(regression control, same _phase arithmetic; not validation). Loaders: raw_only/ and drive_raw_cache frame loader exactly as tools/regen_seasonal_raw.py.
Modes: --check (writes analyses/M356_check.json, no payload write) | --splice (check + additive splice of phaseEnergy into crawlStopGo and seasonalCharts.charts.CrawlStopGo.data.{all,warm,shoulder}).
Never writes drive_master.csv or raw files. Usage: python tools/m356_splice.py --check|--splice"""
import copy, json, os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import compute_summary_arrays as C
import drive_raw_cache as drc
import regen_seasonal_raw as R

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M356_check.json")
canon = R.canon


def main():
    mode = "--splice" if "--splice" in sys.argv else "--check"
    t0 = time.time()
    A = json.load(open(ARR, encoding="utf-8"))
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    reg = pd.read_csv("seasonal_drive_master.csv", low_memory=False)[["file", "thermal_regime"]]
    dm_r = dm.merge(reg, on="file", how="left")
    assert len(dm_r) == len(dm) and dm_r.thermal_regime.notna().all()
    subsets = {"all": dm, "warm": dm_r[dm_r.thermal_regime == "warm"].drop(columns=["thermal_regime"]).reset_index(drop=True),
               "shoulder": dm_r[dm_r.thermal_regime == "shoulder"].drop(columns=["thermal_regime"]).reset_index(drop=True)}
    fl = drc.make_frame_loader()
    res = {"milestone": "M356", "mode": mode, "nLive": int(len(dm)), "cohortSizes": {k: int(len(v)) for k, v in subsets.items()}, "control": {}, "cohorts": {}}
    ph = {}
    for c, sub in subsets.items():
        t = time.time()
        b = C._crawl_stop_go_phases(sub, R.raw_loader, frame_loader=fl)
        ph[c] = None if b is None else b["phaseEnergy"]
        res["cohorts"][c] = {"seconds": round(time.time() - t, 1), "nCycles": (ph[c] or {}).get("nCycles"), "additiveShare": (ph[c] or {}).get("additiveShare"),
                             "additiveVerified": (ph[c] or {}).get("additiveVerified")}
        print("phases", c, res["cohorts"][c], flush=True)
    # ---- control 1: released composition on all rows == stored top-level block (no leak of the new cycle key) ----
    t = time.time()
    fresh = C._crawl_stop_go(dm, R.raw_loader, frame_loader=fl)
    two = C._crawl_stop_go_two_part(dm, R.raw_loader, frame_loader=fl)
    if fresh is not None and two is not None:
        fresh.update(two)
    stored = {k: v for k, v in A["crawlStopGo"].items() if k != "phaseEnergy"}
    res["control"]["topLevelParity"] = bool(canon(fresh) == canon(stored))
    res["control"]["parityNote"] = "fresh _crawl_stop_go + _crawl_stop_go_two_part (all rows) vs stored crawlStopGo without phaseEnergy, canonical JSON"
    res["control"]["parityMismatchedKeys"] = sorted(k for k in set(fresh) | set(stored) if canon(fresh.get(k)) != canon(stored.get(k)))[:10]
    res["control"]["seconds"] = round(time.time() - t, 1)
    # ---- control 2: window quantiles equal the stored published fields ----
    P = ph["all"]
    q = lambda d: {k: d.get(k) for k in ("median", "p25", "p75", "p95", "n")}
    res["control"]["whLaunchOutEqualsLaunchDischarge"] = bool(q(A["crawlStopGo"]["whLaunchOut"]) == q(P["launch"]["dischargeWh"]))
    res["control"]["whApproachInEqualsApproachRegen"] = bool(q(A["crawlStopGo"]["whApproachIn"]) == q(P["approach"]["regenWh"]))
    res["control"]["whCycleNetEqualsCycleNet"] = bool(q(A["crawlStopGo"]["whCycleNet"]) == q(P["cycle"]["netWh"]))
    res["control"]["netEqualsDischargeMinusRegen"] = "tested per window in tests/synthetic/test_csg_phases.py (known answer)"
    ok = all(res["control"][k] for k in ("topLevelParity", "whLaunchOutEqualsLaunchDischarge", "whApproachInEqualsApproachRegen", "whCycleNetEqualsCycleNet")) and all(v is not None for v in ph.values())
    res["controlPassed"] = bool(ok)
    res["totalSeconds"] = round(time.time() - t0, 1)
    json.dump({**res, "phaseEnergy": ph}, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False, default=float)
    print(json.dumps({"controlPassed": ok, "control": res["control"]}, indent=1))
    if mode == "--check" or not ok:
        sys.exit(0 if ok else 1)
    old = copy.deepcopy(A)
    A["crawlStopGo"]["phaseEnergy"] = json.loads(json.dumps(ph["all"], default=float))
    d = A["seasonalCharts"]["charts"]["CrawlStopGo"]["data"]
    for c in ("all", "warm", "shoulder"):
        d[c]["phaseEnergy"] = json.loads(json.dumps(ph[c], default=float))
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
    print("spliced phaseEnergy into crawlStopGo and seasonalCharts.charts.CrawlStopGo.data.{all,warm,shoulder}")


if __name__ == "__main__":
    main()
