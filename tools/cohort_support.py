#!/usr/bin/env python3
"""M472 (spec analyses/M472_spec.md, external audit 2026-10-21 'Seasonal logic'): the additive payload block `cohortSupport`: descriptive support accounting per thermal cohort (drives, days, km, largest-drive / largest-day
share, effective drives and days, display flags), two km-weighted metrics with a leave-one-day-out range, and the boundary sensitivity (assigned class after the M426 reassignment vs the physical threshold class).
Nothing is typed: every number comes from drive_master.csv, seasonal_drive_master.csv and fuel_recon_master.csv. No interval is attached (nothing here estimates a population quantity).
Usage: python tools/cohort_support.py [--dry-run]   (writes ONLY /cohortSupport and /_artifactStamps/cohortSupport of summary_arrays.json)"""
import copy, datetime, hashlib, json, os, sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
import eligibility as EL

METHOD_VERSION = 1
DOMINATED_SHARE = 0.5          # display convention, not an identified limit
FEW_EFFECTIVE_DAYS = 5.0       # display convention, not an identified limit
ALLOWED = ["/cohortSupport", "/_artifactStamps/cohortSupport"]
DP = 4


def _r(x, dp=DP):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), dp)


def effective_n(weights):
    """1 / sum(s_i^2) with s the shares of `weights` (the inverse Herfindahl index): the number of equally weighted units that would give the same concentration."""
    w = np.asarray(weights, dtype=float)
    t = w.sum()
    if not t > 0:
        return None
    s = w / t
    return float(1.0 / (s ** 2).sum())


def support(df):
    """Support fields of a frame with file, date, distance_km, duration_s."""
    if len(df) == 0:
        return {"nDrives": 0, "nDays": 0, "km": 0.0, "hours": 0.0, "largestDrive": None, "largestDay": None, "effectiveDrives": None, "effectiveDays": None, "flags": {"dominatedByOneDrive": False, "fewEffectiveDays": True}}
    km = float(df["distance_km"].sum())
    big = df.loc[df["distance_km"].idxmax()]
    by_day = df.groupby("date")["distance_km"].sum()
    day = by_day.idxmax()
    eff_d, eff_days = effective_n(df["distance_km"]), effective_n(by_day)
    share_drive = float(big["distance_km"]) / km if km > 0 else None
    return {"nDrives": int(len(df)), "nDays": int(by_day.shape[0]), "km": _r(km, 1), "hours": _r(float(df["duration_s"].sum()) / 3600.0, 2),
            "largestDrive": {"file": str(big["file"]), "km": _r(float(big["distance_km"]), 1), "share": _r(share_drive)},
            "largestDay": {"date": str(day), "km": _r(float(by_day.max()), 1), "share": _r(float(by_day.max()) / km if km > 0 else None)},
            "effectiveDrives": _r(eff_d, 2), "effectiveDays": _r(eff_days, 2),
            "flags": {"dominatedByOneDrive": bool(share_drive is not None and share_drive >= DOMINATED_SHARE), "fewEffectiveDays": bool(eff_days is None or eff_days < FEW_EFFECTIVE_DAYS)}}


def ratio_metric(df, num, den="distance_km", scale=1.0):
    """sum(num) / sum(den) x scale over rows with both non-null (complete case)."""
    d = df[df[num].notna() & df[den].notna()]
    if len(d) == 0 or not d[den].sum() > 0:
        return None, d
    return float(d[num].sum() / d[den].sum() * scale), d


def wmean_metric(df, col):
    """distance-weighted mean of a per-100-km column over rows with a value and a distance."""
    d = df[df[col].notna() & df["distance_km"].notna()]
    if len(d) == 0 or not d["distance_km"].sum() > 0:
        return None, d
    return float((d[col] * d["distance_km"]).sum() / d["distance_km"].sum()), d


METRICS = {
    "grossKwhPer100km": ("canonical-clean drives with a gross energy integral: sum(gross_throughput_kwh) / sum(distance_km) x 100", lambda d: ratio_metric(d, "gross_throughput_kwh", scale=100.0), "master"),
    "fuelLPer100km": ("canonical-clean fuel-instrumented drives (logged, app-calculated fuel rate): distance-weighted mean of fuel_L_per_100km", lambda d: wmean_metric(d, "fuel_L_per_100km"), "fuel"),
}


def metric_block(frame, fn, largest_file):
    val, used = fn(frame)
    if val is None:
        return {"value": None, "nDrives": 0, "nDays": 0, "km": 0.0, "lodo": None, "withoutLargestDrive": None}
    out = {"value": _r(val), "nDrives": int(len(used)), "nDays": int(used["date"].nunique()), "km": _r(float(used["distance_km"].sum()), 1)}
    days = sorted(used["date"].unique())
    lodo = []
    for d in days:
        v, _ = fn(used[used["date"] != d])
        if v is not None:
            lodo.append((str(d), v))
    if len(days) > 1 and lodo:
        lo = min(lodo, key=lambda x: x[1]); hi = max(lodo, key=lambda x: x[1])
        out["lodo"] = {"nDaysLeftOut": len(lodo), "min": _r(lo[1]), "minLeftOutDate": lo[0], "max": _r(hi[1]), "maxLeftOutDate": hi[0],
                       "relativeRange": _r((hi[1] - lo[1]) / val) if val else None}
    else:
        out["lodo"] = None          # one day only: nothing to leave out
    wl, _ = fn(used[used["file"] != largest_file]) if largest_file else (None, None)
    out["withoutLargestDrive"] = None if wl is None else {"value": _r(wl), "relativeChange": _r((wl - val) / val) if val else None}
    return out


def build(dm, sdm, fuel):
    flags = EL.load_flags(os.path.join(ROOT, "drive_master.csv"))
    # master-wide rule (cohort_arrays.py convention, M295): excluded when EITHER canonical flag is explicitly True; 12 early drives carry no flag (no energy integral either) and are not excluded.
    # The fuel rows below use the strict stop checks of eligibility.excluded_files (a missing flag on a fuel-instrumented drive is a STOP).
    ex_all = {r.file for r in flags.itertuples() if EL._true(r.ens_outlier_v2) or EL._true(r.ens_invalid)}
    m = dm[["file", "date", "distance_km", "duration_s", "gross_throughput_kwh"]].merge(
        sdm[["file", "thermal_regime_raw", "thermal_regime_physical", "ambient_time_mean_c", "thermal_regime_override"]], on="file", how="left")
    assert m["thermal_regime_raw"].notna().all(), "drives without a thermal class"
    m["date"] = m["date"].astype(str).str[:10]
    m["canon"] = ~m["file"].isin(ex_all)
    fz = fuel[["file", "fuel_L_per_100km"]]
    fz = fz[~fz["file"].isin(EL.excluded_files(flags, fz["file"]))]
    mf = m.merge(fz, on="file", how="inner")

    def cohort(col, label):
        sub = m[m[col] == label] if label != "all" else m
        subf = mf[mf[col] == label] if label != "all" else mf
        big = sub.loc[sub["distance_km"].idxmax(), "file"] if len(sub) else None
        met = {}
        for k, (desc, fn, src) in METRICS.items():
            frame = sub[sub["canon"]] if src == "master" else subf
            met[k] = metric_block(frame, fn, big if big in set(frame["file"]) else None)
        return {**support(sub), "metrics": met}

    assigned = {c: cohort("thermal_regime_raw", c) for c in ("all", "warm", "shoulder", "cold")}
    physical = {c: cohort("thermal_regime_physical", c) for c in ("warm", "shoulder", "cold")}
    moved = m[m["thermal_regime_raw"] != m["thermal_regime_physical"]]
    reassigned = [{"file": r.file, "date": r.date, "ambientTimeMeanC": _r(r.ambient_time_mean_c, 2), "km": _r(r.distance_km, 1), "assigned": r.thermal_regime_raw,
                   "physical": r.thermal_regime_physical, "override": r.thermal_regime_override} for r in moved.itertuples()]
    return {"_provenance": "GENERATED by tools/cohort_support.py (M472, spec analyses/M472_spec.md); do not hand-edit. Additive block, regenerated at every ingestion. Descriptive support accounting: no interval, nothing here estimates a population quantity.",
            "methodVersion": METHOD_VERSION,
            "definitions": {"cohortBasis": "assigned class = seasonal_drive_master.thermal_regime_raw (after the M426 owner reassignment, before the support gate); physical class = thermal_regime_physical (threshold class before any reassignment)",
                            "effective": "1 / sum(share^2) over the km shares of the drives (effectiveDrives) or days (effectiveDays): the weights of the distance-weighted metrics",
                            "flags": {"dominatedByOneDrive": "largest-drive km share >= %.2f" % DOMINATED_SHARE, "fewEffectiveDays": "effective days < %.0f" % FEW_EFFECTIVE_DAYS,
                                      "note": "display conventions, not identified limits"},
                            "metrics": {k: v[0] for k, v in METRICS.items()},
                            "lodo": "metric recomputed without each single day; min / max over the left-out days; relativeRange = (max - min) / value; withoutLargestDrive = metric without the cohort's largest drive"},
            "population": {"nMasterDrives": int(len(dm)), "nCanonicalExcluded": int(len(ex_all)), "nFuelRows": int(len(fuel))},
            "assigned": assigned, "physicalSensitivity": physical, "reassigned": reassigned,
            "reading": ["support accounting is descriptive: it shows how concentrated a cohort is, it is not an interval and does not make a cohort an inference about winter",
                        "the displayed cohorts use the assigned class; the physical-threshold class is a sensitivity beside it, never a replacement",
                        "ambient class describes context and exposure; it is not a pack-temperature measurement"]}


def splice(A, blk, master_md5, now=None):
    import dependence_sensitivity as DS
    new = copy.deepcopy(A)
    new["cohortSupport"] = blk
    old = (A.get("_artifactStamps") or {}).get("cohortSupport")
    if old and A.get("cohortSupport") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["cohortSupport"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["thermalSupportLedger"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M472: derived by tools/cohort_support.py from drive_master.csv, seasonal_drive_master.csv and fuel_recon_master.csv; additive cohort support block", upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        st["inputBasis"] = {"nDrives": A["meta"]["totalDrives"], "masterMd5": master_md5, "source": "stamping pass: meta.totalDrives, corpusHash"}      # the form tools/stamp_basis.derive gives a freshly computed block (fixed point)
        new["_artifactStamps"]["cohortSupport"] = st
    ch = DS._paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False)
    fuel = pd.read_csv("fuel_recon_master.csv", low_memory=False)
    blk = build(dm, sdm, fuel)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A = json.loads(raw)
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, changed, bad = splice(A, blk, md5)
    print(json.dumps({"nChanged": len(changed), "outsideAllowList": bad, "cold": {k: blk["assigned"]["cold"][k] for k in ("nDrives", "nDays", "km", "largestDrive", "effectiveDays", "flags")}}, indent=1))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
