#!/usr/bin/env python3
"""M723 (analyses/M723_spec.md Rev 2, pre-registered): the cadence covariates of the power-fade design S1 written into the payload, and the specification sensitivity of the S1 interval.
Additive: writes the payload block powerFade.cadenceCovariates (+ nothing else) and the tracked sidecar powerfade_density_alt.csv; the published S1 numbers (powerFade slope, interval, n, note) are unchanged (R1 / A1).
C1 documents `eff_dt_s` and `coverage_frac` (formula in words from the production function's docstring, function sha256, sidecar sha256, counts, medians, per-regime medians; nothing typed).
C2 refits the S1 design under E0 (published) and the reduced / alternative specifications A0-A5 on ONE common drive set (day-cluster percentile bootstrap, 4000 draws, seed 42 for the reading, seeds 43-50 only for the endpoint spread):
  A0 both cadence covariates dropped; A1 coverage replaced by n_I / duration_s; A2 coverage replaced by n_I x eff_dt_s / duration_s; A3 coverage_frac only; A4 eff_dt_s only; A5 the M379a fast / slow regime indicator instead of both.
Three-state reading of an interval: includes zero / excludes zero / within seed noise of zero (band = max(0.1, 2 x the 9-seed range of the endpoint nearest to zero), mOhm/month). E0 stays the only published reading.
Usage: python tools/powerfade_covariates.py [--check] [--dry-run]   (--check is read-only and needs no raw files: it refits from drive_master.csv and the tracked sidecars)"""
import copy, datetime, hashlib, io, json, os, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p_ not in sys.path:
        sys.path.insert(0, p_)

METHOD_VERSION = 1
SPEC = "analyses/M723_spec.md"
SIDECAR_ALT = os.path.join(ROOT, "powerfade_density_alt.csv")
SIDECAR_PROD = os.path.join(ROOT, "powerfade_density.csv")
COLS_ALT = ["file", "date", "n_I", "n_rows", "duration_s", "raw_sha256", "method_version", "reason"]
ICOL_RAW = "[BMS] HV Battery Current (A)"
RCOL, ICOL = "vreg_R_pack_mohm", "vreg_I_p95_A"
MONTH_DAYS = 30.44
N_BOOT = 4000
SEED_READING = 42
SEEDS_EXTRA = [43, 44, 45, 46, 47, 48, 49, 50]
BAND_FLOOR = 0.1
SPEC_IDS = ["E0", "A0", "A1", "A2", "A3", "A4", "A5"]
LABELS = {"E0": "published S1 (median interval + coverage_frac)", "A0": "both cadence covariates dropped (anchor)", "A1": "coverage replaced by n_I / duration_s",
          "A2": "coverage replaced by n_I x eff_dt_s / duration_s", "A3": "reduced: coverage_frac only", "A4": "reduced: eff_dt_s only", "A5": "fast / slow regime indicator instead of both"}
ALLOWED = ["/powerFade/cadenceCovariates"]


# ------------------------------------------------------------------------------------------------ alternative densities (from the raw bytes, same reader as the production function)
def alt_from_bytes(b):
    """(n_I, n_rows, duration_s) of one drive's raw bytes: n_I = rows carrying a HV-current sample, n_rows = logged rows, duration_s = last minus first valid time stamp. Same file reader, time parsing and current column as
    compute_drive_summary_v6._density_of_bytes (coverage_frac = n_I / n_rows; eff_dt_s is the median interval of the current samples)."""
    try:
        df = pd.read_csv(io.BytesIO(b), usecols=lambda c: c in ("time", ICOL_RAW), low_memory=False)
    except Exception:
        return (np.nan, np.nan, np.nan)
    if "time" not in df.columns or ICOL_RAW not in df.columns:
        return (np.nan, np.nan, np.nan)
    ts = df["time"]
    td = pd.to_timedelta(ts, errors="coerce")
    t = td.dt.total_seconds().values if td.notna().mean() > 0.5 else pd.to_numeric(ts, errors="coerce").values
    t = np.asarray(t, float)
    m = df[ICOL_RAW].notna().values
    tv = t[np.isfinite(t)]
    dur = float(tv.max() - tv.min()) if len(tv) >= 2 else np.nan
    return (float(m.sum()), float(len(df)), dur)


def _read(path):
    return pd.read_csv(path, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])


def build_alt(master, loader, sha_lookup, path=SIDECAR_ALT):
    """One row per master drive that carries the vreg proxy and a date. A stored row is reused when its raw sha256, METHOD_VERSION and the extractor code hash are unchanged."""
    import dep_hash
    code = dep_hash.closure_hash([alt_from_bytes], modules=(sys.modules[__name__],), extra={"method": METHOD_VERSION})
    code_ok = dep_hash.sidecar_code_ok(path, code)
    old = {}
    if os.path.exists(path):
        old = {r["file"]: r for r in _read(path).to_dict("records")}
    rows = []
    d = master[master[RCOL].notna() & master["date"].notna()]
    for _, m in d.iterrows():
        f, date = str(m["file"]), str(m["date"])
        prev = old.get(f)
        sha = sha_lookup(f) if sha_lookup else None
        ok_prev = code_ok and prev is not None and prev.get("method_version") == METHOD_VERSION and prev.get("reason") not in ("raw_file_missing",)
        if ok_prev and sha and prev.get("raw_sha256") == sha:
            rows.append({k: (None if (isinstance(prev.get(k), float) and np.isnan(prev.get(k))) else prev.get(k)) for k in COLS_ALT})
            continue
        b = loader(f)
        if b is None:
            rows.append({"file": f, "date": date, "n_I": None, "n_rows": None, "duration_s": None, "raw_sha256": None, "method_version": METHOD_VERSION, "reason": "raw_file_missing"})
            continue
        h = hashlib.sha256(b).hexdigest()
        if ok_prev and prev.get("raw_sha256") == h:
            rows.append({k: (None if (isinstance(prev.get(k), float) and np.isnan(prev.get(k))) else prev.get(k)) for k in COLS_ALT})
            continue
        nI, nr, dur = alt_from_bytes(b)
        ok = np.isfinite(nI) and np.isfinite(nr) and np.isfinite(dur) and dur > 0
        rows.append({"file": f, "date": date, "n_I": None if not np.isfinite(nI) else float(nI), "n_rows": None if not np.isfinite(nr) else float(nr), "duration_s": None if not np.isfinite(dur) else float(dur),
                     "raw_sha256": h, "method_version": METHOD_VERSION, "reason": None if ok else "duration_unresolved"})
    out = pd.DataFrame(rows, columns=COLS_ALT)
    out.to_csv(path, index=False, lineterminator="\n", float_format="%.12g")
    dep_hash.sidecar_code_write(path, code)
    return _read(path)


# ------------------------------------------------------------------------------------------------ design, bootstrap, three-state reading
def design_columns(sid, df):
    """Covariate columns (after months, T_pack_mean_avg, vreg_I_p95_A) of each specification."""
    de, dc = df["_de"].values.astype(float), df["_dc"].values.astype(float)
    nI, dur = df["_nI"].values.astype(float), df["_dur"].values.astype(float)
    if sid == "E0":
        return [("eff_dt_s", de), ("coverage_frac", dc)]
    if sid == "A0":
        return []
    if sid == "A1":
        return [("eff_dt_s", de), ("n_I_per_s", nI / dur)]
    if sid == "A2":
        return [("eff_dt_s", de), ("n_I_x_eff_dt_over_duration", nI * de / dur)]
    if sid == "A3":
        return [("coverage_frac", dc)]
    if sid == "A4":
        return [("eff_dt_s", de)]
    if sid == "A5":
        return [("fast_regime", df["_fast"].values.astype(float))]
    raise KeyError(sid)


def fit_spec(sid, df, t, seeds, n_boot=N_BOOT):
    import day_bootstrap as DB
    extra = design_columns(sid, df)
    X = np.column_stack([np.ones(len(df)), t, df["T_pack_mean_avg"].values.astype(float), df[ICOL].values.astype(float)] + [c for _, c in extra])
    y = df[RCOL].values.astype(float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    days = df["date"].values
    los, his = {}, {}
    for s in seeds:
        boot = DB.ols_boot_slopes(X, y, days, coef=1, nb=n_boot, seed=s, t=t)[0]
        q = np.percentile(boot, [2.5, 97.5])
        los[s], his[s] = float(q[0]), float(q[1])
    return {"id": sid, "label": LABELS[sid], "slope": float(b[1]), "ci95": [los[SEED_READING], his[SEED_READING]], "nDrives": int(len(df)), "nDays": int(len(np.unique(days))),
            "lowerEndpointBySeed": [round(los[s], 4) for s in seeds], "upperEndpointBySeed": [round(his[s], 4) for s in seeds],
            "lowerEndpointRange": round(max(los.values()) - min(los.values()), 4), "upperEndpointRange": round(max(his.values()) - min(his.values()), 4),
            "collinearity": collinearity(X, ["const", "months", "T_pack_mean_avg", "vreg_I_p95_A"] + [n for n, _ in extra])}


def collinearity(X, names):
    """Variance inflation factor of every non-constant column (regressed on all others incl. the constant) and the condition number of the column-standardised design."""
    out = {}
    for j in range(1, X.shape[1]):
        o = [k for k in range(X.shape[1]) if k != j]
        beta = np.linalg.lstsq(X[:, o], X[:, j], rcond=None)[0]
        res = X[:, j] - X[:, o] @ beta
        ss_tot = float(((X[:, j] - X[:, j].mean()) ** 2).sum())
        r2 = 1.0 - float((res ** 2).sum()) / ss_tot if ss_tot > 0 else np.nan
        out[names[j]] = round(1.0 / (1.0 - r2), 3) if np.isfinite(r2) and r2 < 1.0 - 1e-12 else None
    Z = X[:, 1:] / np.sqrt((X[:, 1:] ** 2).mean(axis=0))
    return {"vif": out, "conditionNumber": round(float(np.linalg.cond(Z)), 2)}


def three_state(lo, hi, lo_range, hi_range, floor=BAND_FLOOR):
    """'includesZero' / 'excludesZero' / 'withinSeedNoiseOfZero' (M723 spec section 4): band = max(floor, 2 x the 9-seed range of the endpoint nearest to zero)."""
    near_is_lo = abs(lo) <= abs(hi)
    e, rng_ = (lo, lo_range) if near_is_lo else (hi, hi_range)
    band = max(floor, 2.0 * rng_)
    if abs(e) <= band:
        return "withinSeedNoiseOfZero", round(band, 4)
    return ("includesZero" if lo <= 0.0 <= hi else "excludesZero"), round(band, 4)


# ------------------------------------------------------------------------------------------------ block
def definitions():
    import compute_drive_summary_v6 as D
    doc = D._i_channel_sampling_density.__doc__
    m = re.search(r"Returns dict: file -> \(eff_dt_s, coverage_frac\), where (.*?)\n\s*\"?\"?\"?$", doc, re.S)
    words = " ".join((m.group(1) if m else doc).split())
    src = __import__("inspect").getsource(D._density_of_bytes)
    return {"effDtS": {"unit": "s", "formula": "median inter-sample interval of the HV-current channel (positive intervals below 20 s between consecutive rows carrying a current sample)"},
            "coverageFrac": {"unit": "fraction", "formula": "fraction of logged rows carrying a HV-current sample"},
            "wordsFromProductionDocstring": words, "sourceFunction": "compute_drive_summary_v6._density_of_bytes", "sourceFunctionSha256": hashlib.sha256(src.encode("utf-8")).hexdigest()}


def _stat(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return {"n": int(len(v)), "median": round(float(np.median(v)), 4), "q25": round(float(np.percentile(v, 25)), 4), "q75": round(float(np.percentile(v, 75)), 4)}


def compute_block(dm, prod, alt, spec_sha, n_boot=N_BOOT):
    import powerfade_equivalence as PE
    import compute_drive_summary_v6 as D
    dens = {r["file"]: (float(r["eff_dt_s"]) if pd.notna(r["eff_dt_s"]) else np.nan, float(r["coverage_frac"]) if pd.notna(r["coverage_frac"]) else np.nan) for r in prod.to_dict("records")}
    cc, have_d = PE.s1_rows(dm, dens)
    a = {r["file"]: r for r in alt.to_dict("records")}
    for col, key in (("_nI", "n_I"), ("_dur", "duration_s")):
        cc[col] = cc["file"].map(lambda f, k=key: float(a[f][k]) if f in a and pd.notna(a[f][k]) else np.nan).astype(float)
    per = cc["I_sample_period_s"] if "I_sample_period_s" in cc.columns else pd.Series(np.nan, index=cc.index)
    cc["_fast"] = np.where(per.notna(), (per < D.POWERFADE_FAST_S).astype(float), np.nan)
    dt0 = pd.to_datetime(cc["date"]).min()
    t_all = ((pd.to_datetime(cc["date"]) - dt0).dt.days / MONTH_DAYS).values
    cc = cc.assign(_t=t_all)
    finite = lambda c: np.isfinite(cc[c].values.astype(float))
    ok_dens = finite("_de") & finite("_dc")
    common = ok_dens & finite("_nI") & finite("_dur") & (cc["_dur"].values > 0) & finite("_fast")
    seeds = [SEED_READING] + SEEDS_EXTRA
    base = cc[ok_dens]                                           # E0's own set (the published S1 set)
    com = cc[common]
    res = {}
    e0_own = fit_spec("E0", base, base["_t"].values, seeds, n_boot)
    differs = bool(len(com) != len(base) or com["date"].nunique() != base["date"].nunique())
    for sid in SPEC_IDS:
        res[sid] = fit_spec(sid, com, com["_t"].values, seeds, n_boot)
    for sid, r in res.items():
        st, band = three_state(r["ci95"][0], r["ci95"][1], r["lowerEndpointRange"], r["upperEndpointRange"])
        r["reading"], r["seedNoiseBand"] = st, band
        for k in ("slope",):
            r[k] = round(r[k], 4)
        r["ci95"] = [round(x, 4) for x in r["ci95"]]
    e0_own["slope"] = round(e0_own["slope"], 4)
    e0_own["ci95"] = [round(x, 4) for x in e0_own["ci95"]]
    st0, band0 = three_state(e0_own["ci95"][0], e0_own["ci95"][1], e0_own["lowerEndpointRange"], e0_own["upperEndpointRange"])
    e0_own["reading"], e0_own["seedNoiseBand"] = st0, band0
    ref = res["E0"]["reading"]
    differ = [s for s in SPEC_IDS if s != "E0" and res[s]["reading"] != ref]
    K = len(SPEC_IDS) - 1
    if not differ:
        sentence = "All %d alternative or reduced specifications have the same reading as the published specification." % K          # the frozen R2 template (Director M723 decision: no parenthetical)
    else:
        sentence = "The reading of the published specification is definition-dependent (%d of %d alternative or reduced specifications differ)." % (len(differ), K)
    facts = descriptive_facts(res, seeds)
    return {"method": "M723", "spec": SPEC, "specSha256": spec_sha, "definitions": definitions(),
            "counts": {"cleanCompleteCases": int(len(cc)), "densityResolved": int(ok_dens.sum()), "alternativeResolved": int((finite("_nI") & finite("_dur") & (cc["_dur"].values > 0)).sum()), "commonSet": int(len(com)),
                       "commonSetDays": int(com["date"].nunique())},
            "distributions": {"effDtS": _stat(com["_de"]), "coverageFrac": _stat(com["_dc"]), "effDtSByRegime": {"fast": _stat(com.loc[com["_fast"] == 1.0, "_de"]), "slow": _stat(com.loc[com["_fast"] == 0.0, "_de"])},
                              "coverageFracByRegime": {"fast": _stat(com.loc[com["_fast"] == 1.0, "_dc"]), "slow": _stat(com.loc[com["_fast"] == 0.0, "_dc"])}},
            "specificationSensitivity": {"reading": "estimated resistance proxy trend, model-derived; includes zero = trend not established; E0 stays the only published reading; no fade rate",
                                          "drawsPerSeed": int(n_boot), "seedForReading": SEED_READING, "seedsForEndpointSpread": SEEDS_EXTRA, "bandRule": "max(%.1f, 2 x the 9-seed range of the endpoint nearest to zero), mOhm/month" % BAND_FLOOR,
                                          "commonSet": {"nDrives": int(len(com)), "nDays": int(com["date"].nunique()), "e0OwnSet": {"nDrives": int(len(base)), "nDays": int(base["date"].nunique())}, "differsFromE0OwnSet": differ_flag(differs),
                                                        "e0OnOwnSet": e0_own},
                                          "specs": res, "descriptiveFacts": facts, "nDifferInReading": len(differ), "differingSpecs": differ, "K": K, "sentence": sentence,
                                          "postHocDisclosure": "A1 and A2 were chosen after the blind audit of M721 had rebuilt the coverage covariate two ways (events / duration and events x period / duration); A0, A3, A4 and A5 anchor the set"}}


def descriptive_facts(res, seeds):
    """Leaf additions made after the result (Director M723 decision; stated post-result deviation, descriptive, no change to the frozen rule or the reading labels): for the published specification the number of the pre-listed seeds whose lower
    endpoint is below zero, the across-specification ranges of the slope and of the seed-42 lower endpoint, and the plain percentile reading at seed 42 (the interval's own zero test, no band) per specification."""
    e0 = res["E0"]
    lows = [x for x in e0["lowerEndpointBySeed"]]
    sl = [r["slope"] for r in res.values()]
    lo = [r["ci95"][0] for r in res.values()]
    return {"e0LowerEndpointBelowZero": {"nSeeds": int(sum(1 for x in lows if x < 0.0)), "ofSeeds": int(len(lows)), "seeds": list(seeds), "seed42LowerEndpoint": e0["ci95"][0],
                                         "reading": "number of the pre-listed seeds whose lower endpoint of the published specification is below zero; seed 42 is the published seed"},
            "acrossSpecifications": {"slopeMin": round(min(sl), 4), "slopeMax": round(max(sl), 4), "lowerEndpointMinSeed42": round(min(lo), 4), "lowerEndpointMaxSeed42": round(max(lo), 4)},
            "plainPercentileReadingSeed42": {k: ("excludesZero" if (r["ci95"][0] > 0.0 or r["ci95"][1] < 0.0) else "includesZero") for k, r in res.items()},
            "bandPermissiveness": "the frozen seed-noise band is permissive (it is at least twice the 9-seed endpoint range); it resolves bootstrap Monte Carlo error only, not statistical indistinguishability; the plain percentile readings above are descriptive and not a decision"}


def differ_flag(b):
    return bool(b)


def _word(r):
    return {"includesZero": "the interval includes zero: trend not established", "excludesZero": "the interval excludes zero, not read as fade", "withinSeedNoiseOfZero": "an endpoint lies within seed noise of zero"}[r]


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


def _paths(a, b, p=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(p + "/" + k)
            else:
                out += _paths(a[k], b[k], p + "/" + k)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += _paths(x, y, "%s[%d]" % (p, i))
    elif a != b:
        out.append(p)
    return out


def splice(A, blk):
    new = copy.deepcopy(A)
    new["powerFade"]["cadenceCovariates"] = blk
    ch = _paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A0 = json.loads(raw)
    if "--check" in argv:
        alt = _read(SIDECAR_ALT)
    else:
        import ah_throughput as AH
        alt = build_alt(dm, AH.raw_loader(), AH.manifest_sha_lookup())
    prod = _read(SIDECAR_PROD)
    spec_sha = hashlib.sha256(open(SPEC, "rb").read()).hexdigest()
    blk = _clean(compute_block(dm, prod, alt, spec_sha))
    blk["sidecars"] = {"production": {"file": "powerfade_density.csv", "sha256": hashlib.sha256(open(SIDECAR_PROD, "rb").read()).hexdigest(), "rows": int(len(prod)), "methodVersion": 1},
                       "alternative": {"file": "powerfade_density_alt.csv", "sha256": hashlib.sha256(open(SIDECAR_ALT, "rb").read()).hexdigest(), "rows": int(len(alt)), "methodVersion": METHOD_VERSION}}
    # R1: the published S1 numbers must not move
    pf = A0["powerFade"]
    e0 = blk["specificationSensitivity"]["commonSet"]["e0OnOwnSet"]
    if e0["nDrives"] != pf["nClean"] or abs(e0["slope"] - pf["slopeMohmPerMoTctrl"]) > 0.002:
        print("STOP: E0 on its own set (n %s, slope %s) does not reproduce the published S1 (n %s, slope %s)" % (e0["nDrives"], e0["slope"], pf["nClean"], pf["slopeMohmPerMoTctrl"]))
        return 1
    if "--check" in argv:
        have = pf.get("cadenceCovariates")
        bad = have != blk
        print(json.dumps({"check": "powerFade.cadenceCovariates", "matchesPayload": not bad, "nDifferInReading": blk["specificationSensitivity"]["nDifferInReading"]}))
        return 1 if bad else 0
    new, changed, bad = splice(A0, blk)
    print(json.dumps({"nChanged": len(changed), "outsideAllowList": bad, "nDifferInReading": blk["specificationSensitivity"]["nDifferInReading"], "sentence": blk["specificationSensitivity"]["sentence"]}))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
