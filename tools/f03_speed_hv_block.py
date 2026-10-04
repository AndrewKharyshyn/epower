#!/usr/bin/env python3
"""M347: script-written block fuelStates.f03SpeedHvCheck from analyses/M347_f03_speed_hv_check.json (tools/f03_speed_hv_check.py). Used by tools/fuel_analytics2.py and by the
one-off leaf splice tools/m347_f03_splice.py. No number is typed here."""
import hashlib, json, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "analyses", "M347_f03_speed_hv_check.json")
NOTE_F03 = "not a paired test: date-confounded; before M366 the speed, SoC and engine-speed columns of the then re-exported raw/ files were cell-identical to the sha256-verified originals and their HV current and voltage were rounded (effect computed in the read-only comparison, f03SpeedHvCheck); raw/ now holds the originals"
NOTE_CHG = ("fuel consumed during net pack charging: a temporal state, not a fuel-source allocation; battery offset is estimated; all trips are now on the sha256-verified originals and the strata keep the former re-export split for sensitivity; the former re-export trips had "
            "rounded raw/ current before M366 (effect on pack energy computed in the read-only comparison, f03SpeedHvCheck)")


def build():
    r = json.load(open(SRC, encoding="utf-8"))
    c, d = r["columns"], r["derived"]
    return {"source": "analyses/M347_f03_speed_hv_check.json", "sourceSha256": hashlib.sha256(open(SRC, "rb").read()).hexdigest(),
            "scope": f"{r['nFilesCompared']} canonical files that were re-exported before M366: raw/ copy vs sha256-verified original, read-only comparison (owner-approved 2026-10-03) run before raw/ was overwritten (M366)",
            "nFilesCompared": r["nFilesCompared"], "filesWithoutUsableSpeed": r.get("filesWithoutUsableSpeed"),
            "cellIdentical": {k: {"nFiles": c[k]["nFiles"], "filesAllCellsEqual": c[k]["filesAllCellsEqual"], "maxAbsDiff": c[k]["maxAbsDiff"]} for k in ("speedVCM", "speedOBD", "soc", "rpm")},
            "rounded": {k: {"nFiles": c[k]["nFiles"], "filesAllCellsEqual": c[k]["filesAllCellsEqual"], "maxAbsDiff": c[k]["maxAbsDiff"]} for k in ("hvCurrent", "hvVoltage")},
            "derived": {k: {"n": d[k]["n"], "aggRelDiff": d[k]["aggRelDiff"], "maxAbsPerDriveDiff": d[k]["maxAbsPerDriveDiff"], "nDrivesDiffAbove1pct": d[k]["nDrivesDiffAbove1pct"], "unit": d[k]["unit"]}
                        for k in ("km", "stationaryShare", "dischargeKwh", "chargeKwh")}}
