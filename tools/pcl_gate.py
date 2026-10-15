#!/usr/bin/env python3
"""PCL-1 one-shot analysis (spec analyses/PCL1_spec.md Rev 2, section 4): G2 in its D4 form on the protocol drives (randomized polling arm), the view totals (B1), the reported randomized cadence effect on the native v2 level and an intention-to-treat sensitivity.
Refuses to run unless (i) CHANGELOG.md carries 'PCL1 spec sha256 <hash of the spec>' AND 'PCL1 schedule sha256 <hash of the schedule body>' (B5), (ii) there are at least 60 paired days, or the hard stop 2027-09-30 has passed (then the result is INCONCLUSIVE without any cell and
goes to the FAIL branch), (iii) the lock file analyses/PCL1_gate.lock does not exist. The analysis uses the first 100 paired days. --extension runs the single allowed extension (cumulative paired days up to 160) after an INCONCLUSIVE first result and keeps the first result.
--smoke <out.json> --start <date> runs the same code path on an arbitrary start date WITHOUT the lock and the freeze check and writes only to <out.json> (code test on the existing corpus, never a result).
Usage: python tools/pcl_gate.py | python tools/pcl_gate.py --extension | python tools/pcl_gate.py --smoke OUT.json --start 2026-05-01 [--smoke-min-paired 2]"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import regen_v2_agg as G
import m441_study as S
import m442_gate as MG
import pcl_schedule as PS
import pcl_monitor as PM

SPEC = "analyses/PCL1_spec.md"
BRACKET_FILE = "analyses/M442_result_rerun.json"
MIN_PAIRED, STOP_PAIRED, EXT_PAIRED, HARD_STOP, EXT_DAYS = 60, 100, 160, dt.date(2027, 9, 30), 90
MIN_TEMP_CELLS, MIN_SPEED_CELLS = 3, 5


def sha_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def frozen_ok(schedule_path):
    head = open("CHANGELOG.md", encoding="utf-8").read(80000)
    sched_sha = PS.read(schedule_path)[4]
    return ("PCL1 spec sha256 " + sha_file(SPEC)) in head and sched_sha is not None and ("PCL1 schedule sha256 " + sched_sha) in head


def decide(cells, totals=None):
    """Pure decision rule of spec section 4. cells = {view: {label: {"overallSupported", "supportedBoth", "judgement"}}} for 'temperature' and 'speed'; totals = {view: "ok"|"fail"|"indeterminate"|"notTested"} (None = not checked).
    FAIL if any tested cell or view total fails; PASS if in each view at least half of the pooled-supported cells are supported in both arms, at least 3 temperature and 5 speed cells are tested, every view total is OK and no tested cell is indeterminate;
    INCONCLUSIVE otherwise."""
    tested = {v: [l for l, c in cs.items() if c["overallSupported"] and c["supportedBoth"] and c["judgement"] != "notTested"] for v, cs in cells.items()}
    overall = {v: [l for l, c in cs.items() if c["overallSupported"]] for v, cs in cells.items()}
    fails = [(v, l) for v, ls in tested.items() for l in ls if cells[v][l]["judgement"] == "fail"]
    indet = [(v, l) for v, ls in tested.items() for l in ls if cells[v][l]["judgement"] == "indeterminate"]
    t_fail = [v for v, j in (totals or {}).items() if j == "fail"]
    t_notok = [v for v, j in (totals or {}).items() if j != "ok"]
    half_ok = all(len(overall[v]) > 0 and len(tested[v]) >= len(overall[v]) / 2.0 for v in cells)
    enough = len(tested.get("temperature", [])) >= MIN_TEMP_CELLS and len(tested.get("speed", [])) >= MIN_SPEED_CELLS
    if fails or t_fail:
        verdict = "FAIL"
    elif half_ok and enough and not indet and not t_notok:
        verdict = "PASS"
    else:
        verdict = "INCONCLUSIVE"
    return {"verdict": verdict, "failing": ["%s|%s" % x for x in fails] + ["total|%s" % v for v in t_fail], "indeterminate": ["%s|%s" % x for x in indet] + ["total|%s" % v for v in t_notok if v not in t_fail],
            "nTested": {v: len(ls) for v, ls in tested.items()}, "nOverallSupported": {v: len(ls) for v, ls in overall.items()}, "halfSupportedInBothArms": bool(half_ok), "enoughCells": bool(enough), "totals": totals}


def ci_of(dr, level=95.0):
    """Percentile interval of the finite draws at the given level (95 or 97.5 %); None if more than 2.5 % of the draws are unidentified."""
    fin = np.isfinite(dr)
    if fin.mean() < 1 - G.UNID_MAX or not fin.sum():
        return None
    lo = (100.0 - level) / 2.0
    return [round(float(np.percentile(dr[fin], lo)), 3), round(float(np.percentile(dr[fin], 100.0 - lo)), 3)]


def total_diff(co_a, co_b, view, sel, level=95.0):
    """Paired difference (a minus b, pp) of the pooled ratio summed over the cells of a view: point value and interval at the level (same resamples as the cells)."""
    out = []
    for co in (co_a, co_b):
        mats, labels = co.mats(view)
        C_, _, K_ = co.sums(mats, co.sel[sel])[:3]
        out.append((C_.sum(axis=1), K_.sum(axis=1)))
    (Ca, Ka), (Cb, Kb) = out
    with np.errstate(invalid="ignore", divide="ignore"):
        d = 100.0 * (co_a.counts @ Ca) / (co_a.counts @ Ka) - 100.0 * (co_b.counts @ Cb) / (co_b.counts @ Kb)
        pt = 100.0 * Ca.sum() / Ka.sum() - 100.0 * Cb.sum() / Kb.sum()
    return float(pt), ci_of(d, level)


def own_bracket(bracket, kind):
    """Own (non-borrowed) b values of a view; the 0-10 km/h bin never enters (Director, spec Rev 2.1): returns (own dict, fallback = max of own)."""
    d = bracket.get(kind) or {}
    borrowed = set(d.get("_borrowed", []))
    own = {k: v for k, v in d.items() if not k.startswith("_") and v is not None and k not in borrowed and not (kind == "speed" and k == "0-10")}
    return own, (max(own.values()) if own else None)


def total_judgement(pt, ci, tol, both):
    """B1: OK only if supported in both arms and the whole 95 % interval lies inside +-tolerance; FAIL if the interval excludes 0 and |difference| exceeds the tolerance; INDETERMINATE otherwise."""
    if not both or tol is None or pt is None:
        return "notTested"
    if ci is None:
        return "indeterminate"
    if (ci[0] > 0 or ci[1] < 0) and abs(pt) > tol:
        return "fail"
    return "ok" if (ci[0] >= -tol and ci[1] <= tol) else "indeterminate"


def arm_arrays(dm, start, design, table, keep):
    """Per-row arrays aligned to dm: date, observed-fast, observed-slow, assigned-fast, assigned-slow masks (eligible = on or after the START DATE, canonical-clean, in support, finite cadence)."""
    d = dm.copy()
    d["date"] = d["date"].astype(str).str[:10]
    order = d.sort_values(["date", "time_start"]).groupby("date").cumcount() + 1                    # B6: start order among ALL files of the day
    d["trip"] = order.reindex(d.index)
    ev = d["ev_rpm_dt_med_s"].values
    el = (d["date"] >= start.isoformat()).values & keep & np.isfinite(ev)
    if "ens_outlier_v2" in d:
        el &= ~d["ens_outlier_v2"].astype(bool).values
    asg = np.array([PS.assigned_arm(design, table, a, t, ts) for a, t, ts in zip(d["date"], d["trip"], d["time_start"])])
    return d["date"].values, el & (ev < 1.0), el & (ev >= 1.0), el & (asg == "fast"), el & (asg == "slow"), asg


def paired_days(dates, fast, slow):
    out = []
    for u in sorted(set(dates[fast | slow])):
        if (fast & (dates == u)).sum() >= 2 and (slow & (dates == u)).sum() >= 2:
            out.append(u)
    return out


def compare(T, dm, fast, slow, days, bracket, tag, level=95.0):
    """Per-cell and per-view-total fast-minus-slow comparison on the paired days (temperature view; speed view without the 0-10 km/h bin)."""
    co_f, co_s, co_a = (G.Cohort(T, dm, m, n, days=days) for m, n in ((fast, "fast"), (slow, "slow"), (fast | slow, "all")))
    out, cells, totals = {}, {}, {}
    cb_f, cb_s = co_f.cell_block("all", co_f.sel["noSocCondition"]).get("all", {}), co_s.cell_block("all", co_s.sel["noSocCondition"]).get("all", {})
    both_total = cb_f.get("status") == "supported" and cb_s.get("status") == "supported"
    for view, kind in (("temperature", "temperature"), ("speed", "speed")):
        labels, dd, pp, _ = S.paired_draws(co_f, co_s, view, "noSocCondition")
        bf, bs, ba = (co.cell_block(view, co.sel["noSocCondition"]) for co in (co_f, co_s, co_a))
        bvals, fb = own_bracket(bracket, kind)
        rows, jc = {}, {}
        for j, lab in enumerate(labels):
            if kind == "speed" and j == 0:
                continue                                                           # 0-10 km/h stays in the payload only
            a, b_, o = bf.get(lab, {}), bs.get(lab, {}), ba.get(lab, {})
            if not o.get("n"):
                continue
            both = a.get("status") == "supported" and b_.get("status") == "supported" and np.isfinite(pp[j])
            ci = ci_of(dd[:, j], level) if both else None
            hw = (o["massRange"][1] - o["massRange"][0]) / 2.0 if (both and o.get("massRange")) else None                   # B7: both arms pooled
            bl = bvals.get(lab, fb)
            tol = None if (bl is None or hw is None) else bl + hw
            st = MG.judge(ci, float(pp[j]) if both else None, tol, both)
            rows[lab] = {"fastEff": a.get("eff"), "slowEff": b_.get("eff"), "diffPp": None if not both else round(float(pp[j]), 3), "ci95": ci, "tolerance": None if tol is None else round(tol, 3), "bracket": None if bl is None else round(bl, 3),
                         "supportedFast": a.get("status") == "supported", "supportedSlow": b_.get("status") == "supported", "judgement": st}
            jc[lab] = {"overallSupported": o.get("status") == "supported", "supportedBoth": bool(both), "judgement": st}
        pt, ci_t = total_diff(co_f, co_s, view, "noSocCondition", level)
        tol_t = None if fb is None else fb + MG.mass_hw(co_a, view, "noSocCondition")
        tj = total_judgement(pt, ci_t, tol_t, both_total)
        totals[view] = tj
        out[view] = rows
        out[view + "Total"] = {"diffPp": round(pt, 3), "ci95": ci_t, "tolerance": None if tol_t is None else round(tol_t, 3), "supportedBothArms": bool(both_total), "judgement": tj}
        cells[view] = jc
    return {"tag": tag, "intervalLevel": level, "cells": out, "decision": decide(cells, totals)}


def native_effect(T, dm, fast, slow, days):
    """Estimand (b): the randomized cadence effect on the native v2 level, fast minus slow, per supported cell (reported, not a gate)."""
    co_f, co_s = (G.Cohort(T, dm, m, n, days=days) for m, n in ((fast, "fast"), (slow, "slow")))
    out = {}
    for view in ("temperature", "speed"):
        labels, dd, pp, _ = S.paired_draws(co_f, co_s, view, "noSocCondition")
        bf, bs = co_f.cell_block(view, co_f.sel["noSocCondition"]), co_s.cell_block(view, co_s.sel["noSocCondition"])
        out[view] = {lab: {"diffPp": round(float(pp[j]), 3), "ci95": MG.pct_ci(dd[:, j]), "fastEff": bf[lab]["eff"], "slowEff": bs[lab]["eff"]} for j, lab in enumerate(labels)
                     if bf.get(lab, {}).get("status") == "supported" and bs.get(lab, {}).get("status") == "supported" and np.isfinite(pp[j])}
    return out


def run(schedule_path, smoke_start=None, min_paired=MIN_PAIRED, max_paired=STOP_PAIRED, level=95.0):
    t0 = time.time()
    if smoke_start is None:
        start, seed, design, table, _ = PS.read(schedule_path)
    else:
        start, seed, design, table = smoke_start, 42, "A", {}
    dm, reg = G.load_master()
    files = list(dm["file"])
    oos, info = G.oos_info(files, MG.DELTA)
    dates, ofast, oslow, afast, aslow, asg = arm_arrays(dm, start, design, table, ~oos)
    all_days = paired_days(dates, ofast, oslow)
    out = {"protocol": "PCL-1", "specSha256": sha_file(SPEC), "startDate": start.isoformat(), "seed": seed, "design": design, "nPairedDaysAvailable": len(all_days),
           "rule": "first %d paired days; minimum %d" % (max_paired, min_paired)}
    if len(all_days) < min_paired:
        out["decision"] = {"verdict": "INCONCLUSIVE", "reason": "fewer than %d paired days: no cell computed" % min_paired}
        out["seconds"] = round(time.time() - t0)
        return out
    days = all_days[:max_paired]
    out["nPairedDays"] = len(days)
    bracket = json.load(open(BRACKET_FILE, encoding="utf-8"))["bracket"]["b"]
    out["bracketSource"] = {"file": BRACKET_FILE, "sha256": sha_file(BRACKET_FILE)}
    T_h, T_n = MG.tables(files, MG.HARM), MG.tables(files, ["base"])
    out["G2"] = compare(T_h, dm, ofast, oslow, days, bracket, "harmonized interp3, observed arm, paired days", level)
    out["nativeCadenceEffect"] = native_effect(T_n, dm, ofast, oslow, days)
    itt_days = paired_days(dates, afast, aslow)[:max_paired]
    out["itt"] = compare(T_h, dm, afast, aslow, itt_days, bracket, "harmonized interp3, ASSIGNED arm (intention to treat), sensitivity", level) if table and itt_days else None
    ev_all = dm["ev_rpm_dt_med_s"].values                                                      # compliance denominator = ALL protocol log files with a known observed arm (missed or split logs count as non-compliance)
    elig = (dates >= start.isoformat()) & np.isin(asg, ("fast", "slow")) & np.isfinite(ev_all)
    comp = float((asg[elig] == np.where(ev_all[elig] < 1.0, "fast", "slow")).mean()) if elig.any() else None
    out["compliance"] = {"share": None if comp is None else round(comp, 4), "nCompared": int(elig.sum())}
    out["balance"] = {"fastDrives": int((ofast & np.isin(dates, days)).sum()), "slowDrives": int((oslow & np.isin(dates, days)).sum())}
    out["verdict"] = out["G2"]["decision"]["verdict"]
    itt_v = out["itt"]["decision"]["verdict"] if out["itt"] else None
    out["directorBeforePass"] = bool((comp is not None and comp < PM.ESCALATE_BELOW) or (itt_v is not None and itt_v != out["verdict"]))                                         # B8
    out["seconds"] = round(time.time() - t0)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke")
    ap.add_argument("--start")
    ap.add_argument("--smoke-min-paired", type=int, default=MIN_PAIRED)
    ap.add_argument("--extension", action="store_true")
    ap.add_argument("--schedule", default=os.path.join(ROOT, "analyses", "PCL1_schedule.csv"))
    a = ap.parse_args(argv)
    if a.smoke:
        res = run(a.schedule, smoke_start=dt.date.fromisoformat(a.start), min_paired=a.smoke_min_paired)
        with open(a.smoke, "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1)
        print(json.dumps({"smoke": True, "nPairedDaysAvailable": res["nPairedDaysAvailable"], "verdict": res.get("verdict")}))
        return 0
    if not os.path.exists(a.schedule):
        raise SystemExit("no schedule file: the protocol has not started")
    if not frozen_ok(a.schedule):
        raise SystemExit("refusing to run: CHANGELOG.md must carry 'PCL1 spec sha256 %s' and 'PCL1 schedule sha256 <body hash>'" % sha_file(SPEC))
    lock, resfile, mx = ("analyses/PCL1_gate.lock", "analyses/PCL1_result.json", STOP_PAIRED)
    if a.extension:
        first = json.load(open("analyses/PCL1_result.json", encoding="utf-8")) if os.path.exists("analyses/PCL1_result.json") else None
        if not first or first.get("verdict") != "INCONCLUSIVE" or first.get("nPairedDays", 0) < MIN_PAIRED:
            raise SystemExit("the extension needs a first result INCONCLUSIVE with at least %d paired days" % MIN_PAIRED)
        lock, resfile, mx = ("analyses/PCL1_gate_extension.lock", "analyses/PCL1_result_extension.json", EXT_PAIRED)
        first_day = dt.date.fromisoformat(json.load(open("analyses/PCL1_gate.lock", encoding="utf-8"))["ranAt"][:10])
        ext_end = min(first_day + dt.timedelta(days=EXT_DAYS), HARD_STOP)
    if os.path.exists(lock):
        raise SystemExit("the analysis already ran (%s); a re-run needs a recorded deviation and a Director decision" % lock)
    res = run(a.schedule, max_paired=mx, level=97.5 if a.extension else 95.0)            # two looks inflate the chance of a false PASS: the extension uses 97.5 % intervals
    if a.extension and res["nPairedDaysAvailable"] < EXT_PAIRED and dt.date.today() < ext_end:
        raise SystemExit("the extension ends at the earlier of %d paired days, %s (first analysis + %d days) and %s: %d paired days, today %s" % (EXT_PAIRED, ext_end, EXT_DAYS, HARD_STOP, res["nPairedDaysAvailable"], dt.date.today()))
    if "G2" not in res and dt.date.today() < HARD_STOP:
        raise SystemExit("only %d paired days (minimum %d) and the hard stop %s has not passed" % (res["nPairedDaysAvailable"], MIN_PAIRED, HARD_STOP))
    if "G2" not in res:
        res["verdict"] = "FAIL"
        res["note"] = "fewer than %d paired days at the hard stop: INCONCLUSIVE goes to the FAIL branch (spec section 4)" % MIN_PAIRED
    if a.extension and res.get("verdict") == "INCONCLUSIVE":
        res["verdict"] = "FAIL"
        res["note"] = "INCONCLUSIVE at the extension end counts as FAIL; the extension result decides and the first result is reported beside it (spec section 4)"
    with open(lock, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"specSha256": sha_file(SPEC), "ranAt": time.strftime("%Y-%m-%dT%H:%M:%S")}))
    with open(resfile, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({"verdict": res.get("verdict") or res["decision"]["verdict"], "nPairedDays": res.get("nPairedDays"), "directorBeforePass": res.get("directorBeforePass")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
