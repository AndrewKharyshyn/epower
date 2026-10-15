#!/usr/bin/env python3
"""M441 (spec Rev 2.1, section 5 + B7 + follow-ups): per-drive cache of the interval extractor v2 (tools/regen_v2.py). Owner decision (f) of 2026-10-14: a content-hash-keyed per-drive cache of compact
sufficient statistics (git-ignored `regen_cache/`). A drive's entry is reused only if ALL of these match: SHA-256 of the raw file bytes, the frame-loader schema version, the SHA-256 of the despike and speed-priority sources,
the policy hash (declared constants), the extractor SOURCE hash and the variant id (base | lagP1 | lagM1 | ceil2 | dec0 | dec1). The offset charge (nonlinear in i_off) lives in a separate `<file>.off.npz` keyed by i_off, so an
offset update never invalidates the main arrays. Mass-free quantities only (dv2); the class mass and the cohort are applied at aggregation. Aggregation reads these arrays only; no raw CSV is read for a view change or a SOC selection."""
import hashlib, inspect, json, os, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import regen_v2 as R

CACHE_DIR = os.path.join(ROOT, "regen_cache")
VARIANTS = {"base": {}, "lagP1": {"iv_lag_s": 1.0}, "lagM1": {"iv_lag_s": -1.0}, "ceil2": {"dt_max": 2.0, "iv_gap": 2.0}, "dec0": {"decimate": 0}, "dec1": {"decimate": 1}}
IV_KEYS = ["t0", "dt", "v0", "v1", "dv2", "charge", "tpack", "nprobe", "soc", "cls", "plateau", "trimmed", "endsAtStandstill", "episode"]
sha256_b = lambda b: hashlib.sha256(b).hexdigest()


def _src(path):
    return sha256_b(open(path, "rb").read())


def code_hashes():
    import compute_summary_arrays as C, drive_raw_cache as drc
    return {"loaderSchema": drc.SCHEMA_VERSION, "despikeSrc": _src(os.path.join(ROOT, "soc_spike.py"))[:16], "speedPrioritySrc": sha256_b(inspect.getsource(C._apply_speed_priority).encode())[:16],
            "policyHash": R.POLICY_HASH, "extractorSrc": _src(os.path.join(ROOT, "tools", "regen_v2.py"))[:16], "extractorVersion": R.EXTRACTOR_VERSION}


def raw_dir():
    return os.environ.get("XT_RAW_DIR_STAGED") or os.path.join(ROOT, "raw_only")


def raw_sha256(fn, memo):
    """SHA-256 of the raw file bytes, memoised per (size, mtime) in regen_cache/_sha.json."""
    p = os.path.join(raw_dir(), fn)
    st = os.stat(p); key = "%d:%d" % (st.st_size, int(st.st_mtime))
    e = memo.get(fn)
    if e and e[0] == key:
        return e[1]
    h = sha256_b(open(p, "rb").read()); memo[fn] = [key, h]
    return h


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
    r = R.extract_drive(df, i_off=i_off, **VARIANTS[variant])
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
        with np.load(mp, allow_pickle=False) as z:
            hdrs[fn] = json.loads(str(z["hdr"]))
            if "iv_t0" not in z.files:
                continue
            for k in IV_KEYS:
                cols["iv_" + k].append(z["iv_" + k])
            for k in ("dv2", "charge", "touch"):
                cols["bin_" + k].append(z["bin_" + k])
            cols["drive"].append(np.full(len(z["iv_t0"]), di, np.int32))
        if with_off:
            with np.load(op, allow_pickle=False) as z:
                cols["iv_chargeOff"].append(z["iv_chargeOff"]); cols["bin_chargeOff"].append(z["bin_chargeOff"])
    out = {k: (np.concatenate(v) if v else np.array([])) for k, v in cols.items()}
    return out, hdrs
