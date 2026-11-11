"""M608 (Director follow-up): diff the standardized regeneration views HEAD vs working tree for every cohort x stratum x view: availability, coverage, dropped groups, common-support bands,
bars present, and each bar's standardized point / day interval / week interval. Read-only. Writes the JSON given as argv[1]."""
import json, subprocess, sys
new = json.load(open("summary_arrays.json", encoding="utf-8"))
old = json.loads(subprocess.run(["git", "show", "HEAD:summary_arrays.json"], capture_output=True, text=True, encoding="utf-8", check=True).stdout)
out = {"views": [], "summary": {}}
nb = ni = 0
for coh in ("all", "warm", "shoulder", "cold"):
    for s in ("fast", "slow"):
        for v in ("temperature", "speed"):
            try:
                o = old["regenDisplayV2"]["cohorts"][coh]["strata"][s]["standardized"][v]; n = new["regenDisplayV2"]["cohorts"][coh]["strata"][s]["standardized"][v]
            except KeyError:
                out["views"].append({"view": f"{coh}/{s}/{v}", "missing": True}); continue
            r = {"view": f"{coh}/{s}/{v}", "availability": [o["availability"], n["availability"]], "bandsPrev": o["commonSupportBands"], "bandsNew": n["commonSupportBands"],
                 "bandsChanged": o["commonSupportBands"] != n["commonSupportBands"], "availabilityChanged": o["availability"] != n["availability"], "bars": []}
            ob, nbars = o.get("bars") or {}, n.get("bars") or {}
            r["barSetChanged"] = sorted(ob) != sorted(nbars)
            for k in sorted(set(ob) | set(nbars)):
                a, b = ob.get(k), nbars.get(k)
                if a is None or b is None:
                    r["bars"].append({"bar": k, "prev": bool(a), "new": bool(b)}); continue
                inside = a.get("ci95Days") is not None and a["ci95Days"][0] <= b["standardized"] <= a["ci95Days"][1]
                r["bars"].append({"bar": k, "prevPoint": a["standardized"], "newPoint": b["standardized"], "absDelta": round(abs(a["standardized"] - b["standardized"]), 2),
                                  "newPointInsidePrevDayInterval": inside if a.get("ci95Days") else None, "statusPrevNew": [a.get("status"), b.get("status")]})
                nb += 1; ni += 1 if (a.get("ci95Days") and inside) else 0
            out["views"].append(r)
vs = [x for x in out["views"] if not x.get("missing")]
out["summary"] = {"nViews": len(vs), "nBandSetChanged": sum(x["bandsChanged"] for x in vs), "nAvailabilityChanged": sum(x["availabilityChanged"] for x in vs), "nBarSetChanged": sum(x["barSetChanged"] for x in vs),
                  "changedViews": [x["view"] for x in vs if x["bandsChanged"] or x["availabilityChanged"] or x["barSetChanged"]], "nBarsCompared": nb, "nBarsInsidePrevDayInterval": ni,
                  "maxAbsPointDelta": max([b["absDelta"] for x in vs for b in x["bars"] if "absDelta" in b] or [0])}
json.dump(out, open(sys.argv[1], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(json.dumps(out["summary"], ensure_ascii=False))
