"""M356 known-answer test of the stop-go window energies (compute_summary_arrays._csg_events cycle key `ph`, spec analyses/M356_spec.md Rev 2) on a scripted 1 Hz grid.
Cycle 1 (stop idx 0-4 -> stop idx 20-24, peak 20 km/h): disjoint windows, hand-computed; cycle 2 (idx 24 -> 29, peak 10 km/h < 15): launch end == approach start (one shared
sample), empty creep, not additive. Power p = (-I)*V/1000 kW, energy = sum(p)/3.6 Wh."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np, pandas as pd
import compute_summary_arrays as C
fails = 0
def ok(l, c, e=""):
    global fails
    print(("PASS " if c else "FAIL ") + l + ((" - " + str(e)) if (not c and e) else "")); fails += 0 if c else 1
close = lambda a, b: a is not None and abs(a - b) < 1e-9
n = 34 + 130
speed = np.full(n, 50.0); I = np.zeros(n); V = np.full(n, 350.0)
speed[0:5] = 0; speed[5:10] = [5, 10, 15, 18, 20]; speed[10:15] = 20; speed[15:20] = [15, 10, 8, 4, 2]; speed[20:25] = 0
speed[25:29] = [3, 10, 5, 2]; speed[29:34] = 0
I[5:8] = -10.0; I[12] = -2.0; I[17:20] = 4.0          # cycle 1: launch p=3.5 kW x3; creep p=0.7 kW x1; approach p=-1.4 kW x3
I[26] = -10.0; I[27:29] = 4.0                          # cycle 2: p=3.5 at 26 (shared sample), -1.4 at 27, 28
g = pd.DataFrame({"speed": speed, "I": I, "V": V, "rpm": np.zeros(n)})
r = C._csg_events(g)
ok("two cycles found", r is not None and len(r["cycles"]) == 2, None if r is None else len(r["cycles"]))
c1, c2 = r["cycles"][0]["ph"], r["cycles"][1]["ph"]
ok("c1 disjoint windows", c1["disjoint"] is True)
ok("c1 launch net = discharge = 10.5/3.6, regen 0", close(c1["launch"][0], 10.5 / 3.6) and close(c1["launch"][1], 10.5 / 3.6) and close(c1["launch"][2], 0.0))
ok("c1 creep net = discharge = 0.7/3.6, regen 0", close(c1["creep"][0], 0.7 / 3.6) and close(c1["creep"][1], 0.7 / 3.6) and close(c1["creep"][2], 0.0))
ok("c1 approach net = -4.2/3.6, discharge 0, regen 4.2/3.6", close(c1["approach"][0], -4.2 / 3.6) and close(c1["approach"][1], 0.0) and close(c1["approach"][2], 4.2 / 3.6))
ok("c1 cycle net 7.0/3.6, discharge 11.2/3.6, regen 4.2/3.6", close(c1["cycle"][0], 7.0 / 3.6) and close(c1["cycle"][1], 11.2 / 3.6) and close(c1["cycle"][2], 4.2 / 3.6))
ok("c1 additive: launch + creep + approach nets = cycle net", close(c1["launch"][0] + c1["creep"][0] + c1["approach"][0], c1["cycle"][0]))
ok("net = discharge - regen in every c1 window", all(close(c1[w][0], c1[w][1] - c1[w][2]) for w in ("launch", "creep", "approach", "cycle")))
ok("c1 coverage 1.0", all(c1[w][3] == 1.0 for w in ("launch", "creep", "approach", "cycle")))
ok("c2 NOT disjoint (launch end == approach start), creep empty", c2["disjoint"] is False and c2["creep"] == "empty")
ok("c2 launch net = 3.5/3.6", close(c2["launch"][0], 3.5 / 3.6))
ok("c2 approach net = 0.7/3.6, discharge 3.5/3.6, regen 2.8/3.6", close(c2["approach"][0], 0.7 / 3.6) and close(c2["approach"][1], 3.5 / 3.6) and close(c2["approach"][2], 2.8 / 3.6))
ok("c2 cycle net = 0.7/3.6; launch + approach nets are NOT the cycle net (shared sample)", close(c2["cycle"][0], 0.7 / 3.6) and not close(c2["launch"][0] + c2["approach"][0], c2["cycle"][0]))
cy = r["cycles"]
ok("existing fields unchanged: whLaunchOut / whApproachIn / whCycleNet equal the window values", all(close(cy[i]["whLaunchOut"], cy[i]["ph"]["launch"][1]) and close(cy[i]["whApproachIn"], cy[i]["ph"]["approach"][2]) and close(cy[i]["whCycleNet"], cy[i]["ph"]["cycle"][0]) for i in (0, 1)))
# NaN gap: all-NaN window is None-coded, partial coverage reported
g2 = g.copy(); g2.loc[4:7, "I"] = np.nan
c1b = C._csg_events(g2)["cycles"][0]["ph"]
ok("all-NaN launch window -> (None, None, None, 0.0)", c1b["launch"] == (None, None, None, 0.0), c1b["launch"])
g3 = g.copy(); g3.loc[6, "I"] = np.nan
c1c = C._csg_events(g3)["cycles"][0]["ph"]
ok("one NaN sample in the launch window -> coverage 0.75, net 7.0/3.6", c1c["launch"][3] == 0.75 and close(c1c["launch"][0], 7.0 / 3.6), c1c["launch"])
print("CSG_PHASES FAILS =", fails); sys.exit(1 if fails else 0)
