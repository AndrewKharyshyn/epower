#!/usr/bin/env python3
"""M614 (spec analyses/M614_spec.md Rev 1, Director review R1-R12) additive leaf-level splice. The headline estimator of every degradation trend is the day-clustered cluster-robust OLS and the
mixed model is a sensitivity with separate validity components. This tool recomputes degradationTrends from drive_master.csv with the M614 builder (degradation_trends.build) and writes ONLY:
  degradationTrends.<metric>.{primaryEstimator, headlineEstimatorRule, headlineVsMixed}
  degradationTrends.<metric>.mixedEffects.{valid, validity, reCovarianceSingular, seRatioToOLS, varianceRatio, residVar, degenerateNote}
and refuses (exit 3, nothing written) on any other difference, on a changed OLS block (slope, SE, interval, n), on a changed equivalence (TOST) leaf, on a changed mixed slope / SE / interval,
or when the evidence ledger derived from the new block differs from the one derived from the old block. Usage: python tools/m614_splice.py [--dry-run] [--json PATH]"""
import copy, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

ALLOWED_TOP = ("primaryEstimator", "headlineEstimatorRule", "headlineVsMixed")
ALLOWED_ME = ("valid", "validity", "reCovarianceSingular", "seRatioToOLS", "varianceRatio", "residVar", "degenerateNote")
FROZEN = ("clusterRobustOLS", "tostEstimatorBasis", "tostSlopeUsed", "tostSeUsed", "tostCandidates", "releasedBoundLabel", "releasedEquivalence", "equivalenceBoundStatus", "nObs", "nDays",
          "windowMonths", "proxyMedianMohm", "role", "cadenceControlled", "primaryEstimandRef", "ycol", "unit")
ME_FROZEN = ("slope", "se", "ci95", "nObs", "nDays", "groupVar", "converged", "formula", "error")


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


def allowed(path):
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "degradationTrends" or parts[1] not in ("cellSpread", "resistanceVreg"):
        return False
    rest = parts[2:]
    base = lambda x: x.split("[")[0]
    if base(rest[0]) in ALLOWED_TOP and len(rest) == 1:
        return True
    return base(rest[0]) == "mixedEffects" and len(rest) >= 2 and base(rest[1]) in ALLOWED_ME


def main(argv):
    import degradation_trends as DT
    import compute_summary_arrays as C
    p = "summary_arrays.json"
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    B = copy.deepcopy(A)
    B["degradationTrends"] = json.loads(json.dumps(DT.build("drive_master.csv")))
    for m in ("cellSpread", "resistanceVreg"):
        o, n = A["degradationTrends"][m], B["degradationTrends"][m]
        for k in FROZEN:
            if o.get(k) != n.get(k):
                stop(f"{m}.{k} changed (OLS block, equivalence test and n must not move)")
        for k in ME_FROZEN:
            if (o.get("mixedEffects") or {}).get(k) != (n.get("mixedEffects") or {}).get(k):
                stop(f"{m}.mixedEffects.{k} changed (the sensitivity fit itself must not move)")
        if n["primaryEstimator"] != "clusterRobustOLS" or n["headlineEstimatorRule"] != DT.HEADLINE_RULE:
            stop(f"{m}: the new headline is not the fixed cluster-robust OLS")
    led_new = json.loads(json.dumps(C._evidence_ledger(B)))
    led_old = json.loads(json.dumps(C._evidence_ledger(A)))        # derived from the OLD block: the stored ledger also carries identity back-fills that are not this tool's business
    if led_new != led_old:
        stop("the evidence ledger derived from the new degradationTrends differs from the one derived from the old block: " + str(list(walk(led_old, led_new))[:5]))
    changed = list(walk(A, B))
    bad = [d for d in changed if not allowed(d)]
    if bad:
        stop(f"deep-diff outside the allow-list: {bad[:6]}")
    res = {"changedLeaves": len(changed), "paths": changed, "primary": {m: [A["degradationTrends"][m]["primaryEstimator"], B["degradationTrends"][m]["primaryEstimator"]] for m in ("cellSpread", "resistanceVreg")},
           "evidenceLedgerUnchanged": True}
    print(json.dumps(res, indent=1)[:3000])
    if "--json" in argv:
        json.dump(res, open(argv[argv.index("--json") + 1], "w", encoding="utf-8", newline="\n"), indent=1)
    if "--dry-run" not in argv and changed:
        open(p, "w", encoding="utf-8", newline="").write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
