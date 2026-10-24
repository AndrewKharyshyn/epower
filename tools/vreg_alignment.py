#!/usr/bin/env python3
"""M505 (spec analyses/M505_spec.md Rev 2): sensitivity of the resistance-proxy trend to the current-voltage alignment rule (audit CD-05).
Reporting only: the production estimator (compute_drive_summary_v6._vsag_metrics), the proxy column of drive_master.csv, powerFade and resistanceVreg are read, never changed. The proxy is recomputed
by calling the production _vsag_metrics on the prepared frame of each drive with ONLY compute_drive_summary_v6._asof replaced (in process; restored afterwards); every other step is production code.
Variants: A0 production (nearest within 1500 ms) | A1 synchronous (linear interpolation onto the current timestamps, t_prev <= t_I <= t_next, gap <= 3000 ms) | A2 nearest within 300 ms | A3 backward | A4 forward.
Usage: python tools/vreg_alignment.py [--out analyses/M505_result.json] [--splice]"""
import contextlib, datetime, hashlib, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import compute_drive_summary_v6 as D

VARIANTS = ["A0", "A1", "A2", "A3", "A4"]
N_DRAWS, SEED, MONTH_DAYS = 4000, 42, 30.44
MIN_PAIRED, WIDTH_MAX, FAIL_CAP = 150, 1.5, 0.01
STATS = {"tiedTimestamps": 0, "socRowsPaired": 0, "socRowsChanged": 0}


def make_asof(variant):
    """Replacement for compute_drive_summary_v6._asof(base, other, name, tol) implementing the pairing rule of a variant. `base` and `other` carry columns t (datetime64) and v."""
    orig = D._ASOF_ORIG

    def a0(base, other, name, tol):
        return orig(base, other, name, tol)

    def a2(base, other, name, tol):
        return orig(base, other, name, "300ms")

    def directed(direction):
        def f(base, other, name, tol):
            if other is None:
                base[name] = np.nan
                return base
            return pd.merge_asof(base, other.rename(columns={"v": name}), on="t", direction=direction, tolerance=pd.Timedelta(tol))
        return f

    def a1(base, other, name, tol):
        """Linear interpolation of `other` onto base['t'] between the neighbours t_prev <= t <= t_next (gap <= 2 x tol); an exact timestamp match takes that sample (the first of tied timestamps)."""
        if other is None:
            base[name] = np.nan
            return base
        o = other.sort_values("t", kind="stable").reset_index(drop=True)
        to = o["t"].values.astype("datetime64[ns]").astype("int64")
        vo = o["v"].values.astype(float)
        STATS["tiedTimestamps"] += int((np.diff(to) == 0).sum())
        tb = base["t"].values.astype("datetime64[ns]").astype("int64")
        i = np.searchsorted(to, tb, side="left")
        out = np.full(len(tb), np.nan)
        exact = (i < len(to)) & (to[np.minimum(i, len(to) - 1)] == tb)
        out[exact] = vo[i[exact]]
        inner = (~exact) & (i > 0) & (i < len(to))
        ii = i[inner]
        t0, t1 = to[ii - 1], to[ii]
        ok = (t1 - t0 <= 2 * pd.Timedelta(tol).value) & (t1 > t0)
        w = np.where(ok, (tb[inner] - t0) / np.where(ok, (t1 - t0), 1), np.nan)
        vals = vo[ii - 1] * (1 - w) + vo[ii] * w
        idx = np.where(inner)[0]
        out[idx[ok]] = vals[ok]
        res = base.copy()
        res[name] = out
        if name == "soc":
            near = orig(base.copy(), other, name, tol)[name].values
            both = ~np.isnan(out) & ~np.isnan(near)
            STATS["socRowsPaired"] += int(both.sum())
            STATS["socRowsChanged"] += int((both & (np.abs(out - near) > 1e-9)).sum())
        return res
    f = {"A0": a0, "A1": a1, "A2": a2, "A3": directed("backward"), "A4": directed("forward")}[variant]
    f._xt_variant = variant
    return f


@contextlib.contextmanager
def patched_asof(variant):
    if not hasattr(D, "_ASOF_ORIG"):
        D._ASOF_ORIG = D._asof
    prev = D._asof
    D._asof = make_asof(variant)
    try:
        yield
    finally:
        D._asof = prev


def proxy_all_variants(csv_bytes):
    """{variant: {vreg_R_pack_mohm, vreg_I_p95_A, n_vreg_samples}} for one drive; the frame is prepared once and copied per call. The active-patch sentinel is verified inside each call."""
    df, t = D._prep_bytes(csv_bytes)
    out = {}
    for v in VARIANTS:
        with patched_asof(v):
            if getattr(D._asof, "_xt_variant", None) != v:
                raise SystemExit("STOP: alignment patch not active for variant " + v)
            r = D._vsag_metrics(csv_bytes, _prep=(df.copy(), t.copy() if hasattr(t, "copy") else t))
        out[v] = {k: r.get(k) for k in ("vreg_R_pack_mohm", "vreg_I_p95_A", "n_vreg_samples") if r.get(k) is not None}
    return out


# ------------------------------------------------------------------------------------------------ refits (released designs, proxy columns replaced by the variant's)
def refits(dm_v, dens, nb):
    """S0 (resistanceVreg design) and S1 (powerFade primary design) months coefficient with the released interval and the day / ISO-week bootstrap intervals."""
    import degradation_trends as DT, powerfade_equivalence as PE, day_bootstrap as DB, m499_temp_spec as M9
    out = {}
    d = DT._prep(dm_v, PE.RCOL, icol=PE.ICOL)
    dd = d.dropna(subset=["T", "I"])
    co = DT._cluster_ols(d, covars=("T", "I"))
    X = np.column_stack([np.ones(len(dd)), dd["months"].values, dd["T"].values, dd["I"].values])
    y = dd["y"].values
    days = dd["day"].values
    wk = pd.to_datetime(dd["date"]).dt.strftime("%G-W%V").values
    dr = DB.ols_boot_slopes(X, y, days, coef=1, nb=nb, seed=SEED, t=dd["months"].values)[0]
    wr = M9.cluster_boot(X, y, wk, 1, nb, SEED)
    q = lambda a: [round(float(v), 4) for v in np.percentile(a, [2.5, 97.5])]
    out["S0"] = {"n": int(len(dd)), "nDays": int(dd["day"].nunique()), "slope": round(float(co["slope"]), 4), "releasedCi95Crt": [round(float(x), 4) for x in co["ci95"]],
                 "dayCi95": q(dr), "dayDropped": int(nb - len(dr)), "weekCi95": q(wr), "weekDropped": int(nb - len(wr))}
    cc, have_d = PE.s1_rows(dm_v, dens)
    if len(have_d) >= 20:
        t0 = pd.to_datetime(cc["date"]).min()
        f, _, _, _, _ = M9.fit(have_d, "T0", t0, (0.0, 0.0), nb)
        out["S1"] = {"n": f["n"], "nDays": f["nDays"], "slope": round(float(f["slope"]), 4), "dayCi95": [round(float(x), 4) for x in f["day"]["ci95"]], "dayDropped": f["day"]["drawsDropped"],
                     "weekCi95": [round(float(x), 4) for x in f["isoWeek"]["ci95"]], "weekDropped": f["isoWeek"]["drawsDropped"]}
    else:
        out["S1"] = {"n": int(len(have_d)), "estimable": False}
    for k in ("S0", "S1"):
        r = out[k]
        if "dayCi95" in r:
            r["dayIncludesZero"] = bool(r["dayCi95"][0] <= 0 <= r["dayCi95"][1])
            r["nonDecisive"] = bool(r["dayDropped"] > FAIL_CAP * nb)
    return out


def boot_median(days, vals, nb, seed=SEED):
    """Median of per-drive differences with a day-clustered percentile bootstrap interval."""
    u, di = np.unique(days, return_inverse=True)
    rng = np.random.default_rng(seed)
    G = len(u)
    groups = [vals[di == g] for g in range(G)]
    meds = []
    for _ in range(nb):
        pick = rng.integers(0, G, G)
        meds.append(np.median(np.concatenate([groups[p] for p in pick])))
    return [round(float(x), 3) for x in np.percentile(meds, [2.5, 97.5])]


def verdicts(res):
    """Per design and variant: paired-set governs attribution; own-set flips are labelled 'population change under variant'."""
    out = {}
    for des in ("S0", "S1"):
        out[des] = {}
        a0_own = res["own"]["A0"][des]
        for v in VARIANTS[1:]:
            p0, pv = res["paired"][v]["A0"][des], res["paired"][v]["variant"][des]
            ov = res["own"][v][des]
            row = {"pairedN": pv.get("n"), "pairedSlopeA0": p0.get("slope"), "pairedSlopeVariant": pv.get("slope")}
            if "dayCi95" not in pv or "dayCi95" not in p0 or pv.get("nonDecisive") or p0.get("nonDecisive"):
                row["pairedReading"] = "not estimable"
            else:
                w0, wv = p0["dayCi95"][1] - p0["dayCi95"][0], pv["dayCi95"][1] - pv["dayCi95"][0]
                row["pairedWidthRatio"] = round(wv / w0, 3)
                row["pairedSignFlip"] = bool(np.sign(p0["slope"]) != np.sign(pv["slope"]))
                row["lowPrecision"] = bool(pv["n"] < MIN_PAIRED or row["pairedWidthRatio"] > WIDTH_MAX)
                if pv["dayIncludesZero"] == p0["dayIncludesZero"]:
                    row["pairedReading"] = "unchanged"
                else:
                    row["pairedReading"] = ("excludes zero -> includes zero" if p0["dayIncludesZero"] is False else "includes zero -> excludes zero")
            if "dayCi95" in ov and "dayCi95" in a0_own and not ov.get("nonDecisive"):
                row["ownReading"] = "unchanged" if ov["dayIncludesZero"] == a0_own["dayIncludesZero"] else ("excludes zero -> includes zero" if a0_own["dayIncludesZero"] is False else "includes zero -> excludes zero")
            else:
                row["ownReading"] = "not estimable"
            row["label"] = ("population change under variant" if (row["pairedReading"] == "unchanged" and row["ownReading"] not in ("unchanged", "not estimable")) else
                            "reading unchanged" if row["pairedReading"] == "unchanged" else "not estimable" if row["pairedReading"] == "not estimable" else
                            ("reading depends on the alignment rule; lower precision" if row.get("lowPrecision") else "reading depends on the alignment rule"))
            out[des][v] = row
        labs = [r["label"] for r in out[des].values()]
        out[des]["overall"] = ("reading depends on the alignment rule" if any(l.startswith("reading depends") for l in labs) else
                               "population change under variant" if any(l == "population change under variant" for l in labs) else
                               "not estimable" if all(l == "not estimable" for l in labs) else "reading unchanged across the five pre-registered alignment rules")
    return out


def main():
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "analyses/M505_result.json"
    nb = int(sys.argv[sys.argv.index("--nb") + 1]) if "--nb" in sys.argv else N_DRAWS
    import ah_throughput as AH, signal_resolution as SR, powerfade_equivalence as PE
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    manifest = json.load(open("raw_manifest.json", encoding="utf-8"))
    n_can = SR.identity(manifest, dm)
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    side = PE._read(PE.SIDECAR)
    dens = {r["file"]: (float(r["eff_dt_s"]) if pd.notna(r["eff_dt_s"]) else np.nan, float(r["coverage_frac"]) if pd.notna(r["coverage_frac"]) else np.nan) for r in side.to_dict("records")}
    loader = AH.raw_loader()
    prox = {}
    for f in dm["file"]:
        b = loader(str(f))
        if b is None:
            raise SystemExit("STOP: no raw file for master row %s" % f)
        prox[f] = proxy_all_variants(b)
    # ---- fidelity (R4): A0 reproduces the master proxy per drive; targets read from the payload
    bad = []
    for _, r in dm.iterrows():
        p = prox[r["file"]]["A0"].get("vreg_R_pack_mohm")
        m = r.get("vreg_R_pack_mohm")
        if (p is None) != (pd.isna(m)) or (p is not None and abs(p - float(m)) > 1e-9):
            bad.append(str(r["file"]))
    if bad:
        raise SystemExit("M505 STOP: A0 does not reproduce vreg_R_pack_mohm on %d drives, e.g. %s" % (len(bad), bad[:5]))
    # sentinel (R3): every non-A0 variant must differ from A0 on at least one drive
    for v in VARIANTS[1:]:
        if all(prox[f][v] == prox[f]["A0"] for f in prox):
            raise SystemExit("M505 STOP: variant %s equals A0 on every drive (patch not effective)" % v)
    dmv = {}
    for v in VARIANTS:
        d = dm.copy()
        d["vreg_R_pack_mohm"] = [prox[f][v].get("vreg_R_pack_mohm", np.nan) for f in d["file"]]
        d["vreg_I_p95_A"] = [prox[f][v].get("vreg_I_p95_A", np.nan) for f in d["file"]]
        dmv[v] = d
    own = {v: refits(dmv[v], dens, nb) for v in VARIANTS}
    pf, pe, rv = A["powerFade"], A["powerFadeEquivalence"], A["degradationTrends"]["resistanceVreg"]["clusterRobustOLS"]
    fid = {"S1": {"slope": own["A0"]["S1"]["slope"], "publishedSlope": pe["s1"]["slope"], "n": own["A0"]["S1"]["n"], "publishedN": pf["nClean"], "nDays": own["A0"]["S1"]["nDays"], "publishedNDays": pe["s1"]["nDays"]},
           "S0": {"slope": own["A0"]["S0"]["slope"], "publishedSlope": round(float(rv["slope"]), 4), "n": own["A0"]["S0"]["n"], "publishedN": rv["nObs"]},
           "proxyColumn": "A0 equals vreg_R_pack_mohm on all %d drives (n with proxy: %d)" % (len(dm), int(dm["vreg_R_pack_mohm"].notna().sum()))}
    ok = (round(fid["S1"]["slope"], 4) == round(float(fid["S1"]["publishedSlope"]), 4) and fid["S1"]["n"] == fid["S1"]["publishedN"] and fid["S1"]["nDays"] == fid["S1"]["publishedNDays"]
          and round(fid["S0"]["slope"], 3) == round(float(fid["S0"]["publishedSlope"]), 3) and fid["S0"]["n"] == fid["S0"]["publishedN"])
    fid["passed"] = bool(ok)
    if not ok:
        raise SystemExit("M505 STOP: A0 refits do not reproduce the published slopes: %s" % json.dumps(fid))
    # ---- paired sets
    paired = {}
    reg = pd.read_csv("cadence_regime.csv", low_memory=False)
    dg = lambda f: re.sub(r"\D", "", os.path.basename(str(f)))
    regime = {dg(r["file"]): r["regime"] for r in reg.to_dict("records")}
    shifts = {}
    for v in VARIANTS[1:]:
        both = [f for f in dm["file"] if prox[f]["A0"].get("vreg_R_pack_mohm") is not None and prox[f][v].get("vreg_R_pack_mohm") is not None]
        keep = set(both)
        d0, dvv = dmv["A0"].copy(), dmv[v].copy()
        for dd_ in (d0, dvv):
            dd_.loc[~dd_["file"].isin(keep), ["vreg_R_pack_mohm", "vreg_I_p95_A"]] = np.nan
        paired[v] = {"A0": refits(d0, dens, nb), "variant": refits(dvv, dens, nb)}
        diff = np.array([prox[f][v]["vreg_R_pack_mohm"] - prox[f]["A0"]["vreg_R_pack_mohm"] for f in both])
        days = np.array([str(dm.loc[dm["file"] == f, "date"].iloc[0]) for f in both])
        sh = {"nBoth": len(both), "nKeepOnly": int(sum(1 for f in dm["file"] if prox[f]["A0"].get("vreg_R_pack_mohm") is not None and f not in keep)),
              "nGain": int(sum(1 for f in dm["file"] if prox[f]["A0"].get("vreg_R_pack_mohm") is None and prox[f][v].get("vreg_R_pack_mohm") is not None))}
        sh["nLost"] = sh.pop("nKeepOnly")
        if len(both):
            sh.update(median=round(float(np.median(diff)), 3), q25=round(float(np.percentile(diff, 25)), 3), q75=round(float(np.percentile(diff, 75)), 3), medianDayCi95=boot_median(days, diff, nb))
            sh["byRegime"] = {}
            for rg in ("fast", "slow"):
                m = np.array([regime.get(dg(f)) == rg for f in both])
                if m.sum() >= 10:
                    sh["byRegime"][rg] = {"n": int(m.sum()), "median": round(float(np.median(diff[m])), 3), "medianDayCi95": boot_median(days[m], diff[m], nb)}
        shifts[v] = sh
    res = {"own": own, "paired": paired}
    res["verdicts"] = verdicts(res)
    prov = {"masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "rawManifestSha256": hashlib.sha256(open("raw_manifest.json", "rb").read()).hexdigest(),
            "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "specSha256": hashlib.sha256(open("analyses/M505_spec.md", "rb").read()).hexdigest(),
            "basis": "raw/ = sha256-verified originals (M366)", "nCanonicalManifest": n_can, "seed": SEED, "nDraws": nb}
    out = {"spec": "analyses/M505_spec.md", "provenance": {**prov, "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}, "fidelity": fid, "variantsRule": "A0 nearest 1500 ms | A1 interpolation | A2 nearest 300 ms | A3 backward | A4 forward",
           "asofStats": STATS, "paired": res["paired"], "own": res["own"], "proxyShiftVsA0": shifts, "verdicts": res["verdicts"],
           "perDrive": {str(f): {v: prox[f][v].get("vreg_R_pack_mohm") for v in VARIANTS} for f in dm["file"] if any(prox[f][v].get("vreg_R_pack_mohm") is not None for v in VARIANTS)}}
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1)
    brief = {"fidelity": fid, "verdicts": res["verdicts"], "own": {v: {k: {kk: x.get(kk) for kk in ("n", "slope", "dayCi95", "dayIncludesZero")} for k, x in own[v].items()} for v in VARIANTS},
             "shift": shifts, "asof": STATS}
    print(json.dumps(brief, indent=1)[:9000])
    if "--splice" in sys.argv:
        splice(out, prov)


def splice(out, prov):
    import copy
    P = "summary_arrays.json"
    raw = open(P, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    cut = lambda d: {k: {kk: v.get(kk) for kk in ("n", "nDays", "slope", "dayCi95", "weekCi95", "dayIncludesZero", "releasedCi95Crt", "nonDecisive", "estimable") if kk in v} for k, v in d.items()}
    blk = {"label": "sensitivity of the estimated resistance-proxy trend to the current-voltage alignment rule (reporting only; production stays A0 nearest within 1500 ms; estimated proxy, an association within one warm-season window, not a degradation rate; basis raw/ = sha256-verified originals (M366))",
           "spec": "analyses/M505_spec.md", "specRevision": "Rev 2", **{k: prov[k] for k in ("specSha256", "scriptSha256", "masterMd5", "rawManifestSha256", "basis", "seed", "nDraws")},
           "snapshot": {"nDrives": prov["nCanonicalManifest"], "a0S1Slope": out["fidelity"]["S1"]["slope"], "note": "dated snapshot; semantic_gate warns when the live powerFade slope differs from a0S1Slope"},
           "variantsRule": out["variantsRule"], "fidelity": out["fidelity"], "own": {v: cut(out["own"][v]) for v in VARIANTS},
           "paired": {v: {"A0": cut(out["paired"][v]["A0"]), "variant": cut(out["paired"][v]["variant"])} for v in out["paired"]},
           "proxyShiftVsA0": out["proxyShiftVsA0"], "verdicts": out["verdicts"], "asofStats": out["asofStats"],
           "multiplicity": "per design 4 non-A0 variants x 2 populations day intervals (+ A0 references), plus 5 ISO-week sensitivity intervals; no adjustment; the any-difference rule leans conservative"}
    blk = json.loads(json.dumps(blk))
    A["vregAlignmentSensitivity"] = blk
    st = copy.deepcopy(A["_artifactStamps"]["powerFadeEquivalence"])
    st.update(corpusHash=prov["masterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M505: derived by tools/vreg_alignment.py from the raw files of the canonical drives (spec analyses/M505_spec.md Rev 2); a dated snapshot, no ingestion stage", upstreamHashes={"driveMasterMd5": prov["masterMd5"]})
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["vregAlignmentSensitivity"] = st
    with open(P, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"spliced": True}))


if __name__ == "__main__":
    main()
