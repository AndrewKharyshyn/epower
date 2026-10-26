#!/usr/bin/env python3
"""M512 (analyses/M512_spec.md Rev 2, pre-registered; audit 2026-10-25 A04): engine runtime on a declared time base.
`engine_on_pct` (master) is the engine-on share of the RPM-SUPPORTED, gap-capped interval time; the legacy `engineOnHours` multiplies it by the full elapsed duration. This tool stores, per drive and
from the production helpers (compute_drive_summary_v6._prep_bytes / _series / _tw_stats; no reimplementation), the RPM-supported seconds and the engine-on seconds inside them
(sidecar engine_runtime_sidecar.csv, keyed by raw sha256 + method version + the M498 closure hash) and writes the additive payload block `engineRuntime` (+ stamp):
supported on-time, RPM-supported time, elapsed time, unsupported time, the hard bracket [supportedOn, supportedOn + unsupported] and the duration-scaled (imputed) figure inside it.
Controls (STOP, nothing written): C0 every drive's unrounded on/supported share equals the master engine_on_pct within 0.05 + 1e-9; the recomputed legacy corpus figure equals the stored
meta.engineOnHours; the sidecar covers every master drive. Hour totals are exact over the declared population (no interval); the per-10,000 km rates carry a day-clustered ratio-of-sums
percentile bootstrap (seed 42, 4000 draws). Never writes drive_master.csv or raw files.
Usage: python tools/engine_runtime.py [--check] [--dry-run]   (--check is read-only and needs no raw files)"""
import copy, datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p_ not in sys.path:
        sys.path.insert(0, p_)

METHOD_VERSION = 1
SIDECAR = os.path.join(ROOT, "engine_runtime_sidecar.csv")
COLS = ["file", "date", "rpm_supported_s", "engine_on_s", "elapsed_s", "raw_sha256", "method_version", "reason"]
CLASS_ORDER = ["urban", "mixed", "mixed_highway", "highway"]     # equals compute_summary_arrays.CLASS_ORDER (checked in tests/synthetic/test_engine_runtime.py); no import of the 17k-line builder here


def _cond_class(drive_type):
    return drive_type if drive_type in CLASS_ORDER else None


def _canonical_bad(dm):
    """ens_invalid or ens_outlier_v2 is True; a missing flag is not excluded (the builder's convention, compute_summary_arrays._canonical_bad)."""
    b = lambda s: s.map(lambda x: x is True or str(x).strip().lower() == "true").astype(bool)
    return b(dm["ens_invalid"]) | b(dm["ens_outlier_v2"])


ALLOWED = ["/engineRuntime", "/_artifactStamps/engineRuntime"]
RPM_ON = 400.0
PCT_TOL = 0.05 + 1e-9
N_BOOT, SEED = 4000, 42
MIN_CLASS_DAYS, MIN_CLASS_DRIVES = 10, 20          # M517: a class with fewer days has no interval; fewer drives is flagged
STATEMENT = ("Engine-on time inside RPM-supported intervals (eng_rpm > 400: the engine is rotating, not necessarily fuelled), the RPM-supported time and the elapsed time, per the declared population. "
             "Time without RPM support is unsupported: the engine state there is unknown, so the engine-rotating time over the elapsed span lies between the supported on-time and the supported on-time plus the unsupported time. "
             "The duration-scaled figure assumes the same engine-on share in the unsupported time (imputed).")


def runtime_from_bytes(b):
    """(rpm_supported_s, engine_on_s, reason) of one drive by the production helpers; (nan, nan, reason) when the drive has no usable RPM series."""
    import compute_drive_summary_v6 as D
    df, t = D._prep_bytes(b)
    eng = D._series(df, t, "eng_rpm", lo=0)
    if eng is None or len(eng) <= 2:
        return np.nan, np.nan, "no_rpm_series"
    w = D._tw_stats(eng)
    return float(w.sum()), float(w[eng["v"] > RPM_ON].sum()), None


def _read(path):
    return pd.read_csv(path, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""])


def _fnum(v):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v)


def build_sidecar(master, loader, sha_lookup=None, path=SIDECAR):
    """One row per master drive (master order). A stored row is reused when its raw sha256, the method version and the closure hash are unchanged; a raw_file_missing row is never reused."""
    import dep_hash
    import compute_drive_summary_v6 as _D
    code = dep_hash.closure_hash([runtime_from_bytes], modules=(sys.modules[__name__], _D), extra={"method": METHOD_VERSION})
    code_ok = dep_hash.sidecar_code_ok(path, code)
    old = {r["file"]: r for r in _read(path).to_dict("records")} if os.path.exists(path) else {}
    rows = []
    for _, m in master.iterrows():
        f, date, el = str(m["file"]), str(m.get("date", "")), float(m["duration_s"])
        prev = old.get(f)
        ok_prev = code_ok and prev is not None and prev.get("method_version") == METHOD_VERSION and prev.get("reason") != "raw_file_missing" and abs(float(prev["elapsed_s"]) - el) < 1e-6
        sha = sha_lookup(f) if sha_lookup else None
        if ok_prev and sha and prev.get("raw_sha256") == sha:
            rows.append({k: prev.get(k) for k in COLS}); continue
        b = loader(f)
        if b is None:
            rows.append({"file": f, "date": date, "rpm_supported_s": None, "engine_on_s": None, "elapsed_s": el, "raw_sha256": None, "method_version": METHOD_VERSION, "reason": "raw_file_missing"}); continue
        h = hashlib.sha256(b).hexdigest()
        if ok_prev and prev.get("raw_sha256") == h:
            rows.append({k: prev.get(k) for k in COLS}); continue
        sup, on, why = runtime_from_bytes(b)
        rows.append({"file": f, "date": date, "rpm_supported_s": _fnum(sup), "engine_on_s": _fnum(on), "elapsed_s": el, "raw_sha256": h, "method_version": METHOD_VERSION, "reason": why})
    out = pd.DataFrame(rows, columns=COLS)
    out.to_csv(path, index=False, lineterminator="\n", float_format="%.12g")
    dep_hash.sidecar_code_write(path, code)
    return _read(path)


def _dayboot_ratio(num, den, days, nb=N_BOOT, seed=SEED):
    """Day-clustered ratio-of-sums percentile bootstrap (calendar day = cluster)."""
    num, den, days = np.asarray(num, float), np.asarray(den, float), np.asarray(days)
    uniq = np.unique(days)
    idx = {d: np.where(days == d)[0] for d in uniq}
    rng = np.random.default_rng(seed)
    v = []
    for _ in range(nb):
        s = rng.choice(uniq, len(uniq), replace=True)
        ii = np.concatenate([idx[d] for d in s])
        dd = den[ii].sum()
        if dd > 0:
            v.append(num[ii].sum() / dd)
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))], int(len(uniq))


def _totals(g):
    """Exact totals over a drive set; `g` carries sup/on/elapsed seconds, pct, distance."""
    has = g["rpm_supported_s"].notna()
    h = g[has]
    sup_h, on_h = h["rpm_supported_s"].sum() / 3600, h["engine_on_s"].sum() / 3600
    el_all, el_rpm = g["elapsed_s"].sum() / 3600, h["elapsed_s"].sum() / 3600
    imputed = (h["elapsed_s"] * h["engine_on_pct"] / 100).sum() / 3600
    unsupported = el_all - sup_h
    km_all, km_rpm = float(g["distance_km"].sum()), float(h["distance_km"].sum())
    return {"nDrives": int(len(g)), "nDrivesWithRpm": int(has.sum()), "nDrivesWithoutRpm": int((~has).sum()),
            "supportedOnHours": on_h, "supportedHours": sup_h, "elapsedHours": el_all, "elapsedHoursWithRpm": el_rpm, "unsupportedHours": unsupported,
            "bracketHours": [on_h, on_h + unsupported], "scaledImputedHours": imputed,
            "imputationAddHours": imputed - on_h, "imputationAddPctOfSupportedOn": (imputed - on_h) / on_h * 100 if on_h > 0 else None,
            "supportedOnShareOfSupported": on_h / sup_h if sup_h > 0 else None, "kmWithRpm": km_rpm, "kmAll": km_all,
            "supportedOnPer10kKm": on_h / km_rpm * 10000 if km_rpm > 0 else None, "scaledImputedPer10kKm": imputed / km_rpm * 10000 if km_rpm > 0 else None}


def compute_block(dm, side, legacy_hours):
    d = dm.merge(side[["file", "rpm_supported_s", "engine_on_s"]], on="file", how="left")
    d["elapsed_s"] = d["duration_s"].astype(float)
    sf = side.set_index("file")
    nan_files = d.loc[d["rpm_supported_s"].isna(), "file"]
    if len(d) != len(dm) or set(dm["file"]) - set(sf.index) or not sf.reindex(nan_files)["reason"].notna().all():
        raise SystemExit("STOP: sidecar does not cover every master drive with a value or a reason")
    # C0: per-drive share
    h = d[d["rpm_supported_s"].notna() & (d["rpm_supported_s"] > 0)]
    diff = (h["engine_on_s"] / h["rpm_supported_s"] * 100 - h["engine_on_pct"]).abs()
    bad = h.loc[diff > PCT_TOL, "file"].tolist()
    miss = d.loc[d["rpm_supported_s"].isna() & d["engine_on_pct"].notna() & ~d["file"].isin(side.loc[side["reason"] == "no_rpm_series", "file"]), "file"].tolist()
    if bad or miss:
        raise SystemExit("STOP: C0 failed (%d drives differ from engine_on_pct, %d with a pct but no sidecar value): %s" % (len(bad), len(miss), (bad + miss)[:6]))
    legacy = float((d["duration_s"] * d["engine_on_pct"] / 100).sum(skipna=True)) / 3600
    if round(legacy, 1) != round(float(legacy_hours), 1):
        raise SystemExit("STOP: recomputed legacy corpus figure %.4f differs from the stored meta.engineOnHours %s" % (legacy, legacy_hours))
    d["dclass"] = d["drive_type"].apply(_cond_class)
    pop = _totals(d)
    pop["legacyEngineOnHours"] = legacy                       # numerator skips drives without a pct, as the legacy formula does
    rate_ci = {}
    hh = d[d["rpm_supported_s"].notna()]
    for key, num in (("supportedOnPer10kKm", hh["engine_on_s"] / 3600), ("scaledImputedPer10kKm", hh["elapsed_s"] * hh["engine_on_pct"] / 100 / 3600)):
        ci, nd = _dayboot_ratio(num.values * 10000, hh["distance_km"].values, hh["date"].astype(str).values)
        rate_ci[key] = {"ci95": ci, "nDays": nd, "method": "day-clustered ratio-of-sums percentile bootstrap, seed 42, 4000 draws"}
    clean_files = set(dm.loc[~_canonical_bad(dm), "file"])      # the builder's convention (a missing flag is not excluded): the same clean set as the legacy class avgEngineOnPct
    classes = []
    for k in CLASS_ORDER:
        g = d[d["dclass"] == k]
        t = _totals(g)
        t["key"] = k
        t["avgEngineOnPctCleanSet"] = round(float(g[g["file"].isin(clean_files)]["engine_on_pct"].mean()), 1) if g["file"].isin(clean_files).any() else None
        # M517 (analyses/M517_spec.md Rev 1): day-clustered interval of the per-class rates (same bootstrap as the corpus rate); fewer than 10 days -> no interval, fewer than 20 drives -> flagged
        gr = g[g["rpm_supported_s"].notna()]
        nd_ = int(gr["date"].astype(str).nunique())
        t["nDaysWithRpm"], t["fewDays"], t["fewDrives"] = nd_, bool(nd_ < MIN_CLASS_DAYS), bool(int(len(gr)) < MIN_CLASS_DRIVES)
        for key, num in (("supportedOnPer10kKmCi95", gr["engine_on_s"] / 3600), ("scaledImputedPer10kKmCi95", gr["elapsed_s"] * gr["engine_on_pct"] / 100 / 3600)):
            if nd_ < MIN_CLASS_DAYS or float(gr["distance_km"].sum()) <= 0:
                t[key] = None
            else:
                t[key] = _dayboot_ratio(num.values * 10000, gr["distance_km"].values, gr["date"].astype(str).values)[0]
        classes.append(t)
    return {"methodVersion": METHOD_VERSION, "spec": "analyses/M512_spec.md (Rev 2); per-class rate intervals analyses/M517_spec.md (Rev 1)", "statement": STATEMENT,
            "population": "all master drives (unfiltered exposure total; the legacy corpus-total convention)",
            "timeBase": "supported = native-timestamp steps of the eng_rpm series capped at the production DT_CAP_S; elapsed = master duration_s; unsupported = elapsed - supported (includes drives without an RPM series)",
            "totals": pop, "rateIntervals": rate_ci, "byClass": classes, "unclassified": _totals(d[d["dclass"].isna()]),
            "cleanSensitivity": _totals(d[d["file"].isin(clean_files)]),
            "drivesWithoutRpm": d.loc[d["rpm_supported_s"].isna(), "file"].tolist(),
            "limits": "eng_rpm > 400 means rotating, not fuelled; the supported-basis rate uses the whole-elapsed distance of drives with an RPM series (a lower bound of the elapsed-time rate); totals are exact over the declared population, not estimates of a larger one",
            "basis": "raw/ = sha256-verified originals (M366)"}


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 4)
    if isinstance(o, np.integer):
        return int(o)
    return o


def _paths(a, b, p=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [x for k in sorted(set(a) | set(b)) for x in (_paths(a.get(k), b.get(k), "%s/%s" % (p, k)) if (k in a and k in b) else ["%s/%s" % (p, k)])]
    return [] if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else [p]


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new["engineRuntime"] = blk
    old = (A.get("_artifactStamps") or {}).get("engineRuntime")
    coherent = old and old.get("includedInReleaseAt") == old.get("computedAt") == old.get("generatedAt")
    if old and coherent and A.get("engineRuntime") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["engineRuntime"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M512: derived by tools/engine_runtime.py from drive_master.csv and the tracked engine_runtime_sidecar.csv (RPM-supported time base; analyses/M512_spec.md)",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        import stamp_common as _sc
        new["_artifactStamps"]["engineRuntime"] = _sc.carry_declared(old, st)      # M518: keep the declared-dependency lineage
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
        side = build_sidecar(dm, AH.raw_loader(), AH.manifest_sha_lookup())
    blk = _clean(compute_block(dm, side, A0["meta"]["engineOnHours"]))
    blk["sidecar"] = {"file": "engine_runtime_sidecar.csv", "sha256": hashlib.sha256(open(SIDECAR, "rb").read()).hexdigest(), "rows": int(len(side))}
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    if "--check" in argv:
        bad = A0.get("engineRuntime") != blk
        print(json.dumps({"check": "engineRuntime", "matchesPayload": not bad}))
        return 1 if bad else 0
    new, changed, bad = splice(A0, blk, md5)
    print(json.dumps({"nChanged": len(changed), "outsideAllowList": bad, "totals": blk["totals"]}, default=float))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
