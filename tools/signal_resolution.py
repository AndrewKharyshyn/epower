#!/usr/bin/env python3
"""M503 (spec analyses/M503_spec.md Rev 2): retroactive signal-resolution record of HV current and pack voltage over the canonical corpus (audit CD-07).
Descriptive data-quality inventory: "grid of this CSV copy", never "sensor resolution". No estimator, eligibility rule or published figure depends on it (see the no-consumer test).
Default: write analyses/M503_result.json.  --splice: also write the additive payload block signalResolution + stamp (a dated snapshot of the corpus).
Usage: python tools/signal_resolution.py [--out analyses/M503_result.json] [--splice]"""
import datetime, hashlib, io, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

ICOL, VCOL = "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)"
MIN_DISTINCT, MIN_DISTINCT_CLASS, ROUND, MIN_RUN, SHARE_MIN = 5, 20, 6, 5, 0.99
COARSE = {"0.1 A", "1 A", "0.1 V", "coarser"}


def stats(col_text):
    """Statistics of one channel from the raw TEXT of the column (strings): grid_step, n_nonnull, n_distinct, max_decimals, share on the 1 and 0.1 grids."""
    s = col_text.dropna().astype(str).str.strip()
    s = s[s != ""]
    v = pd.to_numeric(s, errors="coerce")
    ok = v.notna()
    v, s = v[ok].values.astype(float), s[ok]
    n = int(len(v))
    if n == 0:
        return {"n_nonnull": 0, "n_distinct": 0, "grid_step": None, "max_decimals": None, "share_on_1_grid": None, "share_on_0p1_grid": None}
    u = np.unique(np.round(v, ROUND))
    step = None
    if len(u) >= MIN_DISTINCT:
        d = np.diff(u)
        d = d[d > 0]
        step = float(np.round(d.min(), ROUND)) if len(d) else None
    dec = s.map(lambda x: len(x.split(".")[1]) if "." in x else 0)
    on1 = float(np.mean(np.abs(v - np.round(v)) < 1e-9))
    on01 = float(np.mean(np.abs(v * 10 - np.round(v * 10)) < 1e-9))
    return {"n_nonnull": n, "n_distinct": int(len(u)), "grid_step": step, "max_decimals": int(dec.max()), "share_on_1_grid": round(on1, 6), "share_on_0p1_grid": round(on01, 6)}


def classify(st, channel):
    """Classes of the spec: undefined | undefined_sparse | fine | 0.1 A/V | 1 A | coarser | mixed."""
    if st["n_nonnull"] < MIN_DISTINCT or st["n_distinct"] < MIN_DISTINCT or st["grid_step"] is None:
        return "undefined"
    if st["n_distinct"] < MIN_DISTINCT_CLASS:
        return "undefined_sparse"
    g = st["grid_step"]
    if channel == "current":
        c = "fine" if g <= 0.06 else "0.1 A" if g <= 0.15 else "1 A" if g <= 1.5 else "coarser"
    else:
        c = "fine" if g <= 0.06 else "0.1 V" if g <= 0.15 else "coarser"
    if c in ("0.1 A", "0.1 V") and st["share_on_0p1_grid"] < SHARE_MIN:
        return "mixed"
    if c == "1 A" and st["share_on_1_grid"] < SHARE_MIN:
        return "mixed"
    if c == "fine" and st["max_decimals"] is not None and st["max_decimals"] <= 1 and st["share_on_0p1_grid"] >= SHARE_MIN:
        return "mixed"
    return c


def is_coarse(ci, vi):
    return ci in COARSE or vi in COARSE


def digits(name):
    return re.sub(r"\D", "", os.path.basename(str(name)))


def identity(manifest, dm):
    """1:1 mapping manifest canonical <-> master rows by the 14 timestamp digits; any duplicate, orphan or missing key STOPs (R2)."""
    can = [r for r in manifest["files"] if r.get("role") == "canonical"]
    kc = [digits(r["canonical"]) for r in can]
    km = [digits(f) for f in dm["file"]]
    for name, ks in (("manifest canonical", kc), ("master", km)):
        if len(set(ks)) != len(ks):
            raise SystemExit("STOP: duplicate 14-digit keys in " + name)
    if set(kc) != set(km):
        raise SystemExit("STOP: manifest/master mapping is not 1:1 (only in manifest: %d, only in master: %d)" % (len(set(kc) - set(km)), len(set(km) - set(kc))))
    return len(can)


def compute(dm, loader):
    rows = []
    for _, r in dm.iterrows():
        f = str(r["file"])
        b = loader(f)
        if b is None:
            raise SystemExit("STOP: no raw file for master row %s" % f)
        df = pd.read_csv(io.BytesIO(b), dtype=str, low_memory=False, usecols=lambda c: c in (ICOL, VCOL))
        si = stats(df[ICOL]) if ICOL in df.columns else stats(pd.Series([], dtype=str))
        sv = stats(df[VCOL]) if VCOL in df.columns else stats(pd.Series([], dtype=str))
        ci, cv = classify(si, "current"), classify(sv, "voltage")
        rows.append({"file": f, "date": str(r["date"]), "timeStart": str(r.get("time_start", "")), "current": {**si, "class": ci}, "voltage": {**sv, "class": cv}, "coarse": bool(is_coarse(ci, cv))})
    return rows


def order_of(rows):
    return sorted(range(len(rows)), key=lambda k: (rows[k]["date"], rows[k]["timeStart"], rows[k]["file"]))


def runs_of(order, flag, skip, min_run=MIN_RUN):
    """Maximal sequences of consecutive drives (time order) with flag True; drives in `skip` neither break nor extend a run."""
    out, cur = [], []
    for k in order:
        if k in skip:
            continue
        if flag[k]:
            cur.append(k)
        else:
            if len(cur) >= min_run:
                out.append(cur)
            cur = []
    if len(cur) >= min_run:
        out.append(cur)
    return out


def summarize(rows):
    order = order_of(rows)
    undefined = {k for k, r in enumerate(rows) if r["current"]["class"] in ("undefined", "undefined_sparse") and r["voltage"]["class"] in ("undefined", "undefined_sparse")}
    flags = {"coarse": {k: r["coarse"] for k, r in enumerate(rows)}, "currentCoarse": {k: r["current"]["class"] in COARSE for k, r in enumerate(rows)},
             "voltageCoarse": {k: r["voltage"]["class"] in COARSE for k, r in enumerate(rows)}}
    runs = {}
    for name, fl in flags.items():
        rr = runs_of(order, fl, undefined)
        runs[name] = [{"first": rows[r[0]]["date"], "last": rows[r[-1]]["date"], "spanDays": (pd.Timestamp(rows[r[-1]]["date"]) - pd.Timestamp(rows[r[0]]["date"])).days + 1, "nDrives": len(r)} for r in rr]
    cc = {ch: {} for ch in ("current", "voltage")}
    for r in rows:
        for ch in cc:
            cc[ch][r[ch]["class"]] = cc[ch].get(r[ch]["class"], 0) + 1
    coarse_rows = [r for r in rows if r["coarse"]]
    by_month = {}
    for r in coarse_rows:
        by_month[r["date"][:7]] = by_month.get(r["date"][:7], 0) + 1
    longest = max(runs["coarse"], key=lambda x: x["nDrives"]) if runs["coarse"] else None
    inside = sum(1 for r in coarse_rows if longest and longest["first"] <= r["date"] <= longest["last"])
    tr, prev = [], None
    for k in order:
        pair = (rows[k]["current"]["class"], rows[k]["voltage"]["class"])
        if "undefined" in pair or "undefined_sparse" in pair:
            continue
        if prev is not None and prev[1] != pair:
            tr.append({"fromDate": rows[prev[0]]["date"], "toDate": rows[k]["date"], "from": list(prev[1]), "to": list(pair)})
        prev = (k, pair)
    return {"nDrives": len(rows), "classCounts": cc, "nCoarse": len(coarse_rows), "firstCoarseDate": min((r["date"] for r in coarse_rows), default=None), "lastCoarseDate": max((r["date"] for r in coarse_rows), default=None),
            "runs": runs, "windowLongestCoarseRun": longest, "coarseByMonth": dict(sorted(by_month.items())), "coarseInLongestRun": inside, "coarseOutsideLongestRun": len(coarse_rows) - inside,
            "mixedDrives": [r["file"] for r in rows if "mixed" in (r["current"]["class"], r["voltage"]["class"])],
            "undefinedDrives": [rows[k]["file"] for k in sorted(undefined)], "transitions": tr}


def overlap(rows, dm):
    """Counts of coarse drives among the eligible drives of powerFade S1 and of the cell-spread slope, each checked against its named payload key."""
    import powerfade_equivalence as PE
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    side = PE._read(PE.SIDECAR)
    dens = {r["file"]: (float(r["eff_dt_s"]) if pd.notna(r["eff_dt_s"]) else np.nan, float(r["coverage_frac"]) if pd.notna(r["coverage_frac"]) else np.nan) for r in side.to_dict("records")}
    _, have_d = PE.s1_rows(dm, dens)
    s1 = set(digits(f) for f in have_d["file"])
    flag = dm["ens_outlier_v2"]
    clean = ~flag.fillna(False).astype(bool)
    sp = set(digits(f) for f in dm.loc[clean & dm["cell_spread_loaded_p95_mv"].notna(), "file"])
    co = {digits(r["file"]) for r in rows if r["coarse"]}
    exp_s1 = A["powerFade"]["nClean"]
    exp_sp = A["degradationTrends"]["cellSpread"]["clusterRobustOLS"]["nObs"]
    return {"powerFadeS1": {"eligible": len(s1), "payloadKey": "powerFade.nClean", "payloadValue": exp_s1, "verified": bool(len(s1) == exp_s1), "nCoarse": len(s1 & co)},
            "cellSpreadSlope": {"eligible": len(sp), "payloadKey": "degradationTrends.cellSpread.clusterRobustOLS.nObs", "payloadValue": exp_sp, "verified": bool(len(sp) == exp_sp), "nCoarse": len(sp & co)}}


def main():
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "analyses/M503_result.json"
    import ah_throughput as AH
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    manifest = json.load(open("raw_manifest.json", encoding="utf-8"))
    n_can = identity(manifest, dm)
    rows = compute(dm, AH.raw_loader())
    summ = summarize(rows)
    for ch in ("current", "voltage"):
        if sum(summ["classCounts"][ch].values()) != n_can:
            raise SystemExit("STOP: class counts do not add up to the manifest canonical count")
    summ["overlap"] = overlap(rows, dm)
    prov = {"masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawManifestSha256": hashlib.sha256(open("raw_manifest.json", "rb").read()).hexdigest(),
            "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "specSha256": hashlib.sha256(open("analyses/M503_spec.md", "rb").read()).hexdigest(),
            "basis": "raw/ = sha256-verified originals (M366)", "nCanonicalManifest": n_can}
    res = {"spec": "analyses/M503_spec.md", "provenance": {**prov, "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}, "summary": summ, "perDrive": rows}
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({k: summ[k] for k in ("nDrives", "classCounts", "nCoarse", "firstCoarseDate", "lastCoarseDate", "windowLongestCoarseRun", "coarseInLongestRun", "coarseOutsideLongestRun", "overlap", "transitions")}, indent=1)[:4500])
    if "--splice" in sys.argv:
        splice(summ, [r for r in rows if r["coarse"]], prov)


def splice(summ, coarse_rows, prov):
    import copy
    P = "summary_arrays.json"
    raw = open(P, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    blk = {"label": "grid of this CSV copy of the logged HV battery current and pack voltage per canonical drive (descriptive inventory, a dated snapshot; not a sensor resolution; logged / app-calculated values; no effect on any estimate is estimated)",
           "spec": "analyses/M503_spec.md", "snapshotOfDrives": summ["nDrives"],
           "classRule": {"current": "fine <= 0.06 A, 0.1 A <= 0.15, 1 A <= 1.5, coarser above", "voltage": "fine <= 0.06 V, 0.1 V <= 0.15, coarser above",
                         "step": "minimum positive difference of the sorted distinct values rounded to 6 decimals; undefined with fewer than 5 distinct values; undefined_sparse below 20; mixed when the grid shares disagree"},
           **{k: prov[k] for k in ("specSha256", "scriptSha256", "masterMd5", "rawManifestSha256", "basis")}, **summ,
           "coarseDrives": [{"file": r["file"], "date": r["date"], "currentClass": r["current"]["class"], "voltageClass": r["voltage"]["class"]} for r in coarse_rows]}
    blk = json.loads(json.dumps(blk))
    A["signalResolution"] = blk
    st = copy.deepcopy(A["_artifactStamps"]["powerFadeEquivalence"])
    st.update(corpusHash=prov["masterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M503: derived by tools/signal_resolution.py from the raw files of the canonical drives (spec analyses/M503_spec.md Rev 2); a dated snapshot, no ingestion stage", upstreamHashes={"driveMasterMd5": prov["masterMd5"]})
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["signalResolution"] = st
    with open(P, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"spliced": True, "nCoarse": summ["nCoarse"]}))


if __name__ == "__main__":
    main()
