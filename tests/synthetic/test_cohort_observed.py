"""M354 (F08.r1) known-answer test of cohortMeta.{observed, eligibleForCohortView, inferenceAvailable, nDaysObserved}: recomputed independently from
seasonal_drive_master.csv (thermal_regime_raw = physical class, thermal_regime = class after the M310 minimum-support rule)."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
import pandas as pd
A = json.load(open("summary_arrays.json", encoding="utf-8")); cm = A["cohortMeta"]
sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False)
cfg_min = int(json.load(open("seasonal_config.json", encoding="utf-8"))["cohorts"]["minDrivesForStatistics"])
fails = 0
def ok(l, c, e=""):
    global fails
    print(("PASS " if c else "FAIL ") + l + ((" - " + str(e)) if (not c and e) else "")); fails += 0 if c else 1
raw = sdm["thermal_regime_raw"].astype(str); reg = sdm["thermal_regime"].astype(str)
for c in ("warm", "shoulder", "cold"):
    obs = int((raw == c).sum()); elig = int((reg == c).sum()); days = int(sdm.loc[raw == c, "date"].nunique())
    m = cm[c]
    ok(f"{c}: observed {obs}, eligibleForCohortView {elig}, nDaysObserved {days}", (m["observed"], m["eligibleForCohortView"], m["nDaysObserved"]) == (obs, elig, days), m)
    ok(f"{c}: inferenceAvailable == (eligible >= {cfg_min})", m["inferenceAvailable"] == (elig >= cfg_min))
    ok(f"{c}: observed == eligible + nObserved(below support)", m["observed"] == m["eligibleForCohortView"] + m.get("nObserved", 0))
ok("observed conserves: warm + shoulder + cold == all == rows of the seasonal master", cm["warm"]["observed"] + cm["shoulder"]["observed"] + cm["cold"]["observed"] == cm["all"]["observed"] == len(sdm))
ok("all: nDaysObserved equals distinct dates", cm["all"]["nDaysObserved"] == int(sdm["date"].nunique()))
ok("min support is one value everywhere", cfg_min == A["ambientTable"]["cohortMinDrives"] == A["seasonalCharts"]["_meta"]["cohortSuppressedBelowMinSupport"]["minDrivesForStatistics"])
print("COHORT_OBSERVED FAILS =", fails); sys.exit(1 if fails else 0)
