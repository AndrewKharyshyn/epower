#!/usr/bin/env python3
"""M355 (Cs-1): source dates for the odometer and the car age, and the logged km on each side of the odometer date.
M361: also writes meta.intakeAir (tools/intake_air_block.py, availability of the T_intake channel from the master).
Writes summary_arrays.json meta.{odometerAsOf, registeredDate, carAgeAsOf, kmLoggedToOdometerDate, kmLoggedAfterOdometerDate} from
summary_config.json vehicle (odometerAsOf, registered) and drive_master.csv (read-only: date, distance_km). Asserts: carAgeNow equals
(carAgeAsOf - registered)/365.25 in meta, cycleLife and seasonalLife (0.001 yr); the two km parts sum to meta.totalKm (0.1 km); the eligibility families
the Overview line binds to exist by exact name. Idempotent. Usage: python tools/refresh_meta_sources.py"""
import json, os
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
FAMILIES = ("Headline totals (km, kWh, GTC, duration)", "Current-integral energy metrics", "EV traction census (M53)")
cfg = json.load(open("summary_config.json", encoding="utf-8"))["vehicle"]
A = json.load(open("summary_arrays.json", encoding="utf-8"))
dm = pd.read_csv("drive_master.csv", usecols=["date", "distance_km"], low_memory=False)
import sys; sys.path.insert(0, os.path.join(ROOT, "tools"))
from intake_air_block import intake_air_block
dm_in = pd.read_csv("drive_master.csv", usecols=["file", "date", "time_start", "T_intake"], low_memory=False)
dates = pd.to_datetime(dm["date"])
asof = pd.Timestamp(cfg["odometerAsOf"]); reg = pd.Timestamp(cfg["registered"]); last = dates.max()
m = A["meta"]
to = float(dm.loc[dates <= asof, "distance_km"].sum()); after = float(dm.loc[dates > asof, "distance_km"].sum())
assert abs((to + after) - m["totalKm"]) < 0.1, (to, after, m["totalKm"])
age = (last - reg).days / 365.25
for name, blk in (("meta", m), ("cycleLife", A["cycleLife"]), ("seasonalLife", A["seasonalLife"])):
    assert abs(blk["carAgeNow"] - age) < 0.001, (name, blk["carAgeNow"], age)
have = {f["family"] for f in A["eligibility"]["families"]}
assert set(FAMILIES) <= have, sorted(set(FAMILIES) - have)
m.update(odometerAsOf=cfg["odometerAsOf"], registeredDate=cfg["registered"], carAgeAsOf=str(last.date()),
         kmLoggedToOdometerDate=round(to, 1), kmLoggedAfterOdometerDate=round(after, 1))
sdm_in = pd.read_csv("seasonal_drive_master.csv", usecols=["file", "date", "thermal_regime_raw", "ambient_time_mean_c", "batt_intake_time_mean_c"], low_memory=False)
m["intakeAir"] = intake_air_block(dm_in, sdm_in)   # M361
with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(A, ensure_ascii=False, indent=1))
print(json.dumps({k: m[k] for k in ("odometerAsOf", "registeredDate", "carAgeAsOf", "kmLoggedToOdometerDate", "kmLoggedAfterOdometerDate")}))
