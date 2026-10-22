#!/usr/bin/env python3
"""M480b (analyses/M480b_spec.md Rev 3, pre-registered): pair-level restricted-condition outcomes for the released cell-spread slope.
Per-drive outcome = the fixed-n upper L-statistic (exact expectation of the numpy-linear p95 of a random m-subset, closed form, no seeds; about q0.90 for m = 20) over a pair set:
O0m reference (|I| > 50 A), O1m (50 < |I| <= 80 A and 50 <= SoC <= 70 %), O2m (loaded and |offset| <= 50 ms; regime indicator in the model), O3m negative control (|I| < 5 A).
Model for every outcome = the released design (months + T + I, ens_outlier_v2-clean, cluster = calendar day, CR1 interval t(G-1)). Delta = b_restricted - b_O0m|rows on the restricted rows:
day-cluster bootstrap percentile interval (verdict) and analytic stacked CR1 interval (power gate, fallback). Power gate injects a known slope. Decision rule frozen in the spec.
Nothing here changes the released estimator, the master, the payload or the dashboard.
Usage: python tools/m480b_pair_outcomes.py [--out analyses/M480b_results.json] [--boot 4000] [--power-draws 500]"""
import argparse, hashlib, json, os, sys
import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import gammaln

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import dependence_sensitivity as DS      # noqa: E402
import serial_dependence as SD           # noqa: E402
import m480_spread_sensitivity as M0     # noqa: E402

METHOD_VERSION = 1
Q = 0.95
M_PRIMARY, M_SENS = 20, (10, 30)
LOADED_A, BAND_LO, BAND_HI, SOC_LO, SOC_HI, LOW_A = 50.0, 50.0, 80.0, 50.0, 70.0, 5.0
OFFSETS_MS = (50.0, 25.0, 100.0)          # primary first
EPISODE_BREAK_S, EPISODE_K = 10.0, 5
MIN_DRIVES, MIN_DAYS, DETECT_MIN, HALF = 100, 40, 0.8, 0.5
CUTOFFS = ("2026-07-31", "2026-08-31", "2026-09-30")
FAST_S = 1.05


# ------------------------------------------------------------------------------------------------ the fixed-n statistic
def order_weights(N, m, j):
    """E[X(j:m)] weights over the sorted values x(1..N): P(x(i) is the j-th order statistic of an m-subset) = C(i-1, j-1) C(N-i, m-j) / C(N, m)."""
    i = np.arange(1, N + 1, dtype=float)
    lg = gammaln
    ok = (i - 1 >= j - 1) & (N - i >= m - j)
    w = np.zeros(N)
    ii = i[ok]
    w[ok] = np.exp(lg(ii) - lg(j) - lg(ii - j + 1) + lg(N - ii + 1) - lg(m - j + 1) - lg(N - ii - (m - j) + 1) - (lg(N + 1) - lg(m + 1) - lg(N - m + 1)))
    return w


def fixed_n_stat(x, m=M_PRIMARY, q=Q, kind="q"):
    """Closed-form expectation over all m-subsets (without replacement) of the sample statistic: kind 'q' = numpy-linear quantile q (position h = q (m-1), 0-indexed), kind 'median'."""
    x = np.sort(np.asarray(x, float))
    N = len(x)
    if N < m:
        return float("nan")
    if kind == "median":
        lo, hi, f = m // 2, m // 2 + 1, 1.0 / 2
        if m % 2:
            lo, hi, f = (m + 1) // 2, (m + 1) // 2, 0.0
    else:
        h = q * (m - 1)
        lo = int(np.floor(h)) + 1
        f = h - np.floor(h)
        hi = lo + 1
    v = (1.0 - f) * float(order_weights(N, m, lo) @ x)
    if f > 0:
        v += f * float(order_weights(N, m, hi) @ x)
    return v


def balance_episodes(t, k=EPISODE_K, gap=EPISODE_BREAK_S):
    """Indices keeping at most k pairs per load episode (runs of the set separated by gaps over `gap` s), evenly spaced ranks within an episode."""
    order = np.argsort(t, kind="stable")
    ts = np.asarray(t)[order]
    ep = np.concatenate([[0], np.cumsum(np.diff(ts) > gap)])
    keep = []
    for e in np.unique(ep):
        idx = np.flatnonzero(ep == e)
        if len(idx) > k:
            idx = idx[np.unique(np.linspace(0, len(idx) - 1, k).round().astype(int))]
        keep.extend(order[idx])
    return np.array(sorted(keep), dtype=int)


# ------------------------------------------------------------------------------------------------ pair sets
def pair_mask(a, name, off_ms=50.0):
    I, soc, off = a["I"], a["soc"], a["off_ms"]
    with np.errstate(invalid="ignore"):
        cur = np.abs(I)
        if name == "O0":
            return cur > LOADED_A
        if name == "O1":
            return (cur > BAND_LO) & (cur <= BAND_HI) & (soc >= SOC_LO) & (soc <= SOC_HI)
        if name == "O2":
            return (cur > LOADED_A) & (np.abs(off) <= off_ms)
        if name == "O3":
            return cur < LOW_A
    raise ValueError(name)


def drive_values(a, name, m=M_PRIMARY, kind="q", off_ms=50.0, balanced=False):
    """(statistic, N eligible pairs, variable-n p95) of one drive for one outcome; NaN statistic when N < m."""
    mk = pair_mask(a, name, off_ms)
    x = a["spread_mv"][mk]
    N = int(len(x))
    if balanced and N:
        x = x[balance_episodes(a["t"][mk])]
    stat = fixed_n_stat(x, m, kind=kind) if len(x) >= m else float("nan")
    return stat, N, (float(np.quantile(a["spread_mv"][mk], Q)) if N >= m else float("nan"))


# ------------------------------------------------------------------------------------------------ fits, Delta, power
def _prepare(dd, ycol, extra=()):
    d = dd.dropna(subset=[ycol]).copy()
    d["y"] = d[ycol]
    return d


def fit_outcome(dd, ycol, cols=(), B=0, full=False):
    d = _prepare(dd, ycol)
    s, X, y = M0.fit(d, list(cols), B, full=full)
    return s, X, y, d


def _cluster_scores(X, e, inv, G):
    S = np.zeros((G, X.shape[1]))
    np.add.at(S, inv, X * e[:, None])
    return S


def delta_analytic(X, y_r, y_ref, groups, k=1):
    """CR1 interval of b_r[k] - b_ref[k] (same design, same rows): Var(b_r) + Var(b_ref) - 2 Cov from the day-cluster scores of both equations, t(G-1) reference."""
    inv, G = DS._codes(groups)
    n, p = X.shape
    M = np.linalg.inv(X.T @ X)
    br, bf = M @ X.T @ y_r, M @ X.T @ y_ref
    Sr, Sf = _cluster_scores(X, y_r - X @ br, inv, G), _cluster_scores(X, y_ref - X @ bf, inv, G)
    c = (G / (G - 1.0)) * ((n - 1.0) / (n - p))
    d_s = (Sr - Sf) @ M[:, k]                      # delta's cluster score contribution (b_r - b_ref is linear in the two score sets through the same M)
    se = float(np.sqrt(c * (d_s ** 2).sum()))
    delta = float(br[k] - bf[k])
    t1 = stats.t.ppf(0.975, G - 1)
    return {"delta": delta, "se": se, "ci95": [delta - t1 * se, delta + t1 * se], "df": int(G - 1)}


def delta_bootstrap(X, y_r, y_ref, groups, k=1, B=4000, seed=42):
    """Day-cluster bootstrap percentile interval of b_r[k] - b_ref[k]; both fits refitted on every draw (sufficient statistics per day)."""
    inv, nb = DS._codes(groups)
    p = X.shape[1]
    XX, Xr, Xf = np.zeros((nb, p, p)), np.zeros((nb, p)), np.zeros((nb, p))
    np.add.at(XX, inv, X[:, :, None] * X[:, None, :])
    np.add.at(Xr, inv, X * y_r[:, None])
    np.add.at(Xf, inv, X * y_ref[:, None])
    est, skipped = [], 0
    for w in DS.boot_weights(nb, B, seed):
        A = np.tensordot(w, XX, 1)
        if np.linalg.matrix_rank(A) < p:
            skipped += 1
            continue
        est.append(np.linalg.solve(A, np.tensordot(w, Xr, 1))[k] - np.linalg.solve(A, np.tensordot(w, Xf, 1))[k])
    lo, hi = np.percentile(est, [2.5, 97.5])
    return {"ci95": [float(lo), float(hi)], "nDraws": int(len(est)), "skippedSingular": int(skipped), "nBlocks": int(nb)}


def single_label(point, b_ref, d_lo, d_hi, cr1_lo):
    """Per-outcome label under the frozen rule's own conditions (used by the operating characteristic): explained_like / supported_like / consistent_imprecise."""
    if (point < HALF * b_ref and d_hi < 0) or (point < 0 and d_hi < 0):
        return "explained_like"
    if d_lo > -HALF * b_ref and cr1_lo > 0:
        return "supported_like"
    return "consistent_imprecise"


def power_gate(d, X, y_r, y_ref, thetas, draws=500, seed=42):
    """Inject known slopes (theta) into the de-trended outcome and its reference on the real rows, resample whole days (each duplicate its own cluster), refit; report detection probability,
    median CR1 half-width, the share of per-outcome labels (analytic Delta interval per draw) and the minimum effect with 80 % power at the real-data SE."""
    months = X[:, 1]
    days = d["day"].to_numpy()
    ud = np.unique(days)
    idx_by = {u: np.flatnonzero(days == u) for u in ud}
    base_r = y_r - np.linalg.lstsq(X, y_r, rcond=None)[0][1] * months
    base_f = y_ref - np.linalg.lstsq(X, y_ref, rcond=None)[0][1] * months
    rng = np.random.default_rng(seed)
    picks = [rng.integers(0, len(ud), len(ud)) for _ in range(draws)]
    out = {}
    for th_name, th in thetas.items():
        det, hw, labs = 0, [], {"explained_like": 0, "supported_like": 0, "consistent_imprecise": 0}
        used = 0
        for pk in picks:
            rows, cl = [], []
            for c, u in enumerate(ud[pk]):
                ix = idx_by[u]
                rows.append(ix)
                cl.append(np.full(len(ix), c))
            rows, cl = np.concatenate(rows), np.concatenate(cl)
            Xs = X[rows]
            if np.linalg.matrix_rank(Xs) < X.shape[1]:
                continue
            yr, yf = base_r[rows] + th * months[rows], base_f[rows] + th * months[rows]
            b, se, G, n, p = DS.cr1(Xs, yr, cl, 1)
            t1 = stats.t.ppf(0.975, G - 1)
            bf = DS.cr1(Xs, yf, cl, 1)[0]
            da = delta_analytic(Xs, yr, yf, cl)
            used += 1
            det += (b - t1 * se) > 0
            hw.append(t1 * se)
            labs[single_label(b, bf, da["ci95"][0], da["ci95"][1], b - t1 * se)] += 1
        out[th_name] = {"theta": float(th), "draws": used, "detection_probability": det / used if used else None,
                        "median_half_width": float(np.median(hw)) if hw else None,
                        "label_shares": {k: v / used for k, v in labs.items()} if used else None}
    return out


def mde80(se, G):
    return float((stats.t.ppf(0.975, G - 1) + stats.t.ppf(0.80, G - 1)) * se)


def verdict(prim):
    """Frozen decision rule over the primary outcomes. prim: {name: dict(informative, point, b_ref, delta_lo, delta_hi, cr1_lo)}."""
    inf = {k: v for k, v in prim.items() if v["informative"]}
    if inf:
        explained = lambda v: v["point"] < HALF * v["b_ref"] and v["delta_hi"] < 0
        if (len(inf) == len(prim) and len(prim) >= 2 and all(explained(v) for v in inf.values())) or any(v["point"] < 0 and v["delta_hi"] < 0 for v in inf.values()):
            return "not_supported", sorted(inf)
        if all(v["delta_lo"] > -HALF * v["b_ref"] and v["cr1_lo"] > 0 for v in inf.values()):
            return "supported_provisional", sorted(inf)
        return "consistent_imprecise", sorted(inf)
    return "underpowered_inconclusive", []


# ------------------------------------------------------------------------------------------------ run
def outcome_table(frame, data, name, m=M_PRIMARY, kind="q", off_ms=50.0, balanced=False):
    st, N, p95 = [], [], []
    for f in frame["file"].astype(str):
        a = data.get(f)
        if a is None:
            st.append(np.nan), N.append(0), p95.append(np.nan)
            continue
        s, n, p = drive_values(a, name, m, kind, off_ms, balanced)
        st.append(s), N.append(n), p95.append(p)
    return np.array(st), np.array(N), np.array(p95)


def _wls_slope(d, ycol, w, cols=()):
    dd = d.dropna(subset=[ycol]).copy()
    dd["y"] = dd[ycol]
    X, y = M0.design(dd, list(cols))
    sw = np.sqrt(w[dd.index.to_numpy()] if hasattr(w, "__len__") else w)
    b, se, G, n, p = DS.cr1(X * sw[:, None], y * sw, dd["day"].to_numpy(), 1)
    t1 = stats.t.ppf(0.975, G - 1)
    return {"slope": b, "se": se, "ci95": [b - t1 * se, b + t1 * se], "n_drives": int(n), "n_days": int(G)}


def analyse_outcomes(frame, data, B, power_draws, released=None):
    """Everything in the spec for one design frame (columns of M0.build_frame + file) and the pair data. Returns the results dict without provenance."""
    fr = frame.reset_index(drop=True).copy()
    fr["fast"] = (fr["regime"] == "fast").astype(float)
    res = {"outcomes": {}}
    cols = {"O1": ("O1", 50.0), "O2": ("O2", 50.0)}
    for key, (name, off) in cols.items():
        v, N, p95 = outcome_table(fr, data, name, off_ms=off)
        fr["y_" + key], fr["N_" + key], fr["p95_" + key] = v, N, p95
    v0, N0, p950 = outcome_table(fr, data, "O0")
    fr["y_O0"], fr["N_O0"], fr["p95_O0"] = v0, N0, p950
    v3, N3, p953 = outcome_table(fr, data, "O3")
    fr["y_O3"], fr["N_O3"], fr["p95_O3"] = v3, N3, p953
    # reference on all its own rows
    s0, X0, y0, d0 = fit_outcome(fr, "y_O0", (), B, full=True)
    res["O0m"] = s0
    res["O0m"]["moving_block"] = {"L%d" % L: SD.moving_block(X0, y0, SD.day_axis(d0["date"]), L, B) for L in SD.BLOCK_L}
    ref_rows = len(d0)
    prim = {}
    for key, extra in (("O1", ()), ("O2", ("fast",)), ("O3", ())):
        yc = "y_" + key
        rows = fr.dropna(subset=[yc] + (["fast"] if extra else [])).copy()
        rows = rows[rows["y_O0"].notna()]
        if extra:
            rows = rows[rows["regime"].notna()]
        entry = {"n_drives": int(len(rows)), "n_days": int(rows["day"].nunique()) if len(rows) else 0}
        if len(rows) < 20 or entry["n_days"] < 5:
            entry["evaluable"] = False
            res["outcomes"][key] = entry
            continue
        s, X, y, d = fit_outcome(rows, yc, extra, B, full=True)
        sref, Xr, yr, dr = fit_outcome(rows, "y_O0", extra, 0, full=False)
        entry.update(s)
        entry["O0m_on_rows"] = {"slope": sref["slope"], "se": sref["se"], "ci95": sref["ci95"]}
        entry["lost_fraction_vs_O0m_rows"] = 1.0 - len(rows) / ref_rows
        entry["regime_mix"] = rows["regime"].value_counts().to_dict()
        da = delta_analytic(X, y, yr, d["day"].to_numpy())
        db = delta_bootstrap(X, y, yr, d["day"].to_numpy(), 1, B, 42)
        point_in = db["ci95"][0] <= da["delta"] <= db["ci95"][1]
        entry["delta"] = {"point": da["delta"], "analytic": da["ci95"], "bootstrap": db, "bootstrap_contains_point": bool(point_in),
                          "used_for_verdict": "bootstrap" if point_in else "analytic"}
        entry["slope_ratio_vs_O0m_rows"] = s["slope"] / sref["slope"] if sref["slope"] else None
        if key in ("O1", "O2"):
            b_ref = sref["slope"]
            thetas = {"theta_0": 0.0, "theta_half_ref": 0.5 * b_ref, "theta_ref": b_ref}
            entry["power_gate"] = power_gate(d, X, y, yr, thetas, power_draws) if b_ref > 0 else {"skipped": "b_ref not positive"}
            det_ref = entry["power_gate"].get("theta_ref", {}).get("detection_probability") if b_ref > 0 else None
            half_width = (s["ci95"][1] - s["ci95"][0]) / 2
            entry["mde80"] = mde80(s["se"], s["n_days"])
            under = (b_ref <= 0) or (det_ref is None) or (det_ref < DETECT_MIN) or (half_width > b_ref)
            entry["underpowered"] = bool(under)
            entry["informative"] = bool((not under) and entry["n_drives"] >= MIN_DRIVES and entry["n_days"] >= MIN_DAYS)
            dl, dh = (entry["delta"]["bootstrap"]["ci95"] if point_in else entry["delta"]["analytic"])
            prim[key] = {"informative": entry["informative"], "point": s["slope"], "b_ref": b_ref, "delta_lo": dl, "delta_hi": dh, "cr1_lo": s["ci95"][0]}
            entry["moving_block"] = {"L%d" % L: SD.moving_block(X, y, SD.day_axis(d["date"]), L, B) for L in SD.BLOCK_L}
        res["outcomes"][key] = entry
    res["primary_inputs"] = prim
    res["verdict"], res["informative_outcomes"] = verdict(prim)
    res["verdict_rule_precedence"] = "not_supported > supported_provisional > consistent_imprecise > underpowered_inconclusive"
    # sensitivities and companions (reported, never in the verdict)
    sens = {}
    for key, name, extra in (("O1", "O1", ()), ("O2", "O2", ("fast",))):
        for label, kw in (("m10", dict(m=10)), ("m30", dict(m=30)), ("median", dict(kind="median")), ("balanced", dict(balanced=True))) + tuple(("off%d" % o, dict(off_ms=o)) for o in (25.0, 100.0) if name == "O2"):
            v, N, _ = outcome_table(fr, data, name, **kw)
            tmp = fr.copy()
            tmp["y_s"] = v
            rows = tmp.dropna(subset=["y_s"] + (["fast"] if extra else []))
            if extra:
                rows = rows[rows["regime"].notna()]
            if len(rows) < 20 or rows["day"].nunique() < 5:
                sens[key + "_" + label] = {"evaluable": False, "n_drives": int(len(rows))}
                continue
            s, _, _, _ = fit_outcome(rows, "y_s", extra, 0)
            sens[key + "_" + label] = {k: s[k] for k in ("slope", "se", "ci95", "n_drives", "n_days")}
        rows = fr.dropna(subset=["y_" + key] + (["fast"] if extra else []))
        if extra:
            rows = rows[rows["regime"].notna()]
        if len(rows) >= 20:
            w = np.minimum(rows["N_" + key].to_numpy(float), 200.0)
            tmp = rows.copy()
            tmp["w"] = w
            dd = tmp.reset_index(drop=True)
            Xw, yw = M0.design(dd.assign(y=dd["y_" + key]), list(extra))
            sw = np.sqrt(dd["w"].to_numpy())
            b, se, G, n, p = DS.cr1(Xw * sw[:, None], yw * sw, dd["day"].to_numpy(), 1)
            t1 = stats.t.ppf(0.975, G - 1)
            sens[key + "_wls_min(N,200)"] = {"slope": b, "se": se, "ci95": [b - t1 * se, b + t1 * se], "n_drives": int(n), "n_days": int(G)}
            r2 = dd.dropna(subset=["p95_" + key])
            if len(r2) >= 20:
                s, _, _, _ = fit_outcome(r2.assign(y=r2["p95_" + key]), "y", extra, 0)
                sens[key + "_released_statistic_variable_n"] = {k: s[k] for k in ("slope", "se", "ci95", "n_drives", "n_days")}
    res["sensitivities"] = sens
    # slow regime, cutoffs, leave-last-8 for O0m, O1m, O2m
    comp = {}
    for key, extra in (("O0", ()), ("O1", ()), ("O2", ("fast",))):
        yc = "y_" + key
        rows = fr.dropna(subset=[yc])
        sl = rows[rows["regime"] == "slow"]
        if len(sl) >= 20 and sl["day"].nunique() >= 5:
            s, _, _, _ = fit_outcome(sl, yc, (), B, full=True)
            comp[key + "_slow_regime"] = {k: s[k] for k in ("slope", "se", "ci95", "n_drives", "n_days", "months_span")}
        else:
            comp[key + "_slow_regime"] = {"evaluable": False, "n_drives": int(len(sl))}
        series = []
        last = str(pd.to_datetime(rows["date"]).max().date())
        for c in list(CUTOFFS) + [last]:
            sub = rows[pd.to_datetime(rows["date"]) <= pd.Timestamp(c)]
            if len(sub) >= 20 and sub["day"].nunique() >= 5:
                s, _, _, _ = fit_outcome(sub, yc, extra if extra and sub["regime"].notna().all() else (), 0)
                series.append({"cutoff": c, "n_drives": s["n_drives"], "n_days": s["n_days"], "slope": s["slope"], "ci95": s["ci95"]})
            else:
                series.append({"cutoff": c, "evaluable": False, "n_drives": int(len(sub))})
        keep = sorted(rows["day"].unique())[:-8]
        sub = rows[rows["day"].isin(keep)]
        if len(sub) >= 20:
            s, _, _, _ = fit_outcome(sub, yc, (), 0)
            series.append({"cutoff": "leave_last_8_days_out", "n_drives": s["n_drives"], "n_days": s["n_days"], "slope": s["slope"], "ci95": s["ci95"]})
        comp[key + "_cutoffs"] = series
    comp["O2_slow_regime_primary_adjacent"] = comp["O2_slow_regime"]
    res["companions"] = comp
    return res


def cache_checks(master, side, data):
    """Internal known-answer checks (spec): loaded count, pair count and loaded p95 reproduce the master / sidecar for every drive. Returns the list of problems."""
    bad = []
    s = side.set_index("file")
    mm = master.set_index("file")
    for f in master["file"].astype(str):
        a = data.get(f)
        nl_m = mm.loc[f].get("n_loaded_spread_samples")
        if a is None:
            if not pd.isna(nl_m):
                bad.append("%s: no pairs but master has loaded samples" % f)
            continue
        ld = np.abs(a["I"]) > LOADED_A
        n_l = int(np.nansum(ld))
        if (pd.isna(nl_m) and n_l != 0) or (not pd.isna(nl_m) and n_l != int(nl_m)):
            bad.append("%s: loaded %d != master %s" % (f, n_l, nl_m))
        sn = s.loc[f].get("n_loaded")
        if not pd.isna(sn) and int(sn) != n_l:
            bad.append("%s: loaded %d != sidecar %s" % (f, n_l, sn))
        sp = s.loc[f].get("n_pairs")
        if not pd.isna(sp) and int(sp) != len(a["t"]):
            bad.append("%s: pairs %d != sidecar %s" % (f, len(a["t"]), sp))
        p95_m = mm.loc[f].get("cell_spread_loaded_p95_mv")
        if n_l and not pd.isna(p95_m) and abs(float(np.quantile(a["spread_mv"][ld], Q)) - float(p95_m)) > 0.05 + 1e-9:
            bad.append("%s: loaded p95 %.4f vs master %.1f" % (f, float(np.quantile(a["spread_mv"][ld], Q)), p95_m))
    return bad


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main(argv=None):
    import pair_cache as PC
    import ah_throughput as AH
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M480b_results.json"))
    ap.add_argument("--boot", type=int, default=4000)
    ap.add_argument("--power-draws", type=int, default=500)
    a = ap.parse_args(argv)
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    side = pd.read_csv(os.path.join(ROOT, "timing_support.csv"), keep_default_na=False, na_values=[""], dtype={"raw_sha256": str})
    data, man, mh = PC.build_all(dm, AH.raw_loader(), AH.manifest_sha_lookup())
    bad = cache_checks(dm, side, data)
    if bad:
        for b in bad[:20]:
            print("FAIL", b)
        raise SystemExit("STOP: pair cache does not reproduce the master / sidecar (%d problems)" % len(bad))
    A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    released = A["degradationTrends"]["cellSpread"]["clusterRobustOLS"]
    frame = M0.build_frame(dm, side)
    s0, _, _ = M0.fit(frame, [], 0)
    if abs(s0["slope"] - released["slope"]) > M0.S0_TOL:
        raise SystemExit("STOP: S0 does not reproduce the released slope")
    res = analyse_outcomes(frame, data, a.boot, a.power_draws, released)
    res["cache_checks"] = {"drives_checked": int(len(dm)), "problems": 0}
    res["method"] = {"version": METHOD_VERSION, "estimator": "fixed-n upper L-statistic, exact expectation of the numpy-linear p95 of an m-subset (m=20 primary)", "design": "OLS y ~ months + T + I (+ regime indicator for O2m); cluster = calendar day; CR1 t(G-1)",
                     "seed": 42, "boot": a.boot, "power_draws": a.power_draws, "halfRule": HALF, "minDrives": MIN_DRIVES, "minDays": MIN_DAYS, "detectMin": DETECT_MIN,
                     "implementationNote": "the power gate's operating characteristic is reported per outcome (labels explained_like / supported_like / consistent_imprecise) because the combined verdict needs both outcomes on different rows"}
    res["provenance"] = {"master_md5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "sidecar_sha256": sha256(os.path.join(ROOT, "timing_support.csv")),
                         "pair_cache_manifest_hash": mh, "script_sha256": sha256(os.path.abspath(__file__)), "pair_cache_script_sha256": sha256(os.path.join(ROOT, "tools", "pair_cache.py")),
                         "spec_sha256": sha256(os.path.join(ROOT, "analyses", "M480b_spec.md"))}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=float)
        f.write("\n")
    print(json.dumps({"verdict": res["verdict"], "informative": res["informative_outcomes"], "O0m": [round(res["O0m"]["slope"], 4), res["O0m"]["n_drives"], res["O0m"]["n_days"]]}))


if __name__ == "__main__":
    main()
