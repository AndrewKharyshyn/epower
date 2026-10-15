#!/usr/bin/env python3
"""M442 gate driver (spec analyses/M442_spec.md Rev 1.2): the harmonized estimator (primary = interp3: speed, I and V interpolated to a common 3 s grid, four phases), the resolution bracket b and the gates G1-G3.
  --dev       odd calendar days only (development, NOT counted toward any gate); H1-form invariance report; writes analyses/M442_dev.json
  --confirm   run ONCE (lock file analyses/M442_confirm.lock; a re-run needs --rerun-deviation "<reason>" and writes a separate file): H1/H2 (reported, non-blocking), bracket b on all fast days, G1, G2 (H3 with tolerance b + mass
              half-width), G3 (out-of-support KE), the adjacent-bin contrasts (resolved / not resolved) and the sensitivities (last3, box3, native v2). Refuses to run unless CHANGELOG.md carries "M442 spec sha256 <hash>" of the frozen spec.
Every number is computed here from the cache arrays; nothing is typed."""
import hashlib, json, os, sys, time
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import regen_v2 as R
import regen_v2_cache as K
import regen_v2_agg as G
import m441_study as S

DELTA = 3.0
PH = [0, 1, 2, 3]
HARM = ["l3p%d" % k for k in PH]                                                           # primary: interp3
DEC_H = {f: ["d%dp%dl3p%d" % (f, q, k) for q in range(f) for k in PH] for f in (2, 3)}
DEC_V2 = {f: ["d%dp%d" % (f, q) for q in range(f)] for f in (2, 3)}                         # native v2 at 1/f of the native rate
LAST3 = ["h3p%d" % k for k in PH]
VIEWS = [("temperature", "allSoc"), ("speed", "allSoc")] + [("all", s) for s in G.SOC_SELS[2:-1]]
SPEC = "analyses/M442_spec.md"


def spec_sha():
    return hashlib.sha256(open(SPEC, "rb").read()).hexdigest()


def frozen_ok():
    return ("M442 spec sha256 " + spec_sha()) in open("CHANGELOG.md", encoding="utf-8").read(60000)


def tables(files, variants, workers=5):
    A = json.load(open("summary_arrays.json", encoding="utf-8")); i_off = float(A["offsetUncertainty"]["pointEstimateA"])
    for v in variants:
        K.ensure(files, i_off, variant=v, workers=workers)
    return K.load_stack(files, variants)[0] if len(variants) > 1 else K.load(files, variants[0])[0]


def judge(ci, pt, hw, sup):
    """C6: fail = CI excludes 0 and |point| > half-width; indeterminate = CI contains 0 but |point| > half-width; ok otherwise (supported cells only)."""
    if not sup or ci is None or pt is None or hw is None:
        return "notTested"
    if abs(pt) > hw:
        return "fail" if (ci[0] > 0 or ci[1] < 0) else "indeterminate"
    return "ok"


def pct_ci(dr):
    fin = np.isfinite(dr)
    return [round(float(np.percentile(dr[fin], 2.5)), 3), round(float(np.percentile(dr[fin], 97.5)), 3)] if fin.mean() >= 1 - G.UNID_MAX and fin.sum() else None


def gate(dm, files, fast, days, T_nat, T_dec, label):
    """H1 form (reported, non-blocking since Rev 1.2): paired difference harmonized(native) - harmonized(decimated) per cell of the decision views on the given days; one resample matrix per day set (C5)."""
    co_a = G.Cohort(T_nat, dm, fast, "nat", days=days)
    co_b = G.Cohort(T_dec, dm, fast, "dec", days=days)
    out, fails, indet, views = {}, [], [], {}
    for view, sel in VIEWS:
        labels, dd, pp, _ = S.paired_draws(co_a, co_b, view, sel)
        base = co_a.cell_block(view, co_a.sel[sel])
        cells, n_sup, n_cells = {}, 0, 0
        for j, lab in enumerate(labels):
            bc = base.get(lab, {})
            if not bc.get("n"):
                continue
            n_cells += 1
            ci = pct_ci(dd[:, j])
            hw = (bc["massRange"][1] - bc["massRange"][0]) / 2.0 if bc.get("massRange") else None
            pt = float(pp[j]) if np.isfinite(pp[j]) else None
            sup = bc.get("status") == "supported"
            n_sup += int(sup)
            st = judge(ci, pt, hw, sup)
            cells[lab] = {"eff": bc.get("eff"), "n": bc.get("n"), "status": bc.get("status"), "diffPp": None if pt is None else round(pt, 3), "ci95": ci, "massHalfWidth": None if hw is None else round(hw, 2), "judgement": st}
            if st == "fail":
                fails.append("%s|%s|%s" % (view, sel, lab))
            if st == "indeterminate":
                indet.append("%s|%s|%s" % (view, sel, lab))
        out["%s|%s" % (view, sel)] = cells
        views["%s|%s" % (view, sel)] = {"nCells": n_cells, "nSupported": n_sup, "inconclusive": bool(n_cells == 0 or n_sup < n_cells / 2.0)}
    return {"label": label, "cells": out, "views": views, "failing": fails, "indeterminate": indet}


# ------------------------------------------------------------------------------------------------ view totals (G1) and cell series (contrasts)
def total_pair(co_a, co_b, view, sel):
    """Paired difference (a minus b, pp) of the pooled ratio summed over the cells of a view: point value, day-clustered interval, and the half-width of the assumed-mass range of a's total."""
    out = []
    for co in (co_a, co_b):
        mats, labels = co.mats(view)
        C_, _, K_ = co.sums(mats, co.sel[sel])[:3]
        out.append((C_.sum(axis=1), K_.sum(axis=1)))
    (Ca, Ka), (Cb, Kb) = out
    with np.errstate(invalid="ignore", divide="ignore"):
        d = 100.0 * (co_a.counts @ Ca) / (co_a.counts @ Ka) - 100.0 * (co_b.counts @ Cb) / (co_b.counts @ Kb)
        pt = 100.0 * Ca.sum() / Ka.sum() - 100.0 * Cb.sum() / Kb.sum()
    return float(pt), pct_ci(d), float(100.0 * Ca.sum() / Ka.sum())


def mass_hw(co, view, sel):
    """Half-width of the assumed-mass range of the pooled view total."""
    mats, labels = co.mats(view)
    C_, _, K_, Ku_ = co.sums(mats, co.sel[sel])[:4]
    c, k, ku = float(C_.sum()), float(K_.sum()), float(Ku_.sum())
    kh = k - ku
    lo, hi = 100.0 * c / (kh + ku * G.MASS_HI / 1890.0), 100.0 * c / (kh + ku * G.MASS_LO / 1890.0)
    return (hi - lo) / 2.0


def series(co, kind):
    """Ordered cells of a displayed series: list of (label, day sums of charge, day sums of KE, cell block). Temperature bins (no SOC condition), speed bins at or above 10 km/h, SOC bands."""
    out = []
    if kind == "temperature":
        mats, labels = co.mats("temperature"); sel = co.sel["noSocCondition"]
        C_, _, K_ = co.sums(mats, sel)[:3]; cb = co.cell_block("temperature", sel)
        out = [(l, C_[:, j], K_[:, j], cb.get(l, {})) for j, l in enumerate(labels)]
    elif kind == "speed":
        mats, labels = co.mats("speed"); sel = co.sel["noSocCondition"]
        C_, _, K_ = co.sums(mats, sel)[:3]; cb = co.cell_block("speed", sel)
        out = [(l, C_[:, j], K_[:, j], cb.get(l, {})) for j, l in enumerate(labels) if j >= 1]           # 0-10 km/h stays in the payload only (D5)
    else:
        mats, labels = co.mats("all")
        for band in G.SOC_SELS[2:-1]:
            if band == "below40":
                continue
            C_, _, K_ = co.sums(mats, co.sel[band])[:3]; cb = co.cell_block("all", co.sel[band])
            out.append((band, C_[:, 0], K_[:, 0], cb.get("all", {})))
    return out


def ratio(C_, K_):
    return 100.0 * C_.sum() / K_.sum() if K_.sum() > 0 else float("nan")


def contrasts(dm, T_nat, days_even, days_odd, days_all, bracket):
    """D5: adjacent supported cells A, B of each displayed series; resolved iff (i) even-day interval excludes 0, (ii) |diff| > b(A) + b(B), (iii) same sign at both mass ends, (iv) same sign on even, odd and all days."""
    allm = np.ones(len(dm), bool)
    co_e, co_o, co_a = (G.Cohort(T_nat, dm, allm, n_, days=d_) for n_, d_ in (("even", days_even), ("odd", days_odd), ("all", days_all)))
    res = {}
    for kind in ("temperature", "speed", "soc"):
        se, so, sa = series(co_e, kind), series(co_o, kind), series(co_a, kind)
        rows = []
        for i in range(len(se) - 1):
            (la, Ca, Ka, ba), (lb, Cb, Kb, bb) = se[i], se[i + 1]
            if ba.get("status") != "supported" or bb.get("status") != "supported":
                continue
            dr = 100.0 * (co_e.counts @ Cb) / (co_e.counts @ Kb) - 100.0 * (co_e.counts @ Ca) / (co_e.counts @ Ka)
            ci = pct_ci(dr)
            d_e = ratio(Cb, Kb) - ratio(Ca, Ka)
            d_o = ratio(so[i + 1][1], so[i + 1][2]) - ratio(so[i][1], so[i][2])
            d_a = ratio(sa[i + 1][1], sa[i + 1][2]) - ratio(sa[i][1], sa[i][2])
            lo = bb["massRange"][0] - ba["massRange"][0]; hi = bb["massRange"][1] - ba["massRange"][1]
            fb = max([v for k_, v in bracket.get(kind, {}).items() if not k_.startswith("_") and v is not None] or [None]) if bracket.get(kind) else None      # D3: a cell without fast-drive support borrows the largest b of its view
            b_ = bracket.get(kind, {}).get(la, fb), bracket.get(kind, {}).get(lb, fb)
            bsum = None if None in b_ else b_[0] + b_[1]
            sgn = lambda x: 0 if not np.isfinite(x) else (1 if x > 0 else -1)
            checks = {"intervalExcludesZero": bool(ci is not None and (ci[0] > 0 or ci[1] < 0)), "exceedsBracket": bool(bsum is not None and abs(d_e) > bsum),
                      "sameSignAtMassEnds": bool(sgn(lo) == sgn(hi) == sgn(d_e) != 0), "sameSignOnEvenOddAllDays": bool(sgn(d_e) == sgn(d_o) == sgn(d_a) != 0)}
            rows.append({"a": la, "b": lb, "diffPp": round(d_e, 3), "ci95": ci, "bracketSum": None if bsum is None else round(bsum, 3), "diffOddPp": round(d_o, 3), "diffAllPp": round(d_a, 3),
                         "massEndDiffPp": [round(lo, 3), round(hi, 3)], "checks": checks, "label": "resolved" if all(checks.values()) else "not resolved at this resolution"})
        res[kind] = rows
    return res


def brackets(dm, files, fast, fast_days, T_nat, workers):
    """D3: b(cell) = max over f in {2, 3} of |harm(native) - harm(decimated f)| on ALL fast days (point values, pp); unsupported cells take the largest b of their view's supported cells."""
    co_a = G.Cohort(T_nat, dm, fast, "nat", days=fast_days)
    diffs = {}
    for f in (2, 3):
        T_dec = tables(list(dm["file"]), DEC_H[f], workers)
        co_b = G.Cohort(T_dec, dm, fast, "dec", days=fast_days)
        for view, sel, kind in (("temperature", "noSocCondition", "temperature"), ("speed", "noSocCondition", "speed")):
            labels, dd, pp, _ = S.paired_draws(co_a, co_b, view, sel)
            for j, lab in enumerate(labels):
                if np.isfinite(pp[j]):
                    diffs.setdefault(kind, {}).setdefault(lab, []).append(abs(float(pp[j])))
        for band in G.SOC_SELS[2:-1]:
            if band == "below40":
                continue
            labels, dd, pp, _ = S.paired_draws(co_a, co_b, "all", band)
            if np.isfinite(pp[0]):
                diffs.setdefault("soc", {}).setdefault(band, []).append(abs(float(pp[0])))
    sup = {"temperature": {l for l, c in co_a.cell_block("temperature", co_a.sel["noSocCondition"]).items() if c.get("status") == "supported"},
           "speed": {l for l, c in co_a.cell_block("speed", co_a.sel["noSocCondition"]).items() if c.get("status") == "supported"},
           "soc": {b for b in G.SOC_SELS[2:-1] if b != "below40" and co_a.cell_block("all", co_a.sel[b]).get("all", {}).get("status") == "supported"}}
    b = {}
    for kind, d in diffs.items():
        own = {l: max(v) for l, v in d.items() if l in sup[kind]}
        fallback = max(own.values()) if own else None
        b[kind] = {l: (max(v) if l in sup[kind] else fallback) for l, v in d.items()}
        b[kind]["_borrowed"] = sorted(l for l in d if l not in sup[kind])
    return b


def run(mode, workers=5):
    t0 = time.time()
    dm, reg = G.load_master()
    files = list(dm["file"])
    fast = (dm["ev_rpm_dt_med_s"] < 1.0).values
    day_all = dm["date"].astype(str).str[:10].values
    parity = 1 if mode == "dev" else 0
    out = {"_provenance": {"spec": SPEC, "specSha256": spec_sha(), "mode": mode, "delta": DELTA, "phases": PH, "primary": "interp3", "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(),
                           "bootstrap": {"B": G.B_DRAWS, "seed": G.SEED}, "counts": "per-phase averages",
                           "label": ("apparent KE recovery at common sampling resolution (3 s grid, assumed mass); dev results do not count toward any gate" if mode == "dev" else "apparent KE recovery at common sampling resolution (3 s grid, assumed mass); gate run")}}
    T_nat = tables(files, HARM, workers)
    fast_days = sorted(set(day_all[fast]))
    pdays = [d for d in fast_days if int(d[8:10]) % 2 == parity]
    out["H1"] = {"days": len(pdays), "reported": True, "blocks": False, "factors": {}}
    for f in (2, 3):
        T_dec = tables(files, DEC_H[f], workers)
        out["H1"]["factors"][str(f)] = gate(dm, files, fast, pdays, T_nat, T_dec, "H1 factor %d, %s days" % (f, "even" if parity == 0 else "odd (dev)"))
    if mode != "confirm":
        out["seconds"] = round(time.time() - t0)
        return out
    out["H2"] = gate(dm, files, fast, fast_days, T_nat, tables(files, DEC_H[2], workers), "H2 factor 2, all fast days (reported)")
    out["H2"]["reported"] = True; out["H2"]["blocks"] = False
    # bracket b (all fast days)
    b = brackets(dm, files, fast, fast_days, T_nat, workers)
    out["bracket"] = {"definition": "max over f in {2,3} of |harmonized(native) - harmonized(decimated f)| (pp, point values) on all fast days; unsupported cells borrow the largest b of their view", "b": b}
    # G1: at every view total and both factors
    T_v2 = tables(files, ["base"], workers)
    co_h = G.Cohort(T_nat, dm, fast, "nat", days=pdays)
    co_n = G.Cohort(T_v2, dm, fast, "nat-v2", days=pdays)
    g1, g1_ok = {}, True
    for f in (2, 3):
        co_hd = G.Cohort(tables(files, DEC_H[f], workers), dm, fast, "dec", days=pdays)
        co_nd = G.Cohort(tables(files, DEC_V2[f], workers), dm, fast, "dec-v2", days=pdays)
        for view, sel in (("temperature", "allSoc"), ("speed", "allSoc"), ("all", "allSoc")):
            ph, cih, lvl = total_pair(co_h, co_hd, view, sel)
            pn, cin, lvl_n = total_pair(co_n, co_nd, view, sel)
            hw = mass_hw(co_h, view, sel)
            ok = bool(abs(ph) < abs(pn) or abs(ph) <= hw)
            g1_ok &= ok
            g1["factor%d|%s|%s" % (f, view, sel)] = {"harmonizedDiffPp": round(ph, 3), "harmonizedCi95": cih, "nativeV2DiffPp": round(pn, 3), "nativeV2Ci95": cin, "massHalfWidth": round(hw, 2), "ok": ok}
    out["G1"] = {"cells": g1, "pass": bool(g1_ok), "daysEven": len(pdays)}
    # G2: H3 fast versus slow, even days, tolerance b + mass half-width
    slow = ~fast & np.isfinite(dm["ev_rpm_dt_med_s"].values)
    both_all = sorted(set(day_all[fast]) & set(day_all[slow]))
    both = [d for d in both_all if int(d[8:10]) % 2 == 0]
    co_f = G.Cohort(T_nat, dm, fast, "fast", days=both); co_s = G.Cohort(T_nat, dm, slow, "slow", days=both)
    h3 = {"daysWithBoth": len(both_all), "evenDaysWithBoth": len(both), "cells": {}, "fails": []}
    for view, sel, kind in (("temperature", "noSocCondition", "temperature"), ("speed", "noSocCondition", "speed")):
        labels, dd, pp, _ = S.paired_draws(co_f, co_s, view, sel)
        bf, bs = co_f.cell_block(view, co_f.sel[sel]), co_s.cell_block(view, co_s.sel[sel])
        cells = {}
        for j, lab in enumerate(labels):
            a, c_ = bf.get(lab, {}), bs.get(lab, {})
            if a.get("status") != "supported" or c_.get("status") != "supported" or not np.isfinite(pp[j]):
                continue
            ci = pct_ci(dd[:, j])
            hw = max((a["massRange"][1] - a["massRange"][0]) / 2.0, (c_["massRange"][1] - c_["massRange"][0]) / 2.0)
            bl = b.get(kind, {}).get(lab)
            tol = None if bl is None else bl + hw
            fail = bool(ci is not None and tol is not None and (ci[0] > 0 or ci[1] < 0) and abs(pp[j]) > tol)
            cells[lab] = {"fastEff": a["eff"], "slowEff": c_["eff"], "diffPp": round(float(pp[j]), 3), "ci95": ci, "bracket": None if bl is None else round(bl, 3), "massHalfWidth": round(hw, 2), "tolerance": None if tol is None else round(tol, 3), "fails": fail}
            if fail:
                h3["fails"].append("%s|%s" % (view, lab))
        h3["cells"][view] = cells
    out["G2"] = dict(h3, **{"pass": bool(not h3["fails"]), "goesToDirectorOnFail": True})
    oos, info = G.oos_info(files, DELTA)
    out["G3"] = dict(info, **{"pass": bool(info["keShare"] <= 0.10)})
    out["outOfSupport"] = info
    # contrasts (D5) on cohort all, harmonized primary
    all_days = sorted(set(day_all))
    ev = [d for d in all_days if int(d[8:10]) % 2 == 0]; od = [d for d in all_days if int(d[8:10]) % 2 == 1]
    out["contrasts"] = contrasts(dm, T_nat, ev, od, all_days, b)
    # sensitivities: last3, box3, native v2 (cohort all, all days): totals and the displayed series
    sens = {}
    for name, var in (("interp3 (primary)", HARM), ("last3", LAST3), ("box3", ["box3"]), ("nativeV2", ["base"])):
        T_ = tables(files, var, workers)
        co = G.Cohort(T_, dm, np.ones(len(dm), bool), name, days=all_days)
        sens[name] = {kind: {l: {"eff": c.get("eff"), "n": c.get("n")} for (l, _, _, c) in series(co, kind) if c.get("n")} for kind in ("temperature", "speed", "soc")}
        sens[name]["total"] = {k_: co.cell_block("all", co.sel["noSocCondition"])["all"].get(k_) for k_ in ("eff", "ci95", "n")}
    out["sensitivities"] = {"note": "levels of the same cells under the declared reductions (cohort all, all days); a range over declared conventions, not an interval", "levels": sens}
    out["verdict"] = {"G1": "pass" if out["G1"]["pass"] else "FAILED", "G2": "pass" if out["G2"]["pass"] else "FAILED (goes to the Director)", "G3": "pass" if out["G3"]["pass"] else "FAILED (blocks ME)",
                      "stageME": "may proceed to the bootstrap-CI audit, the Director ruling and Andrii's sign-off" if (out["G1"]["pass"] and out["G2"]["pass"] and out["G3"]["pass"]) else "BLOCKED"}
    out["seconds"] = round(time.time() - t0)
    return out


def main():
    mode = "confirm" if "--confirm" in sys.argv else ("dev" if "--dev" in sys.argv else None)
    if mode is None:
        raise SystemExit("usage: m442_gate.py --dev | --confirm [--rerun-deviation \"<reason>\"]")
    if mode == "confirm" and not frozen_ok():
        raise SystemExit("refusing to run --confirm: CHANGELOG.md does not carry 'M442 spec sha256 %s' (spec section 6, safeguards)" % spec_sha())
    path = "analyses/M442_dev.json" if mode == "dev" else "analyses/M442_result.json"
    if mode == "confirm":
        if os.path.exists("analyses/M442_confirm.lock"):
            if "--rerun-deviation" not in sys.argv:
                raise SystemExit("--confirm already ran (analyses/M442_confirm.lock); a re-run needs --rerun-deviation <recorded reason> and goes to the Director (spec C9)")
            path = "analyses/M442_result_rerun.json"
        else:
            with open("analyses/M442_confirm.lock", "w", encoding="utf-8", newline=chr(10)) as f:
                f.write(json.dumps({"specSha256": spec_sha(), "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}))
    res = run(mode)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(json.dumps({"mode": mode, "seconds": res["seconds"], "verdict": res.get("verdict")}))


if __name__ == "__main__":
    main()
