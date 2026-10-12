#!/usr/bin/env python3
"""M415 (spec analyses/M413_spec.md Rev 1-3): leaf-level splice of the exposure flip into summary_arrays.json.

Inputs: the published summary_arrays.json (P), control build A (XT_EXPOSURE_BASIS=legacy2p1kWh) and control build B (default rated5Ah, legacy-tagged blocks pinned to the legacy columns), both written by
tools/exposure_control_build.py on the same master, raw set and sidecar. The diff B vs A is the expected-changed set:
  * every differing leaf must lie in ALLOWED (must-change keys and the two meta leaves); a differing leaf anywhere else ESCALATES (exit 1, nothing written);
  * every MUST_CHANGE key must appear in the diff (a key that should switch but did not is also an escalation);
  * a leaf is spliced only where the published payload equals build A at that leaf (otherwise it carries hand edits or earlier splices: escalate and decide per leaf);
  * arrays whose length changes are replaced whole.
Also writes the additive top-level block `exposureBasis` (per-block basis tags, required labels, the factor line, the legacy values of the switched headlines taken from build A) and its artifact stamp.
Usage: python tools/exposure_splice.py --a A.json --b B.json [--dry-run] [--report FILE]"""
import copy, datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import exposure_control_diff as D

ALLOWED_TOP = ("cycleByType", "cycleCumulative", "cycleBySpeed", "cycleBySpeedMeta", "metricConvention", "riskColdEngineBattery", "cRatePoints", "cRatePointsAK", "cRateRefLines", "cRateRefLinesAK", "cRateAxes",
               "records", "ledgerCrossCheck")
ALLOWED_LEAVES = ("/meta/gtcSum", "/meta/fceSum")
MUST_CHANGE = ("cycleByType", "cycleCumulative", "cycleBySpeed", "metricConvention", "cRatePoints", "cRateRefLines", "cRateAxes", "ledgerCrossCheck") + ALLOWED_LEAVES
LEGACY_BLOCKS = {"cycleLife": "threshold block (20,000-GTC scenario, verified:false)", "fadeModes": "threshold block (capacity fade scenario)", "seasonalLife": "threshold block (model extrapolation)",
                 "officialDisclosureCorrelation": "threshold block (capacityFadeAnchor); chemistry comparison", "observedMix": "threshold block", "kLadderScenarios": "threshold block (reference threshold)",
                 "dailyFingerprints": "k-means feature gtcMean of the legacy ML columns", "energyUncertaintyMC": "Monte Carlo draws are kWh / 2.1 (not rescalable to Ah)",
                 "crossVehicle": "both legs legacy until an e-4ORCE Ah sidecar exists", "interDriveCarryover": "legacy ML feature"}
LABELS = {"rated": "rated capacity 5 Ah (Nissan Article-10), documentary; throughput integrated from logged current, estimated, offset-uncorrected; verified:false; drivetrain applicability not stated by the document",
          "legacy": "legacy 2.1 kWh reference (verified:false)",
          "scalesInversely": "scales inversely with the reference; physical throughput unchanged",
          "thresholdScenario": "scenario 20,000 GTC (verified:false) on legacy basis; threshold reference undocumented; not a life estimate",
          "crate": "C-rate = current/5 A (rated); no longer pack-voltage dependent",
          "ledger": "session notes quote GTC, FCE and C-rates on the legacy 2.1 kWh basis (hand-curated, not rebased); rf_efc is reference-independent, so rf_efc vs FCE in these notes reflects the legacy reference only"}


def get(o, path):
    for k in [p for p in path.split("/") if p != ""]:
        o = o[int(k)] if isinstance(o, list) else o[k]
    return o


def put(o, path, v):
    ks = [p for p in path.split("/") if p != ""]
    for k in ks[:-1]:
        o = o[int(k)] if isinstance(o, list) else o[k]
    if isinstance(o, list):
        o[int(ks[-1])] = v
    else:
        o[ks[-1]] = v


def top(path):
    return path.split("/")[1]


def plan(P, A, B):
    D.IGNORE.clear(); D.IGNORE.add("generatedAt")
    out = D.diff(A, B)
    esc, ops = [], []
    seen_must = set()
    for path, kind, a, b in out:
        t = top(path)
        ok = t in ALLOWED_TOP or any(path == lf or path.startswith(lf + "/") for lf in ALLOWED_LEAVES)
        if not ok:
            esc.append({"path": path, "why": "differing leaf outside the allow-list (a block that must stay legacy changed, or an unexpected key)"})
            continue
        for m in MUST_CHANGE:
            if path == m or path.startswith(m + "/") or (m == t):
                seen_must.add(m)
        if kind == "only in B":
            ops.append({"path": path, "mode": "add", "reason": kind})        # additive leaf/block that exists only on the rated build (Ah fields, basis tags): must be absent in P and A
        elif kind.startswith("list length") or kind == "only in A":
            # whole-structure replacement at the parent list/dict path
            ops.append({"path": path, "mode": "replace-whole", "reason": kind})
        else:
            ops.append({"path": path, "mode": "leaf"})
    for m in MUST_CHANGE:
        if m not in seen_must:
            esc.append({"path": m, "why": "must-change key did not change between build A and build B"})
    # published == A at every spliced leaf
    for op in ops:
        if op["mode"] == "add":
            for nm, src in (("published payload", P), ("build A", A)):
                try:
                    get(src, op["path"])
                    esc.append({"path": op["path"], "why": "additive path already exists in the " + nm})
                except (KeyError, IndexError, ValueError):
                    pass
            continue
        try:
            pv, av = get(P, op["path"]), get(A, op["path"])
            if D.diff({"x": pv}, {"x": av}):
                esc.append({"path": op["path"], "why": "published payload differs from build A at this leaf (hand edit or earlier splice): decide per leaf"})
        except (KeyError, IndexError, ValueError):
            esc.append({"path": op["path"], "why": "path missing in the published payload or build A"})
    return ops, esc, out


def populations():
    import pandas as pd
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    sc = pd.read_csv("ah_throughput.csv").set_index("file")
    ah = dm["file"].map(sc["ah_throughput"])
    fin = ah.notna() & dm["gtc"].notna()
    clean = fin & (dm["ens_outlier_v2"].astype("object") == False)   # noqa: E712
    out = {}
    for name, m in (("allDrivesWithAhValue", fin), ("canonicalClean", clean)):
        out[name] = {"nDrives": int(m.sum()), "nDays": int(dm.loc[m, "date"].nunique()), "ratedOverLegacyGtc": round(float((ah[m] / 5.0).sum() / dm.loc[m, "gtc"].sum()), 4)}
    return out


def build_block(A, B, P, now=None):
    Am, Bm = A["meta"], B["meta"]
    fac = Bm["gtcSum"] / Am["gtcSum"]
    pops = populations()
    tags = {k: {"basis": "rated5Ah"} for k in ALLOWED_TOP}
    tags["meta.gtcSum"] = tags["meta.fceSum"] = {"basis": "rated5Ah"}
    tags.update({k: {"basis": "legacy2p1kWh", "reason": r} for k, r in LEGACY_BLOCKS.items()})
    tags["sessionGroups / sessions (summary_config.json notes)"] = {"basis": "legacy2p1kWh", "reason": LABELS["ledger"]}
    tags["seasonal_drive_master.csv:gtc"] = {"basis": "rated5Ah", "reason": "the seasonal master carries the rated-basis gtc since M415; same column name as the legacy master column"}
    tags["drive_master.csv:gtc / fce / efc_per100km / cap_ah_est / *_Crate"] = {"basis": "legacy2p1kWh", "reason": "published master columns, never rewritten (corpus anchor); historical names; efc_per100km is legacy-basis GTC per 100 km, not an EFC"}
    tags["seasonalCharts.CycleByType / CycleBySpeed / CycleBySpeedMeta"] = {"basis": "rated5Ah", "reason": "cohort versions of cycleByType / cycleBySpeed, refreshed by the seasonal stages"}
    return {"_provenance": "GENERATED by tools/exposure_splice.py (M415, spec analyses/M413_spec.md Rev 1-3); do not hand-edit. Additive block: per-block exposure basis tags, required labels and the legacy values of the switched headlines (control build A).",
            "basis": "rated5Ah", "referenceAh": 5.0, "referenceSource": "CAP_AH_RATED (constantProvenance), Nissan Article-10, documentary, verified:false",
            "labels": LABELS, "tags": tags,
            "populations": pops,
            "factor": {"aggregateRatedOverLegacy": round(fac, 4), "line": "the rated-basis accumulation (GTC, FCE) is higher than the legacy-basis one by the factor %.4f over the %d drives (%d days) with an Ah value (%.4f over the %d canonical-clean drives, %d days); %s" % (fac, pops["allDrivesWithAhValue"]["nDrives"], pops["allDrivesWithAhValue"]["nDays"], pops["canonicalClean"]["ratedOverLegacyGtc"], pops["canonicalClean"]["nDrives"], pops["canonicalClean"]["nDays"], LABELS["scalesInversely"])},
            "legacy": {"meta": {"gtcSum": Am["gtcSum"], "fceSum": Am["fceSum"]}, "metricConvention": A["metricConvention"], "cycleByType": A["cycleByType"], "cycleBySpeed": A["cycleBySpeed"],
                       "cycleCumulativeLast": A["cycleCumulative"][-1] if A.get("cycleCumulative") else None, "cRateAxesCPerA": A["cRateAxes"]["cPerA"], "cRateRefLinesLines": A["cRateRefLines"].get("lines"),
                       "note": "legacy-basis values of the switched headlines (control build A, same master and raw set); shown beside the rated value as a disclosure line"},
            "ratedPointBesideMonteCarlo": {"gtc": Bm["gtcSum"], "fce": Bm["fceSum"], "note": "point values from the Ah sidecar; no Monte Carlo interval exists on the rated basis (the interval in energyUncertaintyMC is on the legacy basis and is never shown beside this point)"},
            "weakestCellCaveat": "pack-level counts are a lower bound for the weakest cell only if that cell's capacity is at or below the reference",
            "windowFractionBand": (P.get("capacityBasis") or {}).get("exposure", {}).get("windowFractionBand"),
            "primaryExposure": {**((P.get("capacityBasis") or {}).get("exposure", {}).get("primaryRaw") or {}), "nDrives": pops["canonicalClean"]["nDrives"], "nDays": pops["canonicalClean"]["nDays"],
                                "population": (P.get("capacityBasis") or {}).get("exposure", {}).get("population", {}).get("rule"), "note": "raw Ah / kWh throughput is the primary, reference-independent exposure; the headline GTC / FCE sums use the all-drives population, the primary figures the canonical-clean one"}}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    a_path, b_path = argv[argv.index("--a") + 1], argv[argv.index("--b") + 1]
    A, B = json.load(open(a_path, encoding="utf-8")), json.load(open(b_path, encoding="utf-8"))
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    P = json.loads(raw)
    if "--block-only" in argv:
        new = copy.deepcopy(P)
        new["exposureBasis"] = build_block(A, B, P)
        md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
        st = copy.deepcopy(P["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=md5, generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
                  computationStatusNote="M415: derived by tools/exposure_splice.py from the control builds A (legacy) and B (rated5Ah); exposure basis tags and legacy disclosure values", upstreamHashes={"driveMasterMd5": md5})
        st.pop("carriedForward", None)
        new["_artifactStamps"]["exposureBasis"] = st
        if "--dry-run" not in argv:
            with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("refreshed exposureBasis block only")
        return 0
    ops, esc, diff = plan(P, A, B)
    rep = {"nDiffLeavesBvsA": len(diff), "byTopLevelKey": D.summary(diff), "nOps": len(ops), "escalations": esc[:200], "nEscalations": len(esc)}
    if "--report" in argv:
        json.dump(rep, open(argv[argv.index("--report") + 1], "w", encoding="utf-8", newline="\n"), indent=1)
    print(json.dumps({k: rep[k] for k in ("nDiffLeavesBvsA", "byTopLevelKey", "nOps", "nEscalations")}, indent=1))
    if esc:
        print(json.dumps(esc[:20], indent=1))
        return 1
    new = copy.deepcopy(P)
    for op in ops:
        put(new, op["path"], copy.deepcopy(get(B, op["path"])))
    blk = build_block(A, B, P)
    new["exposureBasis"] = blk
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    st = copy.deepcopy(P["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=md5, generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M415: derived by tools/exposure_splice.py from the control builds A (legacy) and B (rated5Ah) of tools/exposure_control_build.py; exposure basis tags and legacy disclosure values",
              upstreamHashes={"driveMasterMd5": md5})
    st.pop("carriedForward", None)
    new["_artifactStamps"]["exposureBasis"] = st
    if "--dry-run" not in argv:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("spliced", len(ops), "ops + exposureBasis block")
    return 0


if __name__ == "__main__":
    sys.exit(main())
