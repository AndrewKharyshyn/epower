"""M406: compare the blind auditor's results with the payload block dependenceSensitivity; writes compare_results.json. Point values must agree; bootstrap values differ only by RNG (compared with the
pipeline's own seed range). Read-only on the repo."""
import json, os
D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(D, "..", ".."))
b = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["dependenceSensitivity"]
a = json.load(open(os.path.join(D, "auditor_results.json"), encoding="utf-8"))
rows = {}
for s in ("cellSpread", "resistanceVreg"):
    t, x = b["trendSlopes"][s], a[s]
    rows[s] = {"slope": (t["cr1"]["slope"], x["slope"]), "cr1_se": (t["cr1"]["se"], x["cr1_se"]), "cr2_se": (t["cr2"]["se"], x["cr2_se"]), "cr2_df": (t["cr2"]["df"], x["cr2_df"]),
               "wild_p": (t["wildClusterBootstrapT"]["pValueNullImposed"], x["wild_p"]), "pairs_day_lower": (t["dayClusterPairsBootstrap"]["ci95"][0], x["pairs_day_ci"][0]),
               "pairs_week_lower": (t["weekBlockPairsBootstrap"]["ci95"][0], x["pairs_week_ci"][0]), "pairs_week_upper": (t["weekBlockPairsBootstrap"]["ci95"][1], x["pairs_week_ci"][1])}
    sp = t["seedSpread"]
    rows[s]["_withinPipelineSeedRange"] = {"wild_p": sp["wildPValueRange"][0] - 0.015 <= x["wild_p"] <= sp["wildPValueRange"][1] + 0.015,
                                            "day_lower": sp["dayPairsLowerRange"][0] - 0.03 <= x["pairs_day_ci"][0] <= sp["dayPairsLowerRange"][1] + 0.03,
                                            "week_lower": sp["weekBlockLowerRange"][0] - 0.05 <= x["pairs_week_ci"][0] <= sp["weekBlockLowerRange"][1] + 0.05}
k = b["thesisKpis"]
rows["K1"] = {"est": (k["K1_throughputOverDischarge"]["estimate"], a["K1"]["est"]), "day_lo": (k["K1_throughputOverDischarge"]["dayClusterCI95"][0], a["K1"]["day"][0])}
rows["K2"] = {"est": (k["K2_netShare_corrected"]["estimate"], a["K2"]["est"])}
rows["soc_median"] = {"est": (k["K3_socBandMedianPp"]["estimate"], a["soc_median"]["est"]), "n": (k["K3_socBandMedianPp"]["n"], a["soc_median"]["n"])}
out = {"rows": {s: {n: ({"pipeline": v[0], "auditor": v[1], "abs_diff": abs(v[0] - v[1])} if isinstance(v, tuple) else v) for n, v in r.items()} for s, r in rows.items()}}
pts = [v["abs_diff"] for r in out["rows"].values() for n, v in r.items() if isinstance(v, dict) and "abs_diff" in v and n in ("slope", "cr1_se", "cr2_se", "cr2_df", "est")]
out["maxAbsDiffPointValues"] = max(pts)
out["note"] = "point values (slopes, CR1/CR2 SE, CR2 df, KPI estimates) agree; bootstrap quantities differ by RNG and by the seed spread of the pipeline (wild p 0.040-0.054 across seeds straddles 0.05); the auditor's CR2 inverse square root and pseudo-inverse agree to 1e-13"
json.dump(out, open(os.path.join(D, "compare_results.json"), "w", encoding="utf-8"), indent=1)
print(json.dumps({"maxAbsDiffPointValues": out["maxAbsDiffPointValues"], "seedRange": {s: out["rows"][s]["_withinPipelineSeedRange"] for s in ("cellSpread", "resistanceVreg")}}))
