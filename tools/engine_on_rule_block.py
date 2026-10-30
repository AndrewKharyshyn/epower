#!/usr/bin/env python3
"""M540 (analyses/M540_spec.md Rev 2): wave 2a of the engine-on migration: the additive top-level payload block engineOnRule (+ stamp). Engine-on under the project rule (tools/engine_on_rule.py: logged rpm > 400, strict) and the closed
low-rpm rotation band [300, 400], next to the stored >= 300 basis, pooled and by drive type, with day-clustered intervals. rpmDistribution is not touched (M541 displays this block).

Per-drive sidecar engine_on_rule_sidecar.csv (tracked; keyed by the raw-file SHA-256 AND by engine_on_rule_sidecar.meta.json: source hash of the row function + the rule constants + RPM_HIST_EDGES; a mismatch rebuilds all): the
valid 1 Hz grid seconds of rpm_opt_band.grid_rpm (byte-faithful to _RawAccum.add), seconds >= 300, > 400, exactly 400, > 6000 and the 13 integer RPM_HIST bin counts. Gates (STOP, nothing written): round(sum/3600, 3) of the 13 bins equals the stored
rpmDistribution.pooledHours and every byClass hours vector EXACTLY; per drive ge300 == sum(bins[1:]) + n(rpm > 6000). Usage: python tools/engine_on_rule_block.py [--dry-run] [--check] [--rebuild]"""
import copy, datetime, hashlib, inspect, io, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import engine_on_rule as ER
import rpm_opt_band as OB

KEY = "engineOnRule"
SIDECAR = os.path.join(ROOT, "engine_on_rule_sidecar.csv")
META = os.path.join(ROOT, "engine_on_rule_sidecar.meta.json")
SPEC = "analyses/M540_spec.md"
NB, SEED = 4000, 42
CLASSES = ("urban", "mixed", "mixed_highway", "highway")


def grid_rpm_last(df, cs):
    """M542 aggregator sensitivity: the same 1 Hz grid as rpm_opt_band.grid_rpm (native ffill 15 rows before, grid ffill 15 s after, negatives dropped) with the LAST value of the (natively forward-filled) series in each clock-aligned 1 s bin instead of the mean."""
    df = df.rename(columns={k: v for k, v in cs.RAW_MAP.items() if k in df.columns})
    if "time" not in df or "eng_rpm" not in df:
        return None
    t = cs._ft(df["time"], mixed=True)
    rpm = pd.to_numeric(df["eng_rpm"], errors="coerce").ffill(limit=15)
    rpm = rpm.where(rpm >= 0)
    g1 = pd.DataFrame({"t": t, "eng_rpm": rpm.values}).dropna(subset=["t"]).set_index("t")
    hz = g1.resample("1s").last().ffill(limit=15)
    return hz["eng_rpm"].dropna().values


def row_counts(csv_bytes, cs):
    """one drive -> dict of integer counts, or None when the drive has no usable rpm series"""
    g = OB.grid_rpm(pd.read_csv(io.BytesIO(csv_bytes), low_memory=False), cs)
    if g is None or not len(g[0]):
        return None
    rr = g[0]
    h, _ = np.histogram(rr, bins=cs.RPM_HIST_EDGES)
    out = {"n_valid": int(len(rr)), "ge300": int((rr >= ER.BAND_LO_RPM).sum()), "gt400": int(ER.engine_on(rr).sum()), "eq400": int((rr == ER.THRESHOLD_RPM).sum()), "gt6000": int((rr > cs.RPM_HIST_EDGES[-1]).sum())}
    out.update({"h%d" % k: int(v) for k, v in enumerate(h)})
    rl = grid_rpm_last(pd.read_csv(io.BytesIO(csv_bytes), low_memory=False), cs)
    rl = rl if rl is not None else np.array([])
    out.update({"n_valid_last": int(len(rl)), "ge300_last": int((rl >= ER.BAND_LO_RPM).sum()), "gt400_last": int(ER.engine_on(rl).sum())})
    return out


def _src_hash():
    import compute_summary_arrays as cs
    return hashlib.sha256((inspect.getsource(row_counts) + inspect.getsource(grid_rpm_last) + repr((ER.THRESHOLD_RPM, ER.BOUNDARY, ER.BAND_LO_RPM, list(cs.RPM_HIST_EDGES)))).encode()).hexdigest()


def build_sidecar(dm, rebuild=False):
    import compute_summary_arrays as cs
    import ah_throughput as AH
    load = AH.raw_loader(); src = _src_hash()
    meta = json.load(open(META, encoding="utf-8")) if os.path.exists(META) else {}
    old = {}
    if not rebuild and os.path.exists(SIDECAR) and meta.get("rowFnSha256") == src:
        old = pd.read_csv(SIDECAR, dtype={"sha256": str}).set_index("file").to_dict("index")
    prev_sc = pd.read_csv(SIDECAR) if os.path.exists(SIDECAR) else None
    rows, rep = [], 0
    for f, d in zip(dm["file"], dm["date"]):
        raw = load(f)
        if raw is None:
            continue
        sha = hashlib.sha256(raw).hexdigest(); prev = old.get(f)
        if prev and prev["sha256"] == sha and str(prev["date"]) == str(d):
            rows.append({"file": f, **prev}); continue
        r = row_counts(raw, cs)
        if r is None:
            continue
        rows.append({"file": f, "sha256": sha, "date": d, **r}); rep += 1
    sc = pd.DataFrame(rows)
    g3 = meta.get("g3MeanColumnsIdenticalToPrevious")
    if prev_sc is not None and "gt400_last" not in prev_sc.columns:        # M542 G3: the mean-aggregator columns are byte-identical to the previous (M540) sidecar
        common = [c for c in prev_sc.columns if c in sc.columns]
        a = prev_sc.sort_values("file").reset_index(drop=True)[common]; b = sc.sort_values("file").reset_index(drop=True)[common]
        g3 = bool(len(a) == len(b) and a.equals(b))
    sc.to_csv(SIDECAR, index=False, lineterminator="\n")
    json.dump({"rowFnSha256": src, "rule": {"thresholdRpm": ER.THRESHOLD_RPM, "boundary": ER.BOUNDARY, "bandLoRpm": ER.BAND_LO_RPM}, "g3MeanColumnsIdenticalToPrevious": g3, "note": "raw/ = sha256-verified originals (M366)"}, open(META, "w", encoding="utf-8", newline=chr(10)), indent=1)
    return sc, rep


def _hrs(x):
    return round(float(x) / 3600.0, 4)


def part(sc, days_col="date"):
    """hours, shares and day-clustered intervals of one subset of the sidecar"""
    n = sc["n_valid"].values.astype(float); ge = sc["ge300"].values.astype(float); gt = sc["gt400"].values.astype(float)
    band = ge - gt
    days = sc[days_col].astype(str).values
    pt, ci, nd, _ = OB.ratio_ci(gt, n, days)
    bp, bci, _, _ = OB.ratio_ci(band, ge, days)
    return {"nDrives": int(len(sc)), "nDays": int(nd), "validSeconds": int(n.sum()), "validHours": _hrs(n.sum()), "ge300Seconds": int(ge.sum()), "ge300Hours": _hrs(ge.sum()), "engineOnSeconds": int(gt.sum()),
            "engineOnHours": _hrs(gt.sum()), "lowRpmBandSeconds": int(band.sum()), "lowRpmBandHours": _hrs(band.sum()), "exact400Seconds": int(sc["eq400"].sum()),
            "engineOnPctOfValid": {"pct": round(100 * pt, 4), "ci95Pct": [round(100 * ci[0], 4), round(100 * ci[1], 4)]}, "lowRpmBandPctOfGe300": {"pct": round(100 * bp, 4), "ci95Pct": [round(100 * bci[0], 4), round(100 * bci[1], 4)]}}


def sens_rel(sc):
    a, b = float(sc["gt400"].sum()), float(sc["gt400_last"].sum())
    return 100 * (b - a) / a


def cohort_blocks(sc, dm, A, rg):
    """M542 (analyses/M542_spec.md Rev 2): byCohort (thermal_regime of seasonal_drive_master.csv, every label present) and aggregatorSensitivity (mean = record, last = sensitivity), with gates G1-G3."""
    import compute_summary_arrays as cs
    sdm = pd.read_csv(os.path.join(ROOT, "seasonal_drive_master.csv"), low_memory=False, usecols=["file", "thermal_regime"]).set_index("file")["thermal_regime"]
    lab = sc["file"].map(sdm).fillna("unclassified").values
    labels = sorted(set(lab))
    pooled = part(sc)
    sub = {k: sc[lab == k] for k in labels}
    byc = {k: part(v) for k, v in sub.items()}
    for k, v in byc.items():
        v["exploratory"] = bool(v["nDays"] < 10)
        v["note"] = ("few distinct calendar days (%d): a percentile interval over days has no reliable coverage; exploratory, no claim" % v["nDays"]) if v["exploratory"] else "day-clustered percentile bootstrap within the cohort"
    g1 = bool(sum(v["nDrives"] for v in byc.values()) == len(sc) and all(sum(v[f] for v in byc.values()) == pooled[f] for f in ("validSeconds", "ge300Seconds", "engineOnSeconds", "lowRpmBandSeconds")))
    hcols = ["h%d" % k for k in range(len(cs.RPM_HIST_EDGES) - 1)]
    sd = (A.get("seasonalCharts") or {}).get("charts", {}).get("RpmDistribution", {}).get("data", {})
    g2 = {}
    for k, v in sub.items():
        H = v[hcols].values.astype(np.int64)
        ident = bool((v["ge300"].values == H[:, 1:].sum(1) + v["gt6000"].values).all())
        st = sd.get(k)
        hrs_ok = None if not st else ([round(float(x) / 3600, 3) for x in H.sum(0)] == st["pooledHours"])
        g2[k] = {"binsEqualStoredCohortHistogram": hrs_ok, "perDriveIdentityGe300": ident}
    counts = ((A.get("seasonalCharts") or {}).get("_meta") or {}).get("cohortCounts") or {}
    counts_ok = all(int(counts.get(k, -1)) == len(v) for k, v in sub.items() if k in counts)
    meta = json.load(open(META, encoding="utf-8")) if os.path.exists(META) else {}
    g3 = meta.get("g3MeanColumnsIdenticalToPrevious")
    n_ok = bool((sc["n_valid_last"].values == sc["n_valid"].values).all())
    gates = {"G1CohortPartition": g1, "G2": g2, "G2StoredCohortCountsEqual": bool(counts_ok), "G3MeanColumnsIdenticalToM540Sidecar": g3, "nValidLastEqualsNValid": n_ok}
    gates["passed"] = bool(g1 and counts_ok and n_ok and g3 is not False and all(x["perDriveIdentityGe300"] and x["binsEqualStoredCohortHistogram"] is not False for x in g2.values()))
    out = {"byCohort": byc, "cohortSource": "thermal_regime of seasonal_drive_master.csv (every label present; the M426 overrides and the M310 _insufficient relabel are already applied)",
           "cohortBootstrap": "each cohort is bootstrapped separately on its own calendar days; a calendar day can occur in two cohorts; no cohort contrast is computed", "cohortGates": gates}

    def agg(sub_sc):
        ge, gt = sub_sc["ge300"].values.astype(float), sub_sc["gt400"].values.astype(float)
        gel, gtl = sub_sc["ge300_last"].values.astype(float), sub_sc["gt400_last"].values.astype(float)
        band, bandl = ge - gt, gel - gtl
        rel = lambda a, b: round(100 * (b - a) / a, 4) if a else None
        return {"engineOnHoursMean": _hrs(gt.sum()), "engineOnHoursLast": _hrs(gtl.sum()), "engineOnRelDiffPct": rel(gt.sum(), gtl.sum()),
                "bandHoursMean": _hrs(band.sum()), "bandHoursLast": _hrs(bandl.sum()), "bandRelDiffPct": rel(band.sum(), bandl.sum()),
                "driveLevelBandSecondsDiff": {"p5": float(np.percentile(bandl - band, 5)), "median": float(np.median(bandl - band)), "p95": float(np.percentile(bandl - band, 95)), "nDrivesDiffering": int((bandl != band).sum())}}
    sens = {"pooled": agg(sc), "byCohort": {k: agg(v) for k, v in sub.items()}, "byCadenceStratum": {g: agg(sc[rg == g]) for g in ("fast", "slow", "unlabelled") if (rg == g).any()},
            "definition": "last = last value of the natively forward-filled (15 rows) series in each clock-aligned 1 s bin, then grid forward fill 15 s, negatives dropped; mean = the pipeline convention (the record). The hold limits (15 rows / 15 s) are untested (wave 2c)."}
    sens["tripwires"] = {"pooledEngineOnOver1Pct": bool(abs(sens_rel(sc)) >= 1.0),
                         "bandOver25PctPooledOrWarmShoulder": bool(any((x["bandRelDiffPct"] is not None and abs(x["bandRelDiffPct"]) > 25) for x in [sens["pooled"]] + [v for k, v in sens["byCohort"].items() if k in ("warm", "shoulder")]))}
    out["aggregatorSensitivity"] = sens
    return out


def compute(sc, dm, A):
    import compute_summary_arrays as cs
    out = {}
    hcols = ["h%d" % k for k in range(len(cs.RPM_HIST_EDGES) - 1)]
    H = sc[hcols].values.astype(np.int64)
    rd = A["rpmDistribution"]
    cls = sc["file"].map(dm.set_index("file")["drive_type"]).fillna("unknown").values
    pooled_ok = [round(float(v) / 3600, 3) for v in H.sum(0)] == rd["pooledHours"]
    byc_ok = {k: ([round(float(v) / 3600, 3) for v in H[cls == k].sum(0)] == rd["byClass"][k]["hours"]) for k in rd["byClass"]}
    ident = bool(((sc["ge300"].values) == H[:, 1:].sum(1) + sc["gt6000"].values).all())
    out["faithfulness"] = {"pooledHoursEqualStored": bool(pooled_ok), "byClassHoursEqualStored": byc_ok, "nBins": len(hcols), "perDriveIdentityGe300": ident, "drivesWithRpmGt6000": int((sc["gt6000"] > 0).sum()),
                           "secondsRpmGt6000": int(sc["gt6000"].sum()), "driveCount": int(len(sc)), "storedDriveCount": int(rd["coverage"]["nDrives"])}
    out["faithfulness"]["passed"] = bool(pooled_ok and all(byc_ok.values()) and ident and len(sc) == rd["coverage"]["nDrives"])
    out["pooled"] = part(sc)
    out["byClass"] = {k: part(sc[cls == k]) for k in CLASSES if (cls == k).any()}
    un = ~np.isin(cls, CLASSES)
    if un.any():
        out["unclassified"] = {**part(sc[un]), "note": "drives without a drive_type of the four classes (the master label unknown): included in pooled, absent from byClass"}
    p = out["pooled"]
    out["boundaryEvidence"] = {"exact400Seconds": p["exact400Seconds"], "exact400Hours": _hrs(p["exact400Seconds"]), "nDrivesWithExact400": int((sc["eq400"] > 0).sum()), "maxExact400SecondsPerDrive": int(sc["eq400"].max())}
    er = (A.get("engineRuntime") or {}).get("totals", {})
    if "supportedOnHours" in er and p["engineOnHours"]:
        term = p["engineOnHours"] - float(er["supportedOnHours"])
        term_pct = 100 * term / p["engineOnHours"]
        out["integrationCrossCheck"] = {"engineOnGridHours": p["engineOnHours"], "engineRuntimeSupportedOnHours": er["supportedOnHours"], "integrationTermHours": round(term, 4), "integrationTermPctOfEngineOn": round(term_pct, 4),
                                        "expectedInterval_M536wave0_pct": [0.6424, 0.8724], "flag": "within" if 0.6424 <= term_pct <= 0.8724 else "OUTSIDE (flag only; escalate)"}
    reg = pd.read_csv(os.path.join(ROOT, "cadence_regime.csv")).set_index("file")["regime"]
    rg = sc["file"].map(reg).fillna("unlabelled").values
    out["bandByCadenceStratum"] = {g: {"nDrives": int((rg == g).sum()), "lowRpmBandPctOfGe300": round(100 * float((sc["ge300"].values - sc["gt400"].values)[rg == g].sum()) / max(1.0, float(sc["ge300"].values[rg == g].sum())), 3)} for g in ("fast", "slow", "unlabelled") if (rg == g).any()}
    out.update(cohort_blocks(sc, dm, A, rg))
    out["faithfulness"]["cohortGatesPassed"] = out["cohortGates"]["passed"]
    out["faithfulness"]["passed"] = bool(out["faithfulness"]["passed"] and out["cohortGates"]["passed"])
    out["tripwires"] = {"classUnder10Days": [k for k, v in out["byClass"].items() if v["nDays"] < 10], "exact400HoursOver0.1": bool(out["boundaryEvidence"]["exact400Hours"] > 0.1),
                        "integrationOutsideExpected": bool(out.get("integrationCrossCheck", {}).get("flag", "within") != "within")}
    return out


def build_block(dm, A, rebuild=False):
    sc, rep = build_sidecar(dm, rebuild)
    r = compute(sc, dm, A)
    sha = lambda p: hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest()
    return {"estimand": "seconds and hours of the 1 Hz grid with logged rpm > 400 (engine-on under the project rule), the closed band 300 <= rpm <= 400 (low-rpm rotation band) and the stored rpm >= 300 basis, pooled and by drive type",
            "basis": "logged rpm (app-reported), resampled to the pipeline 1 Hz grid (hold limit 15 native rows and 15 grid seconds); deterministic re-definition on the same data, not a correction",
            "descriptive": True, "displayed": True,
            "rule": {"thresholdRpm": ER.THRESHOLD_RPM, "boundary": ER.BOUNDARY, "bandClosedRpm": [ER.BAND_LO_RPM, ER.THRESHOLD_RPM], "engineOnName": "engine-on (rpm > 400, 1 Hz grid)", "bandName": "low-rpm rotation band (logged rpm, 300-400 rpm)", "nanPolicy": ER.NAN_POLICY,
                     "separateNames": ["generator-active (reconstructed Pgen > 0)", "RPM onset (> 300 rpm, run >= 2 s)", "engine-start trigger (> 800 after <= 100)", "engine-off proxy (300 rpm, owner decision 2026-10-14 (g))"]},
            **r, "method": {"cluster": "calendar day", "draws": NB, "seed": SEED, "interval": "percentile, ratio of sums"},
            "limits": ["logged rpm is app-reported, not measured", "the low-rpm band carries load (about 99 % positive app-calculated load in M536): it is reported, not discarded", "the day bootstrap does not capture serial day correlation",
                       "the hold limit counts native rows and grid seconds", "convenience sample; the shares describe this corpus, not representative use", "aggregator sensitivity (M542): last = last value of the natively forward-filled series per 1 s bin; the variant defined as the last raw non-NaN row before the fill was not run; n_valid_last equals n_valid by construction (it tests nothing); the 15-row / 15-s hold limits are untested (wave 2c)", "the band (300-400 rpm) is aggregator-sensitive (pooled and per cadence stratum differences are in aggregatorSensitivity); no cadence contrast is drawn; cold is exploratory (few days)", "displayed since M541 (wave 2b-i): the pooled engine-on and band figures in the Fuel tab; the occupancy bins, OPT-band and mode-centre shares stay on the rpm >= 300 basis until M543"],
            "provenance": {"spec": SPEC, "specSha256": sha(SPEC), "toolSha256": sha("tools/engine_on_rule_block.py"), "ruleModuleSha256": sha("tools/engine_on_rule.py"), "specCohort": "analyses/M542_spec.md", "specCohortSha256": sha("analyses/M542_spec.md"), "sidecar": "engine_on_rule_sidecar.csv", "sidecarSha256": sha("engine_on_rule_sidecar.csv"),
                           "masterMd5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "reparsedDrives": rep}}


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new[KEY] = blk
    old = (A.get("_artifactStamps") or {}).get(KEY)
    if old and A.get(KEY) == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"][KEY] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M540: derived by tools/engine_on_rule_block.py from drive_master.csv and the raw drive files through engine_on_rule_sidecar.csv (keyed by raw sha256); gates against the stored rpmDistribution",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        import stamp_common as _sc
        new["_artifactStamps"][KEY] = _sc.carry_declared(old, st)
    ch = [k for k in set(A) | set(new) if A.get(k) != new.get(k)]
    bad = [k for k in ch if k not in (KEY, "_artifactStamps")]
    st_bad = [k for k in set(A["_artifactStamps"]) | set(new["_artifactStamps"]) if A["_artifactStamps"].get(k) != new["_artifactStamps"].get(k) and k != KEY]
    return new, ch, bad + st_bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw_txt = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A = json.loads(raw_txt)
    blk = build_block(dm, A, rebuild="--rebuild" in argv)
    if not blk["faithfulness"]["passed"]:
        print(json.dumps({"STOP": "faithfulness / identity gate failed", "faithfulness": blk["faithfulness"]}))
        return 1
    if "--check" in argv:
        have = A.get(KEY)
        keep = lambda b: {k: v for k, v in (b or {}).items() if k != "provenance"}
        print(json.dumps({"check": KEY, "matchesPayload": keep(have) == keep(blk)}))
        return 0 if keep(have) == keep(blk) else 1
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, ch, bad = splice(A, blk, md5)
    res = os.path.join("analyses", "M540_result.json")
    if not os.path.exists(res):                                    # run-once lock: the first output is kept
        json.dump(blk, open(res, "w", encoding="utf-8", newline=chr(10)), indent=1, ensure_ascii=False)
    print(json.dumps({"pooled": blk["pooled"], "boundaryEvidence": blk["boundaryEvidence"], "integrationCrossCheck": blk.get("integrationCrossCheck"), "tripwires": blk["tripwires"], "nChanged": len(ch), "outsideAllowList": bad}, default=float))
    if bad:
        return 1
    if "--dry-run" not in argv and ch:
        with open("summary_arrays.json", "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + (chr(10) if raw_txt.endswith(chr(10)) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
