"""M578 (Director): the payload stores the M438 stratum weights at 4 decimals; each stored weight must equal its stratum share n_i / N to that precision, and their sum must be 1 within 5e-5 x k."""
TOL = 0.5e-4


def weights_match_shares(weights, ns, n_total):
    if len(weights) != len(ns) or sum(ns) != n_total or n_total <= 0:
        return False
    return abs(sum(weights) - 1.0) <= TOL * len(weights) + 1e-9 and all(abs(w - n / n_total) <= TOL + 1e-9 for w, n in zip(weights, ns))
