"""M361 (spec analyses/M361_spec.md): script-written availability block for the HV battery intake-air temperature channel (T_intake), from the master only.
The raw -100 degC sentinel is a raw-file observation recorded in CHANGELOG M319 and is NOT recomputed here; the master NaNs it through the [-40, 90] bound in compute_drive_summary_v6.
status 'unavailable' = no valid value after lastValidDate in drive order (date, time_start); 'available' = the newest drive has a value. Counts only; cause is not stated."""
import pandas as pd


def intake_air_block(dm, sdm=None):
    ch = dm.sort_values(["date", "time_start"]).reset_index(drop=True)
    valid = ch.index[ch["T_intake"].notna()]
    nvalid = int(len(valid)); n = int(len(ch))
    blk = {"channel": "HV battery intake-air temperature (T_intake)", "nDrives": n, "nDrivesValid": nvalid, "nDrivesNoValue": n - nvalid,
           "source": "drive_master.csv T_intake (NaN = unavailable; the raw -100 degC sentinel is removed by the -40 bound, see CHANGELOG M319)"}
    if not nvalid:
        blk.update(status="unavailable", lastValidDate=None, lastValidDrive=None, nDrivesAfterLastValid=n, nDaysAfterLastValid=int(ch["date"].nunique()), firstDriveWithoutValue=str(ch.at[0, "file"]) if n else None)
        return blk
    lv = int(valid[-1]); after = ch.iloc[lv + 1:]
    blk.update(status="unavailable" if len(after) else "available", lastValidDate=str(ch.at[lv, "date"])[:10], lastValidDrive=str(ch.at[lv, "file"]),
               nDrivesAfterLastValid=int(len(after)), nDaysAfterLastValid=int(after["date"].nunique()),
               firstDriveWithoutValue=str(after.iloc[0]["file"]) if len(after) else None)
    if sdm is not None:
        blk.update(_cohort_counts(sdm, set(after["file"]) if len(after) else set()))
    return blk


def _cohort_counts(sdm, after_files):
    """per thermal cohort (thermal_regime_raw, the same classes as cohortMeta.observed): drives and drives with a valid intake-air value; and how many of the ten coldest drives by logged ambient (ambient_time_mean_c) come after the last valid drive in drive order (the outage began mid-day, so a date comparison would miss same-day drives)."""
    out = {}
    for k, g in sdm.groupby("thermal_regime_raw"):
        out[str(k)] = {"nDrives": int(len(g)), "nDrivesValid": int(g["batt_intake_time_mean_c"].notna().sum())}
    cold10 = sdm.nsmallest(10, "ambient_time_mean_c")
    return {"byCohort": out, "coldestTenByAmbient": {"n": int(len(cold10)), "nAfterLastValidDrive": int(cold10["file"].isin(after_files).sum())}}
