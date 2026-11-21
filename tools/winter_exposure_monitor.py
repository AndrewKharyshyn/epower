#!/usr/bin/env python3
"""M726 (analyses/M726_spec.md Rev 2, pre-registered), guard G3: report-only exposure and support monitor for the M717 winter freeze.
Writes ONE record per master MD5 into analyses/M717_winter_exposure_log.json (a record for the same master MD5 is replaced, so a re-run is idempotent). It counts exposure and support ONLY, never a prediction metric (no early peeking),
never changes a payload number and never stops an ingestion. Reads analyses/M713/exposure_drives.csv (per-drive probe temperatures, hours below 0 / 5 / 10 C, start time), seasonal_drive_master.csv (ambient) and drive_master.csv (MD5, file list).
Events (spec section 2): E1 first sub-zero reading (a drive with >= 10 samples of the 2 s pack-probe grid, i.e. >= 20 s, below 0 C and a finite probe resolution); E2 flag (a drive after F + 1 h with a probe minimum below 5 C); E3 live refit after F (every ingestion).
Scoring-set definitions (spec): F = 2026-11-17T19:01:29+02:00 (freeze commit), drive start times are logger clock (assumed Europe/Kyiv local time), a drive that starts within one hour of F is excluded, the scoring set = drives that start after F + 1 h,
the stratum 'post-basis, pre-freeze' = drives that start from 2026-11-10 until F - 1 h (reported beside, never primary), the frozen basis = drives through 2026-11-09 (never scored).
Usage: python tools/winter_exposure_monitor.py [--dry-run] [--check]"""
import datetime as dt, hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LOG = os.path.join(ROOT, "analyses", "M717_winter_exposure_log.json")
FRAME = os.path.join(ROOT, "analyses", "M713", "exposure_drives.csv")
SPEC = "analyses/M726_spec.md"
F = pd.Timestamp("2026-11-17 19:01:29")                    # freeze commit time, local clock
GUARD = pd.Timedelta(hours=1)
BASIS_LAST_DAY = "2026-11-09"
POST_BASIS_FIRST_DAY = "2026-11-10"
E1_MIN_SECONDS = 20.0                                      # >= 10 samples of the 2 s probe grid
SUPPORT_DRIVES, SUPPORT_DAYS = 10, 5                       # the freeze's own support rule
WINDOW_LO, WINDOW_HI = -5.0, 3.0                           # fixed probe window of P3, P4, P6 (spec section 2)
AMBIENT_MAX = 20.0                                         # P5, P7: ambient below 20 C


def sets(frame):
    """(basis, post_basis, scoring) boolean masks over the frame (start times, clock assumptions in the module docstring)."""
    st = pd.to_datetime(frame["start"])
    basis = frame["day"].astype(str) <= BASIS_LAST_DAY
    post_basis = (frame["day"].astype(str) >= POST_BASIS_FIRST_DAY) & (st < F - GUARD)
    scoring = st > F + GUARD
    return basis.values, post_basis.values, scoring.values


def _support(df):
    return {"nDrives": int(len(df)), "nDays": int(df["day"].nunique()), "meetsSupportRule": bool(len(df) >= SUPPORT_DRIVES and df["day"].nunique() >= SUPPORT_DAYS)}


def compute_record(frame, ambient, master_md5, n_master, probe_resolution_c):
    fr = frame.copy()
    fr["day"] = pd.to_datetime(fr["day"]).dt.strftime("%Y-%m-%d")
    fr["amb"] = fr["key"].astype(str).map(ambient) if ambient is not None else np.nan
    basis, post_basis, scoring = sets(fr)
    sub0_s = fr["h_lt0"].astype(float) * 3600.0
    e1_rows = fr[(sub0_s >= E1_MIN_SECONDS)]
    in_window = fr[(fr["Tlo_min"] >= WINDOW_LO) & (fr["Tlo_min"] <= WINDOW_HI)]
    cold5 = fr[fr["Tlo_min"] < 5.0]

    def hours(mask):
        d = fr[mask]
        return {"below0": round(float(d["h_lt0"].sum()), 4), "below5": round(float(d["h_lt5"].sum()), 4), "below10": round(float(d["h_lt10"].sum()), 4)}

    def coldest(mask):
        d = fr[mask & fr["Tlo_min"].notna().values]
        if not len(d):
            return None
        r = d.loc[d["Tlo_min"].idxmin()]
        return {"probeMinC": round(float(r["Tlo_min"]), 2), "day": str(r["day"])}

    amb_ok = fr["amb"].notna() & (fr["amb"] < AMBIENT_MAX)
    rec = {"masterMd5": master_md5, "nDrivesMaster": int(n_master), "nDrivesFrame": int(len(fr)), "spec": SPEC,
           "freezeTimestampLocal": str(F), "guardHours": 1, "clockAssumption": "logger clock = Europe/Kyiv local time",
           "frozenBasis": {"throughDay": BASIS_LAST_DAY, "nDrives": int(basis.sum()), "hours": hours(basis), "coldest": coldest(basis),
                           "tStartMinC": None if not fr.loc[basis, "T_start"].notna().any() else round(float(fr.loc[basis, "T_start"].min()), 2),
                           "ambientRangeC": None if not fr.loc[basis, "amb"].notna().any() else [round(float(fr.loc[basis, "amb"].min()), 2), round(float(fr.loc[basis, "amb"].max()), 2)]},
           "postBasisPreFreeze": {"nDrives": int(post_basis.sum()), "hours": hours(post_basis), "coldest": coldest(post_basis), "nProbeMinBelow5": int((post_basis & (fr["Tlo_min"] < 5.0).values).sum())},
           "scoringSet": {"nDrives": int(scoring.sum()), "nDaysFirst": None if not scoring.any() else str(fr.loc[scoring, "day"].min()), "hours": hours(scoring), "coldest": coldest(scoring),
                          "nProbeMinBelow5": int((scoring & (fr["Tlo_min"] < 5.0).values).sum()), "nProbeMinBelow0": int((scoring & (fr["Tlo_min"] < 0.0).values).sum())},
           "support": {"P3_P4_P6_probeWindow": _support(in_window[scoring[in_window.index]]) if len(in_window) else {"nDrives": 0, "nDays": 0, "meetsSupportRule": False},
                       "P5_P7_ambientBelow20": _support(fr[scoring & amb_ok.values]),
                       "P1_P2_restartPairs": None, "P1_P2_note": "restart pairs and the realised ambient are not counted by this monitor"},
           "events": {"E1_firstSubZero": bool(len(e1_rows) > 0 and probe_resolution_c is not None and np.isfinite(probe_resolution_c)), "E1_driveDays": sorted(set(map(str, e1_rows["day"]))) if len(e1_rows) else [],
                      "E1_singleSampleFlagOnly": bool(((fr["Tlo_min"] < 0.0) & (sub0_s < E1_MIN_SECONDS)).any()), "probeResolutionC": None if probe_resolution_c is None else float(probe_resolution_c),
                      "E2_postFreezeColdDrives": int((scoring & (fr["Tlo_min"] < 5.0).values).sum()), "E3_liveRefitAfterF": True},
           "reading": "exposure and support counts only; no prediction metric; model-derived frame; not evaluable is not no effect"}
    return json.loads(json.dumps(rec, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def load_inputs():
    frame = pd.read_csv(FRAME, low_memory=False, usecols=["key", "day", "start", "T_start", "Tlo_min", "h_lt0", "h_lt5", "h_lt10"])
    sd = pd.read_csv(os.path.join(ROOT, "seasonal_drive_master.csv"), low_memory=False, usecols=["file", "ambient_time_mean_c"])
    ambient = {"".join(ch for ch in str(f) if ch.isdigit()): v for f, v in zip(sd["file"], sd["ambient_time_mean_c"]) if pd.notna(v)}
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    n = int(len(pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file"])))
    res = None
    try:
        A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
        res = A["seasonalLife"]["hotTail"]["packThermalMeasured"]["sampleOccupancy"].get("probeResolutionC")
    except (KeyError, FileNotFoundError, ValueError):
        res = None
    return frame, ambient, md5, n, res


def merge_log(log, rec):
    recs = [r for r in (log or {}).get("records", []) if r.get("masterMd5") != rec["masterMd5"]]
    recs.append(rec)
    return {"milestone": "M726", "spec": SPEC, "note": "report-only exposure and support log of the M717 winter freeze (one record per master MD5); counts only, no prediction metric", "records": recs}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    frame, ambient, md5, n, res = load_inputs()
    rec = compute_record(frame, ambient, md5, n, res)
    log = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else None
    new = merge_log(log, rec)
    if "--check" in argv:
        have = next((r for r in (log or {}).get("records", []) if r.get("masterMd5") == md5), None)
        ok = have == rec
        print(json.dumps({"check": "winterExposureLog", "matches": ok}))
        return 0 if ok else 1
    print(json.dumps({"masterMd5": md5, "scoringSet": rec["scoringSet"]["nDrives"], "E1": rec["events"]["E1_firstSubZero"], "E2": rec["events"]["E2_postFreezeColdDrives"],
                      "coldestEver": rec["frozenBasis"]["coldest"]}))
    if "--dry-run" not in argv:
        with open(LOG, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
