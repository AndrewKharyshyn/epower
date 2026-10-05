#!/usr/bin/env python3
"""Logger PID-cadence regime per drive (M379a, analyses/M379_spec.md Rev 2 P1). Descriptive covariate, derived deterministically from the master column
`I_sample_period_s` (median update interval of the HV-current PID): regime "fast" if the period is below THRESHOLD_S (1.05 s, the midpoint of the empty gap in the
bimodal distribution), "slow" if at or above it, null when the period is missing. STOP (exit 1) when any drive lies inside the declared gap [1.0, 1.1) s.
Writes the sidecar cadence_regime.csv (file, date, time_start, I_sample_period_s, regime) and the additive payload block summary_arrays.json['loggerCadence']
(rule, counts, runs in time order, days with both regimes, the statement that the effect on the pipeline keys is not yet quantified). The master is not touched.
Usage: python tools/cadence_regime.py [--dry-run]"""
import argparse, copy, datetime, hashlib, json, os, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
THRESHOLD_S, GAP = 1.05, (1.0, 1.1)


def classify(period):
    """Pure: regime of one drive from its median I-PID update interval (seconds)."""
    if period is None or period != period:
        return None
    if GAP[0] <= period < GAP[1]:
        raise SystemExit("STOP: a drive lies inside the declared empty gap [%.1f, %.1f) s (period %.3f): the bimodal assumption no longer holds (Director)" % (GAP[0], GAP[1], period))
    return "fast" if period < THRESHOLD_S else "slow"


def build(dm):
    """Pure: (per-drive frame, payload block) from a master frame with file, date, time_start, I_sample_period_s."""
    d = dm[["file", "date", "time_start", "I_sample_period_s"]].copy()
    d["regime"] = [classify(p) for p in d["I_sample_period_s"]]
    d["t"] = pd.to_datetime(d["date"].astype(str) + " " + d["time_start"].astype(str), errors="coerce")
    d = d.sort_values(["t", "file"]).reset_index(drop=True)
    runs, cur = [], None
    for r in d.itertuples():
        if pd.isna(r.regime):
            continue
        day = str(r.date)[:10]
        if cur and cur["regime"] == r.regime:
            cur["nDrives"] += 1; cur["end"] = str(r.t)[:16]; cur["_days"].add(day)
        else:
            if cur:
                runs.append(cur)
            cur = {"regime": r.regime, "nDrives": 1, "start": str(r.t)[:16], "end": str(r.t)[:16], "_days": {day}}
    if cur:
        runs.append(cur)
    for x in runs:
        x["nDays"] = len(x.pop("_days"))
    by_day = d.dropna(subset=["regime"]).groupby(d["date"].astype(str).str[:10])["regime"].nunique()
    counts = d["regime"].value_counts(dropna=False)
    n_null = int(d["regime"].isna().sum())
    blk = {"rule": "regime = fast if I_sample_period_s < %.2f s, slow if >= %.2f s, null if missing; I_sample_period_s = median update interval of the HV-current PID per drive (master column); the distribution is bimodal with an empty gap [%.1f, %.1f) s that is asserted at every run" % (THRESHOLD_S, THRESHOLD_S, GAP[0], GAP[1]),
           "thresholdS": THRESHOLD_S, "gapS": list(GAP), "nDrives": int(len(d)),
           "counts": {"fast": int(counts.get("fast", 0)), "slow": int(counts.get("slow", 0)), "null": n_null},
           "nDaysByRegime": {g: int(d[d["regime"] == g]["date"].astype(str).str[:10].nunique()) for g in ("fast", "slow")},
           "runs": runs, "daysWithBothRegimes": sorted(by_day[by_day > 1].index.tolist()),
           "effectOnKeys": "not yet quantified (emulated sampling-sensitivity study pending, M379b); observational comparisons across regimes are confounded by season, ambient and drive mix",
           "source": "drive_master.csv I_sample_period_s; sidecar cadence_regime.csv"}
    return d.drop(columns="t"), blk


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args()
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    d, blk = build(dm)
    blk["masterMd5"] = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    new = copy.deepcopy(A)
    new["loggerCadence"] = blk
    old_st = (A.get("_artifactStamps") or {}).get("loggerCadence")
    if A.get("loggerCadence") == blk and old_st and old_st.get("corpusHash") == blk["masterMd5"]:
        new["_artifactStamps"]["loggerCadence"] = old_st                    # idempotent: an unchanged block keeps its stamp (generatedAt)
    else:                                                                    # every top-level key must carry an artifact stamp (build_html gate, M235)
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=blk["masterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
                  computationStatusNote="M379a: derived by tools/cadence_regime.py from the master column I_sample_period_s; descriptive covariate, additive, no published value recomputed; not M299-reproducible.",
                  upstreamHashes={"driveMasterMd5": blk["masterMd5"]})
        st.pop("carriedForward", None)
        new["_artifactStamps"]["loggerCadence"] = st
    chk = copy.deepcopy(new); chk.pop("loggerCadence"); chk["_artifactStamps"].pop("loggerCadence")
    base = copy.deepcopy(A); base.pop("loggerCadence", None); base["_artifactStamps"].pop("loggerCadence", None)
    assert chk == base, "only the loggerCadence key and its stamp may change"
    if a.dry_run:
        print(json.dumps({k: blk[k] for k in ("counts", "nDaysByRegime", "daysWithBothRegimes")}), "runs:", len(blk["runs"]))
        return
    d.to_csv("cadence_regime.csv", index=False, lineterminator="\n")
    if new != A:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1))
    print(json.dumps({k: blk[k] for k in ("counts", "nDaysByRegime", "daysWithBothRegimes")}), "runs:", len(blk["runs"]))


if __name__ == "__main__":
    main()
