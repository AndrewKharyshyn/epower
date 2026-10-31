#!/usr/bin/env python3
"""M545 (analyses/M545_spec.md Rev 2): module-level PURE kernels of the _RawAccum engine-on blocks (engineOnDuration, engineOnBySpeed, turboByRpm / turboBySpeedCtx, hvcTurboActivity) with an explicit threshold argument
and the strict comparison `rpm > thr`. _RawAccum calls them at ENGINE_ON_STORED_RPM (300; the stored payload stays byte-identical, G0); the sidecar stage tools/engine_on_blocks_stage.py calls them at the rule threshold (400).
Array semantics are those of the former inline code: NaN is never engine-on; the grid kernel returns run lengths of the contiguous engine-on runs on the 1 Hz grid (NaN breaks a run); native-row kernels use native rows."""
import numpy as np

ENGINE_ON_STORED_RPM = 300      # the stored (legacy) engine-on gate of _RawAccum; the project rule (rpm > 400) is tools/engine_on_rule.py
GRID_VERSION = "M543-floor-to-second-mean"


def engine_on_runs(rr, thr):
    """1 Hz grid -> None when no valid sample, else dict(durs=float array of run lengths (s), on, valid, nseg). Segment = maximally contiguous run of rr > thr (NaN breaks a run)."""
    valid = ~np.isnan(rr)
    if not valid.any():
        return None
    eon = (rr > thr) & valid
    dd = np.diff(eon.astype(int), prepend=0)
    starts = np.where(dd == 1)[0]
    ends = np.where(np.diff(eon.astype(int), append=0) == -1)[0]
    nseg = min(len(starts), len(ends))
    durs = (ends[:nseg] - starts[:nseg] + 1).astype(float)
    return {"durs": durs, "on": float(eon.sum()), "valid": float(valid.sum()), "nseg": float(nseg)}


def engine_on_by_speed(sp, rp, speed_edges, n_zones, thr):
    """native rows -> (tot, on, any_ok): per-zone counts of rows with a valid speed and rpm, and of those with rpm > thr. speed_edges are the inner zone edges (np.digitize)."""
    z = np.digitize(sp, speed_edges)
    eng = rp > thr
    ok = ~np.isnan(sp) & ~np.isnan(rp)
    tot = np.zeros(n_zones)
    on = np.zeros(n_zones)
    for i in range(n_zones):
        m = (z == i) & ok
        tot[i] += m.sum()
        on[i] += (eng & m).sum()
    return tot, on, bool(ok.any())


def turbo_by_rpm_band(bo, rp, bands, thr):
    """native rows -> {label: dict(n, act, sumAct, max)} for the rpm bands holding at least one engine-on row with a valid boost; act = boost > 0.1 bar"""
    eng = rp > thr
    out = {}
    for lo, hi, lbl in bands:
        m = (rp >= lo) & (rp < hi) & eng & ~np.isnan(bo)
        if not m.any():
            continue
        bb = bo[m]
        act = bb[bb > 0.1]
        out[lbl] = {"n": len(bb), "act": len(act), "sumAct": act.sum(), "max": float(bb.max())}
    return out


def turbo_by_speed_zone(bo, rp, sp, zones, thr):
    """native rows -> {label: dict(n, act, max)} for the speed zones holding at least one engine-on row with a valid boost"""
    eng = rp > thr
    out = {}
    for lo, hi, lbl in zones:
        m = (sp >= lo) & (sp < hi) & eng & ~np.isnan(bo)
        if not m.any():
            continue
        bb = bo[m]
        out[lbl] = {"n": len(bb), "act": (bb > 0.1).sum(), "max": float(bb.max())}
    return out


def hvc_turbo_counts(bo, rp, thr):
    """native rows -> None when no engine-on row with a valid boost, else dict(n, act, max)"""
    m = (rp > thr) & ~np.isnan(bo)
    if not m.any():
        return None
    bb = bo[m]
    return {"n": int(len(bb)), "act": int((bb > 0.1).sum()), "max": float(bb.max())}
