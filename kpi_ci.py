"""Day-cluster percentile bootstrap for ratio-of-sums KPIs (Section 9 CI/ESS plumbing)."""
import numpy as np, pandas as pd

def day_cluster_ci(num, den, days, scale=100.0, B=4000, seed=20260919, dmode='num_den'):
    """CI for scale*sum(num)/sum(den), resampling calendar days (clusters) with replacement.
    Returns (value, lo, hi, nClusters, essDays). ESS = Kish (sum w)^2/sum w^2, w = per-day denominator."""
    df = pd.DataFrame({'n': np.asarray(num, float), 'd': np.asarray(den, float), 'day': np.asarray(days)})
    g = df.groupby('day')[['n', 'd']].sum()
    K = len(g); N = g['n'].to_numpy(); D = g['d'].to_numpy()
    val = scale * N.sum() / D.sum()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, K, size=(B, K))
    bs = scale * N[idx].sum(1) / D[idx].sum(1)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    w = D
    ess = (w.sum() ** 2) / (w ** 2).sum()
    return val, float(lo), float(hi), int(K), float(ess)
