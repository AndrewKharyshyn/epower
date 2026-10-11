"""M403: compare the blind auditor's results (auditor_results.json) with the payload block capacityBasis; writes compare_results.json. Read-only on the repo."""
import json, os
D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(D, "..", ".."))
aud = json.load(open(os.path.join(D, "auditor_results.json"), encoding="utf-8"))
cb = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["capacityBasis"]
a, k = cb["ahPer100"], cb["kWhPer100"]
pairs = {"B_ah_per100": (a["point"], aud["B_ah_per100"]), "B_kwh_per100": (k["point"], aud["B_kwh_per100"]), "B_offset_A": (cb["currentOffsetFitA"]["value"], aud["B_offset_A"]),
         "B_reverse_ah_per100": (cb["eventsB"]["reverseAh100"], aud["B_reverse_ah_per100"]), "A_segment_ah_per100": (cb["eventsB"]["segmentAAh100"], aud["A_segment_ah_per100"]),
         "W10_anchored_ah_per100": (cb["windows"]["10"]["Q_Ah"]["est"], aud["W10_anchored_ah_per100"]),
         "B_ci95_low": (a["bootstrapCI95"][0], aud["B_ci95"][0]), "B_ci95_high": (a["bootstrapCI95"][1], aud["B_ci95"][1])}
rows = {n: {"pipeline": p, "auditor": q, "abs_diff": abs(p - q), "rel_diff": abs(p - q) / abs(p) if p else None} for n, (p, q) in pairs.items()}
out = {"rows": rows, "max_rel_point": max(r["rel_diff"] for n, r in rows.items() if "ci95" not in n and n != "B_offset_A"),
       "n_drives": {"pipeline": cb["population"]["nDrives"], "auditor": aud["n_drives"]}, "n_days": {"pipeline": cb["population"]["nDays"], "auditor": aud["n_days"]},
       "n_events": {"pipeline": cb["population"]["nEvents"], "auditor": aud["n_events"]}}
json.dump(out, open(os.path.join(D, "compare_results.json"), "w", encoding="utf-8"), indent=1)
print(json.dumps({"max_rel_point": out["max_rel_point"], "n_drives": out["n_drives"], "n_days": out["n_days"], "n_events": out["n_events"], "rows": {n: [round(r["pipeline"], 4), round(r["auditor"], 4)] for n, r in rows.items()}}))
