#!/usr/bin/env python3
"""M441 (spec Rev 2.1, section 5 + B7 + follow-ups): per-drive cache of the interval extractor v2 (tools/regen_v2.py). Owner decision (f) of 2026-10-14: a content-hash-keyed per-drive cache of compact
sufficient statistics (git-ignored `regen_cache/`). A drive's entry is reused only if ALL of these match: SHA-256 of the raw file bytes, the frame-loader schema version, the SHA-256 of the despike and speed-priority sources,
the policy hash (declared constants), the extractor SOURCE hash and the variant id (base | lagP1 | lagM1 | ceil2 | dec0 | dec1). The offset charge (nonlinear in i_off) lives in a separate `<file>.off.npz` keyed by i_off, so an
offset update never invalidates the main arrays. Mass-free quantities only (dv2); the class mass and the cohort are applied at aggregation. Aggregation reads these arrays only; no raw CSV is read for a view change or a SOC selection."""
import hashlib, inspect, json, os, re, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import regen_v2 as R

CACHE_DIR = os.environ.get("XT_REGEN_CACHE_DIR") or os.path.join(ROOT, "regen_cache")      # M490: an environment override reaches the spawned extraction workers (a module attribute set in the parent does not); default unchanged
VARIANTS = {"base": {}, "lagP1": {"iv_lag_s": 1.0}, "lagM1": {"iv_lag_s": -1.0}, "ceil2": {"dt_max": 2.0, "iv_gap": 2.0}, "dec0": {"decimate": 0}, "dec1": {"decimate": 1}}
def variant_kwargs(variant):
    """Extractor keyword arguments of a cache variant id. base | lagP1 | lagM1 | ceil2 | dec0 | dec1 | box3 (P3 boxcar W = 3 s) | h{D}p{k} (M442 common grid Delta = D s, phase k * D / 4 s)
    | d{f}p{q}h{D}p{k} (decimate every f-th native sample from index q, then the common grid)."""
    if variant in VARIANTS:
        return dict(VARIANTS[variant])
    m = re.fullmatch(r"(?:d(\d)p(\d))?(box3|h(\d)p(\d)|l(\d)p(\d)|)", variant)
    if not m:
        raise KeyError(variant)
    f, q, core, hD, hk, lD, lk = m.groups()
    out = {}
    if core == "":
        out["decimate"] = (int(f), int(q))                  # decimation only (native v2 at a lower rate)
        return out
    if core == "box3":
        out["boxcar_s"] = 3.0
    elif hD is not None:
        out["harmonize"] = (float(hD), int(hk) * float(hD) / 4.0)
    else:
        out["harmonize"] = (float(lD), int(lk) * float(lD) / 4.0); out["harm_interp"] = True     # exploratory interpolation onto the grid
    if f is not None:
        out["decimate"] = (int(f), int(q))
    return out


IV_KEYS = ["t0", "dt", "v0", "v1", "dv2", "charge", "tpack", "nprobe", "soc", "cls", "plateau", "trimmed", "endsAtStandstill", "episode"]
sha256_b = lambda b: hashlib.sha256(b).hexdigest()


def _src(path):
    return sha256_b(open(path, "rb").read())


def code_hashes():
    import compute_summary_arrays as C, drive_raw_cache as drc
    return {"loaderSchema": drc.SCHEMA_VERSION, "despikeSrc": _src(os.path.join(ROOT, "soc_spike.py"))[:16], "speedPrioritySrc": sha256_b(inspect.getsource(C._apply_speed_priority).encode())[:16],
            "policyHash": R.POLICY_HASH, "extractorSrc": _src(os.path.join(ROOT, "tools", "regen_v2.py"))[:16], "extractorVersion": R.EXTRACTOR_VERSION,
            "closureSrc": closure_src(C, drc)}


def closure_src(C, drc):
    """M489 (audit A05): hash of the dependency closure of the extractor and of the frame loader: every shared helper they reach (compute_summary_arrays _apply_speed_priority / _ft / RAW_MAP, the drive_raw_cache loader
    and what it calls), its constants, the repository modules it imports, the library versions. The former key hashed regen_v2.py, soc_spike.py and _apply_speed_priority only, so a change to RAW_MAP, _ft or the loader
    body (only SCHEMA_VERSION was keyed) left stale entries valid."""
    import dep_hash
    return dep_hash.closure_hash([R.extract_drive, drc.make_frame_loader], modules=(C, drc), extra={"loaderSchema": drc.SCHEMA_VERSION, "extractorVersion": R.EXTRACTOR_VERSION})[:16]


def raw_dir():
    return os.environ.get("XT_RAW_DIR_STAGED") or os.path.join(ROOT, "raw_only")


def raw_sha256(fn, memo):
    """SHA-256 of the raw file bytes, memoised per (size, mtime_ns) in regen_cache/_sha.json. M467 (audit F07): the key was (size, whole-second mtime), so a
    same-length edit within one second returned the former digest; nanosecond mtime narrows that window to filesystem timestamp granularity. The memo is a
    speed cache, not a content-identity proof: new or changed identities are always hashed in full (a key mismatch rehashes)."""
    p = os.path.join(raw_dir(), fn)
    st = os.stat(p); key = "%d:%d" % (st.st_size, st.st_mtime_ns)
    e = memo.get(fn)
    if e and e[0] == key:
        return e[1]
    h = sha256_b(open(p, "rb").read()); memo[fn] = [key, h]
    return h


class CacheAbsentError(RuntimeError):
    """M489 (audit A09): the aggregation reads the per-drive cache only; a missing entry (a fresh clone, a cleared regen_cache/, a variant never extracted) is a named failure with its remedy, not a bare FileNotFoundError."""


def _require(path, fn, variant):
    if not os.path.exists(path):
        raise CacheAbsentError("regen cache entry missing: %s (drive %s, variant %s). regen_cache/ is derived and git-ignored: build it with the ingestion stage regen_v2 (tools/regen_v2_stage.py) or "
                               "regen_v2_cache.ensure(files, i_off, variant=%r), which needs the staged raw files (raw_only/ or XT_RAW_DIR_STAGED); aggregation never rereads raw CSVs." % (path, fn, variant, variant))
    return path


def _paths(fn, variant):
    d = os.path.join(CACHE_DIR, variant)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, fn + ".npz"), os.path.join(d, fn + ".off.npz")


def _save(path, hdr, arrays):
    np.savez_compressed(path, hdr=np.array(json.dumps(hdr, sort_keys=True)), **arrays)


def _hdr(path):
    try:
        with np.load(path, allow_pickle=False) as z:
            return json.loads(str(z["hdr"]))
    except Exception:
        return None


def entry_valid(fn, variant, sha, ch, i_off):
    mp, op = _paths(fn, variant)
    h = _hdr(mp)
    want = dict(ch, rawSha256=sha, variant=variant)
    main_ok = h is not None and all(h.get(k) == v for k, v in want.items())
    ho = _hdr(op) if main_ok else None
    off_ok = ho is not None and ho.get("rawSha256") == sha and ho.get("iOff") == i_off and ho.get("extractorSrc") == ch["extractorSrc"] and ho.get("variant") == variant
    return main_ok, off_ok


def extract_and_store(fn, variant, sha, ch, i_off, FL, need_main=True):
    df = FL(fn)
    if df is None:
        return {"file": fn, "status": "noFrame"}
    r = R.extract_drive(df, i_off=i_off, **variant_kwargs(variant))
    mp, op = _paths(fn, variant)
    iv, bins = r["intervals"], r["bins"]
    hdr = dict(ch, rawSha256=sha, variant=variant, counts=r["counts"], nCandidates=r["nCandidates"], cadence=r["cadence"], nInt=0 if iv is None else int(len(iv["t0"])))
    if need_main:
        arr = {}
        if iv is not None:
            for k in IV_KEYS:
                arr["iv_" + k] = iv[k]
            for k in ("dv2", "charge", "touch"):
                arr["bin_" + k] = bins[k].astype(np.float64 if k != "touch" else np.int8)
        _save(mp, hdr, arr)
    ho = {"rawSha256": sha, "iOff": i_off, "extractorSrc": ch["extractorSrc"], "variant": variant}
    arr = {} if iv is None else {"iv_chargeOff": iv["chargeOff"], "bin_chargeOff": bins["chargeOff"]}
    _save(op, ho, arr)
    return {"file": fn, "status": "extracted", "nInt": hdr["nInt"]}


_FL = None


def _work(args):
    global _FL
    fn, variant, sha, ch, i_off, need_main = args
    import drive_raw_cache as drc
    if _FL is None:
        _FL = drc.make_frame_loader(raw_dir=raw_dir())
    return extract_and_store(fn, variant, sha, ch, i_off, _FL, need_main)


def ensure(files, i_off, variant="base", workers=5):
    """Extract only the new or invalidated drives (and the offset files whose i_off changed). Returns the stats dict."""
    from concurrent.futures import ProcessPoolExecutor
    ch = code_hashes()
    if not os.path.isdir(raw_dir()):
        raise CacheAbsentError("raw directory not found: %s. The cache extractor needs the staged raw files (raw_only/, or XT_RAW_DIR_STAGED); run tools/stage_raw.py (ingestion stage stage_raw) first." % raw_dir())
    os.makedirs(CACHE_DIR, exist_ok=True)
    mp = os.path.join(CACHE_DIR, "_sha.json")
    memo = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {}
    jobs, shas, hit = [], {}, 0
    for fn in files:
        sha = raw_sha256(fn, memo); shas[fn] = sha
        m_ok, o_ok = entry_valid(fn, variant, sha, ch, i_off)
        if m_ok and o_ok:
            hit += 1
        else:
            jobs.append((fn, variant, sha, ch, i_off, not m_ok))
    with open(mp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(memo, f)
    t0 = time.time()
    if jobs:
        if workers <= 1:
            res = [_work(j) for j in jobs]
        else:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                res = list(ex.map(_work, jobs, chunksize=4))
    else:
        res = []
    return {"nFiles": len(files), "cacheHits": hit, "extracted": len(jobs), "noFrame": sum(1 for x in res if x["status"] == "noFrame"), "seconds": round(time.time() - t0, 1), "codeHashes": ch, "rawSha": shas}


def load(files, variant="base", with_off=True):
    """Concatenate the cached arrays of all drives. Returns (tables, hdrs): tables is a dict of concatenated arrays with 'drive' (index into files)."""
    cols = {k: [] for k in ["iv_" + k for k in IV_KEYS] + ["bin_dv2", "bin_charge", "bin_touch"] + (["iv_chargeOff", "bin_chargeOff"] if with_off else []) + ["drive"]}
    hdrs = {}
    for di, fn in enumerate(files):
        mp, op = _paths(fn, variant)
        with np.load(_require(mp, fn, variant), allow_pickle=False) as z:
            hdrs[fn] = json.loads(str(z["hdr"]))
            if "iv_t0" not in z.files:
                continue
            for k in IV_KEYS:
                cols["iv_" + k].append(z["iv_" + k])
            for k in ("dv2", "charge", "touch"):
                cols["bin_" + k].append(z["bin_" + k])
            cols["drive"].append(np.full(len(z["iv_t0"]), di, np.int32))
        if with_off:
            with np.load(_require(op, fn, variant), allow_pickle=False) as z:
                cols["iv_chargeOff"].append(z["iv_chargeOff"]); cols["bin_chargeOff"].append(z["bin_chargeOff"])
    out = {k: (np.concatenate(v) if v else np.array([])) for k, v in cols.items()}
    return out, hdrs


def load_stack(files, variants, with_off=True):
    """Stack the tables of several variants (e.g. the four grid phases of the M442 harmonized estimator) with a row weight 1 / len(variants); the headers are those of the first variant plus the mean exclusion counts."""
    parts, hdrs = [], None
    for v in variants:
        T, H = load(files, v, with_off=with_off)
        T["w"] = np.full(len(T["drive"]), 1.0 / len(variants))
        parts.append(T)
        if hdrs is None:
            hdrs = {fn: dict(h, counts=dict(h["counts"])) for fn, h in H.items()}
        else:
            for fn, h in H.items():
                for k_, c_ in h["counts"].items():
                    hdrs[fn]["counts"][k_] += c_
    for fn in hdrs:
        hdrs[fn]["counts"] = {k_: int(round(c_ / len(variants))) for k_, c_ in hdrs[fn]["counts"].items()}
    return {k: np.concatenate([p_[k] for p_ in parts]) for k in parts[0]}, hdrs

