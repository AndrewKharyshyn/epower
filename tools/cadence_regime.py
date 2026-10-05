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


def summarize_sensitivity(study, dm, regime):
    """Pure: the compact payload summary of analyses/M379_cadence_sensitivity.json (M379b) with the derived corpus implication (descriptive, not a correction)."""
    em = study["emulation"]
    f2s, f2sl, s2sl = em["fast_to_slow"]["keys"], em["fast_to_slower"]["keys"], em["slow_to_slower"]["keys"]
    neutral = lambda s: 1.0 if "ratio" in s["statistic"] else 0.0
    cls = {"insensitive": [], "sensitive": [], "notEstablishedInsensitive": [], "reportedOnly": []}
    for k, s in f2s.items():
        c = s.get("class", "")
        if c.startswith("cadence-insensitive"):
            cls["insensitive"].append(k)
        elif c.startswith("cadence-sensitive"):
            (cls["notEstablishedInsensitive"] if s["ci95"][0] <= neutral(s) <= s["ci95"][1] else cls["sensitive"]).append(k)
        else:
            cls["reportedOnly"].append(k)
    g = lambda d, k: {"estimate": d[k]["estimate"], "ci95": d[k]["ci95"]}
    d = dm.copy()
    d["regime"] = regime
    ok = d["gross_throughput_kwh"].notna() & (d["distance_km"] > 0) & (d["ens_outlier_v2"].astype(str) != "True")
    share = float(d.loc[ok & (d["regime"] == "fast"), "gross_throughput_kwh"].sum() / d.loc[ok, "gross_throughput_kwh"].sum())
    shift = float(f2s["gross_throughput_kwh"]["estimate"] - 1.0)
    m = study["meta"]
    return {"basis": "emulated sampling sensitivity (M379b): fast-regime drives thinned per PID column to the slow-regime interval distribution (and to twice it), pipeline re-run on the emulated logs; not a causal cadence effect (PID-set / polling-order change, I-V co-timing, jitter and app-internal calculations are not emulated); fast -> slow direction only",
            "study": {"nDrives": m["nStudyDrives"], "nFastRegimeDrives": int((regime == "fast").sum()), "studySetNote": "the fast-regime drives with an energy block (gross_throughput_kwh present, distance_km > 0, not canonically flagged)", "nDays": m["nStudyDays"], "seeds": len(m["seeds"]), "controlSlowToSlowerDrives": m["nControlDrives"], "robustnessDrives": m["nRobustnessDrives"]},
            "grossThroughputRatio": {"fastToSlow": g(f2s, "gross_throughput_kwh"), "fastToSlower": g(f2sl, "gross_throughput_kwh"), "slowToSlowerControl": g(s2sl, "gross_throughput_kwh")},
            "sameDirectionKeys": {k: g(f2s, k) for k in ("gross_discharge_kwh", "gross_charge_kwh", "fce", "rf_efc")},
            "distanceRatio": g(f2s, "distance_km"),
            "classificationFastToSlow": cls,
            "classificationNote": "cadence-insensitive = 95% CI inside the pre-registered margin; cadence-sensitive = outside the margin and the CI excludes the neutral value; notEstablishedInsensitive = outside the margin but the CI includes the neutral value (not established as insensitive; the margin is narrower than the CI); reportedOnly = no pre-registered margin, peaks (negative controls) and counts",
            "negativeControls": {k: {"estimate": f2s[k]["estimate"], "movementDetected": f2s[k].get("movementDetected")} for k in ("peak_discharge_kw", "peak_I_charge")},
            "validation": {"identityKeepAllMaxAbsDiff": study["validation"]["identityKeepAll"]["maxAbsDiffAllKeys"], "intervalMeanRelDiff": study["validation"]["intervalMatch"]["relDiffMean"], "intervalMeanWithin5pct": study["validation"]["intervalMatch"]["withinFivePercent"],
                           "intervalMedianQuantized": True, "masterReproduction": study["validation"]["masterReproduction"], "ivGapFlagOutside25pct": study["validation"]["ivGap"]["flagOutsidePlusMinus25pct"], "ivGapRelDiff": study["validation"]["ivGap"]["relDiff"]},
            "headlineQuarterRule": study["headlineQuarterRule"], "robustnessClassFlips": list(study["robustnessClassFlips"]),
            "corpusImplication": {"fastRegimeShareOfGrossThroughput": share, "impliedCorpusGrossThroughputShiftIfAllSlow": share * shift,
                                  "note": "descriptive arithmetic on the emulation, not a correction of any published figure"},
            "limits": m["limits"], "source": "analyses/M379_cadence_sensitivity.json"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args()
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    d, blk = build(dm)
    blk["masterMd5"] = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    sp = os.path.join(ROOT, "analyses", "M379_cadence_sensitivity.json")
    if os.path.exists(sp):                         # M379b: the frozen study (one-time; labelled with its basis) is carried in the block
        study = json.load(open(sp, encoding="utf-8"))
        dmi = dm.copy(); rg = d.set_index("file").reindex(dm["file"])["regime"].values
        blk["sensitivity"] = summarize_sensitivity(study, dmi, rg)
        blk["sensitivity"]["basisMasterMd5"] = study["meta"]["masterMd5"]
        blk["sensitivity"]["basisNDrives"] = int(len(dm))
        blk["sensitivity"]["specSha256Frozen"] = study["meta"]["specSha256Frozen"]
        blk["effectOnKeys"] = "quantified for the pipeline keys listed under sensitivity by an emulated sampling-sensitivity study (M379b), which is not a causal cadence effect; observational comparisons across regimes are confounded by season, ambient and drive mix"
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
