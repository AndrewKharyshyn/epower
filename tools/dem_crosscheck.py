#!/usr/bin/env python3
"""M762 (spec analyses/M762_spec.md Rev 6): independent-DEM cross-check of the FABDEM step grade. Auxiliary, report-only, offline.

Sources: FABDEM v1.2 (object under test), NASADEM_HGT v001 (SRTM lineage, with the NUM layer), the AW3D30 mosaic (optical stereo, no mask) and Copernicus GLO-30 with its edit / filling masks (never an independence corner;
used for the bare-earth stratum and the fill mask). The step set is the frozen M757 step set (tools/dem_step_grade.py build_steps, called once per source: the step selection does not depend on the DEM).
Stages: C0 integrity and coverage, C2 pairwise agreement, C3 three-cornered hat (error standard deviation of each source), C4 2SLS grade coefficient (descriptive), C5 bare-earth stratum, C6 grade-class shares and misclassification.
Nothing is written to the payload, the dashboard or the master. Aggregates only in the result (public repository): no coordinates, tracks or per-drive geometry. DEM files stay outside the repository (env XT_DEM_DIR with the sub-folders fabdem, nasadem, aw3d30, glo30).

Usage: python tools/dem_crosscheck.py --manifest | [--run]   Exit codes: 0 done or skipped (missing inputs), 1 master pin failed, 3 manifest mismatch or a documented-coding violation."""
import argparse, hashlib, io, json, math, os, sys, tarfile, zipfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

SEED, NB_DEFAULT = 42, 4000
G = 9.80665
S_ADEQUATE, S_NOT_ADEQUATE, S_CI_UPPER = 0.67, 1.33, 1.0          # spec 4 R3 / 8.3 (frozen): one third and two thirds of the 2 pp class width; interval upper end 1.0 pp
OUTLIER_M, UNTOUCHED_M, FILLSIG_M = 100.0, 2.0, 0.5                 # spec 10.4 / 3 C5 / 10.6
NUM_SRTM = (1, 23)                                                   # spec 12: NASADEM NUM 1 to 23 = SRTM-measured; everything else excluded
NUM_RANGES = (("water", 0, 0), ("srtm", 1, 23), ("prism", 41, 94), ("gdem3", 110, 160), ("gdem2", 170, 220), ("srtm_from_gdem", 231, 234),
              ("national_dem", 241, 246), ("interpolation", 250, 250), ("quad_edge", 251, 251), ("error", 255, 255))
TILES = ["N48E023", "N48E024", "N49E023", "N49E024", "N49E025", "N49E026", "N49E027", "N49E028", "N49E030", "N49E031", "N49E032", "N50E025", "N50E026", "N50E027", "N50E028", "N50E029", "N50E030"]
VOID = -32000.0


class Stop(Exception):
    pass


# ------------------------------------------------------------------ raster blocks and surfaces (known-answer tested)
class Cell:
    """One raster block covering the one-degree cell with lower-left corner (N, E): array a, latitude of the first row (top), longitude of the first column (left), pixels per degree in y and x, area (cell-edge) or point convention."""
    __slots__ = ("a", "top", "left", "ppy", "ppx", "area")

    def __init__(self, a, top, left, ppy, ppx, area):
        self.a, self.top, self.left, self.ppy, self.ppx, self.area = a, float(top), float(left), float(ppy), float(ppx), bool(area)


class Surface:
    """Height (or mask) surface made of one-degree cells supplied lazily by loader(N, E) -> Cell | None. Bilinear height at a position (area rasters: the same grid shifted half a pixel); a node outside the
    block is looked up in the neighbouring block by its own position, so tiles with different pixel spacing (GLO-30 above 50 N) and shared edge rows (HGT) are handled. void: values at or below it become NaN."""

    def __init__(self, loader, void=VOID, name="surface"):
        self.loader, self.void, self.name, self.cells = loader, void, name, {}

    def _cell(self, N, E):
        k = (int(N), int(E))
        if k not in self.cells:
            self.cells[k] = self.loader(*k)
        return self.cells[k]

    def _clean(self, v):
        v = np.asarray(v, dtype=np.float64)
        if self.void is not None:
            v = np.where(v <= self.void, np.nan, v)
        return v

    def nearest(self, lat, lon):
        """Nearest-node (area: containing-pixel) value; NaN where no block holds the position."""
        lat, lon = np.atleast_1d(np.asarray(lat, float)), np.atleast_1d(np.asarray(lon, float))
        out = np.full(lat.shape, np.nan)
        fin = np.isfinite(lat) & np.isfinite(lon)
        found = np.zeros(lat.shape, bool)
        la9, lo9 = np.round(np.where(fin, lat, 0.0), 9), np.round(np.where(fin, lon, 0.0), 9)
        for off in (0, -1):                                    # a latitude on a block edge may belong to the block below (point rasters keep the shared row there)
            N = np.floor(la9).astype(np.int64) + off
            E = np.floor(lo9).astype(np.int64)
            todo = fin & ~found
            if off == -1:
                todo &= np.isclose(la9, np.rint(la9), atol=1e-9)
            code = N * 1000 + E
            for c in np.unique(code[todo]):
                m = todo & (code == c)
                cell = self._cell(int(N[m][0]), int(E[m][0]))
                if cell is None:
                    continue
                fr, fc = (cell.top - la9[m]) * cell.ppy, (lo9[m] - cell.left) * cell.ppx
                r, cc = (np.floor(fr), np.floor(fc)) if cell.area else (np.rint(fr), np.rint(fc))
                r, cc = r.astype(np.int64), cc.astype(np.int64)
                ok = (r >= 0) & (r < cell.a.shape[0]) & (cc >= 0) & (cc < cell.a.shape[1])
                v = np.full(r.shape, np.nan)
                v[ok] = self._clean(cell.a[r[ok], cc[ok]])
                out[m] = np.where(ok, v, out[m])
                f = np.zeros(r.shape, bool)
                f[ok] = True
                found[m] |= f
        return out

    def height(self, lat, lon):
        lat, lon = np.atleast_1d(np.asarray(lat, float)), np.atleast_1d(np.asarray(lon, float))
        out = np.full(lat.shape, np.nan)
        fin = np.isfinite(lat) & np.isfinite(lon)
        la9, lo9 = np.round(np.where(fin, lat, 0.0), 9), np.round(np.where(fin, lon, 0.0), 9)
        N, E = np.floor(la9).astype(np.int64), np.floor(lo9).astype(np.int64)
        code = N * 1000 + E
        for c in np.unique(code[fin]):
            m = fin & (code == c)
            cell = self._cell(int(N[m][0]), int(E[m][0]))
            if cell is None:
                continue
            sh = 0.5 if cell.area else 0.0
            fr, fc = (cell.top - la9[m]) * cell.ppy - sh, (lo9[m] - cell.left) * cell.ppx - sh
            r0, c0 = np.floor(fr).astype(np.int64), np.floor(fc).astype(np.int64)
            wy, wx = fr - r0, fc - c0
            R, C = cell.a.shape
            v = []
            for dr, dc in ((0, 0), (0, 1), (1, 0), (1, 1)):
                rr, cc = r0 + dr, c0 + dc
                inside = (rr >= 0) & (rr < R) & (cc >= 0) & (cc < C)
                val = np.full(rr.shape, np.nan)
                val[inside] = self._clean(cell.a[rr[inside], cc[inside]])
                if (~inside).any():
                    la = np.round(cell.top - (rr[~inside] + sh) / cell.ppy, 9)
                    lo = np.round(cell.left + (cc[~inside] + sh) / cell.ppx, 9)
                    val[~inside] = self.nearest(la, lo)
                v.append(val)
            out[m] = (1 - wy) * (1 - wx) * v[0] + (1 - wy) * wx * v[1] + wy * (1 - wx) * v[2] + wy * wx * v[3]
        return out


class MaskSurface:
    """Derived surface whose height() is 0.0 where the condition holds at the position and NaN elsewhere; a step difference of two such heights is finite only when BOTH fixes satisfy the condition."""

    def __init__(self, fn, name="mask"):
        self.fn, self.name = fn, name

    def height(self, lat, lon):
        ok = self.fn(np.atleast_1d(np.asarray(lat, float)), np.atleast_1d(np.asarray(lon, float)))
        return np.where(ok, 0.0, np.nan)


def num_mask(num_surface):
    return MaskSurface(lambda la, lo: (lambda v: np.isfinite(v) & (v >= NUM_SRTM[0]) & (v <= NUM_SRTM[1]))(num_surface.nearest(la, lo)), "nasadem_num_srtm")


def glo_unflagged_mask(edm, flm, edm_mode, flm_mode):
    def fn(la, lo):
        a, b = edm.nearest(la, lo), flm.nearest(la, lo)
        return np.isfinite(a) & np.isfinite(b) & (a == edm_mode) & (b == flm_mode)
    return MaskSurface(fn, "glo30_unflagged")


def screen_mask(sf, sn, sa):
    """Outlier screen (spec 10.4): any source height differs from the median of the three by more than 100 m."""
    def fn(la, lo):
        h = np.vstack([sf.height(la, lo), sn.height(la, lo), sa.height(la, lo)])
        med = np.median(h, axis=0)
        return np.isfinite(h).all(axis=0) & (np.abs(h - med) <= OUTLIER_M).all(axis=0)
    return MaskSurface(fn, "outlier_screen")


def diff_mask(s1, s2, limit, name):
    def fn(la, lo):
        a, b = s1.height(la, lo), s2.height(la, lo)
        return np.isfinite(a) & np.isfinite(b) & (np.abs(a - b) <= limit)
    return MaskSurface(fn, name)


# ------------------------------------------------------------------ loaders
def hgt_loader(dem_dir, kind):
    """NASADEM_HGT zip (n49e024.hgt big-endian int16 3601 x 3601; .num uint8): read from the zip stream, nothing extracted. Point convention, shared edge rows and columns."""
    def load(N, E):
        name = "n%02de%03d" % (N, E)
        p = os.path.join(dem_dir, "NASADEM_HGT_%s.zip" % name)
        if not os.path.exists(p):
            return None
        with zipfile.ZipFile(p) as z:
            raw = z.read("%s.%s" % (name, kind))
        a = np.frombuffer(raw, dtype=">i2" if kind == "hgt" else np.uint8)
        if a.size != 3601 * 3601:
            raise Stop("unexpected size of %s.%s" % (name, kind))
        return Cell(a.reshape(3601, 3601).astype(np.int16 if kind == "hgt" else np.uint8), N + 1, E, 3600, 3600, False)
    return load


def _geotiff_geo(im):
    """(top latitude, left longitude, scale x, scale y, area) from the GeoTIFF tags."""
    tag = im.tag_v2
    sc, tie = tag.get(33550), tag.get(33922)
    if sc is None or tie is None:
        raise Stop("GeoTIFF without ModelPixelScale/ModelTiepoint")
    keys = tag.get(34735) or ()
    area = True
    for i in range(4, len(keys) - 3, 4):
        if keys[i] == 1025:
            area = keys[i + 3] != 2
    return float(tie[4]), float(tie[3]), float(sc[0]), float(sc[1]), area


def glo30_loader(dem_dir, kind):
    """Copernicus GLO-30 COG tiles (DEM, EDM, FLM); pixel spacing from the file (2400 columns above 50 N)."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None

    def load(N, E):
        p = os.path.join(dem_dir, "Copernicus_DSM_COG_10_N%02d_00_E%03d_00_%s.tif" % (N, E, kind))
        if not os.path.exists(p):
            return None
        im = Image.open(p)
        top, left, sx, sy, area = _geotiff_geo(im)
        a = np.array(im, dtype=np.float32 if kind == "DEM" else np.uint8)
        if abs(top - (N + 1)) > 1e-6 or abs(left - E) > 1e-6:
            raise Stop("GLO-30 tile name and georeference disagree: %s" % os.path.basename(p))
        return Cell(a, top, left, 1.0 / sy, 1.0 / sx, area)
    return load


def aw3d_loader(tif_path):
    """AW3D30 single-band mosaic read lazily one-degree cell at a time (crop of the cell-edge raster; heights in whole metres)."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(tif_path)
    top0, left0, sx, sy, area = _geotiff_geo(im)
    W, H = im.size
    ppx, ppy = 1.0 / sx, 1.0 / sy

    def load(N, E):
        x0, y0 = (E - left0) * ppx, (top0 - (N + 1)) * ppy
        if abs(x0 - round(x0)) > 1e-3 or abs(y0 - round(y0)) > 1e-3:
            raise Stop("AW3D30 mosaic is not aligned to the one-degree grid")
        x0, y0 = int(round(x0)), int(round(y0))
        x1, y1 = x0 + int(round(ppx)), y0 + int(round(ppy))
        if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
            return None
        a = np.asarray(im.crop((x0, y0, x1, y1)), dtype=np.int32).astype(np.int16)
        return Cell(a, N + 1, E, ppy, ppx, area)
    return load


# ------------------------------------------------------------------ statistics (known-answer tested)
def hat_variances(v_fn, v_fa, v_na):
    """Three-cornered hat: var(d_ij) = s_i^2 + s_j^2 for the pairs F-N, F-A, N-A -> error variances of F, N, A (assumes uncorrelated errors)."""
    sf = (v_fn + v_fa - v_na) / 2.0
    sn = (v_fn + v_na - v_fa) / 2.0
    sa = (v_fa + v_na - v_fn) / 2.0
    return sf, sn, sa


def day_index(days):
    ud = np.array(sorted(set(days)))
    return ud, np.searchsorted(ud, np.asarray(days))


def boot_weights(nd, nb, seed=SEED):
    rng = np.random.default_rng(seed)
    W = np.zeros((nb, nd))
    for b in range(nb):
        W[b] = np.bincount(rng.integers(0, nd, nd), minlength=nd)
    return W


def _day_moments(d, di, nd):
    n, s1, s2 = np.zeros(nd), np.zeros(nd), np.zeros(nd)
    np.add.at(n, di, 1.0)
    np.add.at(s1, di, d)
    np.add.at(s2, di, d * d)
    return n, s1, s2


def var_draws(d, di, nd, W):
    """Population variance of d at the point (all days) and under the day weights W (nb x nd)."""
    n, s1, s2 = _day_moments(d, di, nd)
    def v(w):
        N = w @ n
        return (w @ s2) / N - ((w @ s1) / N) ** 2
    return float(v(np.ones(nd))), v(W)


def pct_ci(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))] if len(x) > 20 else [None, None]


def hat_block(g_f, g_n, g_a, days, W=None, nb=NB_DEFAULT):
    """Step grades (pp) of the three corners on one step set. Returns the error standard deviations with day-clustered intervals, the reliability of the FABDEM step grade and the identification flag."""
    g_f, g_n, g_a = (np.asarray(x, float) for x in (g_f, g_n, g_a))
    ud, di = day_index(days)
    nd = len(ud)
    if W is None:
        W = boot_weights(nd, nb)
    p1, b1 = var_draws(g_f - g_n, di, nd, W)
    p2, b2 = var_draws(g_f - g_a, di, nd, W)
    p3, b3 = var_draws(g_n - g_a, di, nd, W)
    pf, pn, pa = hat_variances(p1, p2, p3)
    bf, bn, ba = hat_variances(b1, b2, b3)
    out = {"n_steps": int(len(g_f)), "n_days": int(nd), "var_diff_pp2": {"F-N": p1, "F-A": p2, "N-A": p3}, "identified": bool(pf > 0 and pn > 0 and pa > 0)}
    pv_f, _ = var_draws(g_f, di, nd, W)
    for key, p, b in (("F", pf, bf), ("N", pn, bn), ("A", pa, ba)):
        s = float(math.sqrt(p)) if p > 0 else None
        sd = np.where(b > 0, np.sqrt(np.where(b > 0, b, 1.0)), np.nan)
        out["s_" + key] = {"var_pp2": float(p), "sd_pp": s, "ci95_pp": pct_ci(sd), "share_draws_nonpositive": float(np.mean(b <= 0))}
    out["lambda_F"] = float(1.0 - pf / pv_f) if pv_f > 0 else None
    return out


def verdict_one(block):
    """Adequacy word from one hat block (spec 4 R3, thresholds frozen): not identified when any variance is not positive."""
    if not block["identified"]:
        return "not identified"
    s = block["s_F"]
    lo, hi = s["ci95_pp"]
    if lo is None or hi is None:
        return "not identified"
    if s["sd_pp"] > S_NOT_ADEQUATE or lo > S_CI_UPPER:
        return "not adequate"
    if s["sd_pp"] <= S_ADEQUATE and hi <= S_CI_UPPER:
        return "adequate"
    return "marginal"


ORDER = {"adequate": 0, "marginal": 1, "not adequate": 2}


def worst(words):
    """Worse verdict of several (spec 8.3 / 10.4): any 'not identified' makes the whole 'not identified'."""
    words = list(words)
    if any(w == "not identified" for w in words):
        return "not identified"
    return max(words, key=lambda w: ORDER[w])


def ladder(word, checks_complete):
    """Spec 10.1: only 'not adequate' may be final; 'adequate' and 'marginal' are provisional unless every check ran (stratum, fill mask, provenance)."""
    if word in ("not adequate", "not identified"):
        return word
    return word if checks_complete else "provisional (upper bound): %s" % word


# ------------------------------------------------------------------ 2SLS (descriptive; known-answer tested)
def iv_fit(Xe, Z, y, days, W=None, nb=NB_DEFAULT, endog=-1):
    """2SLS of y on the columns of Xe (the endogenous column is Xe[:, endog]) with instruments Z (the exogenous columns of Xe plus the instrument columns). Day-clustered bootstrap of both stages,
    cluster-robust first-stage F of the excluded instruments, and a cluster-robust J statistic (descriptive)."""
    Xe, Z, y = np.asarray(Xe, float), np.asarray(Z, float), np.asarray(y, float)
    ud, di = day_index(days)
    nd = len(ud)
    kx, kz = Xe.shape[1], Z.shape[1]
    sx, sz = np.sqrt((Xe ** 2).mean(axis=0)) + 1e-12, np.sqrt((Z ** 2).mean(axis=0)) + 1e-12
    Xs, Zs = Xe / sx, Z / sz
    ZZ, ZX, Zy = np.zeros((nd, kz, kz)), np.zeros((nd, kz, kx)), np.zeros((nd, kz))
    for d in range(nd):
        m = di == d
        ZZ[d], ZX[d], Zy[d] = Zs[m].T @ Zs[m], Zs[m].T @ Xs[m], Zs[m].T @ y[m]

    def solve(w):
        ZZw = np.einsum("...d,dij->...ij", w, ZZ)
        ZXw = np.einsum("...d,dij->...ij", w, ZX)
        Zyw = np.einsum("...d,di->...i", w, Zy)
        P = np.linalg.pinv(ZZw)
        A = np.swapaxes(ZXw, -1, -2) @ P
        beta = (np.linalg.pinv(A @ ZXw) @ (A @ Zyw[..., None]))[..., 0]
        return beta
    bpt = solve(np.ones(nd))
    if W is None:
        W = boot_weights(nd, nb)
    bdr = solve(W)
    out = {"n_steps": int(len(y)), "n_days": int(nd), "b_iv": float(bpt[endog] / sx[endog])}
    out["b_iv_ci95"] = pct_ci(bdr[:, endog] / sx[endog])
    # first stage: endogenous column on Z, cluster-robust Wald F for the excluded instruments (the Z columns beyond the exogenous ones)
    excl = list(range(kx - 1, kz))
    xe_s = Xs[:, endog]
    ZZt = Zs.T @ Zs
    iZZ = np.linalg.pinv(ZZt)
    pi = iZZ @ (Zs.T @ xe_s)
    e = xe_s - Zs @ pi
    U = np.zeros((nd, kz))
    for d in range(nd):
        m = di == d
        U[d] = Zs[m].T @ e[m]
    Vc = iZZ @ (U.T @ U) @ iZZ * (nd / max(nd - 1, 1))
    Vx = Vc[np.ix_(excl, excl)]
    out["first_stage_F"] = float(pi[excl] @ np.linalg.pinv(Vx) @ pi[excl] / len(excl))
    # J (descriptive): overidentifying restriction, cluster-robust weight matrix
    u = y - Xs @ bpt
    gbar = Zs.T @ u / len(y)
    Gc = np.zeros((nd, kz))
    for d in range(nd):
        m = di == d
        Gc[d] = Zs[m].T @ u[m]
    S = Gc.T @ Gc / len(y)
    out["J_overid"] = float(len(y) * gbar @ np.linalg.pinv(S) @ gbar)
    out["overid_df"] = int(kz - kx)
    return out


# ------------------------------------------------------------------ manifest
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def sha256_tar_member(tar_path, member):
    h = hashlib.sha256()
    with tarfile.open(tar_path, "r:gz") as t:
        m = t.getmember(member)
        if not m.isfile() or "/" in m.name or ".." in m.name:
            raise Stop("unexpected archive member %s" % member)
        f = t.extractfile(m)
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def used_files(dem_dir):
    """(group, relative path) of every file the run reads."""
    out = []
    for t in TILES:
        out.append(("fabdem", "fabdem/%s_FABDEM_V1-2.tif" % t))
        N, E = int(t[1:3]), int(t[4:7])
        out.append(("nasadem", "nasadem/NASADEM_HGT_n%02de%03d.zip" % (N, E)))
        for k in ("DEM", "EDM", "FLM"):
            out.append(("glo30", "glo30/Copernicus_DSM_COG_10_N%02d_00_E%03d_00_%s.tif" % (N, E, k)))
    out.append(("aw3d30", "aw3d30/rasters_AW3D30.tar.gz"))
    return out


PROVENANCE = {
    "fabdem": {"product": "FABDEM v1.2 (University of Bristol)", "licence": "non-commercial use", "source": "https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/"},
    "nasadem": {"product": "NASADEM_HGT v001 (NASA LP DAAC), one zip per tile with .hgt, .num, .swb", "licence": "NASA open data", "source": "https://www.earthdata.nasa.gov/data/catalog/lpcloud-nasadem-hgt-001"},
    "aw3d30": {"product": "ALOS World 3D 30 m (AW3D30) V3.2 Jan 2021, average-downsampled JAXA product as distributed by OpenTopography, single-band GeoTIFF mosaic (output_AW3D30.tif) inside a tar.gz; no mask layer",
               "licence": "portal licence field 'not provided'; acknowledge OpenTopography and JAXA", "source": "https://portal.opentopography.org/raster?opentopoID=OTALOS.112016.4326.2", "doi": "10.5069/G94M92HB", "downloadDate": "2026-11-24 (file timestamp)"},
    "glo30": {"product": "Copernicus DEM GLO-30 COG (DEM, EDM, FLM) from the public AWS bucket copernicus-dem-30m", "licence": "Copernicus DEM licence (see ESA)", "source": "https://copernicus-dem-30m.s3.amazonaws.com/"},
}


def write_manifest(dem_dir, out_path):
    files = []
    for grp, rel in used_files(dem_dir):
        p = os.path.join(dem_dir, rel)
        if not os.path.exists(p):
            raise Stop("missing file %s" % rel)
        files.append({"group": grp, "file": rel, "bytes": os.path.getsize(p), "sha256": sha256_file(p)})
    tar_p = os.path.join(dem_dir, "aw3d30", "rasters_AW3D30.tar.gz")
    man = {"milestone": "M762", "spec": "analyses/M762_spec.md Rev 6", "provenance": PROVENANCE, "files": files,
           "aw3d30_member": {"name": "output_AW3D30.tif", "sha256": sha256_tar_member(tar_p, "output_AW3D30.tif")}}
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, indent=1)
    return man


def verify_manifest(dem_dir, man_path):
    if not os.path.exists(man_path):
        raise Stop("manifest missing: %s" % man_path)
    with open(man_path, encoding="utf-8") as f:
        man = json.load(f)
    for e in man["files"]:
        p = os.path.join(dem_dir, e["file"])
        if not os.path.exists(p) or os.path.getsize(p) != e["bytes"] or sha256_file(p) != e["sha256"]:
            raise Stop("manifest mismatch: %s" % e["file"])
    tar_p = os.path.join(dem_dir, "aw3d30", "rasters_AW3D30.tar.gz")
    if sha256_tar_member(tar_p, man["aw3d30_member"]["name"]) != man["aw3d30_member"]["sha256"]:
        raise Stop("manifest mismatch: AW3D30 member")
    return man


# ------------------------------------------------------------------ the run (needs the real tiles, the cloud store and the raw files; optional stage)
def _hist_ranges(counts):
    out = {n: 0 for n, _, _ in NUM_RANGES}
    other = 0
    for v, c in counts.items():
        for n, lo, hi in NUM_RANGES:
            if lo <= v <= hi:
                out[n] += int(c)
                break
        else:
            other += int(c)
    out["undocumented"] = other
    return out


def integrity_stage(dem_dir):
    """C0 coding checks on the real tiles: NASADEM NUM codes must be documented codes only; GLO-30 EDM / FLM unflagged code = the dominant value (share above 0.9)."""
    from PIL import Image
    num_counts, edm_c, flm_c = {}, {}, {}
    for t in TILES:
        N, E = int(t[1:3]), int(t[4:7])
        cell = hgt_loader(os.path.join(dem_dir, "nasadem"), "num")(N, E)
        u, c = np.unique(cell.a, return_counts=True)
        for v, k in zip(u, c):
            num_counts[int(v)] = num_counts.get(int(v), 0) + int(k)
        for kind, acc in (("EDM", edm_c), ("FLM", flm_c)):
            cell = glo30_loader(os.path.join(dem_dir, "glo30"), kind)(N, E)
            u, c = np.unique(cell.a, return_counts=True)
            for v, k in zip(u, c):
                acc[int(v)] = acc.get(int(v), 0) + int(k)
    ranges = _hist_ranges(num_counts)
    if ranges["undocumented"] > 0:
        raise Stop("NASADEM NUM carries undocumented codes: %s" % ranges)
    modes = {}
    for name, acc in (("EDM", edm_c), ("FLM", flm_c)):
        tot = sum(acc.values())
        v, k = max(acc.items(), key=lambda kv: kv[1])
        if k / tot < 0.9:
            raise Stop("GLO-30 %s has no dominant code above 0.9 share" % name)
        modes[name] = {"unflagged_code": int(v), "share": k / tot, "histogram_share": {str(a): b / tot for a, b in sorted(acc.items())}}
    tot = sum(num_counts.values())
    return {"nasadem_num_share_by_range": {k: v / tot for k, v in ranges.items()}, "glo30_masks": modes,
            "glo30_coding_note": "the EDM / FLM value meanings could not be read from the product handbook (host unreachable); the unflagged code is taken as the dominant value and any other value counts as flagged (edited or filled)"}


def build_surfaces(dem_dir):
    import dem_step_grade as dsg
    sf = dsg.Dem(os.path.join(dem_dir, "fabdem"))
    sn = Surface(hgt_loader(os.path.join(dem_dir, "nasadem"), "hgt"), name="nasadem")
    numS = Surface(hgt_loader(os.path.join(dem_dir, "nasadem"), "num"), None, "nasadem_num")
    import tempfile
    tmp = tempfile.mkdtemp(prefix="m762_aw3d_", dir=dem_dir)
    with tarfile.open(os.path.join(dem_dir, "aw3d30", "rasters_AW3D30.tar.gz"), "r:gz") as t:
        m = t.getmember("output_AW3D30.tif")
        if not m.isfile() or "/" in m.name or ".." in m.name:
            raise Stop("unexpected AW3D30 archive member")
        with open(os.path.join(tmp, "output_AW3D30.tif"), "wb") as out:
            f = t.extractfile(m)
            for b in iter(lambda: f.read(1 << 22), b""):
                out.write(b)
    sa = Surface(aw3d_loader(os.path.join(tmp, "output_AW3D30.tif")), name="aw3d30")
    sg = Surface(glo30_loader(os.path.join(dem_dir, "glo30"), "DEM"), name="glo30")
    edm = Surface(glo30_loader(os.path.join(dem_dir, "glo30"), "EDM"), None, "glo30_edm")
    flm = Surface(glo30_loader(os.path.join(dem_dir, "glo30"), "FLM"), None, "glo30_flm")
    return sf, sn, sa, sg, numS, edm, flm, tmp


def collect_multi(args, dems):
    """Steps of the registered corpus (central scenario, primary shift) with the step height difference of every source. Same step set for every source (the step selection does not depend on the DEM)."""
    import bisect
    import pandas as pd
    import dem_step_grade as dsg
    mi, mc, mg = dsg.mi, dsg.mc, dsg.mg
    master = mc.load_master(args.master)
    dmaster = pd.read_csv(args.master)
    regime = {}
    if os.path.exists(args.seasonal):
        sd = pd.read_csv(args.seasonal, usecols=["file", "thermal_regime"])
        regime = dict(zip(sd["file"], sd["thermal_regime"]))
    geo = mi.load_stream(args.store, "Geolocation")
    cpos = [(t, mc.fnum(x["LocationLatitude"]), mc.fnum(x["LocationLongitude"])) for t, x in geo]
    cpos = [(t, la, lo) for t, la, lo in cpos if la is not None and lo is not None and not (la == 0 and lo == 0) and mc.BOX[0] <= la <= mc.BOX[1] and mc.BOX[2] <= lo <= mc.BOX[3]]
    ct, cla, clo = np.array([c[0] for c in cpos]), np.array([c[1] for c in cpos]), np.array([c[2] for c in cpos])
    idx = mg.raw_index(args.raw_dir)
    mrows = {r["file"]: r for _, r in dmaster.iterrows()}
    rows_all = []
    fixes = {k: [0, 0] for k in dems}                   # fixes with a value / fixes tried (all sources)
    for m in master:
        key = __import__("re").sub(r"\D", "", os.path.basename(m["file"]))
        path = idx.get(key)
        if not path:
            continue
        i0, i1 = bisect.bisect_left(ct, m["t0"] - 60.0), bisect.bisect_right(ct, m["t1"] + 60.0)
        if i1 - i0 < 2:
            continue
        mrow = mrows.get(m["file"])
        if mrow is None:
            continue
        arr = dsg.drive_arrays(args.raw_dir, path, mrow, m["t0"], "central", None)
        fuel = arr is not None
        if arr is None:
            arr = dsg.speed_only_arrays(path, m["t0"])
            if arr is None:
                continue
        base, _ = dsg.build_steps(arr, ct[i0:i1], cla[i0:i1], clo[i0:i1], dems["F"], dsg.PRIMARY_SHIFT)
        if not base:
            continue
        for k, d in dems.items():
            if k == "F":
                hh = d.height(cla[i0:i1], clo[i0:i1])
                fixes[k][0] += int(np.isfinite(hh).sum()); fixes[k][1] += len(hh)
                continue
            rk, _ = dsg.build_steps(arr, ct[i0:i1], cla[i0:i1], clo[i0:i1], d, dsg.PRIMARY_SHIFT)
            if len(rk) != len(base):
                raise Stop("step sets differ between sources (internal error)")
            real = k in ("N", "A", "G")
            for r0, r1 in zip(base, rk):
                r0["dh_" + k] = r1["dh"]
                if real:
                    r0["dhpl_" + k], r0["dhpr_" + k] = r1["dh_pl"], r1["dh_pr"]
            if real:
                hh = d.height(cla[i0:i1], clo[i0:i1])
                fixes[k][0] += int(np.isfinite(hh).sum()); fixes[k][1] += len(hh)
        for r in base:
            r.update({"day": m["date"], "drive": m["file"], "cohort": regime.get(m["file"], "unknown"), "fuel": fuel})
        rows_all.extend(base)
    return pd.DataFrame(rows_all), fixes


def _grades(df):
    df = df.copy()
    df["gF"] = 100.0 * df["dh"] / df["d_m"]
    for k in ("N", "A", "G"):
        df["g" + k] = 100.0 * df["dh_" + k] / df["d_m"]
    return df


def analyse(df, nb, glo_checks):
    """All stages on the collected steps. Returns the result dict (aggregates only)."""
    import dem_step_grade as dsg
    import pandas as pd
    df = _grades(df)
    res = {}
    base = df[~df["first"] & ~df["last"] & (df["vmin_kmh"] >= dsg.V_MIN_KMH)]
    stages = {"all_steps_before_exclusions": int(len(df)), "after_first_last_speed": int(len(base))}
    cs = base[np.isfinite(base["gF"]) & np.isfinite(base["gN"]) & np.isfinite(base["gA"])]
    stages["common_support_F_N_A_finite"] = int(len(cs))
    nasok = cs[np.isfinite(cs["dh_num"])]
    stages["after_nasadem_num_srtm_mask"] = int(len(nasok))
    gloOK = nasok[np.isfinite(nasok["dh_glo"])]
    stages["after_glo30_unflagged_mask"] = int(len(gloOK))
    prim = gloOK[gloOK["gF"].abs() <= dsg.GRADE_EXCL_PP]
    stages["after_fabdem_grade_8pp_exclusion"] = int(len(prim))
    res["C1_step_stages"] = stages
    sets = {"primary": prim,
            "no_glo_flag_exclusion": nasok[nasok["gF"].abs() <= dsg.GRADE_EXCL_PP],
            "outlier_screened": prim[np.isfinite(prim["dh_screen"])],
            "untouched_stratum": prim[np.isfinite(prim["dh_untouched"])]}
    med = nasok[["gF", "gN", "gA"]].median(axis=1)
    sets["grade_exclusion_on_cross_source_median"] = gloOK[med.loc[gloOK.index].abs() <= dsg.GRADE_EXCL_PP]
    support = {}
    blocks, words = {}, {}
    for name, d in sets.items():
        days = d["day"].values
        ud = len(set(days))
        km = float(d["d_m"].sum() / 1000.0)
        n2 = int((100.0 * d["dh"].abs() / d["d_m"] > 2.0).sum())
        floors = {"days": ud, "km": km, "steps_above_2pp": n2, "met": bool(ud >= 30 and km >= 100.0 and n2 >= 1000)}
        support[name] = floors
        if len(d) < 50:
            continue
        W = boot_weights(len(set(days)), nb)
        blocks[name] = {"all": hat_block(d["gF"], d["gN"], d["gA"], days, W, nb)}
        for lab, lo_, hi_ in (("300_500m", 300.0, 500.0), ("500_900m", 500.0, 900.0001)):
            s = d[(d["d_m"] >= lo_) & (d["d_m"] < hi_)]
            if len(s) >= 50 and len(set(s["day"])) >= 5:
                blocks[name][lab] = hat_block(s["gF"], s["gN"], s["gA"], s["day"].values, boot_weights(len(set(s["day"])), nb), nb)
        words[name] = {k: verdict_one(v) for k, v in blocks[name].items()}
    res["C0_support"] = support
    res["C3_hat"] = blocks
    res["C3_verdict_words"] = words
    # verdict (spec 8.3, 10.1, 10.4): worse of overall and 500-900 m, of primary and screened, and of the untouched stratum; provisional unless every check ran
    comps = []
    for name in ("primary", "outlier_screened", "untouched_stratum"):
        w = words.get(name, {})
        for k in ("all", "500_900m"):
            if k in w:
                comps.append(w[k])
    stratum_ok = "untouched_stratum" in words and support["untouched_stratum"]["met"]
    complete = bool(stratum_ok and glo_checks)
    base_word = worst(comps) if comps else "not testable"
    res["R3"] = {"components": comps, "worst": base_word, "checks_complete": complete,
                 "final_wording": ladder(base_word, complete) if comps else "not testable",
                 "missing_checks": [] if complete else (["untouched stratum below the support floors or not run"] if not stratum_ok else []) + ([] if glo_checks else ["GLO-30 fill mask not applied"]),
                 "limits": ["common-mode errors are not identified (position error, embankments, bridges, shared smoothing); s_F is the inter-product DEM error only",
                            "correlation between NASADEM and AW3D30 (AW3D30 has no mask; fills from SRTM or other products) inflates s_F and can give a spurious 'not adequate'",
                            "correlation between FABDEM and a corner, and FABDEM fill cells not covered by the GLO-30 mask rule, bias s_F downwards",
                            "NASADEM and AW3D30 heights are whole metres (quantisation about 0.08 pp of grade on a 500 m step), FABDEM is metric floats",
                            "the three-cornered hat assumes uncorrelated errors between sources"]}
    # C2 pairwise agreement on the primary set
    pw = {}
    for a_, b_, lab in (("gF", "gN", "F-N"), ("gF", "gA", "F-A"), ("gN", "gA", "N-A")):
        pw[lab] = dsg.f1_stats(prim[a_].values, prim[b_].values, prim["day"].values, nb)
    res["C2_pairwise_primary"] = pw
    # C4: grade coefficient with each source, placebo per source, 2SLS (descriptive)
    prim_all = prim
    prim = prim[prim["fuel"]]                              # the energy-balance fits need the traction reconstruction (fuel-flow channel), as in M757 F2; C2, C3, C5 and C6 use every step
    res["C4_fuel_instrumented_steps"] = {"n_steps": int(len(prim)), "n_drives": int(prim["drive"].nunique()), "n_days": int(prim["day"].nunique()), "km": float(prim["d_m"].sum() / 1000.0)}
    days_u = sorted(prim["day"].unique())
    Wd = dsg.boot_weights(len(days_u), nb)
    fits = {}
    for lab, col, pl, pr in (("F", "dh", "dh_pl", "dh_pr"), ("N", "dh_N", "dhpl_N", "dhpr_N"), ("A", "dh_A", "dhpl_A", "dhpr_A"), ("G", "dh_G", "dhpl_G", "dhpr_G")):
        if col not in prim:
            continue
        sub = prim[np.isfinite(prim[col])]
        if lab == "F":
            sub = prim
        f = dsg.fit_b(sub, col, W=Wd, nb=nb, all_days=days_u)
        p1 = dsg.fit_b(sub, pl if lab != "F" else "dh_pl", W=Wd, nb=nb, all_days=days_u)
        p2 = dsg.fit_b(sub, pr if lab != "F" else "dh_pr", W=Wd, nb=nb, all_days=days_u)
        fits[lab] = {"b": {k: v for k, v in f.items() if not k.startswith("_")}, "placebo_left": {k: v for k, v in p1.items() if not k.startswith("_")}, "placebo_right": {k: v for k, v in p2.items() if not k.startswith("_")}}
    res["C4_b_per_source"] = fits
    pv = prim[np.isfinite(prim["E_kJ"])]
    Xe, y = dsg.design(pv, "dh")
    pe = lambda c: dsg.MASS_KG * dsg.G * pv[c].values / 1000.0
    Z = np.column_stack([Xe[:, :4], pe("dh_N"), pe("dh_A")])
    iv = iv_fit(Xe, Z, y, pv["day"].values, None, nb)
    iv["reported"] = bool(iv["first_stage_F"] >= 10.0)
    if not iv["reported"]:
        iv["b_iv"], iv["b_iv_ci95"] = None, [None, None]
        iv["note"] = "first-stage F below 10: b_IV not reported"
    iv["label"] = "descriptive; conditional on the traction reconstruction and the assumed mass; never 'validated' or 'corrected'"
    res["C4_2sls"] = iv
    prim = prim_all
    # C5 diagnostic and untouched stratum share
    res["C5_untouched_share_of_primary"] = float(len(sets["untouched_stratum"]) / max(len(prim), 1))
    res["C5_fill_signature_share_aw3d30_vs_nasadem_both_fixes_within_0.5m"] = float(np.isfinite(prim["dh_fillsig"]).mean()) if "dh_fillsig" in prim else None
    # C6 grade classes
    cl = lambda g: np.digitize(g, dsg.CLASS_EDGES)
    cls = {}
    for k in ("F", "N", "A", "G"):
        g = prim["g" + k].values
        ok = np.isfinite(g)
        cls[k] = {"step_share": [float(np.mean(cl(g[ok]) == i)) for i in range(5)], "n": int(ok.sum())}
    res["C6_class_shares"] = cls
    res["C6_misclassification_vs_fabdem"] = {k: float(np.mean(cl(prim["gF"].values) != cl(prim["g" + k].values))) for k in ("N", "A")}
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dem-dir", default=os.environ.get("XT_DEM_DIR") or "")
    ap.add_argument("--store", default=None)
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or "")
    ap.add_argument("--out-dir", default=os.path.join(HERE, "..", "analyses"))
    ap.add_argument("--master", default=os.path.join(HERE, "..", "drive_master.csv"))
    ap.add_argument("--seasonal", default=os.path.join(HERE, "..", "seasonal_drive_master.csv"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    ap.add_argument("--cache", default="")
    a = ap.parse_args(argv)
    man_path = os.path.join(HERE, "..", "analyses", "M762_dem_manifest.json")     # fixed: the manifest committed with the spec, never the output folder
    for sub in ("fabdem", "nasadem", "aw3d30", "glo30"):
        if not a.dem_dir or not os.path.isdir(os.path.join(a.dem_dir, sub)):
            print("dem_crosscheck: DEM directories missing, skipped (optional)")
            return 0
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        if a.manifest:
            man = write_manifest(a.dem_dir, man_path)
            print("dem_crosscheck: manifest written, %d files" % len(man["files"]))
            return 0
        if not a.run:
            print(__doc__)
            return 0
        import mynissan_import as mi
        a.store = a.store or mi.default_store()
        if not os.path.exists(os.path.join(a.store, "manifest.json")) or not os.path.isdir(a.raw_dir):
            print("dem_crosscheck: no cloud store or raw directory, skipped (optional)")
            return 0
        verify_manifest(a.dem_dir, man_path)
        import dem_step_grade as dsg
        if dsg.mc.md5(a.master) != dsg.PINNED_MD5:
            print("dem_crosscheck: master pin failed")
            return 1
        c0 = integrity_stage(a.dem_dir)
        sf, sn, sa, sg, numS, edm, flm, tmp = build_surfaces(a.dem_dir)
        try:
            dems = {"F": sf, "N": sn, "A": sa, "G": sg, "num": num_mask(numS),
                    "glo": glo_unflagged_mask(edm, flm, c0["glo30_masks"]["EDM"]["unflagged_code"], c0["glo30_masks"]["FLM"]["unflagged_code"]),
                    "screen": screen_mask(sf, sn, sa), "untouched": diff_mask(sf, sg, UNTOUCHED_M, "fabdem_glo30_within_2m"), "fillsig": diff_mask(sa, sn, FILLSIG_M, "aw3d30_nasadem_within_0.5m")}
            if a.cache and os.path.exists(a.cache):
                import pickle
                df, fixes = pickle.load(open(a.cache, "rb"))
            else:
                df, fixes = collect_multi(a, dems)
                if a.cache:
                    import pickle
                    pickle.dump((df, fixes), open(a.cache, "wb"))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        res = analyse(df, a.nb, glo_checks=True)
        res.update({"milestone": "M762", "spec": "analyses/M762_spec.md Rev 6", "masterMd5": dsg.PINNED_MD5, "m757_tool_sha256": sha256_file(os.path.join(HERE, "dem_step_grade.py")),
                    "tool_sha256": sha256_file(os.path.abspath(__file__)), "manifest_sha256": sha256_file(man_path), "seed": SEED, "nBoot": a.nb, "C0_codings": c0,
                    "C0_coverage_fixes": {k: {"with_value": v[0], "tried": v[1], "share": (v[0] / v[1] if v[1] else None)} for k, v in fixes.items() if v[1]},
                    "privacy": "aggregates only; no coordinates, tracks or per-drive geometry"})
        if dsg.mc.md5(a.master) != dsg.PINNED_MD5:
            print("dem_crosscheck: master changed during the run")
            return 1
        os.makedirs(a.out_dir, exist_ok=True)
        with open(os.path.join(a.out_dir, "M762_dem_crosscheck.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, default=lambda o: None if o != o else str(o))
        print("dem_crosscheck: verdict", res["R3"]["final_wording"], "| worst", res["R3"]["worst"], "| complete", res["R3"]["checks_complete"])
        return 0
    except Stop as e:
        print("dem_crosscheck: STOP (%s)" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
