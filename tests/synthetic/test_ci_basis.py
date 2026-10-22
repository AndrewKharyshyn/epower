"""M351 (p22.12), updated at M473: the published clusterRobustOLS interval of the degradation trends uses the cluster-t reference t(G-1), G = day clusters (it was a normal interval before M473): (hi - lo) / (2 * se)
equals t_{0.975, G-1} within the 4-dp rounding of the payload values, and the leaf ciReference says so. The dashboard label is bound to ciReference, never typed."""
import json, os, sys
from scipy import stats
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
    tcr = stats.t.ppf(0.975, d["nDays"] - 1)
    ok(f"{key}: half-width / se = {r:.3f} (t(G-1) with {d['nDays']} days = {tcr:.3f}; the normal reference would be 1.960)", abs(r - tcr) < 0.01 and r > 1.96, r)
    ok(f"{key}: ciReference states the reference", d.get("ciReference") == f"t(df={d['nDays'] - 1})", d.get("ciReference"))
print("CI_BASIS FAILS =", fails); sys.exit(1 if fails else 0)
