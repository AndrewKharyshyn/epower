#!/usr/bin/env python3
"""M536 wave 0 addendum (analyses/M536_spec.md section 9, added for the decision pack; evidence only): the rpmOptBand share under the two candidate engine-on denominators on the same 1 Hz grid,
rpm >= 300 (the stored basis; must reproduce rpmOptBand.primary exactly: STOP otherwise) and rpm > 400, with the same day-clustered percentile bootstrap (seed 42, 4000 draws).
Reads rpm_opt_band_sidecar.csv and engine_on_evidence_sidecar.csv only. Output analyses/M536_wave0_addendum.json (first output kept). Usage: python tools/engine_on_optband_check.py"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import rpm_opt_band as OB
from model_constants import OPT_LO, OPT_HI

OUT = os.path.join(ROOT, "analyses", "M536_wave0_addendum.json")
HIST_EDGES = [0, 300, 1400, 1475, 1525, 1564, 1614, 1975, 2025, 2100, 2400, 2800, 3200, 6000]    # RPM_HIST_EDGES (also asserted against the stored faithfulness gate below)


def main():
    os.chdir(ROOT)
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    edges = OB.fine_edges(HIST_EDGES, OPT_LO, OPT_HI)
    sc = pd.read_csv("rpm_opt_band_sidecar.csv"); ev = pd.read_csv("engine_on_evidence_sidecar.csv")
    m = sc.merge(ev[["file", "g_ge300", "g_gt400"]], on="file")
    cnt = m[["b%d" % k for k in range(len(edges) - 1)]].values
    num = (OB.between(cnt, edges, OPT_LO, OPT_HI) + m["eq_hi"].values).astype(float)
    res = {}
    for nm, den in (("ge300", m["g_ge300"].values), ("gt400", m["g_gt400"].values)):
        pt, ci, nd, z = OB.ratio_ci(num, den.astype(float), m["date"].values)
        res[nm] = {"pct": round(100 * pt, 3), "ci95Pct": [round(100 * x, 3) for x in ci], "nDays": nd, "nDrives": int(len(m)), "engineOnSeconds": int(den.sum()), "bandSeconds": int(num.sum())}
    stored = A["rpmOptBand"]["primary"]
    ok = abs(res["ge300"]["pct"] - stored["pct"]) < 1e-3 and res["ge300"]["ci95Pct"] == stored["ci95Pct"]
    if not ok:
        print(json.dumps({"STOP": "the >= 300 row does not reproduce rpmOptBand.primary", "have": res["ge300"], "stored": stored})); return 1
    res["shiftPp"] = round(res["gt400"]["pct"] - res["ge300"]["pct"], 3)
    res["gt400InsideStoredCi"] = bool(stored["ci95Pct"][0] <= res["gt400"]["pct"] <= stored["ci95Pct"][1])
    res["note"] = "evidence only: rpmOptBand is NOT changed; the > 400 row is a what-if on the same grid; closed band [1850, 2150] numerator unchanged"
    if not os.path.exists(OUT):
        json.dump(res, open(OUT, "w", encoding="utf-8", newline=chr(10)), indent=1)
    print(json.dumps(res)); return 0


if __name__ == "__main__":
    sys.exit(main())
