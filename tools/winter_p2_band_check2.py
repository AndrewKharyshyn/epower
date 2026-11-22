#!/usr/bin/env python3
"""M735 (Director freeze review of M731, conditions 1 and 2; no winter observation is read): two checks of the vendored engine and the M731 band runner on the FROZEN inputs.
C-P2e (window additivity, blind-style known answer for a PARTIAL window): in a fresh interpreter that imports only the vendored engine, the same S3b draws are simulated (a) over all months, (b) with the window months {12, 1, 2} kept and every other synthetic day pointed at a day without drives,
(c) with the complement kept. Per draw the Ah throughput and the Ah below 10 C of (b) + (c) must equal (a) to 1e-9 relative, and the window share must equal ah_lt10(b) / ah(b). This re-implements the null-day idea in its own code (not tools/winter_p2_band_run.py).
C-P2f (ambient scale): on the frozen basis, per calendar month, the day-mean offset between the driver-read ambient (mean of drive A0 and A1) and the engine's reconstructed drive ambient (mean of Abar_s and Abar_e); the shift is reported with and without that offset as a sensitivity, never as the primary.
Writes analyses/M735_p2_window_check.json. Usage: python tools/winter_p2_band_check2.py"""
import json, os, subprocess, sys, tempfile
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
VROOT = os.path.join(ROOT, "analyses", "M731_frozen_engine", "root")
OUT = os.path.join(ROOT, "analyses", "M735_p2_window_check.json")

CHILD = r'''
import json, os, sys
import numpy as np
VROOT = sys.argv[1]
sys.path.insert(0, os.path.join(VROOT, "tools"))
import scenario_engine as SE
M = SE.load_model(os.path.join(VROOT, "analyses", "M713"))
sc = SE.scenarios(M.ODO_KM)["S3b_cold_winter"]
Bn = 4000
rng = np.random.default_rng(SE.SEED)
par = dict(M.params); par.update(sc.get("par", {}))
w_sum = sc.get("w_sum", SE.W_SUM_BAL)
tilt = SE.solve_tilt(M, sc["km"], w_sum, par["f_s"], par["f_a"]) if "km" in sc else 0.0
src, iss = SE.draw_days(M, Bn, w_sum, rng, tilt=tilt, pools=sc.get("pools", ("summer", "autumn")))
shift = np.repeat(np.array([[-6, -6, -3, 0, 0, 0, 0, 0, 0, 0, -3, -6]], float), Bn, axis=0)
tgt = np.repeat(shift, SE.DIM, axis=1)
mo = SE.month_of_doy() + 1
null = np.flatnonzero(M.P["valid"].sum(axis=1) == 0)[0]
def run(keep):
    s = src.copy()
    if keep is not None:
        s[:, ~np.isin(mo, keep)] = null
    o = SE.summarise(SE.simulate(M, s, tgt, par, iss))
    return o["ah_throughput"], o["ahShare_T_lt10"] * o["ah_throughput"]
win = [12, 1, 2]
a_ah, a_c = run(None)
w_ah, w_c = run(win)
c_ah, c_c = run([m for m in range(1, 13) if m not in win])
res = {"drawsChecked": Bn, "maxRelDiffAh": float(np.max(np.abs(w_ah + c_ah - a_ah) / a_ah)), "maxRelDiffAhLt10": float(np.max(np.abs(w_c + c_c - a_c) / np.maximum(a_c, 1e-12))),
       "windowShareRange": [float(np.nanmin(w_c / w_ah)), float(np.nanmax(w_c / w_ah))], "annualShareRange": [float(np.nanmin(a_c / a_ah)), float(np.nanmax(a_c / a_ah))], "windowAhShareOfAnnual": float(np.mean(w_ah / a_ah))}
D = M.D
off = {}
for m in range(1, 13):
    d = D[D["day"].str[5:7].astype(int) == m]
    drv = (d["A0"] + d["A1"]) / 2.0
    eng = (d["Abar_s"] + d["Abar_e"]) / 2.0
    ok = np.isfinite(drv) & np.isfinite(eng)
    if ok.sum():
        dd = d[ok].assign(_o=(drv - eng)[ok]).groupby("day")["_o"].mean()
        off[str(m)] = {"days": int(len(dd)), "meanOffsetC": float(dd.mean())}
res["ambientOffsetByMonth"] = off
res["bias"] = float(M.BIAS)
print("RESULT " + json.dumps(res))
'''


def main(argv=None):
    cp = os.path.join(tempfile.mkdtemp(prefix="m735_"), "child.py")
    with open(cp, "w", encoding="utf-8") as f:
        f.write(CHILD)
    r = subprocess.run([sys.executable, "-I", cp, VROOT], capture_output=True, text=True, cwd=VROOT)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT ")]
    if r.returncode != 0 or not line:
        print(r.stderr[-800:])
        return 1
    res = json.loads(line[0][7:])
    res["C-P2e"] = {"pass": bool(res["maxRelDiffAh"] < 1e-9 and res["maxRelDiffAhLt10"] < 1e-9), "criterion": "per-draw window + complement equals annual to 1e-9 relative (Ah and Ah below 10 C)"}
    rec = {"milestone": "M735", "spec": "Director freeze review of M731 (analyses/M735_director_review_M731.json)", "result": res}
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(rec, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
