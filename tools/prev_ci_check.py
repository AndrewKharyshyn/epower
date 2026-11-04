#!/usr/bin/env python3
"""M575 (Director pre-merge condition): for the cell-spread blocks, check that every estimate lies inside the CI the same estimate had in the committed (HEAD) payload.
Walks the named blocks of HEAD:summary_arrays.json for dicts that carry a 95% interval (ci95 / ci95T / ci95T_Gminus1 / ci95PercentileT, two numbers) and a point value (est / slope / estimate / lateEffect_mv / olsSlopeMvPerMo / huberSlopeMvPerMo / value),
compares the working-tree payload at the same path and writes analyses/<out>. Exit 1 if any estimate is outside its previous CI. Read-only on the payload.
Usage: python tools/prev_ci_check.py [--out analyses/M575_cellspread_prev_ci_check.json] [--blocks cellSpreadStep cellHealthTrend ...]"""
import argparse, hashlib, json, os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
ap = argparse.ArgumentParser(); ap.add_argument("--out", default="analyses/M575_cellspread_prev_ci_check.json"); ap.add_argument("--blocks", nargs="*", default=["cellSpreadStep", "cellHealthTrend", "cellSpreadRelaxation", "cellSpreadRelaxationSensitivity", "thermalStepResponse"])
ap.add_argument("--also", nargs="*", default=["dependenceSensitivity.trendSlopes.cellSpread", "degradationTrends.cellSpread"])
a = ap.parse_args()
H = json.loads(subprocess.run(["git", "show", "HEAD:summary_arrays.json"], capture_output=True, check=True).stdout.decode("utf-8"))
A = json.load(open("summary_arrays.json", encoding="utf-8"))
CI = ("ci95", "ci95T", "ci95T_Gminus1", "ci95PercentileT", "huberSlopeCi95")
PT = ("est", "slope", "estimate", "lateEffect_mv", "olsSlopeMvPerMo", "huberSlopeMvPerMo", "value")
num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
def get(o, p):
    for k in p:
        if isinstance(o, dict) and k in o: o = o[k]
        else: return None
    return o
rows = []
def walk(h, c, p):
    if not isinstance(h, dict): return
    for ck in CI:
        ci = h.get(ck)
        if isinstance(ci, list) and len(ci) == 2 and all(num(x) for x in ci):
            for pk in PT:
                if num(h.get(pk)) and isinstance(c, dict) and num(c.get(pk)):
                    rows.append({"path": "/".join(p) + "/" + pk, "ci": ck, "previousCi": ci, "previous": h[pk], "current": c[pk], "inside": bool(ci[0] <= c[pk] <= ci[1])})
    for k, v in h.items():
        if isinstance(v, dict): walk(v, c.get(k) if isinstance(c, dict) else None, p + (k,))
for b in a.blocks:
    if b in H: walk(H[b], A.get(b), (b,))
for dotted in a.also:
    p = tuple(dotted.split(".")); h = get(H, p)
    if isinstance(h, dict): walk(h, get(A, p), p)
out = {"spec": "Director pre-merge condition, M575", "master": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "nChecked": len(rows), "nOutside": sum(not r["inside"] for r in rows), "rows": rows}
json.dump(out, open(a.out, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
print(json.dumps({"nChecked": out["nChecked"], "nOutside": out["nOutside"], "outside": [r for r in rows if not r["inside"]]}, ensure_ascii=False)[:1500])
sys.exit(1 if out["nOutside"] else 0)
