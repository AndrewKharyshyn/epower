#!/usr/bin/env python3
"""M757 (spec analyses/M757_spec.md Rev 2): DEM step grade (FABDEM v1.2) from cloud fixes, feasibility and validation. Auxiliary, report-only, offline.

Stages: F0 tile integrity and coverage; F1 step-grade agreement with logged GPS altitude (descriptive below the support floor); F2 grade-term recovery in an energy balance (CONDITIONAL on the
traction reconstruction; primary: joint fit of road-load terms, a duration term and the potential-energy term with coefficient b); F3 grade-class shares. Nothing is written to the payload,
the dashboard or the master. Aggregates only in the result (public repository): no coordinates, tracks or per-drive geometry. The FABDEM tiles stay outside the repository (env XT_DEM_DIR).

Usage: python tools/dem_step_grade.py [--store DIR] [--raw-dir DIR] [--dem-dir DIR] [--out-dir analyses] [--cache FILE] [--nb 4000]
Exit codes: 0 done or skipped (no tiles / no store / no raw), 1 master pin failed, 3 tile sha256 mismatch."""
import argparse, glob, hashlib, json, math, os, re, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import mynissan_import as mi
import mynissan_coverage as mc
import mynissan_grade as mg

ROOT = mi.ROOT
PINNED_MD5 = mg.PINNED_MD5
SEED, NB_DEFAULT = 42, 4000
G = 9.80665
MASS_KG = 1950.0                         # assumed class mass (compute_summary_arrays.VEHICLE_MASS_KG basis); labelled, never measured
PRIMARY_SHIFT = 16.0                     # Rev 2 9.1: frozen before any DEM value; 0 and -16 are sensitivities
SHIFTS = (16.0, 0.0, -16.0)
STEP_MIN_M, STEP_MAX_M, GAP_MAX_S = 300.0, 900.0, 120.0
GRADE_EXCL_PP = 8.0                      # Rev 2 9.2 (bare-earth flag)
V_MIN_KMH = 8.0                          # Rev 2 9.6
PLACEBO_M = 2000.0                       # Rev 2 9.4
LOW_POWER_KW = 2.0                       # sensitivity only (Rev 2 9.3): mean |traction power| below this is excluded
FLAT_PP = 1.0
MIN_DAYS, MIN_KM, MIN_STEPS_2PP, MIN_DAYS_PER_SIGN = 30, 100.0, 1000, 10
CLASS_EDGES = (-3.0, -1.0, 1.0, 3.0)
CLASS_NAMES = ("below-3", "-3to-1", "-1to1", "1to3", "above3")
R4_BIAS, R4_BIAS_CI, R4_MAD = 0.5, 1.0, 1.5
R3_LO, R3_HI = 0.8, 1.25
SPEED_CLASSES = mg.SPEED_CLASSES
LICENCE = "FABDEM v1.2, University of Bristol; non-commercial use"


class TileMismatch(Exception):
    pass


# ------------------------------------------------------------------ DEM reader (known-answer tested)
def read_tile(path):
    """Read one FABDEM GeoTIFF: (array float32 with NaN at nodata, top latitude, left longitude, pixels per degree, raster type 'point'|'area').
    The raster type comes from GTRasterTypeGeoKey (1025: 1 area, 2 point); the real tiles are flagged point."""
    from PIL import Image
    im = Image.open(path)
    arr = np.array(im, dtype=np.float32)
    tag = im.tag_v2
    sc, tie = tag.get(33550), tag.get(33922)
    if sc is None or tie is None:
        raise ValueError("GeoTIFF without ModelPixelScale/ModelTiepoint: %s" % os.path.basename(path))
    n = arr.shape[1]
    if abs(sc[0] * n - 1.0) > 1e-6 or abs(sc[1] * arr.shape[0] - 1.0) > 1e-6:
        raise ValueError("tile is not one degree wide at the stated pixel scale")
    keys = tag.get(34735) or ()
    rtype = "area"
    for i in range(4, len(keys) - 3, 4):
        if keys[i] == 1025:
            rtype = "point" if keys[i + 3] == 2 else "area"
    nod = tag.get(42113)
    if nod is not None:
        try:
            arr[arr == np.float32(float(nod))] = np.nan
        except ValueError:
            pass
    return arr, float(tie[4]), float(tie[3]), n, rtype


class Dem:
    """Global grid of one-degree tiles; bilinear height. Node space: lat = Y / n (rows decrease with Y), lon = X / n; an area-type raster is the same grid shifted half a pixel."""

    def __init__(self, dem_dir=None, tiles=None):
        self.dir, self.tiles, self.n, self.rtype, self.used = dem_dir, {}, None, None, set()
        if tiles:
            for (N, E), a in tiles.items():
                self.tiles[(N, E)] = a
            self.n = next(iter(tiles.values())).shape[1]
            self.rtype = "point"

    def _tile(self, N, E):
        if (N, E) not in self.tiles:
            p = os.path.join(self.dir, "N%02dE%03d_FABDEM_V1-2.tif" % (N, E)) if self.dir else None
            if p and os.path.exists(p):
                a, top, left, n, rt = read_tile(p)
                if int(round(top)) - 1 != N or int(round(left)) != E:
                    raise ValueError("tile name and georeference disagree: %s" % os.path.basename(p))
                self.tiles[(N, E)] = a
                self.n, self.rtype = n, rt
            else:
                self.tiles[(N, E)] = None
        if self.tiles[(N, E)] is not None:
            self.used.add((N, E))
        return self.tiles[(N, E)]

    def _nodes(self, Y, X):
        n = self.n
        out = np.full(Y.shape, np.nan)
        N, E = (Y - 1) // n, X // n
        code = N * 100000 + E
        for c in np.unique(code):
            m = code == c
            nn, ee = int(N[m][0]), int(E[m][0])
            a = self._tile(nn, ee)
            if a is None:
                continue
            row, col = (nn + 1) * n - Y[m], X[m] - ee * n
            ok = (row >= 0) & (row < a.shape[0]) & (col >= 0) & (col < a.shape[1])
            v = np.full(row.shape, np.nan)
            v[ok] = a[row[ok], col[ok]]
            out[m] = v
        return out

    def height(self, lat, lon):
        lat, lon = np.atleast_1d(np.asarray(lat, float)), np.atleast_1d(np.asarray(lon, float))
        if self.n is None:
            self._tile(int(np.floor(np.nanmin(lat))), int(np.floor(np.nanmin(lon))))
        n = self.n or 3600
        sh = 0.5 if self.rtype == "area" else 0.0
        y, x = lat * n + sh, lon * n - sh
        fin = np.isfinite(y) & np.isfinite(x)
        y0, x0 = np.floor(np.where(fin, y, 0)).astype(np.int64), np.floor(np.where(fin, x, 0)).astype(np.int64)
        fy, fx = y - y0, x - x0
        v00, v01 = self._nodes(y0, x0), self._nodes(y0, x0 + 1)
        v10, v11 = self._nodes(y0 + 1, x0), self._nodes(y0 + 1, x0 + 1)
        h = (1 - fy) * (1 - fx) * v00 + (1 - fy) * fx * v01 + fy * (1 - fx) * v10 + fy * fx * v11
        return np.where(fin, h, np.nan)


def verify_tiles(dem_dir):
    """sha256 of every tile named in the manifest; returns (list of {tile, sha256}, manifest dict). Raises TileMismatch."""
    mp = os.path.join(dem_dir, "fabdem_tiles_manifest.json")
    man = json.load(open(mp, encoding="utf-8"))
    out = []
    for k, v in sorted(man["tiles"].items()):
        p = os.path.join(dem_dir, v["file"])
        if not os.path.exists(p):
            raise TileMismatch("missing tile %s" % v["file"])
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for blk in iter(lambda: f.read(1 << 22), b""):
                h.update(blk)
        if h.hexdigest() != v["sha256"]:
            raise TileMismatch("sha256 mismatch for %s" % v["file"])
        out.append({"tile": k, "sha256": v["sha256"]})
    return out, man


def displace(lat1, lon1, lat2, lon2, dist_m, side=1.0):
    """Both fixes moved dist_m perpendicular to the heading of fix 1 -> fix 2 (side +1 left, -1 right). Returns lat/lon of both fixes (NaN when the heading is undefined)."""
    lat1, lon1, lat2, lon2 = (np.asarray(a, float) for a in (lat1, lon1, lat2, lon2))
    phi = np.radians((lat1 + lat2) / 2)
    dx, dy = (lon2 - lon1) * np.cos(phi), lat2 - lat1
    nrm = np.hypot(dx, dy)
    with np.errstate(invalid="ignore", divide="ignore"):
        ux, uy = dx / nrm, dy / nrm
    px, py = -uy * side, ux * side
    dlat = dist_m * py / 111320.0
    dlon = dist_m * px / (111320.0 * np.cos(phi))
    return lat1 + dlat, lon1 + dlon, lat2 + dlat, lon2 + dlon


# ------------------------------------------------------------------ steps (known-answer tested)
def alt_at(t_alt, alt, tq, half=3.0):
    """Mean of the altitude samples within +-half seconds of each time; NaN with fewer than two samples."""
    t_alt, alt = np.asarray(t_alt, float), np.asarray(alt, float)
    ok = np.isfinite(alt)
    t_alt, alt = t_alt[ok], alt[ok]
    out = np.full(len(tq), np.nan)
    if len(t_alt) < 2:
        return out
    cs = np.concatenate([[0.0], np.cumsum(alt)])
    lo, hi = np.searchsorted(t_alt, np.asarray(tq) - half, "left"), np.searchsorted(t_alt, np.asarray(tq) + half, "right")
    cnt = hi - lo
    good = cnt >= 2
    out[good] = (cs[hi[good]] - cs[lo[good]]) / cnt[good]
    return out


def build_steps(obd, ft, flat, flon, dem, shift=PRIMARY_SHIFT, step_min=STEP_MIN_M, step_max=STEP_MAX_M, gap_max=GAP_MAX_S):
    """Steps between consecutive cloud fixes (times ft, positions flat/flon). The OBD window of a step is [ft_k + shift, ft_k+1 + shift].
    obd: dict t (epoch s), v (m/s), dt (s), P (kW, signed traction at the bus), optional t_alt/alt. Returns a list of per-step dicts (path-independent DEM height difference dh,
    the displaced-DEM placebo heights, OBD distance, energy integrals). Steps outside [step_min, step_max] metres or with a gap above gap_max are counted in 'dropped'."""
    t, v, dt, P = (np.asarray(obd[k], float) for k in ("t", "v", "dt", "P"))
    cD, cV2, cV3 = np.cumsum(v * dt), np.cumsum(v * v * dt), np.cumsum(v ** 3 * dt)
    Pn = np.nan_to_num(P)
    cE, cEn, cEp = np.cumsum(Pn * dt), np.cumsum(np.minimum(Pn, 0.0) * dt), np.cumsum(np.maximum(Pn, 0.0) * dt)
    ft, flat, flon = np.asarray(ft, float), np.asarray(flat, float), np.asarray(flon, float)
    rows, dropped = [], {"gap": 0, "short": 0, "long": 0, "outside_obd": 0}
    n = len(ft)
    h = dem.height(flat, flon) if n else np.zeros(0)
    pairs = [(k, k + 1) for k in range(n - 1)]
    ia = lambda c, x: np.interp(x, t, c)
    in_obd = [(ft[k] + shift >= t[0]) and (ft[k + 1] + shift <= t[-1]) for k, _ in pairs]
    cand = [k for (k, _), ok in zip(pairs, in_obd) if ok]
    first_k, last_k = (cand[0], cand[-1]) if cand else (None, None)
    for (k, k2), ok in zip(pairs, in_obd):
        if not ok:
            dropped["outside_obd"] += 1
            continue
        if ft[k2] - ft[k] > gap_max or ft[k2] <= ft[k]:
            dropped["gap"] += 1
            continue
        a, b = ft[k] + shift, ft[k2] + shift
        d = float(ia(cD, b) - ia(cD, a))
        if d < step_min:
            dropped["short"] += 1
            continue
        if d > step_max:
            dropped["long"] += 1
            continue
        i0, i1 = np.searchsorted(t, a, "left"), np.searchsorted(t, b, "right")
        vmin = float(v[i0:i1].min()) if i1 > i0 else float(min(ia(v, a), ia(v, b)))
        chord = float(mg.hav_arr(flat[k], flon[k], flat[k2], flon[k2]))
        row = {"d_m": d, "T_s": float(b - a), "E_kJ": float(ia(cE, b) - ia(cE, a)), "Eneg_kJ": float(ia(cEn, b) - ia(cEn, a)), "Epos_kJ": float(ia(cEp, b) - ia(cEp, a)),
               "V2": float(ia(cV2, b) - ia(cV2, a)), "V3": float(ia(cV3, b) - ia(cV3, a)), "vs": float(ia(v, a)), "ve": float(ia(v, b)),
               "vmin_kmh": vmin * 3.6, "vmean_kmh": d / (b - a) * 3.6, "chord_m": chord, "first": k == first_k, "last": k == last_k,
               "dh": float(h[k2] - h[k]), "dh_pl": np.nan, "dh_pr": np.nan, "dh_obd": np.nan}
        for side, name in ((1.0, "dh_pl"), (-1.0, "dh_pr")):
            la1, lo1, la2, lo2 = displace(flat[k], flon[k], flat[k2], flon[k2], PLACEBO_M, side)
            hh = dem.height([la1, la2], [lo1, lo2])
            row[name] = float(hh[1] - hh[0]) if np.all(np.isfinite(hh)) else np.nan
        if obd.get("alt") is not None:
            aa = alt_at(obd["t_alt"], obd["alt"], [a, b])
            if np.all(np.isfinite(aa)):
                row["dh_obd"] = float(aa[1] - aa[0])
        rows.append(row)
    return rows, dropped


# ------------------------------------------------------------------ energy-balance regression (known-answer tested)
COLS = ["d_km", "V2", "V3", "T", "mgdh"]            # F0, F1, F2, c (duration, auxiliary load), b (potential energy)


def design(df, dh_col="dh", mass=MASS_KG, split=False):
    """Unscaled design matrix and response in kJ. y = traction net energy of the step minus the kinetic-energy change (assumed mass). Columns: d (km), integral v^2 dt, integral v^3 dt, duration (s),
    then mg*dh (kJ) or, with split, its positive and negative parts."""
    kin = mass * (df["ve"].values ** 2 - df["vs"].values ** 2) / 2.0 / 1000.0
    y = df["E_kJ"].values - kin
    pe = mass * G * df[dh_col].values / 1000.0
    X = [df["d_m"].values / 1000.0, df["V2"].values, df["V3"].values, df["T_s"].values]
    X += [np.where(pe > 0, pe, 0.0), np.where(pe < 0, pe, 0.0)] if split else [pe]
    return np.column_stack(X), y


def day_sums(X, y, di, nd):
    k = X.shape[1]
    A, c, yy, n = np.zeros((nd, k, k)), np.zeros((nd, k)), np.zeros(nd), np.zeros(nd)
    for d in np.unique(di):
        m = di == d
        A[d], c[d], yy[d], n[d] = X[m].T @ X[m], X[m].T @ y[m], float(y[m] @ y[m]), int(m.sum())
    return A, c, yy, n


def solve_w(A, c, w=None, cols=None):
    """Coefficients from per-day sums, with day weights w (bootstrap counts); cols selects a column subset. Batched when w is 2-D; a pseudo-inverse covers draws that leave a column empty."""
    cols = list(range(A.shape[1])) if cols is None else list(cols)
    Ac, cc = A[:, cols][:, :, cols], c[:, cols]
    if w is None:
        w = np.ones(A.shape[0])
    if w.ndim == 1:
        return np.linalg.pinv(np.tensordot(w, Ac, axes=(0, 0))) @ (w @ cc)
    M = np.einsum("bd,dij->bij", w, Ac)
    return (np.linalg.pinv(M) @ (w @ cc)[:, :, None])[:, :, 0]


def boot_weights(nd, nb, seed=SEED):
    rng = np.random.default_rng(seed)
    W = np.zeros((nb, nd))
    for b in range(nb):
        W[b] = np.bincount(rng.integers(0, nd, nd), minlength=nd)
    return W


def ci(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))] if len(x) > 20 else [None, None]


def fit_b(df, dh_col="dh", mass=MASS_KG, W=None, nb=NB_DEFAULT, split=False, flat_first=False, all_days=None):
    """Joint fit of F0, F1, F2, c and b (b = coefficient of m g dh). Returns the point estimate, the day-clustered percentile interval, the standard error of the bootstrap draws,
    the minimum detectable b (2.8 se) and n. Column scaling by the root mean square keeps the normal equations conditioned; coefficients are rescaled back.
    flat_first: road-load terms and the duration term are fitted on DEM-flat steps (|grade| < 1 pp), then b by regression of the residual on m g dh."""
    df = df[np.isfinite(df[dh_col]) & np.isfinite(df["E_kJ"])]
    if len(df) < 20:
        return {"n_steps": int(len(df)), "b": None}
    days = np.array(sorted(df["day"].unique() if all_days is None else all_days))
    di = np.searchsorted(days, df["day"].values)
    nd = len(days)
    X, y = design(df, dh_col, mass, split)
    s = np.sqrt((X ** 2).mean(axis=0)) + 1e-12
    A, c, yy, n = day_sums(X / s, y, di, nd)
    bcols = [4, 5] if split else [4]
    if flat_first:
        flat = (100.0 * df[dh_col].values / df["d_m"].values) ** 2 < FLAT_PP ** 2
        A2, c2, _, _ = day_sums((X / s)[flat], y[flat], di[flat], nd)
        rl = [0, 1, 2, 3]

        def est(w):
            cf = solve_w(A2, c2, w, rl)
            Aw = np.tensordot(w, A, axes=(0, 0)) if w.ndim == 1 else np.einsum("bd,dij->bij", w, A)
            cw = w @ c
            Abx = Aw[..., 4, :4]
            num = cw[..., 4] - (Abx * cf).sum(-1)
            return num / Aw[..., 4, 4] / s[4]
        coef_fn = est
    else:
        def coef_fn(w):
            cf = solve_w(A, c, w)
            return (cf[..., 4] / s[4]) if not split else (cf[..., 4:6] / s[4:6])
    if W is None:
        W = boot_weights(nd, nb)
    pt = coef_fn(np.ones(nd))
    bs = coef_fn(W)
    out = {"n_steps": int(len(df)), "n_drives": int(df["drive"].nunique()), "n_days": int(df["day"].nunique()), "km": float(df["d_m"].sum() / 1000.0)}
    if split:
        for j, nm in enumerate(("b_pos", "b_neg")):
            out[nm] = float(pt[j]); out[nm + "_ci95"] = ci(bs[:, j])
    else:
        out.update({"b": float(pt), "b_ci95": ci(bs), "b_se": float(np.nanstd(bs)), "mde_b": float(2.8 * np.nanstd(bs))})
        if not flat_first:
            out["coefficients"] = dict(zip(("F0_kJ_per_km", "F1_kJ_per_m2s", "F2_kJ_per_m3s2", "c_kJ_per_s", "b"), [float(x) for x in solve_w(A, c) / s]))
        out["_draws"] = bs
    return out


def cv_incremental(df, dh_col="dh", mass=MASS_KG, W=None, nb=NB_DEFAULT):
    """Day-blocked cross-validation (odd / even calendar-day ordinal): fit on one half, score on the other, both directions pooled.
    Incremental R2 = 1 - SSE(with b) / SSE(without b) on the held-out halves; the interval is a day-clustered bootstrap of the pooled held-out sums (fold coefficients held fixed)."""
    df = df[np.isfinite(df[dh_col]) & np.isfinite(df["E_kJ"])]
    days = np.array(sorted(df["day"].unique()))
    if len(days) < 4:
        return {"incremental_r2": None}
    di = np.searchsorted(days, df["day"].values)
    nd = len(days)
    par = np.array([pd.Timestamp(str(d)).toordinal() % 2 for d in days])
    X, y = design(df, dh_col, mass)
    s = np.sqrt((X ** 2).mean(axis=0)) + 1e-12
    A, c, yy, n = day_sums(X / s, y, di, nd)
    sse_f, sse_0, bfold = np.zeros(nd), np.zeros(nd), {}
    for tr in (0, 1):
        w = (par == tr).astype(float)
        cf = solve_w(A, c, w)
        c0 = solve_w(A, c, w, [0, 1, 2, 3])
        bfold["train_parity_%d" % tr] = float(cf[4] / s[4])
        for d in np.where(par != tr)[0]:
            sse_f[d] = yy[d] - 2 * cf @ c[d] + cf @ A[d] @ cf
            cc0 = np.zeros(5); cc0[:4] = c0
            sse_0[d] = yy[d] - 2 * cc0 @ c[d] + cc0 @ A[d] @ cc0
    if W is None:
        W = boot_weights(nd, nb)
    r2 = 1.0 - sse_f.sum() / sse_0.sum()
    bs = 1.0 - (W @ sse_f) / (W @ sse_0)
    return {"incremental_r2": float(r2), "incremental_r2_ci95": ci(bs), "b_fold": bfold, "n_days": int(nd)}


# ------------------------------------------------------------------ F1 statistics (known-answer tested)
def lin_ccc(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3:
        return None
    sa, sb = a.var(), b.var()
    return float(2 * np.cov(a, b, bias=True)[0, 1] / (sa + sb + (a.mean() - b.mean()) ** 2)) if sa + sb > 0 else None


def spearman(a, b):
    ra, rb = pd.Series(a).rank().values, pd.Series(b).rank().values
    return float(np.corrcoef(ra, rb)[0, 1]) if len(a) > 2 else None


def f1_stats(dem_g, obd_g, days, nb=NB_DEFAULT):
    """DEM minus OBD-altitude step grade (pp): bias (median), median absolute difference, P90 of |diff|, Pearson, Spearman, Lin CCC, each with a day-clustered percentile interval."""
    dem_g, obd_g, days = np.asarray(dem_g, float), np.asarray(obd_g, float), np.asarray(days)
    if len(dem_g) < 5:
        return {"n_steps": int(len(dem_g))}
    ud = np.unique(days)
    idx = [np.where(days == u)[0] for u in ud]

    def stats(sel):
        a, b = dem_g[sel], obd_g[sel]
        d = a - b
        return [np.median(d), np.median(np.abs(d)), np.percentile(np.abs(d), 90), np.corrcoef(a, b)[0, 1] if np.std(a) > 0 and np.std(b) > 0 else np.nan, spearman(a, b), lin_ccc(a, b)]
    pt = stats(np.arange(len(dem_g)))
    rng = np.random.default_rng(SEED)
    bs = []
    for _ in range(nb):
        pick = rng.integers(0, len(ud), len(ud))
        bs.append(stats(np.concatenate([idx[i] for i in pick])))
    bs = np.array(bs, float)
    nm = ["bias_median_pp", "median_abs_diff_pp", "p90_abs_diff_pp", "pearson", "spearman", "lin_ccc"]
    out = {"n_steps": int(len(dem_g)), "n_days": int(len(ud))}
    for j, k in enumerate(nm):
        out[k] = float(pt[j]) if pt[j] is not None and np.isfinite(pt[j]) else None
        out[k + "_ci95"] = ci(bs[:, j])
    return out


def r4_decision(f1, days, unique_km):
    """R4: accepted only at the support floor and with |bias| <= 0.5 pp (interval inside +-1.0) and median absolute difference <= 1.5 pp; below the floor F1 is not testable."""
    if days < MIN_DAYS or unique_km < MIN_KM:
        return "not testable (support below %d days / %d unique km)" % (MIN_DAYS, MIN_KM)
    lo, hi = f1.get("bias_median_pp_ci95", [None, None])
    ok = f1.get("bias_median_pp") is not None and lo is not None and abs(f1["bias_median_pp"]) <= R4_BIAS and lo >= -R4_BIAS_CI and hi <= R4_BIAS_CI and f1["median_abs_diff_pp"] <= R4_MAD
    return "accepted" if ok else "not accepted"


# ------------------------------------------------------------------ decisions (known-answer tested)
def r2_decision(base, placebo, cv, support, b_obd, b_obd_testable):
    """R2 (Rev 2 9.4 / 9.5). support: {days, unique_km, n_above2pp, days_pos, days_neg}. Returns the reading and the reasons."""
    why = []
    sup_ok = (support["days"] >= MIN_DAYS and support["unique_km"] >= MIN_KM and support["n_above2pp"] >= MIN_STEPS_2PP
              and support["days_pos"] >= MIN_DAYS_PER_SIGN and support["days_neg"] >= MIN_DAYS_PER_SIGN)
    if not sup_ok:
        return "not testable", ["support below the floors: %s" % json.dumps(support)]
    lo, hi = base["b_ci95"]
    pos = base["b"] > 0 and lo is not None and lo > 0
    folds = all(v > 0 for v in cv.get("b_fold", {}).values()) and cv.get("incremental_r2") is not None and cv["incremental_r2"] > 0 and cv["incremental_r2_ci95"][0] is not None and cv["incremental_r2_ci95"][0] > 0
    plo, phi = placebo["b_ci95"]
    placebo_ok = plo is not None and plo <= 0 <= phi
    if pos and folds:
        if placebo_ok:
            return "informative at step scale", []
        return "inconclusive", ["negative control failed: displaced-DEM placebo interval excludes zero (downgrade one level)"]
    if not pos:
        thr = 0.25 * b_obd if (b_obd_testable and b_obd is not None) else 0.2
        if hi is not None and hi < thr:
            return "not informative at this precision (falsifies 'DEM step grade is usable here')", ["upper bound %.3f below %.3f" % (hi, thr)]
        return "inconclusive", ["b interval not above zero but upper bound %.3f not below %.3f; minimum detectable b %.3f" % (hi if hi is not None else float("nan"), thr, base.get("mde_b", float("nan")))]
    return "inconclusive", ["cross-validation criterion (ii) not met"]


def r3_decision(ratio_ci, obd_days):
    if obd_days < MIN_DAYS:
        return "not testable (logged-altitude days %d < %d)" % (obd_days, MIN_DAYS)
    lo, hi = ratio_ci
    return "met" if lo is not None and lo >= R3_LO and hi <= R3_HI else "not met"


def grade_class(g):
    return np.digitize(g, CLASS_EDGES)


# ------------------------------------------------------------------ I/O driver
def drive_arrays(raw_dir, fname, mrow, t0, scen="central", paux=None):
    """Per-sample traction power (kW, signed, the GTR reconstruction) and speed on the epoch axis. None when the drive has no fuel-flow channel (the reconstruction's own eligibility)."""
    import recon_engine as RE
    import model_constants as MC
    RE.BASE = raw_dir.rstrip("/\\") + "/"
    off = float(mrow.get("I_offset_A_applied", 0.0) or 0.0)
    g = RE.load_drive(os.path.basename(fname), off)
    if g is None:
        return None
    old = MC.P_AUX_KW
    if paux is not None:
        MC.P_AUX_KW = (paux,) + tuple(old[1:])
    try:
        pc = RE.precompute(g)
        agg, ps = RE.central_estimate_v2_persample(pc, mrow, scen)
    finally:
        MC.P_AUX_KW = old
    first = pd.read_csv(os.path.join(raw_dir, os.path.basename(fname)), usecols=["time"], nrows=1)["time"].iloc[0]
    tod = lambda ts: ts.hour * 3600 + ts.minute * 60 + ts.second + ts.microsecond / 1e6
    tod0 = tod(pd.to_datetime(str(first), format="mixed"))
    tg = (g["t"] - g["t"].iloc[0]).dt.total_seconds().values
    tod_g0 = tod(g["t"].iloc[0])
    t = t0 + ((tod_g0 - tod0) % 86400.0) + tg
    v = pd.Series(g["speed"].values, dtype=float).interpolate(limit=5, limit_area="inside").fillna(0.0).values / 3.6
    return {"t": t, "v": v, "dt": g["dt"].values, "P": ps["Ptrac"]}


def altitude_arrays(path, t0):
    o = mg.read_obd(path, t0)
    if o is None or not np.isfinite(o["alt"]).any():
        return None
    return o["t"], o["alt"]


def collect(args, dem, master, dmaster, regime, scens, nb):
    """Build all steps. Returns (steps DataFrame per shift/variant key, coverage dict)."""
    geo = mi.load_stream(args.store, "Geolocation")
    cpos = [(t, mc.fnum(x["LocationLatitude"]), mc.fnum(x["LocationLongitude"])) for t, x in geo]
    cpos = [(t, la, lo) for t, la, lo in cpos if la is not None and lo is not None and not (la == 0 and lo == 0) and mc.BOX[0] <= la <= mc.BOX[1] and mc.BOX[2] <= lo <= mc.BOX[3]]
    ct = np.array([c[0] for c in cpos]); cla = np.array([c[1] for c in cpos]); clo = np.array([c[2] for c in cpos])
    idx = mg.raw_index(args.raw_dir)
    mrows = {r["file"]: r for _, r in dmaster.iterrows()}
    cov = {"screened_fixes_total": int(len(cpos)), "fixes_in_drive_windows": 0, "fixes_with_dem": 0, "drives": len(master), "drives_ge3_fixes": 0, "drives_ge1km_track": 0,
           "track_km": 0.0, "track_km_with_dem": 0.0, "fuel_instrumented_drives_used": 0, "drives_with_altitude_days": 0, "cells": set()}
    tabs = {}
    import bisect
    for m in master:
        key = re.sub(r"\D", "", os.path.basename(m["file"]))
        path = idx.get(key)
        if not path:
            continue
        i0, i1 = bisect.bisect_left(ct, m["t0"] - 60.0), bisect.bisect_right(ct, m["t1"] + 60.0)
        nfix = i1 - i0
        cov["fixes_in_drive_windows"] += nfix
        if nfix:
            hh = dem.height(cla[i0:i1], clo[i0:i1])
            cov["fixes_with_dem"] += int(np.isfinite(hh).sum())
        if nfix >= 3:
            cov["drives_ge3_fixes"] += 1
        if nfix < 2:
            continue
        mrow = mrows.get(m["file"])
        if mrow is None:
            continue
        al = altitude_arrays(path, m["t0"])
        km_track = 0.0
        for scen_key, (scen, paux) in scens.items():
            arr = drive_arrays(args.raw_dir, path, mrow, m["t0"], scen, paux)
            if arr is None:
                break
            if al is not None:
                arr["t_alt"], arr["alt"] = al
            if scen_key == "central":
                cov["fuel_instrumented_drives_used"] += 1
            for shift in SHIFTS if scen_key == "central" else (PRIMARY_SHIFT,):
                rows, drop = build_steps(arr, ct[i0:i1], cla[i0:i1], clo[i0:i1], dem, shift)
                for r in rows:
                    r.update({"day": m["date"], "drive": m["file"], "cohort": regime.get(m["file"], "unknown"), "has_alt": al is not None})
                tabs.setdefault((scen_key, shift), []).extend(rows)
                if scen_key == "central" and shift == PRIMARY_SHIFT:
                    km_track = sum(r["d_m"] for r in rows) / 1000.0
                    cov["track_km"] += km_track
                    cov["track_km_with_dem"] += sum(r["d_m"] for r in rows if np.isfinite(r["dh"])) / 1000.0
                    cov["drives_ge1km_track"] += int(km_track >= 1.0)
                    if al is not None:
                        cov["drives_with_altitude_days"] += 1
                    for la, lo in zip(cla[i0:i1], clo[i0:i1]):
                        cov["cells"].add((int(math.floor(la / mg.CELL_DEG)), int(math.floor(lo / mg.CELL_DEG))))
    return {k: pd.DataFrame(v) for k, v in tabs.items()}, cov


def apply_primary(df):
    """Rev 2 primary exclusions: first and last step of each drive, minimum OBD speed below 8 km/h, |DEM step grade| above 8 pp."""
    g = 100.0 * df["dh"] / df["d_m"]
    return df[~df["first"] & ~df["last"] & (df["vmin_kmh"] >= V_MIN_KMH) & (g.abs() <= GRADE_EXCL_PP)]


def f2_block(prim, nb):
    """All F2 estimands on the primary step set; returns the result dict and the primary fit."""
    days = sorted(prim["day"].unique())
    W = boot_weights(len(days), nb)
    base = fit_b(prim, "dh", W=W, nb=nb, all_days=days)
    pl, pr = fit_b(prim, "dh_pl", W=W, nb=nb, all_days=days), fit_b(prim, "dh_pr", W=W, nb=nb, all_days=days)
    cv = cv_incremental(prim, "dh", W=W, nb=nb)
    return base, pl, pr, cv


def strip(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store())
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--dem-dir", default=os.environ.get("XT_DEM_DIR") or "")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--seasonal", default=os.path.join(ROOT, "seasonal_drive_master.csv"))
    ap.add_argument("--cache", default="")
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    a = ap.parse_args(argv)
    if not a.dem_dir or not os.path.isdir(a.dem_dir) or not os.path.exists(os.path.join(a.dem_dir, "fabdem_tiles_manifest.json")) \
            or not os.path.exists(os.path.join(a.store, "manifest.json")) or not os.path.isdir(a.raw_dir):
        print("dem_step_grade: no DEM tiles, cloud store or raw directory, skipped (optional)")
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        tiles, man = verify_tiles(a.dem_dir)
    except TileMismatch as e:
        print("dem_step_grade: STOP, tile integrity failed:", e)
        return 3
    md5 = mc.md5(a.master)
    if md5 != PINNED_MD5:
        print("dem_step_grade: master pin failed")
        return 1
    master = mc.load_master(a.master)
    dmaster = pd.read_csv(a.master)
    regime = {}
    if os.path.exists(a.seasonal):
        sd = pd.read_csv(a.seasonal, usecols=["file", "thermal_regime"])
        regime = dict(zip(sd["file"], sd["thermal_regime"]))
    dem = Dem(a.dem_dir)
    import model_constants as MC
    scens = {"central": ("central", None), "bsfc_optimistic": ("optimistic", None), "bsfc_conservative": ("conservative", None),
             "paux_low": ("central", MC.P_AUX_KW[1]), "paux_high": ("central", MC.P_AUX_KW[2])}
    if a.cache and os.path.exists(a.cache):
        import pickle
        tabs, cov = pickle.load(open(a.cache, "rb"))
    else:
        tabs, cov = collect(a, dem, master, dmaster, regime, scens, a.nb)
        if a.cache:
            import pickle
            pickle.dump((tabs, cov), open(a.cache, "wb"))
    res = report(a, tabs, cov, tiles, man, md5, dem)
    if mc.md5(a.master) != PINNED_MD5:
        print("dem_step_grade: master changed during the run")
        return 1
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(res, open(os.path.join(a.out_dir, "M757_dem_grade_feasibility.json"), "w", encoding="utf-8", newline="\n"), indent=1, default=lambda o: None if o != o else str(o))
    print("dem_step_grade: R1", res["F0"]["R1"], "| R2", res["F2"]["R2"]["reading"], "| R4", res["F1"]["R4"])
    return 0


def report(a, tabs, cov, tiles, man, md5, dem):
    nb = a.nb
    res = {"milestone": "M757", "spec": "analyses/M757_spec.md Rev 2", "role": "auxiliary, report-only", "masterMd5": md5, "pinnedMd5": PINNED_MD5, "seed": SEED, "nBoot": nb,
           "tool_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "dem": {"source": man.get("source"), "dataset": man.get("dataset"), "licence": LICENCE,
           "tiles_sha256": tiles, "tiles_used": sorted("N%02dE%03d" % t for t in dem.used), "raster_type": dem.rtype, "heights": "above EGM2008; only differences used"},
           "assumed_mass_kg": MASS_KG, "mass_label": "assumed class mass, never measured", "privacy": "aggregates only; no coordinates, tracks or per-drive geometry"}
    cen = tabs.get(("central", PRIMARY_SHIFT), pd.DataFrame())
    n_fix = max(cov["fixes_in_drive_windows"], 1)
    f0 = {"screened_fixes_total": cov["screened_fixes_total"], "fixes_in_drive_windows": cov["fixes_in_drive_windows"], "share_fixes_with_dem": cov["fixes_with_dem"] / n_fix,
          "share_step_km_with_dem": (cov["track_km_with_dem"] / cov["track_km"]) if cov["track_km"] else None, "drives": cov["drives"], "drives_ge3_fixes": cov["drives_ge3_fixes"],
          "drives_ge1km_track_fuel_instrumented": cov["drives_ge1km_track"], "fuel_instrumented_drives_with_steps_analysis": cov["fuel_instrumented_drives_used"],
          "unique_km_approx_100m_cells": len(cov["cells"]) * 0.1}
    f0["R1"] = "passed" if f0["share_fixes_with_dem"] >= 0.90 else "stopped: DEM value at fewer than 90 % of screened fixes"
    res["F0"] = f0
    if cen.empty or f0["R1"] != "passed":
        res["F2"] = {"R2": {"reading": "not testable", "reasons": ["no steps or R1 stop"]}}
        res["F1"] = {"R4": "not testable"}
        return res
    prim = apply_primary(cen)
    prim = prim[np.isfinite(prim["dh"])]
    res["steps"] = {"all_built": int(len(cen)), "primary": int(len(prim)), "primary_km": float(prim["d_m"].sum() / 1000.0), "primary_days": int(prim["day"].nunique()),
                    "primary_drives": int(prim["drive"].nunique()),
                    "excluded_first_last": int((cen["first"] | cen["last"]).sum()), "excluded_vmin_below_8": int((cen["vmin_kmh"] < V_MIN_KMH).sum()),
                    "excluded_abs_grade_above_8pp": int(((100 * cen["dh"] / cen["d_m"]).abs() > GRADE_EXCL_PP).sum()),
                    "chord_over_obd_distance_median": float((cen["chord_m"] / cen["d_m"]).median()),
                    "share_chord_outside_0p5_to_1p1": float(((cen["chord_m"] / cen["d_m"] < 0.5) | (cen["chord_m"] / cen["d_m"] > 1.1)).mean()),
                    "step_length_m": {"p10": float(cen["d_m"].quantile(.1)), "median": float(cen["d_m"].median()), "p90": float(cen["d_m"].quantile(.9))}}
    # ---------------- F1
    f1 = {}
    alt = prim[np.isfinite(prim["dh_obd"])]
    ag, ao = 100 * alt["dh"] / alt["d_m"], 100 * alt["dh_obd"] / alt["d_m"]
    cells_alt = len(alt)  # unique km approximated by step km on the altitude days (no coordinates kept)
    f1["all_speeds"] = f1_stats(ag.values, ao.values, alt["day"].values, nb) if len(alt) else {"n_steps": 0}
    f1["all_speeds"]["step_km"] = float(alt["d_m"].sum() / 1000.0) if len(alt) else 0.0
    f1["by_speed_class"] = {}
    for lo_, hi_, nm in SPEED_CLASSES:
        s = alt[(alt["vmean_kmh"] >= lo_) & (alt["vmean_kmh"] < hi_)]
        f1["by_speed_class"][nm] = f1_stats((100 * s["dh"] / s["d_m"]).values, (100 * s["dh_obd"] / s["d_m"]).values, s["day"].values, nb) if len(s) else {"n_steps": 0}
    f1["shift_sensitivity"] = {}
    for sh in SHIFTS:
        t_ = tabs.get(("central", sh))
        if t_ is None or t_.empty:
            continue
        q = apply_primary(t_)
        q = q[np.isfinite(q["dh"]) & np.isfinite(q["dh_obd"])]
        f1["shift_sensitivity"]["%+.0fs" % sh] = f1_stats((100 * q["dh"] / q["d_m"]).values, (100 * q["dh_obd"] / q["d_m"]).values, q["day"].values, min(nb, 1000)) if len(q) else {"n_steps": 0}
    f1["support"] = {"days": int(alt["day"].nunique()), "step_km": float(alt["d_m"].sum() / 1000.0), "descriptive_only_below_floor": bool(alt["day"].nunique() < MIN_DAYS)}
    f1["R4"] = r4_decision(f1["all_speeds"], f1["support"]["days"], f1["support"]["step_km"])
    res["F1"] = f1
    # ---------------- F2
    base, pl, pr, cv = f2_block(prim, nb)
    gp = 100 * prim["dh"] / prim["d_m"]
    big = prim[gp.abs() > 2.0]
    support = {"days": int(prim["day"].nunique()), "unique_km": float(prim["d_m"].sum() / 1000.0), "n_above2pp": int(len(big)),
               "days_pos": int(big[big["dh"] > 0]["day"].nunique()), "days_neg": int(big[big["dh"] < 0]["day"].nunique()),
               "note": "unique km is approximated by the summed step length of the fitted steps (an upper bound on unique road)"}
    fo = prim[np.isfinite(prim["dh_obd"])]
    dall = sorted(prim["day"].unique())
    Wall = boot_weights(len(dall), nb)
    bo = fit_b(fo, "dh_obd", W=Wall, nb=nb, all_days=dall) if len(fo) >= 20 else {"b": None, "b_ci95": [None, None]}
    b_same = fit_b(fo, "dh", W=Wall, nb=nb, all_days=dall) if len(fo) >= 20 else {"b": None}
    obd_days = int(fo["day"].nunique())
    obd_testable = obd_days >= MIN_DAYS
    ratio = {"b_over_b_obd": None}
    if bo.get("b") not in (None, 0.0) and base.get("b") is not None:
        ratio["b_over_b_obd"] = float(base["b"] / bo["b"])
        ratio["same_steps_b_dem_over_b_obd"] = float(b_same["b"] / bo["b"]) if b_same.get("b") is not None else None
        ratio["b_over_b_obd_ci95"] = ci(base["_draws"] / np.where(np.abs(bo["_draws"]) > 1e-9, bo["_draws"], np.nan))
        ratio["note"] = "ratio of two day-clustered bootstrap draws (same day weights); with few logged-altitude days the interval is wide or unbounded and is descriptive"
    r2, why = r2_decision(strip(base) | {"b_ci95": base["b_ci95"]}, strip(pl) | {"b_ci95": pl["b_ci95"]}, cv, support, bo.get("b"), obd_testable)
    f2 = {"primary": strip(base), "placebo_left_2km": strip(pl), "placebo_right_2km": strip(pr), "cross_validation": cv, "support": support,
          "b_obd_logged_altitude_days": strip(bo), "b_dem_on_same_steps_as_b_obd": strip(b_same), "attenuation": ratio, "b_obd_testable": obd_testable,
          "R2": {"reading": r2, "reasons": why}, "R3": r3_decision(ratio.get("b_over_b_obd_ci95", [None, None]), obd_days), "note": "validation CONDITIONAL on the traction reconstruction (Rev 2 9.3); fuel-instrumented drives only"}
    # sensitivities (all reported, none selects)
    sens = {}
    sens["road_load_on_flat_steps_first"] = strip(fit_b(prim, "dh", nb=nb, flat_first=True))
    sens["sign_split"] = strip(fit_b(prim, "dh", nb=nb, split=True))
    sens["abs_grade_above_8pp_kept"] = strip(fit_b(cen[~cen["first"] & ~cen["last"] & (cen["vmin_kmh"] >= V_MIN_KMH) & np.isfinite(cen["dh"])], "dh", nb=nb))
    sens["no_first_last_or_speed_exclusion"] = strip(fit_b(cen[np.isfinite(cen["dh"]) & ((100 * cen["dh"] / cen["d_m"]).abs() <= GRADE_EXCL_PP)], "dh", nb=nb))
    pw = (prim["Epos_kJ"] - prim["Eneg_kJ"]) / prim["T_s"]
    sens["low_power_steps_excluded_below_%gkW" % LOW_POWER_KW] = strip(fit_b(prim[pw >= LOW_POWER_KW], "dh", nb=nb))
    cs = cen[~cen["first"] & ~cen["last"] & (cen["vmin_kmh"] >= V_MIN_KMH)]
    cs = cs[np.isfinite(cs["dh"]) & ((cs["chord_m"] / cs["d_m"]) <= 1.1) & ((cs["chord_m"] / cs["d_m"]) >= 0.5) & ((100 * cs["dh"] / cs["d_m"]).abs() <= GRADE_EXCL_PP)]
    sens["chord_screen_0p5_to_1p1"] = strip(fit_b(cs, "dh", nb=nb))
    for sh in (0.0, -16.0):
        t_ = tabs.get(("central", sh))
        if t_ is not None and not t_.empty:
            q = apply_primary(t_)
            sens["shift_%+.0fs" % sh] = strip(fit_b(q[np.isfinite(q["dh"])], "dh", nb=nb))
    for k in ("bsfc_optimistic", "bsfc_conservative", "paux_low", "paux_high"):
        t_ = tabs.get((k, PRIMARY_SHIFT))
        if t_ is not None and not t_.empty:
            q = apply_primary(t_)
            sens["energy_variant_" + k] = strip(fit_b(q[np.isfinite(q["dh"])], "dh", nb=nb))
    sens["by_thermal_cohort"] = {c: strip(fit_b(g_, "dh", nb=nb)) for c, g_ in prim.groupby("cohort") if g_["day"].nunique() >= 5}
    bvals = [v["b"] for k, v in sens.items() if isinstance(v, dict) and v.get("b") is not None and k != "by_thermal_cohort"]
    sens["spread_of_b_over_variants"] = {"min": float(min(bvals)), "max": float(max(bvals)), "n_variants": len(bvals)} if bvals else None
    f2["sensitivities"] = sens
    res["F2"] = f2
    # ---------------- F3
    cls = grade_class(gp.values)
    km = prim["d_m"].values / 1000.0
    f3 = {"class_names": list(CLASS_NAMES), "edges_pp": list(CLASS_EDGES), "step_scale_caveat": "mean grade over a 300 to 900 m step, not a road profile",
          "step_share": [float((cls == i).mean()) for i in range(5)], "km_share": [float(km[cls == i].sum() / km.sum()) for i in range(5)], "by_cohort": {}}
    for c, g_ in prim.groupby("cohort"):
        gc = grade_class((100 * g_["dh"] / g_["d_m"]).values)
        f3["by_cohort"][c] = {"n_steps": int(len(g_)), "n_days": int(g_["day"].nunique()), "km_share": [float(g_["d_m"].values[gc == i].sum() / g_["d_m"].sum()) for i in range(5)]}
    if r2.startswith("informative"):
        eneg = prim["Eneg_kJ"].values
        f3["regen_bus_energy_share_by_class"] = [float(eneg[cls == i].sum() / eneg.sum()) for i in range(5)]
    else:
        f3["regen_bus_energy_share_by_class"] = "not computed (F2 not informative, Rev 1 section 3)"
    res["F3"] = f3
    res["deviations_from_spec"] = [
        "Rev 2 registered changes: shift +16 s primary; |grade| above 8 pp excluded; duration term in the primary fit; displaced-DEM placebo; first and last step and vmin below 8 km/h excluded; R2/R3 rewritten.",
        "F2 covers fuel-instrumented drives only: the traction reconstruction (recon_engine, central_estimate_v2_persample) needs the fuel-flow channel. The spec text said 'all drives with cloud fixes'; the effect is a smaller step set, reported in steps and F0.",
        "Energy-variant sensitivities cover the BSFC scenario scalar (optimistic, conservative) and the auxiliary power (low, high) of model_constants only; the ten-axis GTR sensitivity block was not rerun.",
        "Unique-km support is approximated by the summed step length of the fitted steps (no coordinates are kept); F1 support likewise by the step km on logged-altitude days.",
        "The mass in the kinetic and potential terms is the assumed class mass 1950 kg (compute_summary_arrays.VEHICLE_MASS_KG basis); b scales with it and is read through b / b_obd.",
        "Step length is limited to 300 to 900 m (Rev 2 9.1 estimand); longer steps are counted, not used. The chord/odometer ratio is a reported diagnostic and a sensitivity, not a primary screen."]
    return res


if __name__ == "__main__":
    sys.exit(main())
