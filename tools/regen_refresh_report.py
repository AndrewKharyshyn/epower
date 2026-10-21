#!/usr/bin/env python3
"""M466 regen refresh report (Director conditions c2-c5 of the M463 O7 flag, plus the owner's re-check of cells above 100 %). Compares the CURRENT summary_arrays.json (regen blocks refreshed on the
current corpus) with the same file at a previous git ref and writes analyses/M466_regen_refresh.json. Read-only except for that JSON.
  c2  per-cell support status previous/new for every cell whose status changed, cells whose point left the previous day-clustered interval, and for those cells the new-drives-only estimate
      (same cohort x stratum x view x SOC selection, restricted to the drives absent from the previous master) with the overlap against the previous interval.
  c3  cold standardized view: availability reason, supported groups, dropped groups (coverage 0.000 must come from the < 2 supported groups rule).
  c4  shoulder speed standardized coverage after the band reduction (>= 0.80 or the view is dropped).
  c5  S* (referenceMix weights) maximum absolute change.
  A100  every displayed row with eff > 100 %: status, n/drives/days, interval, conventionRange, massRange, bNat.
Usage: python tools/regen_refresh_report.py --prev-ref 3eb3f3c~1 [--out analyses/M466_regen_refresh.json]"""
import argparse, json, os, subprocess, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)


def git_json(ref, path):
    return json.loads(subprocess.run(["git", "show", "%s:%s" % (ref, path)], capture_output=True, check=True).stdout.decode("utf-8"))


def git_csv_files(ref):
    import io, csv
    raw = subprocess.run(["git", "show", "%s:drive_master.csv" % ref], capture_output=True, check=True).stdout.decode("utf-8")
    return {r["file"] for r in csv.DictReader(io.StringIO(raw))}


def cells(disp):
    """Flatten regenDisplayV2 rows: key (cohort, stratum, view, soc, label) -> row."""
    out = {}
    for c, cb in disp["cohorts"].items():
        for p, sb in cb.get("strata", {}).items():
            for v, vb in (sb.get("views") or {}).items():
                for s, sv in vb["bySoc"].items():
                    for l, r in sv["rows"].items():
                        out[(c, p, v, s, l)] = r
    return out


def std_bars(disp):
    out = {}
    for c, cb in disp["cohorts"].items():
        for p, sb in cb.get("strata", {}).items():
            for v, res in (sb.get("standardized") or {}).items():
                out[(c, p, v)] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev-ref", required=True)
    ap.add_argument("--out", default="analyses/M466_regen_refresh.json")
    a = ap.parse_args()
    old = git_json(a.prev_ref, "summary_arrays.json")["regenDisplayV2"]
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    new = A["regenDisplayV2"]
    co, cn = cells(old), cells(new)
    rep = {"prevRef": a.prev_ref, "prevMasterMd5": old["masterMd5"], "newMasterMd5": new["masterMd5"]}
    # ---- c2
    ib_old = {k: r for k, r in co.items() if r.get("ci95")}
    both = [k for k in ib_old if k in cn and cn[k].get("eff") is not None]
    left = [k for k in both if not (ib_old[k]["ci95"][0] <= cn[k]["eff"] <= ib_old[k]["ci95"][1])]
    status_chg = [k for k in co if k in cn and co[k].get("status") != cn[k].get("status")]
    rep["c2"] = {"nIntervalBearingPrev": len(ib_old), "nComparable": len(both), "nLeftPrevInterval": len(left), "nStatusChanged": len(status_chg), "nCellsPrev": len(co), "nCellsNew": len(cn)}
    focus = sorted(set(left) | set(status_chg))
    import regen_display as RD
    import regen_v2_agg as G
    import regen_v2_cache as K
    dm, reg = G.load_master()
    files = list(dm["file"])
    prev_files = git_csv_files(a.prev_ref)
    is_new = np.array([f not in prev_files for f in files])
    T, hdrs = K.load(files, "base")
    ev = dm["ev_rpm_dt_med_s"].values
    sm = RD.stratum_masks(ev, None)
    cohort_mask = {"all": np.ones(len(dm), bool), "warm": reg.values == "warm", "shoulder": reg.values == "shoulder", "cold": reg.values == "cold"}
    cache = {}
    rows = []
    for k in focus:
        c, p, v, s, l = k
        key = (c, p)
        if key not in cache:
            m = cohort_mask[c] & sm[p] & is_new
            cache[key] = G.Cohort(T, dm, m, "%s-%s-new" % (c, p)) if m.sum() else None
        cc = cache[key]
        nd = None
        if cc is not None and len(cc.drive):
            mats, labels = RD.mats_of(cc, v)
            cb = cc.cell_block(v, cc.sel[s], mats, labels).get(l)
            if cb:
                nd = RD.cell(cb)
        prev, cur = co.get(k), cn.get(k)
        ov = None
        if nd and nd.get("ci95") and prev and prev.get("ci95"):
            ov = bool(nd["ci95"][0] <= prev["ci95"][1] and prev["ci95"][0] <= nd["ci95"][1])
        rows.append({"cell": "/".join(k), "reasons": [r for r, f in (("leftPrevInterval", k in left), ("statusChanged", k in status_chg)) if f],
                     "prev": {x: (prev or {}).get(x) for x in ("status", "eff", "ci95", "n", "drives", "days")}, "new": {x: (cur or {}).get(x) for x in ("status", "eff", "ci95", "n", "drives", "days")},
                     "newDrivesOnly": None if nd is None else {x: nd.get(x) for x in ("status", "eff", "ci95", "n", "drives", "days", "ciSuppressed")}, "newDrivesIntervalOverlapsPrev": ov})
    rep["c2"]["cells"] = rows
    rep["c2"]["nDistinctStratumCohort"] = sorted({"/".join(k[:2]) for k in focus})
    # ---- c3 / c4
    sn, so = std_bars(new), std_bars(old)
    sb_prev = sb_left = 0
    sb_cells = []
    for k, res in so.items():
        for g, b in (res.get("bars") or {}).items():
            nb = ((sn.get(k) or {}).get("bars") or {}).get(g)
            if b.get("ci95Days") and nb and nb.get("standardized") is not None:
                sb_prev += 1
                if not (b["ci95Days"][0] <= nb["standardized"] <= b["ci95Days"][1]):
                    sb_left += 1
                    sb_cells.append({"cell": "/".join(k) + "/" + g, "prev": {"standardized": b["standardized"], "ci95Days": b["ci95Days"]}, "new": {"standardized": nb["standardized"], "ci95Days": nb.get("ci95Days")}})
    rep["c2"]["standardizedBars"] = {"nIntervalBearingPrev": sb_prev, "nLeftPrevInterval": sb_left, "cells": sb_cells}
    rep["c2"]["nIntervalBearingPrevTotal"] = len(ib_old) + sb_prev
    rep["c2"]["nLeftPrevIntervalTotal"] = len(left) + sb_left
    def avail(res):
        av = res.get("availability", {})
        return {"available": av.get("available"), "coverage": av.get("coverage"), "droppedGroups": av.get("droppedGroups"), "reason": res.get("reason"), "nBars": len(res.get("bars", {})),
                "barStatus": {g: b.get("status") for g, b in res.get("bars", {}).items()}, "commonSupportBands": res.get("commonSupportBands")}
    rep["c3"] = {"cold": {"/".join(k): {"new": avail(v), "prev": avail(so[k]) if k in so else None} for k, v in sn.items() if k[0] == "cold"}}
    import regen_std as RS
    co_cold = G.Cohort(T, dm, cohort_mask["cold"], "cold")
    diag = {}
    for view in ("temperature", "speed"):
        labels, J = RS.joint(co_cold, view, RS.soc_strata(co_cold))
        cb = co_cold.cell_block(view, co_cold.sel["allSoc"])
        cols = [g for g in range(len(labels)) if (view == "temperature" or 1 <= g <= 12)]
        diag[view] = {labels[g]: {"status": cb[labels[g]].get("status"), "n": cb[labels[g]].get("n"), "drives": cb[labels[g]].get("drives"), "days": cb[labels[g]].get("days"),
                                  "nSupportedSocStrata": int(sum(bool(J[k]["sup"][g]) for k in J))} for g in cols if cb.get(labels[g], {}).get("n")}
        diag[view] = {"groups": diag[view], "nSupportedGroupsAllSoc": sum(1 for x in diag[view].values() if x["status"] == "supported"),
                      "reading": "coverage 0.000 arises from the rule 'fewer than 2 supported groups' when nSupportedGroupsAllSoc < 2; when >= 2 it arises from an EMPTY intersection of the SOC strata supported for every group (no group was dropped)"}
    rep["c3"]["coldCohortDiagnosis"] = diag
    rep["c4"] = {"shoulder": {"/".join(k): {"new": avail(v), "prev": avail(so[k]) if k in so else None} for k, v in sn.items() if k[0] == "shoulder"}}
    # ---- c5
    wo, wn = old["referenceMix"]["weights"], new["referenceMix"]["weights"]
    keys = sorted(set(wo) | set(wn))
    d = {k: abs(wn.get(k, 0.0) - wo.get(k, 0.0)) for k in keys}
    rep["c5"] = {"maxAbsChangeSstar": max(d.values()), "argmax": max(d, key=d.get), "nWeights": len(keys), "shaPrev": old["referenceMix"]["sha256"], "shaNew": new["referenceMix"]["sha256"]}
    sp = "analyses/regen_std_state.json"                                                     # c5: record next to the availability state (the stage keeps 'state' and 'lastFlags')
    st_ = json.load(open(sp, encoding="utf-8"))
    st_["sstarRefresh"] = {"milestone": "M466", "prevRef": a.prev_ref, "maxAbsChangeSstar": rep["c5"]["maxAbsChangeSstar"], "argmax": rep["c5"]["argmax"], "shaPrev": rep["c5"]["shaPrev"], "shaNew": rep["c5"]["shaNew"]}
    with open(sp, "w", encoding="utf-8", newline="
") as f:
        json.dump(st_, f, indent=1, sort_keys=True)
    # ---- cells above 100 %
    ab = []
    for k, r in cn.items():
        if r.get("eff") is not None and r["eff"] > 100.0:
            ab.append({"cell": "/".join(k), "status": r.get("status"), "n": r.get("n"), "drives": r.get("drives"), "days": r.get("days"), "eff": r["eff"], "ci95": r.get("ci95"), "conventionRange": r.get("conventionRange"),
                       "massRange": r.get("massRange"), "bNat": r.get("bNat"), "flagAbove100": r.get("flagAbove100"), "statusReason": r.get("statusReason")})
    ab_old = [k for k, r in co.items() if r.get("eff") is not None and r["eff"] > 100.0]
    rep["above100"] = {"nNew": len(ab), "nPrev": len(ab_old), "nSupportedNew": sum(1 for x in ab if x["status"] == "supported"), "byStatus": {s: sum(1 for x in ab if x["status"] == s) for s in sorted({x["status"] for x in ab})},
                       "cells": sorted(ab, key=lambda x: (x["status"] != "supported", x["cell"]))}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: (v if k in ("c5",) else {kk: vv for kk, vv in v.items() if kk != "cells"} if isinstance(v, dict) else v) for k, v in rep.items()}, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main()
