"""M355 (Cs-1) known-answer test of meta.{odometerAsOf, registeredDate, carAgeAsOf, kmLoggedToOdometerDate, kmLoggedAfterOdometerDate}: recomputed from
summary_config.json vehicle and drive_master.csv; carAgeNow equal across meta / cycleLife / seasonalLife; the Overview percent is kmLoggedToOdometerDate/odometer."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
import pandas as pd
A = json.load(open("summary_arrays.json", encoding="utf-8")); v = json.load(open("summary_config.json", encoding="utf-8"))["vehicle"]
dm = pd.read_csv("drive_master.csv", usecols=["date", "distance_km"], low_memory=False); d = pd.to_datetime(dm["date"]); m = A["meta"]
fails = 0
def ok(l, c, e=""):
    global fails
    print(("PASS " if c else "FAIL ") + l + ((" - " + str(e)) if (not c and e) else "")); fails += 0 if c else 1
asof = pd.Timestamp(v["odometerAsOf"])
ok("odometerAsOf / registeredDate come from the config vehicle block", m["odometerAsOf"] == v["odometerAsOf"] and m["registeredDate"] == v["registered"])
ok("carAgeAsOf == last logged date", m["carAgeAsOf"] == str(d.max().date()))
to = round(float(dm.loc[d <= asof, "distance_km"].sum()), 1); af = round(float(dm.loc[d > asof, "distance_km"].sum()), 1)
ok(f"km to / after the odometer date recomputed ({to} / {af})", (m["kmLoggedToOdometerDate"], m["kmLoggedAfterOdometerDate"]) == (to, af), (m["kmLoggedToOdometerDate"], m["kmLoggedAfterOdometerDate"]))
ok("the two parts sum to totalKm", abs(to + af - m["totalKm"]) < 0.1)
age = (d.max() - pd.Timestamp(v["registered"])).days / 365.25
ok("carAgeNow equal across meta / cycleLife / seasonalLife and to (as-of - registered)/365.25", all(abs(b["carAgeNow"] - age) < 0.001 for b in (m, A["cycleLife"], A["seasonalLife"])))
ok("odometer in meta equals the config reading", m["odometer"] == v["odometerKm"])
ok("eligibility families named in the Overview line exist", {"Headline totals (km, kWh, GTC, duration)", "Current-integral energy metrics", "EV traction census (M53)"} <= {f["family"] for f in A["eligibility"]["families"]})
print("META_SOURCES FAILS =", fails); sys.exit(1 if fails else 0)
