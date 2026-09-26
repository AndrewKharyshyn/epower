#!/usr/bin/env python3
"""m296_refresh_master_seasonal.py (M296, 2026-09-25) — regenerate the MASTER-class carried-forward
seasonalCharts entries on the live corpus.

M293 carried 46 seasonalCharts entries forward at the 410-drive basis. Nine of them are pure functions
of drive_master.csv (pipelineClass == "master"), produced by the same builder functions that already
emit the fresh 446-drive TOP-LEVEL blocks. This script re-runs those exact functions per thermal cohort:

    data[c] = f(drive_master rows whose seasonal_drive_master.thermal_regime == c),  data.all = f(all rows)

  EfficiencyBands, CycleByType, RegenByType, RegenByTypeMeta, DriveTypeChart, DriveDurationDist,
  EvTraction  <- compute_summary_arrays.category_A
  EnergyPath  <- compute_summary_arrays._energy_path
  SocLevelSensitivityChart <- compute_summary_arrays._soc_level_sensitivity(dm, cfg["socLevelWeighting"])

Parity guard: f(all rows) must equal the fresh top-level block byte-for-byte, otherwise the script
aborts (proves the per-cohort call path is the released estimator, not a re-implementation).
Cold stays null (no observations). Stable class keys / not-observed strata are re-applied (M295).
The 37 RAW-class entries remain carried forward and disclosed (they need the per-second raw sweep).
drive_master.csv is read-only; corpus hash unchanged.
"""
import copy, json, os, sys, subprocess
import pandas as pd

W = os.path.dirname(os.path.abspath(__file__)); P = lambda n: os.path.join(W, n)
sys.path.insert(0, W)
import compute_summary_arrays as C

A = json.load(open(P("summary_arrays.json"), encoding="utf-8"))
cfg = json.load(open(P("summary_config.json"), encoding="utf-8"))
dm = pd.read_csv(P("drive_master.csv"), low_memory=False)
reg = pd.read_csv(P("seasonal_drive_master.csv"), low_memory=False)[["file", "thermal_regime"]]
dm_r = dm.merge(reg, on="file", how="left")
assert len(dm_r) == len(dm) and dm_r.thermal_regime.notna().all(), "cohort label join incomplete"

CAT_A = {"EfficiencyBands": "efficiencyBands", "CycleByType": "cycleByType", "RegenByType": "regenByType",
         "RegenByTypeMeta": "regenByTypeMeta", "DriveTypeChart": "driveTypes",
         "DriveDurationDist": "driveDurationDist", "EvTraction": "evTraction"}
odo = A.get("meta", {}).get("odometerKm")


def produce(sub):
    sub = sub.drop(columns=["thermal_regime"]).reset_index(drop=True)
    ca = C.category_A(sub, odometer_km=odo)
    out = {cid: ca.get(key) for cid, key in CAT_A.items()}
    out["EnergyPath"] = C._energy_path(sub)
    out["SocLevelSensitivityChart"] = C._soc_level_sensitivity(sub, (cfg or {}).get("socLevelWeighting"))
    return out


full = produce(dm_r)
# parity guard vs the fresh top-level blocks
TOP = dict(CAT_A, EnergyPath="energyPath", SocLevelSensitivityChart="dodSocLevelSensitivity")
bad = [cid for cid, key in TOP.items() if json.dumps(full[cid], sort_keys=True) != json.dumps(A.get(key), sort_keys=True)]
if bad:
    print("PARITY FAILURE (per-cohort call path != released top-level):", bad); sys.exit(1)

per = {c: produce(dm_r[dm_r.thermal_regime == c]) for c in ("warm", "shoulder")}
ch = A["seasonalCharts"]["charts"]
for cid in TOP:
    d = ch[cid].setdefault("data", {})
    d["all"] = copy.deepcopy(full[cid])
    d["warm"] = copy.deepcopy(per["warm"][cid])
    d["shoulder"] = copy.deepcopy(per["shoulder"][cid])
    d["cold"] = None
    ch[cid]["basisNDrives"] = int(len(dm)); ch[cid]["refreshedBy"] = "M296 (m296_refresh_master_seasonal.py)"

st = A["seasonalCharts"]["_staleness"]
st["stillStale"] = [k for k in st.get("stillStale", []) if k not in TOP]
st["refreshedMasterCharts"] = {
    "keys": sorted(TOP), "milestone": "M296", "basisNDrives": int(len(dm)),
    "method": "same builder functions as the fresh top-level blocks, called per thermal cohort; parity-guarded "
              "(f(all) == top-level byte-for-byte)."}
st["reason"] = (f"M296: the 9 master-class charts are regenerated on the live {len(dm)}-drive corpus. The remaining "
                f"{len(st['stillStale'])} RAW-class seasonal entries are carried forward at the 410-drive basis; they need the "
                "per-second raw sweep over all canonical CSVs (standing follow-up). The corresponding TOP-LEVEL blocks that "
                "drive the main dashboard sections are fresh at the live basis. " + st.get("reason", "").split(" The remaining")[0][:0])
json.dump(A, open(P("summary_arrays.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("refreshed:", sorted(TOP)); print("still carried forward (raw):", len(st["stillStale"]))
# re-apply M295 stable class keys / not-observed strata and dependent payload fixes
subprocess.run([sys.executable, P("m295_payload.py")], check=True)
