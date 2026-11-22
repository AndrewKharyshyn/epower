#!/usr/bin/env python3
"""M736 (analyses/M736_spec.md Rev 1, K3 input): runs the v4 P2 handling with the VENDORED engine on a planted frozen-basis window frame (no winter observation): January, 8 days, driver-read ambient = normal + BIAS + planted shift (+2.0 C).
Reports the three offset bands (window-matched) and the three carry bands for a planted observed interval, and checks that the offset bands move monotonically (a larger offset lowers the shift, a colder scenario, so both band edges RISE; direction fixed after a first run expected the opposite, a check-criterion error, no winter data involved). Writes analyses/M736_engine_check.json. Usage: python tools/winter_p2_v4_check.py"""
import json, os, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_p2_v4 as W4
import winter_p2_band as W2

OUT = os.path.join(ROOT, "analyses", "M736_engine_check.json")


def main(argv=None):
    t0 = time.time()
    wd = __import__("tempfile").mkdtemp(prefix="m736_probe_")
    r0 = W2._run(np.zeros((1, 12)), None, 2, "probe", wd)
    bias, normals = r0["bias"], r0["normals"]
    a = normals[0] + bias + 2.0
    rows = [{"day": "2027-01-%02d" % d, "start": pd.Timestamp("2027-01-%02d 09:00" % d), "ambient_start_c": a - 0.5, "ambient_end_c": a + 0.5} for d in range(2, 10)]
    fr = pd.DataFrame(rows)
    obs = [0.30, 0.36]

    def ev(b):
        lo, hi = b
        return "within the band" if (obs[0] >= lo and obs[1] <= hi) else ("outside the band" if (obs[1] < lo or obs[0] > hi) else "inconclusive")
    v = W4.p2_v4(fr, W4.band_fn_engine, ev)
    his = [v["offsetBands"][k] for k in ("0.00", "1.37", "3.98")]
    rec = {"milestone": "M736", "plantedShiftC": 2.0, "plantedDays": 8, "bias": bias, "provenance": W4.provenance(), "result": {k: v[k] for k in ("status", "offsetBands", "offsetCalls", "carryBands", "carryCalls", "pathCarryBound")},
           "monotone": bool(his[0][0] <= his[1][0] <= his[2][0] and his[0][1] <= his[1][1] <= his[2][1]), "seconds": round(time.time() - t0, 1)}
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False, indent=1, default=float) + "\n")
    print(json.dumps(rec, indent=1, default=float)[:2000])
    return 0 if rec["monotone"] else 1


if __name__ == "__main__":
    sys.exit(main())
