#!/usr/bin/env python3
"""M736 (analyses/M736_spec.md Rev 1): P2 scoring of registry v4. Wraps the UNCHANGED v3 band (winter_p2_band.realised_band) with (2.1) the path-carry bound and (2.2) the offset-adjusted sensitivity.
`p2_v4(frame, band_fn, evaluate_fn, prov=None, expected_primary=None)`: `band_fn(frame, offset)` returns a realised-band dict (windowMatched [lo, hi]) with shift_m reduced by `offset`;
`evaluate_fn(band)` returns the call ('within the band', 'outside the band', 'inconclusive') of the observed interval against a band. Model-derived band; offset-adjusted sensitivity, never a corrected shift."""
import json, os, tempfile
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
VERSION = 1
CHECK = "analyses/M735_p2_window_check.json"


def provenance():
    r = json.load(open(os.path.join(ROOT, CHECK), encoding="utf-8"))["result"]
    offs = [v["meanOffsetC"] for v in r["ambientOffsetByMonth"].values()]
    return {"bound": float(r["maxRelDiffAhLt10"]), "offsets": [0.0, round(min(offs), 2), round(max(offs), 2)]}


def carry_bands(band, b):
    lo, hi = band
    s_lo, s_hi = lo * (1 + b), hi * (1 - b)
    if s_lo > s_hi:
        s_lo = s_hi = (lo + hi) / 2.0
    return {"asComputed": [lo, hi], "shrunk": [s_lo, s_hi], "widened": [lo * (1 - b), hi * (1 + b)]}


def p2_v4(frame, band_fn, evaluate_fn, prov=None, expected_primary=None):
    prov = prov or provenance()
    b, offs = prov["bound"], prov["offsets"]
    runs = {}
    for o in offs:
        rb = band_fn(frame, o)
        if rb.get("status") != "ok":
            return {"status": "not evaluable", "reason": "realised band not available at offset %.2f: %s" % (o, rb.get("reason")), "offsets": offs}
        runs[o] = rb
    prim = runs[offs[0]]
    if expected_primary is not None and list(prim["windowMatched"]) != list(expected_primary):       # R1 (Director M736): the offset-0 band must be the v3 band to float identity
        return {"status": "not evaluable", "reason": "the offset-0 band differs from the v3 realised band (float identity required)", "offsets": offs}
    cb = carry_bands(prim["windowMatched"], b)
    carry_calls = {k: evaluate_fn(v) for k, v in cb.items()}
    off_calls = {("%.2f" % o): evaluate_fn(runs[o]["windowMatched"]) for o in offs}
    out = {"offsets": offs, "pathCarryBound": b, "carryBands": cb, "carryCalls": carry_calls, "offsetCalls": off_calls,
           "offsetBands": {("%.2f" % o): runs[o]["windowMatched"] for o in offs}, "diagnostic": prim.get("table"), "thinMonths": prim.get("thinMonths"), "fillNotOffsetShifted": bool(prim.get("thinMonths")), "primaryCall": off_calls["%.2f" % offs[0]]}
    if len(set(carry_calls.values())) > 1:
        out.update(status="not evaluable (path-carry)", call=None)
    elif len(set(off_calls.values())) > 1:
        out.update(status="not established (ambient-scale sensitive)", call=None)
    else:
        out.update(status=out["primaryCall"], call=out["primaryCall"])
    return out


def band_fn_engine(frame, offset, nb=4000):
    """The v3 band with shift_m reduced by `offset` (normals + offset)."""
    import winter_p2_band as W2
    wd = tempfile.mkdtemp(prefix="m736_band_")
    r0 = W2._run(np.zeros((1, 12)), None, 2, "probe", wd)
    return W2.realised_band(frame, bias=r0["bias"], normals=[n + offset for n in r0["normals"]], nb=nb, workdir=wd)
