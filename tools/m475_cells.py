#!/usr/bin/env python3
"""M475 check E4 (spec analyses/M475_spec.md): old versus new aggregated blocks, cell by cell. `old` and `new` are two summary_arrays.json files (default: the pre-M475 copy given as argv[1] and the live file). A CELL is a dict with
`status` and `eff`. Reported (never tuned): support-status changes, support-count changes (n, drives, days), cells whose new point leaves the OLD day-clustered interval, the largest shifts in pp, cells above 100 % appearing or
disappearing, the standardized bars (SOC-standardized values) and their availability. The pre-registered O7 escalation flags are computed from these. Writes analyses/M475_cells.json.
Usage: python tools/m475_cells.py <old_summary_arrays.json> [new_summary_arrays.json]"""
import json, sys
import numpy as np

BLOCKS = ["regenCaptureV2", "regenCaptureV2H", "regenSocStandardized", "regenDisplayV2"]


def cells(o, path=""):
    if isinstance(o, dict):
        if "status" in o and "eff" in o:
            yield path, o
        for k, v in o.items():
            yield from cells(v, path + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from cells(v, f"{path}[{i}]")


def bars(o, path=""):
    """SOC-standardized bars: dicts with `standardized` and `ci95Days`."""
    if isinstance(o, dict):
        if "standardized" in o and "ci95Days" in o:
            yield path, o
        for k, v in o.items():
            yield from bars(v, path + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from bars(v, f"{path}[{i}]")


def main(argv):
    old = json.load(open(argv[0], encoding="utf-8"))
    new = json.load(open(argv[1] if len(argv) > 1 else "summary_arrays.json", encoding="utf-8"))
    out = {"blocks": {}, "o7": {}}
    flags = {"statusChanged": [], "leftOldInterval": [], "above100Changed": [], "supportCountChanged": [], "barLeftOldInterval": [], "barAvailabilityChanged": []}
    for b in BLOCKS:
        co, cn = dict(cells(old[b], b)), dict(cells(new[b], b))
        keys = sorted(set(co) & set(cn))
        diffs, rec = [], {"nCells": len(keys), "onlyOld": len(set(co) - set(cn)), "onlyNew": len(set(cn) - set(co))}
        for k in keys:
            a, c = co[k], cn[k]
            if a.get("status") != c.get("status"):
                flags["statusChanged"].append([k, a.get("status"), c.get("status")])
            for f in ("n", "drives", "days"):
                if f in a and a.get(f) != c.get(f):
                    flags["supportCountChanged"].append([k, f, a.get(f), c.get(f)])
            if a.get("eff") is not None and c.get("eff") is not None:
                d = c["eff"] - a["eff"]
                diffs.append(d)
                ci = a.get("ci95")
                if ci and not (ci[0] <= c["eff"] <= ci[1]):
                    flags["leftOldInterval"].append([k, a["eff"], c["eff"], ci])
                if (a["eff"] > 100) != (c["eff"] > 100):
                    flags["above100Changed"].append([k, a["eff"], c["eff"]])
        d = np.array(diffs)
        rec.update({"nWithEff": int(d.size), "maxAbsShiftPp": float(np.abs(d).max()) if d.size else None, "medianAbsShiftPp": float(np.median(np.abs(d))) if d.size else None,
                    "p95AbsShiftPp": float(np.percentile(np.abs(d), 95)) if d.size else None, "nShiftOver0p1pp": int((np.abs(d) > 0.1).sum()), "nShiftOver0p5pp": int((np.abs(d) > 0.5).sum())})
        out["blocks"][b] = rec
    bo, bn = dict(bars(old["regenDisplayV2"], "regenDisplayV2")), dict(bars(new["regenDisplayV2"], "regenDisplayV2"))
    bd = []
    for k in sorted(set(bo) & set(bn)):
        a, c = bo[k], bn[k]
        if a.get("standardized") is not None and c.get("standardized") is not None:
            bd.append(c["standardized"] - a["standardized"])
            ci = a.get("ci95Days")
            if ci and not (ci[0] <= c["standardized"] <= ci[1]):
                flags["barLeftOldInterval"].append([k, a["standardized"], c["standardized"], ci])
        if (a.get("standardized") is None) != (c.get("standardized") is None):
            flags["barAvailabilityChanged"].append(k)
    bd = np.array(bd)
    out["bars"] = {"nBars": len(set(bo) & set(bn)), "maxAbsShiftPp": float(np.abs(bd).max()) if bd.size else None, "medianAbsShiftPp": float(np.median(np.abs(bd))) if bd.size else None}
    out["referenceMixSha256"] = {"old": old["regenDisplayV2"]["referenceMix"]["sha256"], "new": new["regenDisplayV2"]["referenceMix"]["sha256"], "weightsEqual": old["regenDisplayV2"]["referenceMix"]["weights"] == new["regenDisplayV2"]["referenceMix"]["weights"]}
    out["b6"] = {"old": old["regenDisplayV2"]["b6Reference"], "new": new["regenDisplayV2"]["b6Reference"], "equal": old["regenDisplayV2"]["b6Reference"] == new["regenDisplayV2"]["b6Reference"]}
    out["o7"] = {"a_displayedCellChangedSupportStatus": len(flags["statusChanged"]), "b_standardizedStarChanged": int(not out["referenceMixSha256"]["weightsEqual"]) + len(flags["barAvailabilityChanged"]),
                 "c_displayedPointLeftPreviousDayInterval": len(flags["leftOldInterval"]) + len(flags["barLeftOldInterval"]), "d_b6Changed": int(not out["b6"]["equal"]),
                 "e_above100Appeared": len(flags["above100Changed"]), "supportCountChanges": len(flags["supportCountChanged"])}
    out["flags"] = {k: v[:30] for k, v in flags.items()}
    json.dump(out, open("analyses/M475_cells.json", "w", encoding="utf-8", newline="\n"), indent=1)
    print(json.dumps({"blocks": out["blocks"], "bars": out["bars"], "referenceMix": out["referenceMixSha256"], "b6Equal": out["b6"]["equal"], "o7": out["o7"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
