#!/usr/bin/env python3
"""M410 (analyses/M409_spec.md Rev 1 + Rev 2): serial-dependence sensitivity of the two released trend slopes. Additive: writes ONLY the payload block
summary_arrays.json['serialDependence'] (+ its artifact stamp); the released estimators, intervals and the TOST decision are unchanged, nothing is tuned.

Designs are exactly the M406 designs (tools/dependence_sensitivity.py::_design). Time axis = calendar day number; all distances are calendar-day distances.
  A/B  day-mean OLS residuals; Pearson autocorrelation of day pairs at calendar distance 1, 2, 3 and pooled 1-3; 95 % CI = percentile bootstrap over ISO weeks, a pair belongs
       to the week of its FIRST day, weights = multinomial week counts, the design is refitted by weighted least squares in every draw (seed 42, 4000 draws).
  C    semivariogram of the day-mean residuals by distance bin {1, 2, 3-4, 5-7, 8-14, 15+}.
  D    time-distance (Bartlett, w = 1 - d/(L+1), d <= L) HAC standard error, L = 3, 7, 14; CR1 small-sample factor; intervals normal and t(W-1), W = ISO weeks with data.
  E    overlapping moving-block bootstrap on the calendar-day axis, block length 7 and 14 days, ceil(D/L) blocks per draw, start uniform on 0..D-L, full refit.
  F    AR(1) variance-inflation diagnostic VIF = s' Omega s / s' s over the day sums s of the months regressor residualised on the other columns (Omega_ij = phi^|t_i - t_j|).
  G    gap-aware AR(1) GLS on day means, REML rho on [0, 0.95], interval t(W-1): a separate estimator, outside every rule.
  H    misspecification control: rho_{1-3} before (design with months) and after (y ~ T + I + smooth(day), cubic truncated-power spline with 4 interior knots, no months column).
Usage: python tools/serial_dependence.py [--dry-run]"""
import copy, datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import dependence_sensitivity as DS

N_BOOT, SEED = 4000, 42
METHOD_VERSION = 1
DMAX = 3
BINS = [(1, 1, "1"), (2, 2, "2"), (3, 4, "3-4"), (5, 7, "5-7"), (8, 14, "8-14"), (15, None, "15+")]
HAC_L = (3, 7, 14)
BLOCK_L = (7, 14)
K = 1  # months column


# ------------------------------------------------------------------------------------------------ helpers
def day_axis(dates):
    d = pd.to_datetime(pd.Series(dates)).dt.normalize()
    return (d - d.min()).dt.days.to_numpy()


def unique_days(t):
    days, inv = np.unique(t, return_inverse=True)
    return days, inv


def wls_resid(X, y, w=None):
    """(beta, residuals, rank) of (weighted) least squares; weights may contain zeros."""
    if w is None:
        b, _, rk, _ = np.linalg.lstsq(X, y, rcond=None)
    else:
        sw = np.sqrt(w)
        b, _, rk, _ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    return b, y - X @ b, rk


def day_means(e, inv, nd):
    s = np.zeros(nd)
    c = np.zeros(nd)
    np.add.at(s, inv, e)
    np.add.at(c, inv, 1.0)
    return s / c


def pair_index(days, dmax=None):
    i_, j_, d_ = [], [], []
    for i in range(len(days)):
        for j in range(i + 1, len(days)):
            d = days[j] - days[i]
            if dmax is not None and d > dmax:
                break
            i_.append(i); j_.append(j); d_.append(d)
    return np.array(i_, int), np.array(j_, int), np.array(d_, int)


def wpearson(a, b, w):
    sw = w.sum()
    if not np.isfinite(sw) or sw <= 0:
        return float("nan")
    ma, mb = (w * a).sum() / sw, (w * b).sum() / sw
    va, vb = (w * (a - ma) ** 2).sum(), (w * (b - mb) ** 2).sum()
    if va <= 0 or vb <= 0:
        return float("nan")
    return float((w * (a - ma) * (b - mb)).sum() / np.sqrt(va * vb))


def spline_cols(t, knots_from=None, nknots=4):
    """Cubic truncated-power spline columns on the scaled day axis (u, u^2, u^3, (u-k_j)+^3); Rev 2: the linear term is included."""
    u0 = np.asarray(knots_from if knots_from is not None else t, float)
    lo, hi = u0.min(), u0.max()
    s = lambda v: (np.asarray(v, float) - lo) / (hi - lo)
    uu = s(t)
    ks = np.quantile(s(np.unique(u0)), np.linspace(0, 1, nknots + 2)[1:-1])
    return np.column_stack([uu, uu ** 2, uu ** 3] + [np.clip(uu - k, 0, None) ** 3 for k in ks])


# ------------------------------------------------------------------------------------------------ autocorrelation, semivariogram
def autocorr_point(r, days):
    out = {}
    i, j, d = pair_index(days, DMAX)
    for g in (1, 2, 3):
        m = d == g
        out[str(g)] = {"rho": float(np.corrcoef(r[i[m]], r[j[m]])[0, 1]) if m.sum() > 2 else None, "nPairs": int(m.sum())}
    out["pooled"] = {"rho": float(np.corrcoef(r[i], r[j])[0, 1]) if len(i) > 2 else None, "nPairs": int(len(i)), "label": "original statistic (Rev 1), reported beside the Rev 3 rule statistic rho_1"}
    return out


def semivariogram(r, days):
    i, j, d = pair_index(days)
    sill = float(np.var(r, ddof=1))
    bins = []
    for lo, hi, lab in BINS:
        m = (d >= lo) & ((d <= hi) if hi is not None else True)
        bins.append({"binDays": lab, "gamma": float(0.5 * np.mean((r[i[m]] - r[j[m]]) ** 2)) if m.sum() else None, "nPairs": int(m.sum())})
    return {"sill": sill, "bins": bins}


def week_bootstrap_rho(X, y, Z, t, week_obs, B=N_BOOT, seed=SEED):
    """Week-pair-set bootstrap of rho_{1-3} (design X, 'pre') and of the control design Z ('post'); draws are paired.
    Returns (rho_pre draws, rho_post draws, rho_g draws, skipped)."""
    days, inv = unique_days(t)
    nd = len(days)
    wcodes, W = DS._codes(week_obs)
    wk_day = np.zeros(nd, int)
    wk_day[inv] = wcodes
    pi, pj, pd_ = pair_index(days, DMAX)
    wpair = wk_day[pi]
    rng = np.random.default_rng(seed)
    counts = rng.multinomial(W, np.full(W, 1.0 / W), size=B).astype(float)
    pre, post = np.full(B, np.nan), np.full(B, np.nan)
    byg = np.full((B, 3), np.nan)
    skipped = 0
    for b in range(B):
        c = counts[b]
        wo, wp = c[wcodes], c[wpair]
        _, e1, rk1 = wls_resid(X, y, wo)
        _, e2, rk2 = wls_resid(Z, y, wo) if Z is not None else (None, None, X.shape[1])
        if rk1 < X.shape[1] or (Z is not None and rk2 < Z.shape[1]):
            skipped += 1
            continue
        r1 = day_means(e1, inv, nd)
        pre[b] = wpearson(r1[pi], r1[pj], wp)
        for g in (1, 2, 3):
            m = pd_ == g
            byg[b, g - 1] = wpearson(r1[pi[m]], r1[pj[m]], wp[m])
        if Z is not None:
            r2 = day_means(e2, inv, nd)
            post[b] = wpearson(r2[pi], r2[pj], wp)
    return pre, post, byg, skipped


# ------------------------------------------------------------------------------------------------ HAC, moving block, VIF, GLS
def hac(X, y, t, L, W):
    """Time-distance Bartlett HAC for the months slope; observations on the same day have weight 1; CR1 small-sample factor."""
    n, p = X.shape
    days, inv = unique_days(t)
    G = len(days)
    b, M, e = DS.ols(X, y)
    S = np.zeros((G, p))
    np.add.at(S, inv, X * e[:, None])
    dist = np.abs(days[:, None] - days[None, :]).astype(float)
    Kmat = np.where(dist <= L, 1.0 - dist / (L + 1.0), 0.0)
    V = (G / (G - 1.0)) * ((n - 1.0) / (n - p)) * M @ (S.T @ Kmat @ S) @ M
    se = float(np.sqrt(V[K, K]))
    bk = float(b[K])
    tq = stats.t.ppf(0.975, W - 1)
    zq = stats.norm.ppf(0.975)
    return {"L": int(L), "slope": bk, "se": se, "ci95Normal": [bk - zq * se, bk + zq * se], "ci95T": [bk - tq * se, bk + tq * se], "dfT": int(W - 1)}


def moving_block(X, y, t, L, B=N_BOOT, seed=SEED):
    D = int(t.max()) + 1
    nb = int(np.ceil(D / L))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, D - L + 1, size=(B, nb))
    slopes, sizes = np.full(B, np.nan), np.zeros(B)
    skipped = 0
    cover = np.zeros(D + L + 1)
    for b in range(B):
        cover[:] = 0
        np.add.at(cover, starts[b], 1.0)
        np.add.at(cover, starts[b] + L, -1.0)
        w = np.cumsum(cover)[:D]
        wo = w[t]
        sizes[b] = wo.sum()
        beta, _, rk = wls_resid(X, y, wo)
        if rk < X.shape[1]:
            skipped += 1
            continue
        slopes[b] = beta[K]
    ok = np.isfinite(slopes)
    lo, hi = np.percentile(slopes[ok], [2.5, 97.5])
    return {"L": int(L), "ci95": [float(lo), float(hi)], "nDraws": int(B), "skippedSingular": int(skipped), "drawSizeRange": [float(sizes.min()), float(sizes.max())], "nBlocksPerDraw": nb}


def vif_ar1(X, t, phi):
    """Variance inflation of the months slope under day-level AR(1) with parameter phi, relative to independent days."""
    others = [c for c in range(X.shape[1]) if c != K]
    xm = X[:, K]
    xr = xm - X[:, others] @ np.linalg.lstsq(X[:, others], xm, rcond=None)[0]
    days, inv = unique_days(t)
    s = np.zeros(len(days))
    np.add.at(s, inv, xr)
    dist = np.abs(days[:, None] - days[None, :]).astype(float)
    Om = phi ** dist
    return float(s @ Om @ s / (s @ s))


def gls_ar1(X, y, t, W):
    days, inv = unique_days(t)
    nd = len(days)
    cnt = np.bincount(inv, minlength=nd).astype(float)
    Xd = np.zeros((nd, X.shape[1]))
    np.add.at(Xd, inv, X)
    Xd /= cnt[:, None]
    yd = np.bincount(inv, weights=y, minlength=nd) / cnt
    dist = np.abs(days[:, None] - days[None, :]).astype(float)
    p = Xd.shape[1]

    def fit(rho):
        R = rho ** dist
        Ri = np.linalg.inv(R)
        A = Xd.T @ Ri @ Xd
        beta = np.linalg.solve(A, Xd.T @ Ri @ yd)
        res = yd - Xd @ beta
        s2 = float(res @ Ri @ res) / (nd - p)
        reml = -0.5 * (np.linalg.slogdet(R)[1] + np.linalg.slogdet(A)[1] + (nd - p) * np.log(s2))
        return reml, beta, s2, A

    grid = np.round(np.arange(0.0, 0.9501, 0.01), 2)
    vals = [fit(r)[0] for r in grid]
    r0 = float(grid[int(np.argmax(vals))])
    fine = np.round(np.arange(max(0.0, r0 - 0.01), min(0.95, r0 + 0.01) + 1e-9, 0.001), 3)
    rho = float(fine[int(np.argmax([fit(r)[0] for r in fine]))])
    _, beta, s2, A = fit(rho)
    se = float(np.sqrt(s2 * np.linalg.inv(A)[K, K]))
    tq = stats.t.ppf(0.975, W - 1)
    return {"rho": rho, "slope": float(beta[K]), "se": se, "ci95T": [float(beta[K] - tq * se), float(beta[K] + tq * se)], "dfT": int(W - 1),
            "note": "separate estimator on day means (not the released slope); outside every rule; never described as a correction"}


# ------------------------------------------------------------------------------------------------ harness summary (Rev 3)
HARNESS = os.path.join(ROOT, "analyses", "M410_harness", "harness_results.json")


def harness_summary():
    """Power, false-support and coverage rates (with Monte Carlo errors) copied from the committed harness file; None if the file is missing."""
    if not os.path.exists(HARNESS):
        return None
    h = json.load(open(HARNESS, encoding="utf-8"))
    sc = h["scenarios"]
    pick = lambda n: {"supportedRho1": sc[n]["supportedRho1"], "supportedPooledOriginal": sc[n]["supportedPooled"], "rhoPostPositive": sc[n]["rhoPostPositive"],
                      "coverage": sc[n]["coverage"], "hacL7OverCR1SeMean": sc[n]["hacL7OverCR1SeMean"]}
    pw = lambda n: sc[n]["supportedRho1"]["rate"]
    disclosure = ("harness on this day grid (simulated outcomes, %d replications): the rho_1 rule has power %.0f %% at phi = 0.3 and %.1f %% at phi = 0.6 and a false-support rate of %.1f %% under the null; "
                  "the pre-registered criterion of at most 10 %% misclassification fails at phi = 0.3 (%.0f %% not supported); moderate dependence (phi about 0.3) is not excluded"
                  % (h["R"], 100 * pw("ar1_phi0.3"), 100 * pw("ar1_phi0.6"), 100 * sc["null"]["supportedRho1"]["rate"], 100 * (1 - pw("ar1_phi0.3"))))
    return {"R": h["R"], "B": h["B"], "trueMonthsSlope": h["trueMonthsSlope"], "scenarios": {n: pick(n) for n in sc}, "powerDisclosure": disclosure,
            "note": "rates carry Monte Carlo errors (mcse); differences within about 2 mcse are not 'better'; CR1 under-covers under dependence and HAC L=14 under-covers under the null; the new rows are partial remedies, never 'corrected'; "
                    "a drop from rho_pre to rho_post also occurs under pure AR(1) and is not read as seasonal",
            "files": ["analyses/M410_harness/harness_results.json", "analyses/M410_harness/harness_results_run1.json", "analyses/M410_harness/harness_results_run2.json"]}


# ------------------------------------------------------------------------------------------------ one series
def _ci(draws, lo=2.5, hi=97.5):
    d = np.asarray(draws, float)
    d = d[np.isfinite(d)]
    return [float(np.percentile(d, lo)), float(np.percentile(d, hi))] if len(d) else [None, None]


def series(dd, X, y, use, released_rows=None, B=N_BOOT):
    t = day_axis(dd["date"])
    wk = DS.week_blocks(dd["date"])
    W = int(len(np.unique(wk)))
    days, inv = unique_days(t)
    nd = len(days)
    _, e, _ = wls_resid(X, y)
    r = day_means(e, inv, nd)
    pt = autocorr_point(r, days)
    others = [c for c in range(X.shape[1]) if c != K]
    Z = np.column_stack([X[:, others], spline_cols(t)])
    pre, post, byg, sk = week_bootstrap_rho(X, y, Z, t, wk, B)
    for gi, g in enumerate(("1", "2", "3")):
        pt[g]["ci95"] = _ci(byg[:, gi])
    pt["1"]["bootstrapMedian"] = float(np.nanmedian(byg[:, 0]))
    pt["pooled"]["ci95"] = _ci(pre)
    pt["pooled"]["nDraws"] = int(B)
    pt["pooled"]["skippedSingular"] = int(sk)
    lo = pt["1"]["ci95"][0]
    supported = bool(lo is not None and lo > 0)
    lo_p = pt["pooled"]["ci95"][0]
    supported_orig = bool(lo_p is not None and lo_p > 0)
    hsum = harness_summary()
    ac = {**pt, "supported": supported, "ruleStatistic": "rho_1 (distance 1 day; Rev 3)", "supportedOriginalPooledStatistic": supported_orig,
          "statement": ("serial dependence at the day scale is supported (lower bound of the 95 % week-resampling interval of rho_1 above 0)" if supported else
                        "serial dependence at the day scale is not supported by these data at this precision (not evidence of absence)"),
          "disagreementWithOriginalStatistic": (None if supported == supported_orig else
                                                "the original Rev 1 statistic rho_{1-3} gives '%s' while the Rev 3 rule statistic rho_1 gives '%s'" % ("supported" if supported_orig else "not supported", "supported" if supported else "not supported")),
          "powerDisclosure": (hsum or {}).get("powerDisclosure"),
          "forkingPathNote": "the rule statistic was switched from rho_{1-3} to rho_1 after simulation power was seen and before any real outcome was computed; the lag-1 value of about 0.25 from the self-audit was known; the original statistic is reported beside",
          "multiplicityNote": "rho_2 and rho_3 are descriptive and were not pre-specified as rules; the rule uses rho_1 only and no multiplicity adjustment is made across lags",
          "bootstrapNote": "the percentile interval of rho_1 is shifted: the bootstrap median lies below the point estimate (bootstrapMedian vs rho); no bias correction is applied",
          "pairsAssignedTo": "ISO week of the first day; week pair-sets resampled, design refitted by weighted least squares in every draw"}
    sv = semivariogram(r, days)
    hacs = {"L%d" % L: hac(X, y, t, L, W) for L in HAC_L}
    mbs = {"L%d" % L: moving_block(X, y, t, L, B) for L in BLOCK_L}
    rho1 = pt["1"]["rho"]
    phi = float(min(max(rho1, 0.0), 0.95)) if rho1 is not None else 0.0
    vif = {"phiRaw": rho1, "phiUsed": phi, "vif": vif_ar1(X, t, phi), "seRatioImplied": float(np.sqrt(vif_ar1(X, t, phi))),
           "note": "diagnostic ratio relative to independent days; no interval; phi is taken from the attenuated rho_1 (hat-matrix), so the ratio is likely understated"}
    gl = gls_ar1(X, y, t, W)
    # H: control, applied (classified) only if the dependence is supported
    diff = pre - post
    pre_pt = pt["pooled"]["rho"]
    _, e2, _ = wls_resid(Z, y)
    r2 = day_means(e2, inv, nd)
    pi, pj, _d = pair_index(days, DMAX)
    post_pt = float(np.corrcoef(r2[pi], r2[pj])[0, 1])
    ci_post, ci_diff = _ci(post), _ci(diff)
    if ci_post[0] is not None and ci_post[0] > 0:
        reading = "positive residual autocorrelation remains after removing a smooth function of calendar day (the 95 % interval of rho_post is above 0)"
    else:
        reading = "the control does not separate slow-varying mean structure from short-memory dependence at this precision"
    ctrl = {"rhoPre": pre_pt, "rhoPost": post_pt, "ci95RhoPost": ci_post, "ci95RhoPreMinusPost": ci_diff, "reading": reading,
            "caution": "a drop from rho_pre to rho_post is not read as seasonal: it also occurs under pure AR(1) in the harness",
            "descriptiveNote": "reported descriptively whatever the rule result (Rev 3 item 3; Rev 1 had conditioned the control on a supported result)",
            "spline": "y ~ T + I + cubic truncated-power spline of calendar day (4 interior knots at day quantiles, linear term included; months column removed)"}
    # rule over rows: any row including zero -> procedure-dependent
    rows = {"cr1": (released_rows or {}).get("cr1", {}).get("ci95T_Gminus1"), "cr2": (released_rows or {}).get("cr2", {}).get("ci95T"),
            "wildClusterBootstrapT": (released_rows or {}).get("wildClusterBootstrapT", {}).get("ci95PercentileT"),
            "dayClusterPairsBootstrap": (released_rows or {}).get("dayClusterPairsBootstrap", {}).get("ci95"),
            "weekBlockPairsBootstrap": (released_rows or {}).get("weekBlockPairsBootstrap", {}).get("ci95")}
    zeroin = {}
    for k_, v in rows.items():
        if v:
            zeroin[k_] = bool(v[0] <= 0 <= v[1])
    for k_, v in hacs.items():
        zeroin["hac" + k_] = bool(v["ci95Normal"][0] <= 0 <= v["ci95Normal"][1] or v["ci95T"][0] <= 0 <= v["ci95T"][1])
    for k_, v in mbs.items():
        zeroin["movingBlock" + k_] = bool(v["ci95"][0] <= 0 <= v["ci95"][1])
    inc = sorted(k_ for k_, v in zeroin.items() if v)
    exc = sorted(k_ for k_, v in zeroin.items() if not v)
    if inc and exc:
        cls = "procedure-dependent"
    elif inc:
        cls = "every row includes zero"
    else:
        cls = "no row includes zero (a count of rows, not a finding)"
    n_by_day = np.bincount(inv)
    cov = {"nPairsByDistance": {g: pt[g]["nPairs"] for g in ("1", "2", "3")},
           "daysWithoutNeighbourWithin3": int(sum(1 for i in range(nd) if not ((np.abs(days - days[i]) <= DMAX) & (np.arange(nd) != i)).any())),
           "singleDriveDayShareOfObservations": float((n_by_day == 1).sum() / len(t))}
    return {"n": int(len(y)), "nDays": int(nd), "nWeeks": W, "formula": "y ~ months" + "".join(" + " + c for c in use), "residualAutocorr": ac, "semivariogram": sv,
            "hac": hacs, "movingBlock": mbs, "vifDiagnostic": vif, "gls": gl, "misspecControl": ctrl,
            "rowsRule": {"classification": cls, "rowsIncludingZero": inc, "rowsExcludingZero": exc,
                         "rule": "procedure-dependent if ANY row includes zero (a HAC row counts as including zero if its normal or its t(W-1) interval does); GLS and the control take no part"},
            "coverage": cov}


def build(dm, released_block=None, B=N_BOOT):
    rel = ((released_block or {}).get("trendSlopes")) or {}
    out = {}
    for key, ycol, icol in (("cellSpread", "cell_spread_loaded_p95_mv", "peak_I_discharge"), ("resistanceVreg", "vreg_R_pack_mohm", "vreg_I_p95_A")):
        dd, X, y, use = DS._design(dm, ycol, ("T", "I"), icol)
        out[key] = series(dd, X, y, use, rel.get(key), B)
    return {"_provenance": "GENERATED by tools/serial_dependence.py (M410, spec analyses/M409_spec.md Rev 0-3a; the rule statistic is the Rev 3 one); do not hand-edit. Additive block: the released estimators and the TOST decision are unchanged.",
            "methodVersion": METHOD_VERSION,
            "resampling": "calendar-day distance; ISO calendar week = block for the autocorrelation interval; moving blocks on the calendar-day axis; seed %d, %d draws" % (SEED, B),
            "trendSlopes": out, "harnessCoverage": harness_summary(),
            "reportingOrder": ["hacL3", "hacL7", "hacL14", "movingBlockL7", "movingBlockL14", "gls"],
            "reportingRule": "the new rows follow the M406 rows in this fixed order with the same format; no single interval is designated primary and no envelope is formed; the L=7 label is weekly-scale truncation, not preferred; GLS is a different estimator outside every rule",
            "reading": "sensitivities of conditional intervals to serial dependence between neighbouring days; they do not remove season, logging-regime or calendar-drift confounding and do not change the released estimators; 'not supported' is not evidence of absence",
            "limits": ["one vehicle, May-October data", "most day pairs at distance 1-3 days come from dense weeks; larger distances are imprecise",
                       "a smooth drift and positive residual autocorrelation are not separable without a model of the mean; the control addresses one direction only",
                       "HAC and block procedures are asymptotic with about 22 effective weeks; GLS assumes a stationary Gaussian AR(1)",
                       "none of these procedures removes confounding by season, logging regime or calendar",
                       "season (or any smooth drift) collinear with months enters the slope and is invisible to residual diagnostics (a seasonal signal absorbed by the months regressor produced no residual autocorrelation in the harness)"]}


# ------------------------------------------------------------------------------------------------ splice
ALLOWED = ["/serialDependence", "/_artifactStamps/serialDependence"]


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new["serialDependence"] = blk
    old = (A.get("_artifactStamps") or {}).get("serialDependence")
    if old and A.get("serialDependence") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["serialDependence"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M410: derived by tools/serial_dependence.py from drive_master.csv; additive serial-dependence sensitivities of the two released trend slopes (analyses/M409_spec.md)",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        new["_artifactStamps"]["serialDependence"] = st
    ch = DS._paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A0 = json.loads(raw)
    blk = DS._round(build(dm, A0.get("dependenceSensitivity")))
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, changed, bad = splice(A0, blk, md5)
    print(json.dumps({"nChanged": len(changed), "outsideAllowList": bad}))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
