#!/usr/bin/env python3
"""M473 (audit 2026-10-21, trend-table convention) additive leaf-level splice. The released cluster-robust OLS interval of degradationTrends.{cellSpread,resistanceVreg} uses the cluster-t reference t(G-1) (the
reference the equivalence test has used since M158); slope, cluster SE, equivalence decisions and every other leaf are unchanged. This tool recomputes degradationTrends from drive_master.csv with the producer and writes ONLY:
  degradationTrends.*.clusterRobustOLS.{ci95, ciReference}
  evidenceLedger.rows[*].checks[*].ci95            (re-derived by compute_summary_arrays._evidence_ledger from the new degradationTrends; the artifactIdentity back-fill is NOT touched)
  dependenceSensitivity ... cr1.referenceNote      (documents that ci95NormalAsReleased is the convention before M473; the released interval is ci95T_Gminus1)
and refuses (exit 3, nothing written) on any other difference, on a changed slope / SE / equivalence leaf, or if the new interval is not slope +/- t(G-1) x SE. Usage: python tools/m473_splice.py [--dry-run]"""
import copy, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import dependence_sensitivity as _DS
NOTE = _DS.CR1_REFERENCE_NOTE


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from walk(a.get(k), b.get(k), f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from walk(x, y, f"{path}[{i}]")
    elif a != b:
        yield path


def stop(msg):
    print("STOP:", msg)
    sys.exit(3)


def add_notes(o, path=""):
    """Put NOTE next to every cr1 dict that carries ci95NormalAsReleased (also under byLoggingRegime etc.)."""
    if isinstance(o, dict):
        if "ci95NormalAsReleased" in o and "ci95T_Gminus1" in o:
            o["referenceNote"] = NOTE
        for k, v in o.items():
            add_notes(v, path + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            add_notes(v, f"{path}[{i}]")


def main(argv):
    import degradation_trends as DT
    import compute_summary_arrays as C
    from scipy import stats
    p = "summary_arrays.json"
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    B = copy.deepcopy(A)
    B["degradationTrends"] = json.loads(json.dumps(DT.build("drive_master.csv")))
    for k in ("cellSpread", "resistanceVreg"):
        o, n = A["degradationTrends"][k]["clusterRobustOLS"], B["degradationTrends"][k]["clusterRobustOLS"]
        if (o["slope"], o["se"], o["nObs"], o["nDays"]) != (n["slope"], n["se"], n["nObs"], n["nDays"]):
            stop(f"{k}: slope / SE / n changed")
        t = stats.t.ppf(0.975, n["nDays"] - 1)
        if abs(n["ci95"][0] - (n["slope"] - t * n["se"])) > 6e-4 or abs(n["ci95"][1] - (n["slope"] + t * n["se"])) > 6e-4:
            stop(f"{k}: the interval is not slope +/- t(G-1) x SE (rounded SE): {n['ci95']}")
    led = C._evidence_ledger(B)
    led = json.loads(json.dumps(led))
    for i, row in enumerate(B["evidenceLedger"]["rows"]):
        for j, ch in enumerate(row.get("checks") or []):
            ch2 = led["rows"][i]["checks"][j]
            if "ci95" in ch and ch2.get("ci95") != ch["ci95"]:
                ch["ci95"] = ch2["ci95"]
    add_notes(B["dependenceSensitivity"], "/dependenceSensitivity")
    changed = list(walk(A, B))

    def ok(d):
        return (d.startswith("/degradationTrends/") and "/clusterRobustOLS/" in d and (d.endswith("/ci95[0]") or d.endswith("/ci95[1]") or d.endswith("/ciReference"))) or \
               (d.startswith("/evidenceLedger/rows[") and "/checks[" in d and "/ci95[" in d) or (d.startswith("/dependenceSensitivity/") and d.endswith("/cr1/referenceNote"))
    bad = [d for d in changed if not ok(d)]
    if bad:
        stop(f"deep-diff outside the allow-list: {bad[:6]}")
    print(json.dumps({"changedLeaves": len(changed), "paths": changed[:40]}, indent=1))
    if "--dry-run" not in argv and changed:
        open(p, "w", encoding="utf-8", newline="").write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
