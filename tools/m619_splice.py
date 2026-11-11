#!/usr/bin/env python3
"""M619 (spec analyses/M618_spec.md Rev 1, Director review R1-R11) additive leaf-level splice of the multi-solver mixed-effects SENSITIVITY fit. It recomputes degradationTrends from drive_master.csv with the
M619 builder (degradation_trends.build) and writes ONLY
  degradationTrends.<metric>.mixedEffects.*        (the sensitivity block: reported solver values, validity components, solver, solversTried, solverAgreement, versions)
  degradationTrends.<metric>.headlineVsMixed       (the signed difference in OLS standard errors; filled where the mixed fit was missing)
and refuses (exit 3, nothing written) unless: the replay analyses/M619_replay.json exists for THIS master MD5 and the installed statsmodels / scipy versions with veto false and the R9 sign-off
condition met (both metrics: the mixed and OLS intervals agree on excluding zero); every other leaf is identical (headline, OLS block, TOST, equivalence); where the old mixed fit existed, its slope, SE,
interval and day variance are reproduced by the new reported fit; and the evidence ledger derived from the new block equals the one derived from the old block.
Usage: python tools/m619_splice.py [--dry-run] [--json PATH]"""
import copy, hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

FROZEN = ("clusterRobustOLS", "tostEstimatorBasis", "tostSlopeUsed", "tostSeUsed", "tostCandidates", "releasedBoundLabel", "releasedEquivalence", "equivalenceBoundStatus", "nObs", "nDays",
          "windowMonths", "proxyMedianMohm", "role", "cadenceControlled", "primaryEstimandRef", "ycol", "unit", "primaryEstimator", "headlineEstimatorRule", "restingSpreadMedianMv")
REPRODUCED = ("slope", "se", "ci95", "groupVar")


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
    base = parts[2].split("[")[0]
    return base in ("mixedEffects", "headlineVsMixed")


def check_replay(path="analyses/M619_replay.json"):
    """Returns the replay record or stops: present, for this master and these library versions, no veto, the R9 sign-off condition met."""
    import scipy, statsmodels
    if not os.path.isfile(path):
        stop("no replay %s (run python analyses/M619_replay.py first)" % path)
    r = json.load(open(path, encoding="utf-8"))
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    if r.get("masterMd5") != md5:
        stop("the replay was made on another master (%s) than the current one (%s): re-run it" % (r.get("masterMd5"), md5))
    if r["versions"]["statsmodels"] != statsmodels.__version__ or r["versions"]["scipy"] != scipy.__version__:
        stop("the replay was made with statsmodels %s / scipy %s, installed %s / %s: re-run it before any splice (R10)" % (r["versions"]["statsmodels"], r["versions"]["scipy"], statsmodels.__version__, scipy.__version__))
    if r["veto"]["veto"]:
        stop("the replay VETOES the procedure: %s" % "; ".join(r["veto"]["reasons"]))
    if not r["r9"]["intervalsAgreeOnExcludingZeroBothMetrics"]:
        stop("R9: the mixed and OLS intervals disagree on excluding zero at the current corpus: the Director rules before any splice")
    return r


def main(argv):
    import degradation_trends as DT
    import compute_summary_arrays as C
    replay = check_replay()
    p = "summary_arrays.json"
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    B = copy.deepcopy(A)
    B["degradationTrends"] = json.loads(json.dumps(DT.build("drive_master.csv")))
    for m in ("cellSpread", "resistanceVreg"):
        o, n = A["degradationTrends"][m], B["degradationTrends"][m]
        for k in FROZEN:
            if o.get(k) != n.get(k):
                stop(f"{m}.{k} changed (headline, OLS block, equivalence test and n must not move)")
        om, nm = o.get("mixedEffects") or {}, n.get("mixedEffects") or {}
        if "slope" in om:
            for k in REPRODUCED:
                if om.get(k) != nm.get(k):
                    stop(f"{m}.mixedEffects.{k}: the shipped fit {om.get(k)} is not reproduced by the new reported fit {nm.get(k)} (solver {nm.get('solver')})")
        if "slope" in nm and nm.get("valid") is not True:
            stop(f"{m}: the reported mixed-effects fit is not valid (agreement {nm.get('solverAgreement')}); it would still be shown, but the replay assumed agreement at the current corpus")
    led_new = json.loads(json.dumps(C._evidence_ledger(B)))
    led_old = json.loads(json.dumps(C._evidence_ledger(A)))
    if led_new != led_old:
        stop("the evidence ledger derived from the new degradationTrends differs from the one derived from the old block: " + str(list(walk(led_old, led_new))[:5]))
    changed = list(walk(A, B))
    bad = [d for d in changed if not allowed(d)]
    if bad:
        stop(f"deep-diff outside the allow-list: {bad[:6]}")
    res = {"changedLeaves": len(changed), "paths": changed, "replay": {"veto": replay["veto"]["veto"], "r9": replay["r9"], "versions": replay["versions"]},
           "solver": {m: [B["degradationTrends"][m]["mixedEffects"].get("solver"), B["degradationTrends"][m]["mixedEffects"].get("solverAgreement")] for m in ("cellSpread", "resistanceVreg")}, "evidenceLedgerUnchanged": True}
    print(json.dumps(res, indent=1)[:3500])
    if "--json" in argv:
        json.dump(res, open(argv[argv.index("--json") + 1], "w", encoding="utf-8", newline="\n"), indent=1)
    if "--dry-run" not in argv and changed:
        open(p, "w", encoding="utf-8", newline="").write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
