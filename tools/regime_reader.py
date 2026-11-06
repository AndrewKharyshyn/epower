"""M585 (spec analyses/M585_spec.md Rev 1; M582b): the ONE source of the logger fast / slow rule on the HV-current sampling period I_sample_period_s (seconds).
fast iff period < THRESHOLD_S (strict), slow iff period >= THRESHOLD_S, None for a missing period; a period inside the guard zone [GUARD_ZONE[0], GUARD_ZONE[1]) STOPs for the Director.
Threshold 1.10 s and the guard zone are the owner decision of M578 (analyses/M379_rev4_addendum.md), chosen post hoc; historical assignments are unchanged. Pure, no I/O.
The window-median crossing test of tools/timing_support.py uses THRESHOLD_S only (window medians are not drive periods)."""
THRESHOLD_S = 1.10
GUARD_ZONE = (1.06, 1.135)


def regime_of(period):
    """'fast' / 'slow' / None (missing). STOP (SystemExit) inside the guard zone."""
    if period is None or period != period:
        return None
    p = float(period)
    if GUARD_ZONE[0] <= p < GUARD_ZONE[1]:
        raise SystemExit("STOP: a drive lies inside the declared guard zone [%.3f, %.3f) s (period %.3f): the bimodal assumption no longer holds (Director)" % (GUARD_ZONE[0], GUARD_ZONE[1], p))
    return "fast" if p < THRESHOLD_S else "slow"


def slow_flag(period, missing=float("nan")):
    """1.0 for slow, 0.0 for fast, `missing` for a missing period (the caller keeps its own old missing-value behaviour)."""
    r = regime_of(period)
    return missing if r is None else (1.0 if r == "slow" else 0.0)
