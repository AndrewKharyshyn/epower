"""M404: compare the blind auditor's results with the payload block capacityBasis; writes compare_results.json. Read-only on the repo.
Claim 1 and claim 3 from auditor_results.json; claim 2 (superseded there by the clarified adjacency rule) from auditor_results_claim2_v2.json."""
import json, os
D = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(D, "..", ".."))
cb = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["capacityBasis"]
a1 = json.load(open(os.path.join(D, "auditor_results.json"), encoding="utf-8"))
a2 = json.load(open(os.path.join(D, "auditor_results_claim2_v2.json"), encoding="utf-8"))
f, k, lv = cb["offsetModelTest"]["full"], cb["keyOnTest"]["all"], cb["levelTest"]
get2 = lambda d, *ks: d["5s"][ks[0]]          # the v2 file is keyed by dt cap; the pre-specified cap is 5 s
rows = {"claim1_K": (f["scaleKwhPer100"]["est"], a1["claim1"]["K"]), "claim1_c": (f["offsetA"]["est"], a1["claim1"]["c"]), "claim1_R": (f["R_ohm"]["est"], a1["claim1"]["R"]),
        "claim3_slope_per10": (lv["unadjustedSlope"]["est"], a1["claim3"]["slope_per10"]), "claim3_ah_per100_at_centre55": (lv["unadjustedScaleAtCentre55AhPer100"]["est"], a1["claim3"]["ah_per100"]),
        "claim2_b": (k["slopeSoCPointsPerAh"]["est"], get2(a2, "b")), "claim2_a": (k["interceptSoCPoints"]["est"], get2(a2, "a"))}
out = {n: {"pipeline": p, "auditor": q, "abs_diff": abs(p - q), "rel_diff": abs(p - q) / abs(p)} for n, (p, q) in rows.items()}
out["n"] = {"offsetTestDrives": {"pipeline": cb["offsetModelTest"]["nDrives"], "auditor": a1["claim1"]["n"]}, "keyOnIntervals": {"pipeline": cb["keyOnTest"]["nIntervals"], "auditor": get2(a2, "n")},
            "levelEvents": {"pipeline": cb["population"]["nEvents"], "auditor": a1["claim3"]["n_events"]}}
out["notes"] = ["the first claim-2 run bridged across excluded / no-pair drives (b = -1.45, n = 535); under the clarified full-master adjacency both implementations give the same sample and the same slope",
                "the brief's '100*C about 4.9' was the pooled B, not the scale at centre 55 of the level model; the model's own constant agrees between implementations",
                "the key-on slope depends on the dt cap of the net-charge integral (auditor: -1.91 at 1 s, -1.47 at 2 s, -1.37 at 5 s, -1.22 uncapped)"]
json.dump(out, open(os.path.join(D, "compare_results.json"), "w", encoding="utf-8"), indent=1)
print(json.dumps({n: [round(v["pipeline"], 4), round(v["auditor"], 4), round(v["rel_diff"], 4)] for n, v in out.items() if isinstance(v, dict) and "pipeline" in v}), out["n"])
