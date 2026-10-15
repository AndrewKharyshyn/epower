"""EXPLORATORY (M442, development days = odd day-of-month only; does not count toward any gate): compare candidate reductions for cadence invariance with the H1 machinery of tools/m442_gate.py.
designs: last3 (spec Rev 1: latest native sample in each 3 s cell), interp3 (linear interpolation of speed/I/V onto the 3 s grid, latest sample for state channels), box3 (3 s boxcar of the power on native samples)."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import numpy as np
import m442_gate as MG
import regen_v2_agg as G

PH = [0, 1, 2, 3]
DESIGNS = {
    "last3": (["h3p%d" % k for k in PH], {f: ["d%dp%dh3p%d" % (f, q, k) for q in range(f) for k in PH] for f in (2, 3)}),
    "interp3": (["l3p%d" % k for k in PH], {f: ["d%dp%dl3p%d" % (f, q, k) for q in range(f) for k in PH] for f in (2, 3)}),
    "box3": (["box3"], {f: ["d%dp%dbox3" % (f, q) for q in range(f)] for f in (2, 3)}),
}
if __name__ == "__main__":
    dm, reg = G.load_master()
    files = list(dm["file"])
    fast = (dm["ev_rpm_dt_med_s"] < 1.0).values
    day_all = dm["date"].astype(str).str[:10].values
    pdays = sorted(d for d in set(day_all[fast]) if int(d[8:10]) % 2 == 1)
    out = {}
    for name in (sys.argv[1:] or list(DESIGNS)):
        nat, dec = DESIGNS[name]
        Tn = MG.tables(files, nat, 5)
        res = {}
        for f in (2, 3):
            Td = MG.tables(files, dec[f], 5)
            g = MG.gate(dm, files, fast, pdays, Tn, Td, "%s factor %d (odd days, exploratory)" % (name, f))
            res[str(f)] = {"failing": g["failing"], "indeterminate": g["indeterminate"], "total": {k: g["total"].get(k) for k in ("eff", "diffPp", "ci95", "judgement")},
                           "cells": {k: {l: (x["diffPp"], x["judgement"]) for l, x in c.items() if x["status"] == "supported"} for k, c in g["cells"].items() if k.startswith(("temperature", "speed"))}}
        out[name] = res
        print(name, json.dumps({f: {"failing": v["failing"], "indet": v["indeterminate"], "total": v["total"]} for f, v in res.items()}), flush=True)
    json.dump(out, open("analyses/M442_explore/designs_dev.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
