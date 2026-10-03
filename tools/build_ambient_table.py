#!/usr/bin/env python3
"""Build summary_arrays.json -> ambientTable (M314): the per-drive ambient temperatures behind the Thermal tab section "Ambient Temperature per Drive".
Single source = summary_config.json `ambientByDrive` (driver-recorded vehicle readouts; canonical form [start, *interim, end]); drive identity, date,
start time and distance come from drive_master.csv. Nothing is typed here. Legacy entries (a bare number or a one-element list, see
tools/ambient_protocol.py) are shown as start = end and flagged `s: 1` (single recorded value).
Row keys (compact): f file id, d date YYYY-MM-DD, t start time HH:MM, n drive number within the day, k distance km, a [start, *interim, end], s 1 if single value,
c thermal class of the drive (seasonal master thermal_regime_raw: warm / shoulder / cold), m ambient mean that sets the thermal class (seasonal master ambient_time_mean_c: trapezoidal for >= 3 readings placed at equal intervals across the drive, the mean of the start and end readings for 2 readings, the single reading for 1 reading), mk its kind (t / e / s).
M352 adds provenanceByCohort, meanKindByCohort and definitions (script-written counts and definitions; no estimate).
M316 adds the start-of-drive temperatures next to the ambient values: p pack start, o oil start, w engine-coolant start (seasonal master / raw temperature triplets, deg C),
ow and cw = oil and coolant temperature 30, 60, 120, 300 and 600 s after the channel's first valid sample (warm-up; raw_temperature_triplets.csv), cs cold-soak status of the drive
(seasonal master cold_soak_status). Missing values are null.
Also stamps the block (clone of the cohortMeta stamp at the current corpus hash). Idempotent; run after ingest_core (needs the new drives in the master).
Usage: python tools/build_ambient_table.py"""
import copy, datetime, hashlib, json, os
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
cfg = json.load(open("summary_config.json", encoding="utf-8"))
amb = cfg["ambientByDrive"]
dm = pd.read_csv("drive_master.csv", low_memory=False)
dm = dm.sort_values(["date", "time_start"], kind="stable").reset_index(drop=True)
sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False).set_index("file")      # thermal cohort + ambient mean (and its kind) per drive
assert set(dm["file"]) <= set(sdm.index), "seasonal master does not cover every drive (run compute_seasonal first)"
trip = pd.read_csv("raw_temperature_triplets.csv", low_memory=False).set_index("file")
assert set(dm["file"]) <= set(trip.index), "raw_temperature_triplets.csv does not cover every drive (run tools/run_raw_temp_pass.py first)"
r1 = lambda v: None if pd.isna(v) else round(float(v), 1)
WU = (30, 60, 120, 300, 600)
missing = [f for f in dm["file"] if f not in amb]
assert not missing, f"drives without an ambientByDrive entry: {missing[:5]} (+{len(missing) - 5 if len(missing) > 5 else 0})"
rows, nlegacy = [], 0
MK = {"trapezoidal": "t", "interpolated_start_end": "e", "arithmetic_fallback": "s"}
assert set(sdm["ambient_time_mean_kind"].astype(str)) <= set(MK), set(sdm["ambient_time_mean_kind"].astype(str))
# arithmetic_fallback <=> one reading (the legacy single value): asserted, not assumed
assert ((sdm["ambient_time_mean_kind"] == "arithmetic_fallback") == (sdm["ambient_n_points"] == 1)).all()
day_n = {}
for _, r in dm.iterrows():
    v = amb[r["file"]]
    single = not (isinstance(v, list) and len(v) >= 2)
    vals = [float(x) for x in (v if isinstance(v, list) else [v])]
    if single:
        nlegacy += 1
        vals = [vals[0], vals[0]]
    day_n[r["date"]] = day_n.get(r["date"], 0) + 1
    row = {"f": r["file"], "d": str(r["date"]), "t": str(r["time_start"])[:5], "n": day_n[r["date"]],
           "k": None if pd.isna(r["distance_km"]) else round(float(r["distance_km"]), 1), "a": [int(x) if float(x).is_integer() else x for x in vals],
           "c": str(sdm.loc[r["file"], "thermal_regime_raw"]), "m": None if pd.isna(sdm.loc[r["file"], "ambient_time_mean_c"]) else round(float(sdm.loc[r["file"], "ambient_time_mean_c"]), 2),
           "p": r1(sdm.loc[r["file"], "pack_temp_start_c"]), "o": r1(sdm.loc[r["file"], "oil_temp_start_c"]), "w": r1(sdm.loc[r["file"], "engine_coolant_start_c"]),
           "ow": [r1(trip.loc[r["file"], f"oil_wu_{s}s"]) for s in WU], "cw": [r1(trip.loc[r["file"], f"cool_wu_{s}s"]) for s in WU],
           "cs": str(sdm.loc[r["file"], "cold_soak_status"]),
           "mk": MK[str(sdm.loc[r["file"], "ambient_time_mean_kind"])]}
    if single:
        row["s"] = 1
    rows.append(row)
flat = [x for r in rows for x in r["a"]]
def _cohort_frames():
    reg = sdm["thermal_regime_raw"].astype(str)
    return {"all": sdm, "warm": sdm[reg == "warm"], "shoulder": sdm[reg == "shoulder"], "cold": sdm[reg == "cold"]}
provenance_by_cohort, mean_kind_by_cohort = {}, {}
for _c, _f in _cohort_frames().items():
    _n = int(len(_f)); _rec = int((_f["ambient_source_primary"].astype(str) == "vehicle_sensor").sum())
    provenance_by_cohort[_c] = {"n": _n, "recorded": _rec, "substituted": _n - _rec,
                                "mixedSource": int(_f["ambient_source_mixed"].astype(str).str.lower().eq("true").sum()),
                                "uncertaintyClass": {k: int(v) for k, v in _f["ambient_uncertainty_class"].astype(str).value_counts().items()}}
    _k = _f["ambient_time_mean_kind"].astype(str).value_counts()
    mean_kind_by_cohort[_c] = {"trapezoidal": int(_k.get("trapezoidal", 0)), "endpointPair": int(_k.get("interpolated_start_end", 0)),
                               "singleValue": int(_k.get("arithmetic_fallback", 0))}
    assert sum(mean_kind_by_cohort[_c].values()) == _n
# auxLoadAmbient reads only list entries (bare-scalar legacy entries are dropped): count the drives with a standstill draw that it excludes
_aux = dm[dm["standstill_draw_kw"].notna()]
aux_excluded = int(sum(1 for f in _aux["file"] if not (isinstance(amb[f], list) and len(amb[f]) > 0)))
definitions = [
    {"use": "Thermal class (warm / shoulder / cold) and the cohort views", "definition": "the ambient mean m: trapezoidal over >= 3 readings placed at equal intervals across the drive (reading times are not recorded), the mean of the start and end readings for 2 readings, the single reading for 1 reading"},
    {"use": "Battery vs Driver-Recorded Ambient (batteryVsAmbient) and belowAmbient", "definition": "pack-mean temperature at the start minus the start reading; pack-mean peak minus the END reading; belowAmbient counts drives whose start delta is negative (start reading only)"},
    {"use": "HV aux/climate load vs ambient (auxLoadAmbient)", "definition": "the start reading only, list entries only; bare-number legacy entries are dropped (" + str(aux_excluded) + " drives with a standstill draw are excluded for that reason)"},
    {"use": "Scope", "definition": "this list covers the charts named above; batteryTempRanges, heatSoakCarryover, dailyFingerprints and linkedAdjacentDriveTable also read ambientByDrive and are not covered here"},
]
block = {"_provenance": ("GENERATED by tools/build_ambient_table.py from summary_config.json ambientByDrive (driver-recorded readings from the vehicle dashboard readout entered by hand; source label vehicle_sensor is the default label, no weather override is present; "
                         "uncertainty class vehicle_uncalibrated; the vehicle's ambient PID is too sparse to use) and drive_master.csv. Regenerate; do not hand-edit."),
         "format": "a = [start, ...interim, end] in chronological order; s = 1: single recorded value (legacy entry), shown as start = end; c = thermal class (raw); m = ambient mean that sets the thermal class: trapezoidal over >= 3 readings placed at equal intervals across the drive, the mean of the start and end readings for 2 readings, the single reading for 1 reading; mk = its kind (t trapezoidal, e start-end pair, s single reading), see meanKindByCohort",
         "cohortMinDrives": int(json.load(open("seasonal_config.json", encoding="utf-8"))["cohorts"].get("minDrivesForStatistics", 10)),
         "cohortCounts": {c: int((dm["file"].map(sdm["thermal_regime_raw"]) == c).sum()) for c in ("warm", "shoulder", "cold")},
         "warmupSeconds": list(WU), "nWithStartTemps": sum(1 for r in rows if r["p"] is not None and r["o"] is not None and r["w"] is not None),
         "coldSoakCounts": {k: int(v) for k, v in pd.Series([r["cs"] for r in rows]).value_counts().items()},
         "nDrives": len(rows), "nDays": len({r["d"] for r in rows}), "nInterimDrives": sum(1 for r in rows if len(r["a"]) > 2),
         "nSingleValueLegacy": nlegacy, "rangeC": [min(flat), max(flat)],
         "provenanceByCohort": provenance_by_cohort, "meanKindByCohort": mean_kind_by_cohort, "definitions": definitions, "rows": rows}
live = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
A = json.load(open("summary_arrays.json", encoding="utf-8"))
A["ambientTable"] = block
s = copy.deepcopy(A["_artifactStamps"]["cohortMeta"])
s.update(corpusHash=live, generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
         computationStatusNote="M314: per-drive ambient table (tools/build_ambient_table.py) from summary_config.json ambientByDrive and drive_master.csv.")
for k in ("carriedForward", "basisNDrives", "reissuedFrom", "reissueNote"):
    s.pop(k, None)
A["_artifactStamps"]["ambientTable"] = s
with open("summary_arrays.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(A, ensure_ascii=False, indent=1))
print(json.dumps({k: block[k] for k in ("nDrives", "nDays", "nInterimDrives", "nSingleValueLegacy", "rangeC")}))
