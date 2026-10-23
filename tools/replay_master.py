#!/usr/bin/env python3
"""M417 (audit F11, owner decision 2026-10-12): pinned replay of drive_master.csv from the raw drive files, in a clean process, never writing the master.

Scope (what is replayed and what is frozen; the honest statement, see analyses/M417_spec.md):
  * RAW-DERIVED columns = deterministic functions of one raw file and the versioned builder (compute_drive_summary_v6.analyze_bytes): replayed per drive.
  * MASTER-LEVEL columns = postprocess_master over the whole corpus, which REFITS the machine-learning columns (ML16, a frozen historic fit): the replay applies the same freeze/restore as an ingestion
    (tools/ingest_core.py: ML16 values of pre-existing rows are restored from the published master, then the Huber adjustment is re-applied) and compares everything else.
  * MANUAL / REPAIRED columns that no builder produces (distance repairs, ledgers) are listed as published-only; they are not replayed.
Two tiers:
  --sample   (default, seconds, in CI / release_check): the pinned sample of drives in analyses/replay/replay_sample.json: analyze_bytes on the raw file (sha256-checked against raw_manifest.json) must reproduce
             every column it produces to 1e-9 (strings, flags and null patterns exactly), except the registered exceptions in analyses/replay/replay_expected.json.
  --full     (about 10 minutes, on demand and before a release that touches the builder): rebuild every drive, postprocess, restore ML16, Huber-adjust, compare every column of every row with the published master.
Both write a report (analyses/replay/replay_report_<tier>.json) that records the environment (python and package versions), the code hashes, the raw_manifest sha256 and the published master MD5.
Usage: python tools/replay_master.py [--sample|--full] [--raw-dir DIR] [--workers N] [--make-sample] [--no-write]"""
import datetime as dt, hashlib, json, os, platform, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
TOL = 1e-9
D = os.path.join(ROOT, "analyses", "replay")
SAMPLE = os.path.join(D, "replay_sample.json")
EXPECTED = os.path.join(D, "replay_expected.json")


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def environment():
    import scipy, sklearn
    return {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__, "sklearn": sklearn.__version__, "platform": platform.system()}


def code_hashes():
    return {f: sha256(os.path.join(ROOT, f))[:16] for f in ("compute_drive_summary_v6.py", "tools/ingest_core.py", "drive_raw_cache.py") if os.path.exists(os.path.join(ROOT, f))}


def raw_dir_default():
    for n in ("raw_only", "raw"):
        d = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, n)
        if os.path.isdir(d):
            return d
    raise SystemExit("no raw directory (raw_only/ or raw/): pass --raw-dir")


_IDX = {}


def resolve(raw_dir, key):
    """raw_only/ (staged view) is named by master key; raw/ is named by the phone export: fall back to the digits of the name (tools/ingest_core.raw_index)."""
    p = os.path.join(raw_dir, key)
    if os.path.exists(p):
        return p
    import ingest_core as IC
    if raw_dir not in _IDX:
        _IDX[raw_dir] = IC.raw_index(raw_dir)
    q = _IDX[raw_dir].get(IC.digits(key))
    if q is None:
        raise SystemExit("no raw file for master key %s in %s" % (key, raw_dir))
    return q


_MAN = {}


def verify_raw_identity(path, key, files=None):
    """M427 (audit F02): the raw file must be the manifest's byte-identical record before anything is replayed. Exactly one manifest record for the master key,
    role canonical, full sha256 equal; a missing, duplicate, non-canonical or mismatched record raises (a changed unused channel used to pass the replay silently)."""
    if files is None:
        if "files" not in _MAN:
            _MAN["files"] = json.load(open(os.path.join(ROOT, "raw_manifest.json"), encoding="utf-8"))["files"]
        files = _MAN["files"]
    names = {key, key.replace(" ", "_")}
    recs = [r for r in files if names & {r.get("canonical"), r.get("record_id"), r.get("raw_name")}]
    if len(recs) != 1:
        raise RuntimeError("raw identity: %d manifest records for %s (need exactly 1)" % (len(recs), key))
    if recs[0].get("role") != "canonical":
        raise RuntimeError("raw identity: manifest role of %s is %r, not canonical" % (key, recs[0].get("role")))
    got = sha256(path)
    if got != recs[0].get("sha256"):
        raise RuntimeError("raw identity: sha256 of %s (%s) differs from its raw_manifest.json record (%s)" % (key, got[:16], str(recs[0].get("sha256"))[:16]))
    return got


def analyze(v6, raw_dir, key):
    p = resolve(raw_dir, key)
    verify_raw_identity(p, key)
    with open(p, "rb") as f:
        r = v6.analyze_bytes(f.read(), key)
    d, tm = v6._date_from_name(p)
    r.setdefault("date", d)
    r.setdefault("time_start", r.get("time_start") or tm)
    return r


def _is_num(v):
    return isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, (bool, np.bool_))


def differs(a, b):
    """True if the rebuilt value a and the published value b differ (null patterns exactly, numbers to TOL, everything else as text)."""
    an, bn = (a is None or (isinstance(a, float) and np.isnan(a))), (b is None or (isinstance(b, float) and np.isnan(b)))
    if an or bn:
        return an != bn
    if _is_num(a) and _is_num(b):
        return abs(float(a) - float(b)) > TOL + TOL * abs(float(b))
    return str(a) != str(b)


def load_expected():
    return json.load(open(EXPECTED, encoding="utf-8")) if os.path.exists(EXPECTED) else {"sample": {"allowedDifferences": {}}, "full": {"publishedOnlyColumns": [], "allowedDifferences": {}}}


def make_sample(dm, n=24, seed=417):
    """Deterministic stratified sample: per (drive_type, month) group the drive with the smallest sha256(seed + file); then the first n by hash order across groups (every group represented first)."""
    dm = dm.copy()
    dm["_grp"] = dm["drive_type"].astype(str) + "|" + dm["date"].astype(str).str[:7]
    dm["_h"] = dm["file"].map(lambda f: hashlib.sha256(("%d|%s" % (seed, f)).encode()).hexdigest())
    firsts = dm.sort_values("_h").groupby("_grp", sort=True).head(1)
    rest = dm[~dm["file"].isin(firsts["file"])].sort_values("_h")
    keys = list(firsts.sort_values("_h")["file"]) + list(rest["file"])
    return keys[:n]


def tier_sample(args):
    import compute_drive_summary_v6 as v6
    dm = pd.read_csv("drive_master.csv", low_memory=False).set_index("file", drop=False)
    keys = json.load(open(SAMPLE, encoding="utf-8"))["files"]
    man = json.load(open("raw_manifest.json", encoding="utf-8"))
    raw_dir = args["raw_dir"]
    exp = load_expected()["sample"]["allowedDifferences"]
    rows, bad = [], []
    for k in keys:
        p = resolve(raw_dir, k)
        rec = {"file": k}
        r = analyze(v6, raw_dir, k)
        pub = dm.loc[k]
        diffs = sorted(c for c in r if c in dm.columns and differs(r[c], pub[c]))
        extra = sorted(c for c in r if c not in dm.columns)
        rec.update(nColumnsReplayed=int(sum(1 for c in r if c in dm.columns)), differing=diffs, columnsNotInMaster=extra, rawSha256=sha256(p)[:16])
        unexpected = [c for c in diffs if c not in exp or (exp[c].get("files") and k not in exp[c]["files"])]
        if unexpected:
            bad.append({"file": k, "unexpectedDifferences": unexpected})
        rows.append(rec)
    return {"tier": "sample", "nDrives": len(keys), "perDrive": rows, "unexpected": bad, "ok": not bad}


def tier_full(args):
    import compute_drive_summary_v6 as v6
    import ingest_core as IC
    pub_raw = pd.read_csv("drive_master.csv", low_memory=False)
    keys = list(pub_raw["file"].astype(str))
    raw_dir, workers = args["raw_dir"], args["workers"]
    t0 = time.time()
    if workers > 1:
        from multiprocessing import Pool
        with Pool(workers) as pl:
            rows = pl.starmap(analyze_worker, [(raw_dir, k) for k in keys], chunksize=4)
    else:
        rows = [analyze(v6, raw_dir, k) for k in keys]
    dm = pd.DataFrame(rows).sort_values(["date", "time_start"], kind="stable").reset_index(drop=True)
    out = v6.postprocess_master(dm, verbose=False)
    dm = out[0] if isinstance(out, tuple) else out
    # freeze / restore exactly as an ingestion does (tools/ingest_core.step1_master), then the Huber adjustment on the restored ens_outlier_v2
    old = pub_raw.set_index("file")
    for c in IC.ML16:
        if c in dm.columns and c in old.columns:
            dm[c] = old[c].reindex(dm["file"]).values
    dm, _ = v6.m19b_huber_adjust(dm)
    # compare through CSV text (what lands on disk), as the ingestion gate does
    tmp = os.path.join(ROOT, "runs", "_replay_tmp_master.csv")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    dm.to_csv(tmp, index=False)
    chk = pd.read_csv(tmp, low_memory=False, dtype=str, keep_default_na=False).set_index("file")
    os.remove(tmp)
    ref = pd.read_csv("drive_master.csv", low_memory=False, dtype=str, keep_default_na=False).set_index("file")
    only_pub = sorted(set(ref.columns) - set(chk.columns))
    only_reb = sorted(set(chk.columns) - set(ref.columns))
    common = [c for c in ref.columns if c in chk.columns]
    chk = chk.loc[ref.index]
    cls = {}
    for c in common:
        a, b = ref[c], chk[c]
        ne = a != b
        if ne.any():
            # numeric comparison to TOL before counting a text difference (the CSV text of a float can differ in the last digit)
            an, bn = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
            numeric = an.notna().all() or (an.notna() == bn.notna()).all() and an.notna().any()
            if numeric:
                nullmis = int((an.isna() != bn.isna()).sum())
                both = an.notna() & bn.notna()
                d = (an[both] - bn[both]).abs()
                nd = int((d > TOL + TOL * an[both].abs()).sum())
                if nd or nullmis:
                    bad_rows = (an.isna() != bn.isna()) | (both & ((an - bn).abs() > TOL + TOL * an.abs()))      # M489 (audit A07): the exact differing rows, every one of them
                    fa = sorted(map(str, ref.index[bad_rows]))
                    cls[c] = {"nRowsDiffer": nd, "nNullPatternMismatch": nullmis, "maxAbsDiff": float(d.max()) if len(d) else 0.0, "files": fa[:12], "filesAll": fa}
            else:
                fa = sorted(map(str, ref.index[ne]))
                cls[c] = {"nRowsDiffer": int(ne.sum()), "nNullPatternMismatch": int(((a == "") != (b == "")).sum()), "maxAbsDiff": None, "files": fa[:12], "filesAll": fa}
    files_diff = sorted({f for c in cls for f in cls[c]["filesAll"]})
    ident = identities(ref, chk, cls)
    return {"tier": "full", "nRowsPublished": int(len(ref)), "nRowsRebuilt": int(len(chk)), "publishedOnlyColumns": only_pub, "rebuiltOnlyColumns": only_reb, "nColumnsCompared": len(common),
            "nColumnsIdentical": len(common) - len(cls), "columnsDiffering": cls, "nFilesWithAnyDifference": len(files_diff), "filesWithAnyDifference": files_diff[:60], "identities": ident, "seconds": round(time.time() - t0, 1)}


ID_TOL = 2.5e-4      # three 4-decimal roundings (offset, net_draw, residual) can each move a value by 5e-5


def identities(ref, chk, cls):
    """M489 (audit A07): the registered exceptions are identities of the frozen transforms, not caps. Evaluated on ALL rows of the replay (published `ref` and rebuilt `chk`, text frames indexed by file):
    (1) frozen offset: the published two-pass offset is ONE constant I_pub; the rebuild refits I_reb; for every row with a non-null published offset the rebuilt minus published value of offset_2p_kwh_removed equals
        (I_reb - I_pub) x V_pack_median x h / 1000 (h = integr_time_h, else duration_s / 3600) and of net_draw_kwh_corr2p and energy_residual_kwh_corr2p equals its negative, within ID_TOL;
    (2) distance: for every row published with distance_reset_repaired true, the rebuilt distance_km equals the published distance_endpoint_raw_km (the builder alone returns the endpoint value);
    and every row that differs in a distance-derived column is a repaired row. Returns counts and the failing files; an empty failure list is the claim."""
    out = {"toleranceKwh": ID_TOL}
    num = lambda df, c: pd.to_numeric(df[c], errors="coerce")
    ip, ir = num(ref, "I_offset_2p_A_applied"), num(chk, "I_offset_2p_A_applied")
    pub_vals, reb_vals = sorted(set(ip.dropna().round(6))), sorted(set(ir.dropna().round(6)))
    out["publishedOffsetValues"], out["rebuiltOffsetValues"] = pub_vals, reb_vals
    fails = {}
    if len(pub_vals) == 1 and len(reb_vals) == 1:
        dI = reb_vals[0] - pub_vals[0]
        V = num(ref, "V_pack_median")
        h = num(ref, "integr_time_h").fillna(num(ref, "duration_s") / 3600.0)
        elig = ip.notna() & V.notna() & h.notna()
        exp_off = dI * V * h / 1000.0
        for c, sign in (("offset_2p_kwh_removed", 1.0), ("net_draw_kwh_corr2p", -1.0), ("energy_residual_kwh_corr2p", -1.0)):
            if c not in ref.columns or c not in chk.columns:
                fails[c] = ["column missing"]
                continue
            d = num(chk, c) - num(ref, c)
            nanmis = (num(chk, c).isna() != num(ref, c).isna()) & elig
            bad = elig & ((d - sign * exp_off).abs() > ID_TOL)
            fails[c] = sorted(map(str, ref.index[bad | nanmis]))
        # per-100-km column: rebuilt - published = -(offset delta) / distance x 100 on the NON-repaired rows (2-decimal rounding of both values)
        if "net_draw_per100km_corr2p" in ref.columns and "distance_reset_repaired" in ref.columns:
            repaired = ref["distance_reset_repaired"].astype(str).str.lower().isin(("true", "1"))
            dist = num(ref, "distance_km")
            c = "net_draw_per100km_corr2p"
            ok_rows = elig & ~repaired & (dist > 0)
            dd = num(chk, c) - num(ref, c)
            bad = ok_rows & ((dd + exp_off / dist * 100.0).abs() > 0.011)
            nanmis = (num(chk, c).isna() != num(ref, c).isna()) & ok_rows
            fails[c] = sorted(map(str, ref.index[bad | nanmis]))
        out["offsetDeltaA"], out["nOffsetRows"] = round(dI, 6), int(elig.sum())
    else:
        fails["offsetConstant"] = ["published or rebuilt offset is not a single constant: %r / %r" % (pub_vals, reb_vals)]
    out["offsetIdentityFailures"] = fails
    if "distance_reset_repaired" in ref.columns:
        rep_mask = ref["distance_reset_repaired"].astype(str).str.lower().isin(("true", "1"))
    else:
        rep_mask = pd.Series(False, index=ref.index)
    out["repairedFiles"] = sorted(map(str, ref.index[rep_mask]))
    dfail = []
    if rep_mask.any():
        e = num(ref, "distance_endpoint_raw_km")[rep_mask]
        r = num(chk, "distance_km")[rep_mask]
        dfail = sorted(map(str, ref.index[rep_mask][(e - r).abs().fillna(float("inf")) > 1e-6]))
    out["distanceIdentityFailures"] = dfail
    dcols = [c for c in cls if c in ("distance_km", "net_draw_per100km", "net_draw_per100km_corr")]      # the columns registered for the repaired row only (the corr2p column also follows the offset: checked above)
    out["distanceDerivedOutsideRepaired"] = sorted({f for c in dcols for f in cls[c]["filesAll"] if f not in set(out["repairedFiles"])})
    return out


def check_expected(rep):
    """-> list of unexpected findings (empty = the replay equals the registered expectation: only the registered columns differ, within their row / difference / file caps)."""
    exp = load_expected()["full"]
    bad = []
    if rep["publishedOnlyColumns"] != sorted(exp["publishedOnlyColumns"]):
        bad.append({"publishedOnlyColumns": rep["publishedOnlyColumns"], "expected": exp["publishedOnlyColumns"]})
    if rep["rebuiltOnlyColumns"]:
        bad.append({"rebuiltOnlyColumns": rep["rebuiltOnlyColumns"]})
    if rep["nRowsPublished"] != rep["nRowsRebuilt"]:
        bad.append({"rows": [rep["nRowsPublished"], rep["nRowsRebuilt"]]})
    for c, d in rep["columnsDiffering"].items():
        e = exp["allowedDifferences"].get(c)
        if e is None:
            bad.append({"column": c, "why": "not registered", "found": d}); continue
        cap, elig = e.get("maxRows"), None
        if cap is None and e.get("maxRowsFromNonNull"):        # M467 (audit F04): the cap is the exact eligible row set of the frozen transform, not a magic number
            pub = pd.read_csv("drive_master.csv", usecols=["file", e["maxRowsFromNonNull"]], low_memory=False)
            elig = set(pub.loc[pub[e["maxRowsFromNonNull"]].notna(), "file"]); cap = len(elig)
            if any(f not in elig for f in d.get("filesAll", d["files"])):
                bad.append({"column": c, "why": "differs on a file outside the eligible row set", "found": [f for f in d.get("filesAll", d["files"]) if f not in elig][:12], "eligibleColumn": e["maxRowsFromNonNull"]})
        if d["nRowsDiffer"] > cap or d["nNullPatternMismatch"] > e.get("maxNullPatternMismatch", 0):
            bad.append({"column": c, "why": "more rows than registered", "found": d, "registered": e})
        if e.get("maxAbsDiff") is not None and d["maxAbsDiff"] is not None and d["maxAbsDiff"] > e["maxAbsDiff"]:
            bad.append({"column": c, "why": "larger difference than registered", "found": d, "registered": e})
        if e.get("files") and any(f not in e["files"] for f in d.get("filesAll", d["files"])):
            bad.append({"column": c, "why": "differs on a file that is not registered", "found": d.get("filesAll", d["files"])[:12], "registered": e["files"]})
        if "filesAll" not in d:
            bad.append({"column": c, "why": "the report lacks the full differing-row list (filesAll): regenerate it with tools/replay_master.py --full"})
    ident = rep.get("identities")
    if not ident:
        bad.append({"identities": "the report lacks the transform identities (M489): regenerate it with tools/replay_master.py --full"})
    else:
        for c, f in (ident.get("offsetIdentityFailures") or {}).items():
            if f:
                bad.append({"identity": "frozen offset", "column": c, "why": "rebuilt - published differs from (I_reb - I_pub) x V x h / 1000", "files": f[:12], "n": len(f)})
        if ident.get("distanceIdentityFailures"):
            bad.append({"identity": "distance repair", "why": "rebuilt distance_km != published distance_endpoint_raw_km on a repaired row", "files": ident["distanceIdentityFailures"][:12]})
        if ident.get("distanceDerivedOutsideRepaired"):
            bad.append({"identity": "distance repair", "why": "a distance-derived column differs on a row that is not a repaired row", "files": ident["distanceDerivedOutsideRepaired"][:12]})
        reg = exp.get("allowedDifferences", {}).get("distance_km", {}).get("files")
        if reg is not None and sorted(ident.get("repairedFiles", [])) != sorted(reg):
            bad.append({"identity": "distance repair", "why": "repaired rows differ from the registered files", "found": ident.get("repairedFiles"), "registered": reg})
    return bad


def analyze_worker(raw_dir, key):
    import compute_drive_summary_v6 as v6
    return analyze(v6, raw_dir, key)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    args = {"raw_dir": argv[argv.index("--raw-dir") + 1] if "--raw-dir" in argv else None, "workers": int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 4}
    os.makedirs(D, exist_ok=True)
    if "--make-sample" in argv:
        dm = pd.read_csv("drive_master.csv", low_memory=False)
        keys = make_sample(dm)
        json.dump({"_provenance": "GENERATED by tools/replay_master.py --make-sample (seed 417): one drive per (drive_type, month) group by sha256 order, then the next drives by hash order; n = %d" % len(keys),
                   "files": keys}, open(SAMPLE, "w", encoding="utf-8", newline="\n"), indent=1)
        print("wrote", SAMPLE, len(keys)); return 0
    args["raw_dir"] = args["raw_dir"] or raw_dir_default()
    tier = "full" if "--full" in argv else "sample"
    rep = tier_full(args) if tier == "full" else tier_sample(args)
    if tier == "full":
        rep["unexpected"] = check_expected(rep)
        rep["ok"] = not rep["unexpected"]
    rep.update(_provenance="GENERATED by tools/replay_master.py (M417); do not hand-edit", generatedAt=dt.datetime.now(dt.timezone.utc).isoformat(), publishedMasterMd5=md5("drive_master.csv"),
               rawManifestSha256=sha256("raw_manifest.json")[:16], environment=environment(), codeHashes=code_hashes())
    if "--no-write" not in argv:
        json.dump(rep, open(os.path.join(D, "replay_report_%s.json" % tier), "w", encoding="utf-8", newline="\n"), indent=1, default=str)
    short = {k: rep[k] for k in rep if k not in ("perDrive", "filesWithAnyDifference", "columnsDiffering")}
    print(json.dumps(short, indent=1, default=str))
    if tier == "full":
        print(json.dumps({"columnsDiffering": rep["columnsDiffering"]}, indent=1)[:3500])
    return 0 if rep.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
