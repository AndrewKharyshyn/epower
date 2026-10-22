#!/usr/bin/env python3
"""M480b (analyses/M480b_spec.md Rev 3): per-drive pair-level cache of the max/min cell-voltage pairs. One compact .npz per drive under pair_cache/ (git-ignored), keyed by the raw-file SHA-256
(raw_manifest.json, else hashed bytes) and the extractor hash (this file plus the production constants it uses), so a changed raw file or a changed extractor invalidates the entry. The pairing
replicates compute_drive_summary_v6.py exactly (cleaned Vcell_max series merged onto Vcell_min, nearest within SPREAD_TOL, dropna; current matched with V_ALIGN_TOL on the |I| < 900 A series; SoC
from _series(..., 'soc') with the M388c spike mask, matched with V_ALIGN_TOL). One row per pair: time (s from the first sample of the file), signed spread (mV), signed offset (min-cell report time
minus max-cell report time, ms), matched current (A, NaN if none), absolute time between pair and matched current (ms), matched SoC (%, NaN if none). Aggregation never rereads raw CSVs.
Usage: python tools/pair_cache.py [--rebuild]    (builds / refreshes the cache for every master drive)"""
import hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
CACHE_DIR = os.path.join(ROOT, "pair_cache")
EXTRACTOR_VERSION = 1
FIELDS = ("t", "spread_mv", "off_ms", "I", "cur_age_ms", "soc")


def extractor_hash():
    """Hash of this file and of the production constants and source of the helpers it relies on."""
    import compute_drive_summary_v6 as D
    import soc_spike
    h = hashlib.sha256()
    h.update(open(os.path.abspath(__file__), "rb").read())
    h.update(json.dumps({"spread_tol": D.SPREAD_TOL, "v_align_tol": D.V_ALIGN_TOL, "soc": [soc_spike.SOC_SPIKE_JUMP_PP, soc_spike.SOC_SPIKE_NEIGHBOUR_TOL_PP, soc_spike.SOC_SPIKE_MAX_GAP_S]}, sort_keys=True).encode())
    h.update(open(soc_spike.__file__, "rb").read())
    return h.hexdigest()


def pairs_from_bytes(csv_bytes):
    """Pair-level arrays of one drive CSV, or None when the drive has no cell-voltage pairs. Replicates production."""
    import compute_drive_summary_v6 as D
    df, t = D._prep_bytes(csv_bytes)
    I = D._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900].reset_index(drop=True)
        I = I if len(I) else None
    vmax = D._series(df, t, "Vcell_max", lo=2.0, hi=5.0)
    vmin = D._series(df, t, "Vcell_min", lo=2.0, hi=5.0)
    soc = D._series(df, t, "soc")
    if vmax is None or vmin is None:
        return None
    vmin2 = vmin.rename(columns={"v": "vmin"}).copy()
    vmin2["t_min"] = vmin2["t"]
    p = pd.merge_asof(vmax.rename(columns={"v": "vmax"}), vmin2, on="t", direction="nearest", tolerance=pd.Timedelta(D.SPREAD_TOL)).dropna().reset_index(drop=True)
    if not len(p):
        return None
    t0 = t.min()
    n = len(p)
    out = {"t": (p["t"] - t0).dt.total_seconds().to_numpy(float), "spread_mv": ((p["vmax"] - p["vmin"]) * 1000.0).to_numpy(float),
           "off_ms": (p["t_min"] - p["t"]).dt.total_seconds().to_numpy(float) * 1000.0,
           "I": np.full(n, np.nan), "cur_age_ms": np.full(n, np.nan), "soc": np.full(n, np.nan)}
    if I is not None:
        I2 = I.copy()
        I2["t_I"] = I2["t"]
        p2 = D._asof(p[["t"]].copy(), I2, "I", D.V_ALIGN_TOL)
        out["I"] = p2["I"].to_numpy(float)
        out["cur_age_ms"] = np.abs((p2["t_I"] - p2["t"]).dt.total_seconds().to_numpy(float)) * 1000.0
    if soc is not None:
        out["soc"] = D._asof(p[["t"]].copy(), soc, "soc", D.V_ALIGN_TOL)["soc"].to_numpy(float)
    return out


def cache_path(sha, ext, cache_dir=CACHE_DIR):
    return os.path.join(cache_dir, "%s_%s.npz" % (sha[:16], ext[:12]))


def load_or_build(file, loader, sha_lookup, ext, cache_dir=CACHE_DIR, rebuild=False):
    """(arrays | None, raw sha256, status) for one drive; status in {'hit', 'built', 'no_pairs', 'raw_missing'}. The cache is read only when the key matches."""
    sha = sha_lookup(file) if sha_lookup else None
    b = None
    if sha is None:
        b = loader(file)
        if b is None:
            return None, None, "raw_missing"
        sha = hashlib.sha256(b).hexdigest()
    path = cache_path(sha, ext, cache_dir)
    if os.path.exists(path) and not rebuild:
        z = np.load(path)
        if int(z["n"]) == 0:
            return None, sha, "no_pairs"
        return {k: z[k] for k in FIELDS}, sha, "hit"
    if b is None:
        b = loader(file)
        if b is None:
            return None, sha, "raw_missing"
    arr = pairs_from_bytes(b)
    os.makedirs(cache_dir, exist_ok=True)
    if arr is None:
        np.savez_compressed(path, n=np.array(0), **{k: np.zeros(0) for k in FIELDS})
        return None, sha, "no_pairs"
    np.savez_compressed(path, n=np.array(len(arr["t"])), **arr)
    return arr, sha, "built"


def build_all(master, loader, sha_lookup, cache_dir=CACHE_DIR, rebuild=False):
    """{file: arrays or None}, manifest {file: [raw sha256, status]}, manifest hash."""
    ext = extractor_hash()
    data, man = {}, {}
    for f in master["file"].astype(str):
        arr, sha, st = load_or_build(f, loader, sha_lookup, ext, cache_dir, rebuild)
        data[f], man[f] = arr, [sha, st]
    mh = hashlib.sha256(json.dumps({"extractor": ext, "files": man}, sort_keys=True).encode()).hexdigest()
    return data, man, mh


def main():
    import ah_throughput as AH
    master = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    data, man, mh = build_all(master, AH.raw_loader(), AH.manifest_sha_lookup(), rebuild="--rebuild" in sys.argv)
    from collections import Counter
    print(json.dumps({"drives": len(data), "status": dict(Counter(v[1] for v in man.values())), "manifest_hash": mh}))


if __name__ == "__main__":
    main()
