#!/usr/bin/env python3
"""M435 (spec analyses/M435_spec.md Rev 2, audit F17): censoring-aware time-to-threshold estimators for the coolant / oil warm-up.
Pure numpy; no repo imports at module level. A drive is (t, e, day): t = event time or censoring time in seconds, e = event observed, day = calendar-day cluster.
Everything is computed with per-drive WEIGHTS so that the day-clustered bootstrap is a matrix operation: a draw = integer counts of each day, a drive's weight = the count of its day.
Estimators (all functions take weights W of shape (B, n); the point estimate is the row of ones):
  km_steps / surv_at   Kaplan-Meier (product-limit), ties: events before censorings (a censored drive at the same second is still at risk)
  tilt_F               hazard-tilt sensitivity: a drive censored at c contributes (S_KM(t)/S_KM(c))**theta for t > c (multiplies the cumulative hazard of the remaining time)
  manski               worst-case identification bounds: F_low = reached by h / n, F_high = (reached by h + censored strictly before h) / n
  median_time, rmst    median = inf{t: S(t) <= 0.5} (inf if never), restricted mean time to tau
E1 (observed share reaching by h before key-off) is numerically F_low: a drive censored for any reason counts as not reached."""
import numpy as np


def day_counts(universe, B, seed):
    """B day-clustered resamples of the days in `universe` (with replacement, as many draws as days): integer counts (B, n_days). One set per cohort, shared by all cells (spec Rev 2.1 C4)."""
    rng = np.random.default_rng(seed)
    nd = len(universe)
    idx = rng.integers(0, nd, (B, nd))
    counts = np.zeros((B, nd))
    for b in range(B):
        counts[b] = np.bincount(idx[b], minlength=nd)
    return counts


class Cell:
    """Sorted, immutable data of one (cohort, fluid, threshold) cell."""

    def __init__(self, t, e, day):
        t = np.asarray(t, float); e = np.asarray(e, bool); day = np.asarray(day)
        order = np.lexsort((~e, t))                       # by time; events before censorings at the same second
        self.t, self.e, self.day_raw = t[order], e[order], day[order]
        self.days, self.day_idx = np.unique(self.day_raw, return_inverse=True)
        self.n = len(t)
        self.u = np.unique(self.t[self.e])                # distinct event times
        self.ev_pos = np.searchsorted(self.u, self.t[self.e])        # event drive -> index into u
        self.cens = np.where(~self.e)[0]
        self.c_t = self.t[self.cens]
        # step index of S at each censoring time: number of event times <= c  (S before the first event = 1)
        self.c_step = np.searchsorted(self.u, self.c_t, side="right")

    # ---- weights
    def ones(self):
        return np.ones((1, self.n))

    def draws(self, B, seed):
        """Day-clustered resample weights from this cell's own days (B, n)."""
        return self.weights(day_counts(self.days, B, seed), self.days)

    def weights(self, counts, universe):
        """Per-drive weights (B, n) from the day counts of a shared resample over `universe` (sorted day labels): a drive's weight is the count of its day."""
        pos = np.searchsorted(universe, self.day_raw)
        return counts[:, pos]

    # ---- Kaplan-Meier on weights
    def surv_steps(self, W):
        """S after each distinct event time, shape (B, len(u)); a draw with no weight at risk keeps S flat."""
        nu = len(self.u)
        if nu == 0:
            return np.ones((W.shape[0], 0))
        for_ev = W[:, self.e]
        # events per distinct time (a 0/1 indicator matrix product avoids a loop over unique times)
        M = np.zeros((self.e.sum(), nu)); M[np.arange(self.e.sum()), self.ev_pos] = 1.0
        d = for_ev @ M
        # at risk at u_j = weight of drives with t >= u_j
        suffix = np.cumsum(W[:, ::-1], axis=1)[:, ::-1]          # suffix[:, k] = sum of W over sorted positions >= k
        first_pos = np.searchsorted(self.t, self.u, side="left")
        n_at = suffix[:, first_pos]
        with np.errstate(divide="ignore", invalid="ignore"):
            f = np.where(n_at > 0, 1.0 - d / n_at, 1.0)
        return np.cumprod(f, axis=1)

    def surv_at(self, S, times):
        """S(t) for scalar/array t from the step matrix S (B, nu)."""
        times = np.atleast_1d(np.asarray(times, float))
        k = np.searchsorted(self.u, times, side="right")          # number of event times <= t
        Sx = np.concatenate([np.ones((S.shape[0], 1)), S], axis=1)
        return Sx[:, k]

    def surv_at_cens(self, S):
        Sx = np.concatenate([np.ones((S.shape[0], 1)), S], axis=1)
        return Sx[:, self.c_step]

    # ---- sensitivity
    def tilt_surv(self, W, S, h, theta):
        """S_theta(h) per draw, shape (B,): events contribute 1{T > h}; drives censored at c >= h contribute 1; censored at c < h contribute (S(h)/S(c))**theta."""
        h = float(h)
        w = W
        ev_alive = (w[:, self.e] * (self.t[self.e] > h)).sum(axis=1)
        cens_alive = (w[:, self.cens] * (self.c_t >= h)).sum(axis=1)
        Sh = self.surv_at(S, h)[:, 0:1]                           # (B,1)
        Sc = self.surv_at_cens(S)                                 # (B, ncens)
        before = self.c_t < h
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(Sc > 0, Sh / Sc, 0.0)
        r = np.where(before[None, :], np.power(np.where(before[None, :], ratio, 1.0), theta), 0.0)
        tilt = (w[:, self.cens] * r).sum(axis=1)
        return (ev_alive + cens_alive + tilt) / w.sum(axis=1)

    def manski(self, W, h):
        h = float(h)
        n = W.sum(axis=1)
        reached = (W[:, self.e] * (self.t[self.e] <= h)).sum(axis=1)
        cens_before = (W[:, self.cens] * (self.c_t < h)).sum(axis=1)
        return reached / n, (reached + cens_before) / n

    def median_time(self, S):
        """Per draw: first event time with S <= 0.5, else inf."""
        if S.shape[1] == 0:                                   # no event time at all: the median is never reached
            return np.full(S.shape[0], np.inf)
        hit = S <= 0.5
        any_ = hit.any(axis=1)
        first = np.argmax(hit, axis=1)
        out = np.full(S.shape[0], np.inf)
        if len(self.u):
            out[any_] = self.u[first[any_]]
        return out

    def rmst(self, S, tau):
        """Integral of S over [0, tau]."""
        tau = float(tau)
        if len(self.u) == 0:
            return np.full(S.shape[0], tau)
        edges = np.concatenate([[0.0], np.minimum(self.u, tau), [tau]])
        widths = np.diff(edges)                                    # widths[j] = length where S equals S_{j-1} (S_{-1}=1)
        Sx = np.concatenate([np.ones((S.shape[0], 1)), S], axis=1)
        return (Sx * widths[None, :]).sum(axis=1)

    # ---- support
    def at_risk(self, h):
        m = self.t >= float(h)
        return int(m.sum()), int(len(np.unique(self.day_raw[m])))


def tilt_limit_inf(cell, h):
    """Exact theta -> infinity limit of S_theta(h) (KAT): events 1{T>h}, censored c >= h -> 1, censored c < h -> 1 if no KM step in (c, h] else 0."""
    k_h = int(np.searchsorted(cell.u, float(h), side="right"))          # Kaplan-Meier steps up to h
    ev = (cell.t[cell.e] > h).sum()
    ca = (cell.c_t >= h).sum()
    flat = ((cell.c_t < h) & (cell.c_step == k_h)).sum()               # no Kaplan-Meier step in (c, h], by step index
    return (ev + ca + flat) / cell.n


def tilt_limit_zero(cell, h):
    """Exact theta -> 0+ limit: censored c < h -> 1 if S_KM(h) > 0 else 0."""
    S = cell.surv_steps(cell.ones())
    Sh = cell.surv_at(S, h)[0, 0]
    ev = (cell.t[cell.e] > h).sum()
    ca = (cell.c_t >= h).sum()
    before = (cell.c_t < h).sum()
    return (ev + ca + (before if Sh > 0 else 0)) / cell.n


def bisect_tipping(cell, h, level=0.5, lo=0.01, hi=100.0, iters=60):
    """theta in [lo, hi] at which F_theta(h) = level (F_theta increases with theta); None if F_theta(h) does not cross the level inside the interval."""
    W = cell.ones(); S = cell.surv_steps(W)
    f = lambda th: 1.0 - cell.tilt_surv(W, S, h, th)[0] - level
    flo, fhi = f(lo), f(hi)
    if flo == 0.0:
        return lo
    if fhi == 0.0:
        return hi
    if flo * fhi > 0:
        return None
    a, b = np.log(lo), np.log(hi)
    for _ in range(iters):
        m = 0.5 * (a + b)
        fm = f(np.exp(m))
        if fm == 0.0:
            return float(np.exp(m))
        if flo * fm < 0:
            b = m
        else:
            a, flo = m, fm
    return float(np.exp(0.5 * (a + b)))


def pct(x, lo=2.5, hi=97.5):
    """Percentile interval over ALL draws, linear interpolation as numpy; +inf draws (an unidentified median) stay in the sample: an interpolation that touches +inf is +inf."""
    x = np.sort(np.asarray(x, float))
    n = len(x)

    def one(q):
        pos = (n - 1) * q / 100.0
        a = int(np.floor(pos)); b = min(a + 1, n - 1); f = pos - a
        if f == 0.0 or x[a] == x[b]:
            return float(x[a])
        if np.isinf(x[b]) or np.isinf(x[a]):
            return float("inf") if np.isinf(x[b]) else float(x[a])
        return float(x[a] + (x[b] - x[a]) * f)
    return [one(lo), one(hi)]


def bisect_limit(cell, W, S, h, side, level=0.5, lo=0.01, hi=100.0, tol_log=0.01):
    """theta at which the 95 % limit (side 'upper' = 97.5th, 'lower' = 2.5th percentile over the draws) of F_theta(h) crosses `level`; bisection on log theta until the interval is shorter
    than tol_log; None if it does not cross inside [lo, hi]. F_theta is monotone in theta for every draw, so is its percentile."""
    q = 97.5 if side == "upper" else 2.5
    f = lambda th: float(np.percentile(1.0 - cell.tilt_surv(W, S, h, th), q)) - level
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None
    a, b = np.log(lo), np.log(hi)
    while b - a >= tol_log:
        m = 0.5 * (a + b)
        fm = f(np.exp(m))
        if flo * fm <= 0:
            b = m
        else:
            a, flo = m, fm
    return float(np.exp(0.5 * (a + b)))
