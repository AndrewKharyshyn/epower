#!/usr/bin/env python3
"""M705 (spec analyses/M705_spec.md Rev 1): per-drive compact histogram cache of engine-on seconds by 25 rpm bin, speed zone and variant, from the state-machine 1 Hz grid (compute_summary_arrays._esm_grid:
1 s mean, last observation carried at most 3 s). Cache `rpm_window_cache/` (git-ignored), one .npz per drive keyed by the raw-file sha256, the grid code hash, the bin width, the zone edges, the threshold / ramp sets and the
reverse-mask version; no cohort, date or stratum enters the cache. Aggregation never rereads raw files. Hard stop (gate, spec item 7): every histogram window sum must equal the direct mask count on the same grid.
Variants: threshold in (300, 400) x ramp r in (0, 3, 5, 10) x first-60-s (0 = kept, 1 = removed) x reverse-consistent seconds (0 = kept, 1 = removed)."""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np

BIN = 25
NBIN = 6000 // BIN                      # 240 bins 0..6000, bin 240 = overflow
THRS = (300, 400)
RAMPS = (0, 3, 5, 10)
F60 = (0, 1)
REV = (0, 1)
VARIANTS = [(t, r, f, v) for t in THRS for r in RAMPS for f in F60 for v in REV]
NZONE = 8                                # 7 engine-on speed zones + "no speed"
Z_EDGES = [0, 20, 40, 60, 80, 100, 120, 999]
CACHE_DIR = os.path.join(ROOT, "rpm_window_cache")
REV_VERSION = "M698-episodes-tStart-duration"
# pre-registered windows [lo, hi) (all multiples of 25): C1, C1b boundaries, C2 and their sensitivities
WINDOWS = {"C1_150": (1850, 2150), "C1_100": (1900, 2100), "C1_250": (1750, 2250), "C2_100": (4300, 4500), "C2_200": (4200, 4600),
           "C1b_lt1500": (0, 1500), "C1b_lt1475": (0, 1475), "C1b_lt1525": (0, 1525), "C1b_1475_1525": (1475, 1525)}
for k in (-50, -25, 25, 50):
    WINDOWS["C1_150_shift%+d" % k] = (1850 + k, 2150 + k)
    WINDOWS["C2_100_shift%+d" % k] = (4300 + k, 4500 + k)


def code_hash():
    import compute_summary_arrays as C
    import inspect
    src = inspect.getsource(C._esm_grid) + open(__file__, encoding="utf-8").read()
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]


def key(sha):
    return "%s_%s_b%d_z%s_t%s_r%s_%s" % (sha, code_hash(), BIN, "-".join(map(str, Z_EDGES)), "-".join(map(str, THRS)), "-".join(map(str, RAMPS)), REV_VERSION)


def runs_of(eon):
    d = np.diff(np.concatenate([[0], eon.astype(int), [0]]))
    s = np.where(d == 1)[0]; e = np.where(d == -1)[0]          # run = [s, e)
    return s, e


def ramp_mask(eon, valid, r):
    """Seconds excluded as ramps (r seconds after an onset and before a stop of every maximal engine-on run; runs of length <= 2r fully excluded), plus counts."""
    n = len(eon); ex = np.zeros(n, bool)
    s, e = runs_of(eon)
    n_full = 0; n_cens = 0
    for a, b in zip(s, e):
        cens_a = (a == 0) or (not valid[a - 1]); cens_b = (b == n) or (not valid[b])
        n_cens += int(cens_a) + int(cens_b)
        if r == 0:
            continue
        if b - a <= 2 * r:
            ex[a:b] = True; n_full += 1
        else:
            ex[a:a + r] = True; ex[b - r:b] = True
    return ex, n_full, n_cens


def drive_arrays(grid, rev):
    rr = grid["rpm"].values.astype(float) if "rpm" in grid else np.full(len(grid), np.nan)
    sp = grid["speed"].values.astype(float) if "speed" in grid else np.full(len(grid), np.nan)
    n = len(rr)
    zone = np.where(np.isnan(sp), NZONE - 1, np.digitize(sp, Z_EDGES[1:-1]))
    revm = np.zeros(n, bool)
    for a, b in (rev or []):
        revm[max(0, int(a)):min(n, int(b) + 1)] = True
    return rr, zone, revm


def build_entry(grid, rev):
    rr, zone, revm = drive_arrays(grid, rev)
    n = len(rr); valid = ~np.isnan(rr)
    H = np.zeros((len(VARIANTS), NZONE, NBIN + 1), np.int32)
    meta = np.zeros((len(THRS), len(RAMPS), 3), np.int64)         # [thr, r] -> engine-on seconds (r=0), fully excluded runs, censored edges
    bi = np.where(valid, np.minimum(np.floor(np.nan_to_num(rr) / BIN).astype(int), NBIN), 0)
    first = np.arange(n) < 60
    for ti, t in enumerate(THRS):
        eon = (rr > t) & valid
        for ri, r in enumerate(RAMPS):
            ramp, nfull, ncens = ramp_mask(eon, valid, r)
            meta[ti, ri] = (int(eon.sum()), nfull, ncens)
            for fi, f in enumerate(F60):
                for vi, v in enumerate(REV):
                    m = eon & ~ramp
                    if f:
                        m = m & ~first
                    if v:
                        m = m & ~revm
                    idx = VARIANTS.index((t, r, f, v))
                    np.add.at(H[idx], (zone[m], bi[m]), 1)
    return H, meta, rr, zone, revm, valid


def window_sum(h, lo, hi, z=None):
    a, b = lo // BIN, hi // BIN
    x = h[:, a:b] if z is None else h[z:z + 1, a:b]
    return int(x.sum())


def gate(H, rr, zone, revm, valid):
    """Hard stop: histogram window sums equal direct mask counts for every pre-registered window and every variant."""
    n = len(rr); first = np.arange(n) < 60
    for idx, (t, r, f, v) in enumerate(VARIANTS):
        eon = (rr > t) & valid
        ramp, _a, _b = ramp_mask(eon, valid, r)
        m = eon & ~ramp
        if f:
            m = m & ~first
        if v:
            m = m & ~revm
        for name, (lo, hi) in WINDOWS.items():
            direct = int((m & (rr >= lo) & (rr < hi)).sum())
            if direct != window_sum(H[idx], lo, hi):
                raise SystemExit("STOP gate: histogram != direct count (%s variant %s window %s: %d vs %d)" % ("", (t, r, f, v), name, window_sum(H[idx], lo, hi), direct))
        if int(H[idx].sum()) != int(m.sum()):
            raise SystemExit("STOP gate: histogram total != mask total (variant %s)" % ((t, r, f, v),))


def build_all(progress=False):
    import compute_summary_arrays as C
    import drive_raw_cache as drc
    import ah_throughput as AH
    os.makedirs(CACHE_DIR, exist_ok=True)
    m = __import__("pandas").read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file", "date", "ens_outlier_v2"], low_memory=False)
    m = m[m["ens_outlier_v2"].astype(str) == "False"].reset_index(drop=True)
    sha_by = AH.manifest_sha_lookup(); loader = AH.raw_loader(os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")); fl = drc.make_frame_loader()
    revdir = os.path.join(ROOT, "reverse_mask_cache"); revidx = {}
    import glob
    for p in glob.glob(os.path.join(revdir, "*.json")):
        revidx.setdefault(os.path.basename(p).split("_v")[0], p)
    out = {"built": 0, "cached": 0, "noGrid": []}
    for _, r in m.iterrows():
        fn = r["file"]; sha = sha_by(fn)
        if not sha:
            b = loader(fn); sha = hashlib.sha256(b).hexdigest() if b else None
        if not sha:
            out["noGrid"].append(fn); continue
        path = os.path.join(CACHE_DIR, key(sha) + ".npz")
        if os.path.isfile(path):
            out["cached"] += 1; continue
        grid = C._esm_grid(fn, loader, fl)
        if grid is None or "rpm" not in grid or grid["rpm"].notna().sum() == 0:
            out["noGrid"].append(fn); continue
        rev = None
        if sha in revidx:
            rec = json.load(open(revidx[sha], encoding="utf-8")); rev = [(e["tStart"], e["tStart"] + e["duration"]) for e in (rec.get("episodes") or [])]
        H, meta, rr, zone, revm, valid = build_entry(grid, rev)
        gate(H, rr, zone, revm, valid)
        np.savez_compressed(path, H=H, meta=meta, n=np.int64(len(rr)))
        out["built"] += 1
    return out


def load_entry(sha):
    p = os.path.join(CACHE_DIR, key(sha) + ".npz")
    if not os.path.isfile(p):
        return None
    z = np.load(p)
    return z["H"], z["meta"], int(z["n"])


if __name__ == "__main__":
    print(json.dumps(build_all()))
