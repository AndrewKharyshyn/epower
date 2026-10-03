"""M351 (p22.12): the published cell-spread clusterRobustOLS interval is a cluster-robust NORMAL (z) interval, so the label 'cluster-robust normal (z)'
is true: (hi - lo) / (2 * se) = 1.96 within rounding of the 4-dp payload values. If the estimator ever switches to t(G-1) this fails and the label must change."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
a = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
fails = 0
def ok(l, c, e=""):
    global fails
    print(("PASS " if c else "FAIL ") + l + ((" - " + str(e)) if (not c and e) else "")); fails += 0 if c else 1
for key in ("cellSpread", "resistanceVreg"):
    d = (a["degradationTrends"].get(key) or {}).get("clusterRobustOLS") or {}
    if not d.get("ci95") or not d.get("se"):
        ok(f"{key}: clusterRobustOLS present", False); continue
    r = (d["ci95"][1] - d["ci95"][0]) / (2 * d["se"])
    ok(f"{key}: half-width / se = {r:.3f} (z = 1.960; t(G-1) with {d['nDays']} days would be larger)", abs(r - 1.96) < 0.01, r)
print("CI_BASIS FAILS =", fails); sys.exit(1 if fails else 0)
