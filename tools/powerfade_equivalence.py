#!/usr/bin/env python3
"""M486 (analyses/M486_spec.md Rev 2.1, pre-registered): equivalence test on the PRIMARY resistance-proxy design (powerFade, specification S1). Additive: writes the payload block
summary_arrays.json['powerFadeEquivalence'] (+ its artifact stamp) and the tracked sidecar powerfade_density.csv; the released estimators, intervals, the released equivalence decision on the S0 design and the
locked bound are unchanged. The verdict is determined by published values (the published S1 slope exceeds the locked bound); this formalises it and closes the disclosure gap.
S1 = months + T_pack_mean_avg + vreg_I_p95_A + eff_dt_s + coverage_frac (the two density covariates come from the production function compute_drive_summary_v6._i_channel_sampling_density on the raw files; cached
per drive in powerfade_density.csv, keyed by raw sha256 + METHOD_VERSION). S0 = the released resistanceVreg design, run through the same code path as a control.
Primary: degradation_trends._cluster_ols (day clusters, CR1, t(G-1)) + degradation_trends._tost against the locked bound (read from the released block, never recomputed).
Secondary: the day-cluster percentile bootstrap of the published function (_powerfade_cadence_specs.fit: days / 30.44, seed 42, N_BOOT draws), 90 % interval.
Verdict: established iff BOTH procedures place the 90 % interval inside (-delta, +delta); procedure-dependent iff exactly one; notEstablished iff neither. Six hard stops (any failure: nothing is written).
Usage: python tools/powerfade_equivalence.py [--check] [--dry-run]   (--check is read-only and needs no raw files: it refits from drive_master.csv and the tracked sidecar)"""
import copy, datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import degradation_trends as DT          # noqa: E402

METHOD_VERSION = 1
SIDECAR = os.path.join(ROOT, "powerfade_density.csv")
RCOL, ICOL = "vreg_R_pack_mohm", "vreg_I_p95_A"
COLS = ["file", "date", "eff_dt_s", "coverage_frac", "raw_sha256", "method_version", "reason"]
ALLOWED = ["/powerFadeEquivalence", "/_artifactStamps/powerFadeEquivalence"]
POWERFADE_MONTH_DAYS = 30.44             # the published bootstrap's months scale (degradation_trends._prep uses 30.4375)
SLOPE_TOL = 0.002
N_BOOT = 4000                          # the published function's draw count (compute_drive_summary_v6.N_BOOT); stop (iii) compares the draws used with the published nBoot
FORMULA_S1 = "y ~ months + T + I + de + dc"
REPEATED_LOOKS = "re-run at every ingestion, no alpha spending"
STATEMENT = ("Equivalence test on the primary design (powerFade, specification S1): a descriptive TOST at the locked bound over a short window; the verdict is determined by the published slope relative to the bound; "
             "not established is not evidence of no degradation; the first established verdict would require a blind audit before it may be displayed.")


# ------------------------------------------------------------------------------------------------ density sidecar
def density_from_bytes(b):
    """(eff_dt_s, coverage_frac) of one drive by the production function (not a reimplementation)."""
    import compute_drive_summary_v6 as D
    return D._i_channel_sampling_density(["x"], lambda f: b)["x"]


def _read(path):
    return pd.read_csv(path, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])


def build_density(master, loader, sha_lookup, path=SIDECAR):
    """One row per master drive that carries the vreg proxy and a date (master order). A stored row is reused when its raw sha256 and METHOD_VERSION are unchanged; otherwise the raw file is read."""
    old = {}
    if os.path.exists(path):
        old = {r["file"]: r for r in _read(path).to_dict("records")}
    rows = []
    d = master[master[RCOL].notna() & master["date"].notna()]
    for _, m in d.iterrows():
        f, date = str(m["file"]), str(m["date"])
        prev = old.get(f)
        sha = sha_lookup(f) if sha_lookup else None
        ok_prev = prev is not None and prev.get("method_version") == METHOD_VERSION and prev.get("reason") not in ("raw_file_missing",)
        if ok_prev and sha and prev.get("raw_sha256") == sha:
            rows.append({k: (None if (isinstance(prev.get(k), float) and np.isnan(prev.get(k))) else prev.get(k)) for k in COLS})
            continue
        b = loader(f)
        if b is None:
            rows.append({"file": f, "date": date, "eff_dt_s": None, "coverage_frac": None, "raw_sha256": None, "method_version": METHOD_VERSION, "reason": "raw_file_missing"})
            continue
        h = hashlib.sha256(b).hexdigest()
        if ok_prev and prev.get("raw_sha256") == h:
            rows.append({k: (None if (isinstance(prev.get(k), float) and np.isnan(prev.get(k))) else prev.get(k)) for k in COLS})
            continue
        eff, cov = density_from_bytes(b)
        rows.append({"file": f, "date": date, "eff_dt_s": None if not np.isfinite(eff) else float(eff), "coverage_frac": None if not np.isfinite(cov) else float(cov),
                     "raw_sha256": h, "method_version": METHOD_VERSION, "reason": None if (np.isfinite(eff) and np.isfinite(cov)) else "density_unresolved"})
    out = pd.DataFrame(rows, columns=COLS)
    out.to_csv(path, index=False, lineterminator="\n", float_format="%.12g")
    return _read(path)


# ------------------------------------------------------------------------------------------------ the fits
def _clean_files(dm, coercion):
    """Clean complete-case file list under one of the two coercions (released 'fillna(False).astype(bool)' or the module's _as_bool)."""
    flag = dm["ens_outlier_v2"]
    keep = ~(flag.fillna(False).astype(bool) if coercion == "released" else DT._as_bool(flag))
    need = [RCOL, "T_pack_mean_avg", ICOL, "date"]
    return dm[keep].dropna(subset=need)


def s1_rows(dm, dens):
    """Replicates _powerfade_cadence_specs: clean complete cases sorted by date / time_start, with density attached. Returns (cc, have_d)."""
    cc = _clean_files(dm, "released").copy()
    cc["date"] = cc["date"].astype(str)
    order = ["date", "time_start"] if "time_start" in cc.columns else ["date"]
    cc = cc.sort_values(order, kind="stable").reset_index(drop=True)
    cc["_de"] = cc["file"].map(lambda f: dens.get(f, (np.nan, np.nan))[0]).astype(float)
    cc["_dc"] = cc["file"].map(lambda f: dens.get(f, (np.nan, np.nan))[1]).astype(float)
    have_d = cc[np.isfinite(cc["_de"]) & np.isfinite(cc["_dc"])]
    return cc, have_d


def bootstrap_s1(cc, have_d, n_boot):
    """The published function's day-cluster percentile bootstrap of the S1 slope (exact replication of _powerfade_cadence_specs.fit): months = days / 30.44 from the minimum date of ALL clean complete cases."""
    dt0 = pd.to_datetime(cc["date"]).min()
    t = ((pd.to_datetime(have_d["date"]) - dt0).dt.days / POWERFADE_MONTH_DAYS).values
    X = np.column_stack([np.ones(len(have_d)), t, have_d["T_pack_mean_avg"].values, have_d[ICOL].values, have_d["_de"].values.astype(float), have_d["_dc"].values.astype(float)])
    y = have_d[RCOL].values.astype(float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    days = have_d["date"].values
    uniq = np.unique(days)
    grp = {d: np.where(days == d)[0] for d in uniq}
    rng = np.random.default_rng(42)
    boot = []
    for _ in range(n_boot):
        idx = np.concatenate([grp[d] for d in rng.choice(uniq, size=len(uniq), replace=True)])
        if len(np.unique(t[idx])) < 3:
            continue
        try:
            boot.append(float(np.linalg.lstsq(X[idx], y[idx], rcond=None)[0][1]))
        except Exception:
            pass
    boot = np.asarray(boot)
    q = np.percentile(boot, [2.5, 5.0, 95.0, 97.5])
    return {"slope": float(b[1]), "ci95": [float(q[0]), float(q[3])], "ci90": [float(q[1]), float(q[2])], "drawsRequested": int(n_boot), "drawsUsed": int(len(boot)),
            "drawsDropped": int(n_boot - len(boot)), "seed": 42, "monthsScale": "days / 30.44 from the minimum date of the clean complete cases (the published function's scale)"}


def _inside(lo, hi, delta):
    return bool(lo > -delta and hi < delta)


def verdict_from(cr1_inside, boot_inside):
    """Frozen decision rule: established iff both procedures place the 90 % interval inside the bound; procedure-dependent iff exactly one; notEstablished iff neither."""
    n = int(bool(cr1_inside)) + int(bool(boot_inside))
    return "established" if n == 2 else ("procedureDependent" if n == 1 else "notEstablished")


def se_max_for_equivalence(delta, df):
    """Rev 3 (reporting only): the largest standard error at which the 90 % interval slope +- t(0.95, df) * SE can lie inside (-delta, +delta) for ANY slope estimate, i.e. delta / t(0.95, df)."""
    from scipy import stats
    return float(delta / stats.t.ppf(0.95, df))


def _fit_block(co, delta):
    G = int(co["nDays"])
    ts = DT._tost(co["slope"], co["se"], delta, df=G - 1)
    smax = se_max_for_equivalence(delta, G - 1)
    return {"slope": co["slope"], "se": co["se"], "df": G - 1, "ci90": ts["equivCI90"], "pTOST": ts["pTOST"], "equivalent": bool(ts["equivalent"]), "nDrives": int(co["nObs"]), "nDays": G, "formula": co["formula"],
            "seMaxForEquivalence": round(smax, 4), "equivalenceAttainable": bool(co["se"] < smax)}


def compute_block(dm, dens, released, n_boot=None):
    """The powerFadeEquivalence block. `released` = {'resistanceVreg': degradationTrends.resistanceVreg, 'powerFade': powerFade}. Raises SystemExit on any hard stop."""
    n_boot = N_BOOT if n_boot is None else n_boot
    rv, pf = released["resistanceVreg"], released["powerFade"]
    delta = rv["releasedEquivalence"]["delta"]
    cc, have_d = s1_rows(dm, dens)
    # (v) file set under both coercions, equal to each other, equal in size to powerFade.nClean, and equal to the density-resolved set
    f_rel = set(_clean_files(dm, "released")["file"])
    f_new = set(_clean_files(dm, "as_bool")["file"])
    if f_rel != f_new:
        raise SystemExit("STOP (v): the clean file set differs between the released coercion and _as_bool (%d vs %d)" % (len(f_rel), len(f_new)))
    if set(have_d["file"]) != f_rel or len(f_rel) != pf["nClean"]:
        raise SystemExit("STOP (v): the S1 drive-file set (%d) is not the clean complete-case set (%d) / powerFade.nClean (%s)" % (len(have_d), len(f_rel), pf["nClean"]))
    # (vi) the published design engaged the density correction
    if pf.get("cadenceControlled") is not True:
        raise SystemExit("STOP (vi): the published powerFade.cadenceControlled is not true")
    # fits through the released code path
    d = DT._prep(dm, RCOL, icol=ICOL)
    d["de"] = d["file"].map(lambda f: dens.get(f, (np.nan, np.nan))[0]).astype(float)
    d["dc"] = d["file"].map(lambda f: dens.get(f, (np.nan, np.nan))[1]).astype(float)
    co0 = DT._cluster_ols(d, covars=("T", "I"))
    co1 = DT._cluster_ols(d, covars=("T", "I", "de", "dc"))
    # (iv) S1 must contain BOTH density columns (_covars_present would silently drop a covariate present on half of the rows or fewer)
    if co1.get("formula") != FORMULA_S1:
        raise SystemExit("STOP (iv): the fitted S1 formula is '%s', not '%s'" % (co1.get("formula"), FORMULA_S1))
    s0, s1 = _fit_block(co0, delta), _fit_block(co1, delta)
    rc = rv["clusterRobustOLS"]
    # (i) S0 control = the released resistanceVreg fit and TOST
    rel_t = rv["releasedEquivalence"]
    if (co0["slope"], co0["se"], co0["nObs"], co0["nDays"]) != (rc["slope"], rc["se"], rc["nObs"], rc["nDays"]) or abs(s0["pTOST"] - rel_t["pTOST"]) > 1e-4 or [round(x, 4) for x in s0["ci90"]] != [round(x, 4) for x in rel_t["equivCI90"]]:
        raise SystemExit("STOP (i): the S0 control does not reproduce the released resistanceVreg fit / TOST: %s vs %s" % ((co0["slope"], co0["se"], s0["pTOST"], s0["ci90"]), (rc["slope"], rc["se"], rel_t["pTOST"], rel_t["equivCI90"])))
    # (ii) the S1 CR1 slope = the published powerFade slope within 0.002, same n
    if abs(co1["slope"] - pf["slopeMohmPerMoTctrl"]) > SLOPE_TOL or co1["nObs"] != pf["nClean"]:
        raise SystemExit("STOP (ii): the S1 CR1 slope %s (n %s) differs from the published %s (n %s)" % (co1["slope"], co1["nObs"], pf["slopeMohmPerMoTctrl"], pf["nClean"]))
    # (iii) the bootstrap reproduces the published 95 % interval and nBoot from the same draws
    bt = bootstrap_s1(cc, have_d, n_boot)
    if [round(bt["ci95"][0], 3), round(bt["ci95"][1], 3)] != [round(x, 3) for x in pf["ci95MohmPerMo"]] or bt["drawsUsed"] != pf["nBoot"]:
        raise SystemExit("STOP (iii): the bootstrap does not reproduce the published interval %s / nBoot %s: %s / %s" % (pf["ci95MohmPerMo"], pf["nBoot"], [round(x, 3) for x in bt["ci95"]], bt["drawsUsed"]))
    cr1_in = s1["equivalent"] and _inside(s1["ci90"][0], s1["ci90"][1], delta)
    boot_in = _inside(bt["ci90"][0], bt["ci90"][1], delta)
    cs = pf.get("cadenceSensitivity") or {}
    return {
        "methodVersion": METHOD_VERSION, "quantity": "pack-resistance proxy slope, primary design (powerFade, specification S1)",
        "bound": {"value": delta, "unit": "mOhm/month", "label": rel_t["label"], "lockDate": DT.SESOI_BASELINE_DATE, "source": "degradationTrends.resistanceVreg.releasedEquivalence.delta, read as a constant (never recomputed, not rescaled)",
                  "baselineMedianMohm": DT.VREG_MED_BASELINE_MOHM, "currentMedianMohm": rv.get("proxyMedianMohm")},
        "s0Control": s0, "s1": s1,
        "bootstrap": {"ci90": bt["ci90"], "ci95Reproduced": bt["ci95"], "drawsRequested": bt["drawsRequested"], "drawsUsed": bt["drawsUsed"], "drawsDropped": bt["drawsDropped"], "seed": bt["seed"], "monthsScale": bt["monthsScale"],
                      "pointSlope": bt["slope"]},
        "procedures": {"cr1TostInside": bool(cr1_in), "bootstrap90Inside": bool(boot_in)},
        "verdict": verdict_from(cr1_in, boot_in),
        "reconciliation": {"s0VsReleased": "slope, SE, n, days, pTOST and 90 % interval equal", "s1SlopeVsPublished": [co1["slope"], pf["slopeMohmPerMoTctrl"]], "publishedCi95": pf["ci95MohmPerMo"],
                           "publishedNBoot": pf["nBoot"], "fileSetSize": len(f_rel), "cadenceControlled": True},
        "cadenceRange": {"slopeMin": cs.get("slopeMin"), "slopeMax": cs.get("slopeMax"), "nSpecs": cs.get("nSpecs"), "allIntervalsSpanZero": cs.get("allIntervalsSpanZero")},
        "blindAuditRef": None, "repeatedLooks": REPEATED_LOOKS, "statement": STATEMENT,
    }


def sentence(blk):
    """The dashboard sentence generated from the block (mirrored in the JSX and the semantic gate)."""
    s1, b, cr = blk["s1"], blk["bound"], blk["cadenceRange"]
    word = {"notEstablished": "equivalence not established", "procedureDependent": "procedure-dependent, equivalence not established", "established": "within the locked bound over this window"}[blk["verdict"]]
    rng = ("The slope depends on the cadence specification (M395: %s to %s mΩ/month across %d specifications%s). " % (cr["slopeMin"], cr["slopeMax"], cr["nSpecs"], ", every 95 % interval spans zero" if cr.get("allIntervalsSpanZero") else "")) if cr.get("nSpecs") else ""
    att = (("The observed SE %.3f is below the %.3f mΩ/month needed for equivalence to be attainable." % (s1["se"], s1["seMaxForEquivalence"])) if s1["equivalenceAttainable"] else
           ("At this precision the test could not show equivalence: it requires an SE below %.3f mΩ/month (bound / t0.95,df), the observed SE is %.3f, so even a slope estimate of exactly 0 would not lie inside the bound." % (s1["seMaxForEquivalence"], s1["se"])))
    return ("Equivalence test on the primary design (powerFade, specification S1, density-adjusted partial slope): slope %s mΩ/month, 90 %% interval [%s, %s] against the locked bound of ±%s mΩ/month; %s. %sThis is not evidence of no change. %s"
            % (s1["slope"], s1["ci90"][0], s1["ci90"][1], b["value"], word, rng, att))


def short(blk):
    """The short clause used in the S0 panels: the primary design's verdict."""
    return {"notEstablished": "primary design (S1): equivalence not established", "procedureDependent": "primary design (S1): procedure-dependent, equivalence not established",
            "established": "primary design (S1): within the locked bound over this window"}[blk["verdict"]]


# ------------------------------------------------------------------------------------------------ additive splice
def _paths(a, b, p=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [x for k in sorted(set(a) | set(b)) for x in (_paths(a.get(k), b.get(k), "%s/%s" % (p, k)) if (k in a and k in b) else ["%s/%s" % (p, k)])]
    return [] if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else [p]


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 4)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new["powerFadeEquivalence"] = blk
    old = (A.get("_artifactStamps") or {}).get("powerFadeEquivalence")
    coherent = old and old.get("includedInReleaseAt") == old.get("computedAt") == old.get("generatedAt")
    if old and coherent and A.get("powerFadeEquivalence") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["powerFadeEquivalence"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M486: derived by tools/powerfade_equivalence.py from drive_master.csv and the tracked powerfade_density.csv; equivalence test on the primary resistance design (analyses/M486_spec.md)",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        new["_artifactStamps"]["powerFadeEquivalence"] = st
    ch = _paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A0 = json.loads(raw)
    if "--check" in argv:
        side = _read(SIDECAR)
    else:
        import ah_throughput as AH
        side = build_density(dm, AH.raw_loader(), AH.manifest_sha_lookup())
    dens = {r["file"]: (float(r["eff_dt_s"]) if pd.notna(r["eff_dt_s"]) else np.nan, float(r["coverage_frac"]) if pd.notna(r["coverage_frac"]) else np.nan) for r in side.to_dict("records")}
    released = {"resistanceVreg": A0["degradationTrends"]["resistanceVreg"], "powerFade": A0["powerFade"]}
    blk = _clean(compute_block(dm, dens, released))
    blk["sidecar"] = {"file": "powerfade_density.csv", "sha256": hashlib.sha256(open(SIDECAR, "rb").read()).hexdigest(), "rows": int(len(side)), "nDensityResolved": int(sum(1 for v in dens.values() if np.isfinite(v[0]) and np.isfinite(v[1])))}
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    if "--check" in argv:
        have = A0.get("powerFadeEquivalence")
        bad = have != blk
        print(json.dumps({"check": "powerFadeEquivalence", "matchesPayload": not bad, "verdict": blk["verdict"]}))
        if blk["verdict"] == "established" and not have.get("blindAuditRef"):
            print("FAIL: an established verdict needs a blindAuditRef")
            return 1
        return 1 if bad else 0
    new, changed, bad = splice(A0, blk, md5)
    print(json.dumps({"nChanged": len(changed), "outsideAllowList": bad, "verdict": blk["verdict"], "sentence": sentence(blk)}))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
