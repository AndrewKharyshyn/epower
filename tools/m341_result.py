#!/usr/bin/env python3
"""M341: script-written before/after table for the regenerated seasonal contracts (HEAD payload vs the working payload) plus the check summary.
Writes analyses/M341_result.json. Read-only. Usage: python tools/m341_result.py"""
import json, os, subprocess
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
new = json.load(open("summary_arrays.json", encoding="utf-8"))
old = json.loads(subprocess.check_output(["git", "show", "HEAD:summary_arrays.json"]).decode("utf-8"))
chk = json.load(open("analyses/M341_check.json", encoding="utf-8"))
cn, co = new["seasonalCharts"]["charts"], old["seasonalCharts"]["charts"]


def g(o, *path):
    for p in path:
        try:
            o = o[p]
        except Exception:
            return None
    return o


def wc_pt(o, c, km):
    pts = g(o, "WarmupCurve", "data", c, "classes", "urban", "points") or []
    return next((p for p in pts if p["km"] == km), None)


heads = {
    "SpeedDist.overall (% time per zone)": lambda o, c: g(o, "SpeedDist", "data", c, "overall"),
    "RpmDistribution.pooledPct": lambda o, c: g(o, "RpmDistribution", "data", c, "pooledPct"),
    "EngineStartsByType.avg (/100 km: urban, mixed, mixed_highway, highway)": lambda o, c: [x.get("avg") for x in (g(o, "EngineStartsByType", "data", c) or [])],
    "WarmupCurve urban @1.0 km (med, p25, p75, n)": lambda o, c: (lambda p: [p["med"], p["p25"], p["p75"], p["n"]] if p else None)(wc_pt(o, c, 1.0)),
    "BufferDebtRecovery (nDrivesCovered, nEvents, half-time median s)": lambda o, c: (lambda b: [b.get("nDrivesCovered"), b.get("nEvents"), (b.get("recoveryHalfTimeS") or {}).get("median")] if b else None)(g(o, "BufferDebtRecovery", "data", c)),
    "CrawlStopGo (keys present)": lambda o, c: sorted((g(o, "CrawlStopGo", "data", c) or {}).keys())[:6],
}
table = {}
for name, f in heads.items():
    table[name] = {c: {"before": f(co, c), "after": f(cn, c)} for c in ("all", "warm", "shoulder")}
cov = {k: {c: {"before": g(co, k, "coverage", c), "after": g(cn, k, "coverage", c)} for c in ("all", "warm", "shoulder")} for k in cn if (cn[k].get("refreshedBy") or "").startswith("M341")}
master = {k: {"basisBefore": g(co, k, "basisNDrives"), "basisAfter": g(cn, k, "basisNDrives")} for k in cn if (cn[k].get("refreshedBy") or "").startswith("M296")}
res = {"milestone": "M341", "liveNDrives": chk["nLive"], "cohortSizes": chk["cohortSizes"], "cacheSchemaVersion": chk["cacheSchemaVersion"], "cacheEntries": chk["cacheEntries"],
       "parityPassed": len(chk["parityPassed"]), "parityFailed": chk["parityFailed"], "timingsS": chk["timings"],
       "conservation": {"nConservedLeaves": sum(e["conservation"]["nConserved"] for e in chk["charts"].values()),
                        "nonConserving": {k: {"nLeaves": e["conservation"]["nViolations"], "examples": e["conservation"]["violations"][:2]} for k, e in chk["charts"].items() if e["conservation"]["nViolations"]},
                        "rule": "warm + shoulder + the 2 below-support cold drives == all (count leaves; floats compared at their rounding)"},
       "cohortRelativeCutpoints": {k: e["cohortRelativeCutpoints"] for k, e in chk["charts"].items() if e["cohortRelativeCutpoints"]},
       "chartsRefreshedRaw": sorted(k for k in cn if (cn[k].get("refreshedBy") or "").startswith("M341")), "masterClassBasis": master,
       "headlineBeforeAfter": table, "coverageBeforeAfter": cov,
       "filesLoaded": chk["filesLoaded"], "builderLoads": chk["builderLoads"], "totalSecondsUncached": chk["totalSeconds"], "cacheIndex": chk["cacheIndex"],
       "crawlStopGoNonConservationCause": "restartProbability.byPrecedingEngineState n: all minus (warm + shoulder) = the cycles of the 2 below-support cold drives (one calendar day), which the builder's dayboot_prop returns as n = 0 (it needs >= 3 distinct days); not event pairing across drives",
       "blindAuditReported": {"verdict": "partial", "toleranceFromAuditorAllCalibration": "speed zones <= 0.2 pt (All), 0.3 (Warm), 0.5 (Shoulder); rpm off-bin within 0.01-0.02 h, transition bins 1-18% (auditor resampling differs); warm-up median exact (n off by one, cold-start gate inferred); engine starts per 100 km Shoulder exact",
                              "open": "speed-channel rule: the auditor's best fit is the OBD channel only, the stated priority rule (VCM if >= 20 native samples) fits worse; unresolved, same estimator as released", "source": "audit report this session (not script-written)"},
       "allowListNote": "deep-diff vs git HEAD: only seasonalCharts changed (46 charts: 37 raw-class by M341, 9 master-class re-run at 489 by m296_refresh_master_seasonal.py); 0 leaves outside seasonalCharts",
       "limits": "raw/ basis via raw_only (F03 provenance-sensitive); shoulder is a late-season batch (mostly September, 98% urban): season-associated, not a temperature effect; cohort numbers carry no CI unless the builder emits one"}
with open("analyses/M341_result.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(res, f, indent=1, ensure_ascii=False, default=float); f.write("\n")
print(json.dumps({"parity": res["parityPassed"], "conserved": res["conservation"]["nConservedLeaves"], "nonConserving": list(res["conservation"]["nonConserving"]), "master": master}))
