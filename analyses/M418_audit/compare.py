"""M418 blind-audit comparison: pipeline-written thermalSupportLedger vs analyses/M418_audit/result.json (definitions + raw path only; the auditor did not read the pipeline code or the payload)."""
import json, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
b = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["thermalSupportLedger"]["estimators"]["warmupLag"]
a = json.load(open(os.path.join(ROOT, "analyses", "M418_audit", "result.json"), encoding="utf-8"))
pairs = [("candidates", b["candidates"], a["n_candidates"]), ("excluded (no frame/coolant + short)", sum(e["n"] for e in b["excluded"]), a["n_excluded"]), ("validCoolant", b["nValidCoolant"], a["n_valid"]),
         ("warmStarts", b["warmStartExcluded"], a["n_warm"]), ("coldStarts", b["coldStarts"], a["n_cold"]), ("nWithOil", b["nWithOil"], a["oil"]["n"])]
for t in ("60", "70", "80"):
    c, ac = b["coolant"][t], a["coolant"][t]
    pairs += [("coolant%s.reached" % t, c["reached"], ac["reached"]), ("coolant%s.censored" % t, c["censored"], ac["censored"]),
              ("coolant%s.censoredSpan p25" % t, c["censoredObservedSeconds"]["p25"], ac["censored_span_p25_med_p75_max"][0]), ("coolant%s.censoredSpan median" % t, c["censoredObservedSeconds"]["median"], ac["censored_span_p25_med_p75_max"][1]),
              ("coolant%s.censoredSpan p75" % t, c["censoredObservedSeconds"]["p75"], ac["censored_span_p25_med_p75_max"][2]), ("coolant%s.censoredSpan max" % t, c["censoredObservedSeconds"]["max"], ac["censored_span_p25_med_p75_max"][3]),
              ("coolant%s.reachedMedian" % t, b["coolant"][t]["reachedTimeSeconds"]["median"], ac["reached_time_median"])]
    o, ao = b["oil"][t], a["oil"][t]
    pairs += [("oil%s.reached" % t, o["reached"], ao["reached_incl_start"]), ("oil%s.atOrAboveAtStart" % t, o["atOrAboveAtStart"], ao["atOrAboveAtStart"]), ("oil%s.censored" % t, o["censored"], ao["censored"])]
rs = {x["t"]: x for x in b["coolant"]["80"]["riskSet"]}
for t, x in a["risk80"].items():
    for k in ("atRisk", "reachedByT", "censoredBeforeT"):
        pairs.append(("risk80.t%s.%s" % (t, k), rs[int(t)][k], x[k]))
rows = [{"quantity": n, "pipeline": p, "audit": q, "equal": abs(float(p) - float(q)) < 1e-9} for n, p, q in pairs]
out = {"pairs": rows, "nPairs": len(rows), "allEqual": all(r["equal"] for r in rows),
       "notAudited": ["hvcEngine80C, warmupCurve and thermalFuelPenalty classifications (covered by the reconciliation with the published estimator n and the known-answer tests, not independently audited)", "oil start gate counts beyond atOrAboveAtStart"],
       "verdict": "accept" if all(r["equal"] for r in rows) else "mismatch"}
json.dump(out, open(os.path.join(ROOT, "analyses", "M418_audit", "compare.json"), "w", encoding="utf-8", newline="\n"), indent=1)
print(out["nPairs"], out["allEqual"], out["verdict"])
