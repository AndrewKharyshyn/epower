"""M362 known-answer test of tools/m362_splice.summarise (numpy linear quantiles, short-drive count, maximum drive) on a scripted per-drive table."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools")); os.chdir(ROOT)
import numpy as np, pandas as pd
import m362_splice as M
fails = 0
def ok(l, c, e=""):
    global fails
    print(("PASS " if c else "FAIL ") + l + ((" - " + str(e)) if (not c and e) else "")); fails += 0 if c else 1
km = [1.0, 1.0, 4.0, 5.0, 10.0, 20.0]; n = [5, 1, 4, 5, 10, 10]
g = pd.DataFrame({"file": list("abcdef"), "date": ["d1", "d1", "d2", "d3", "d3", "d4"], "km": km, "n": n})
g["rate"] = g["n"] / g["km"] * 100.0            # 500, 100, 100, 100, 100, 50
S = M.summarise(g)
ok("n and days", S["n"] == 6 and S["nDays"] == 4)
ok("median (numpy linear) of 50,100,100,100,100,500", S["median"] == 100.0, S["median"])
ok("p25 / p75 are numpy linear (type 7)", S["p25"] == round(float(np.percentile(g.rate, 25)), 1) == 100.0 and S["p75"] == 100.0, (S["p25"], S["p75"]))
ok("p10 / p90 interpolate towards the extremes", S["p10"] == round(float(np.percentile(g.rate, 10)), 1) and S["p90"] == round(float(np.percentile(g.rate, 90)), 1) == 300.0, (S["p10"], S["p90"]))
ok("short drives counted at the 2 km display threshold (two drives of 1 km)", S["nShort"] == 2 and S["shortKm"] == 2.0)
ok("maximum drive and its distance", S["maxDrive"] == "a" and S["maxKm"] == 1.0)
ok("no pooled field is written (the chart binds to M343)", "pooled" not in S)
print("FAILS:", fails); sys.exit(1 if fails else 0)
