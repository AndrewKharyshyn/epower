#!/usr/bin/env python3
"""M441 study driver (spec analyses/M441_spec.md Rev 2.1): writes analyses/M441_result.json = base run of the interval extractor v2 (all cohorts) + the legacy-versus-v2 comparison (published legacy bins, M440 MB fixes,
ordered bridge) + sensitivities (I/V lag +-1 s, 2 s ceiling) + the cadence-invariance study (B6/R1/R6: per-channel decimation of fast-cadence drives, both phases, paired day-clustered differences, common-support variant).
Usage: python tools/m441_study.py [--out analyses/M441_result.json]    Every number is computed here from the cache arrays and the master; nothing is typed."""
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

VIEW_DECISION = [("temperature", "allSoc"), ("speed", "allSoc")]


def legacy_block(A, res_all):
    """Published legacy bins beside the v2 cells of the same bins (the legacy is a reproduction anchor, not a target)."""
    temp = {}
    v2t = res_all["views"]["temperature"]["noSocCondition"]
    br = res_all["bridge"]
    for r in A["regenByTempMeasured"]:
        lab = r["label"]
        if r["n"] == 0 and lab not in v2t:
            continue
        v = v2t.get(lab, {})
        temp[lab] = {"legacy": {"n": r["n"], "eff": r["eff"], "massRange": r.get("effRangeMassUncertainty"), "valid": r.get("valid")},
                     "bridge": {k: {"n": b["byTemperature"].get(lab, {}).get("n"), "eff": b["byTemperature"].get(lab, {}).get("eff")} for k, b in br.items() if k != "S5_instantaneousBinning"},
                     "v2": {"n": v.get("n"), "eff": v.get("eff"), "ci95": v.get("ci95"), "status": v.get("status")}}
    speed = {}
    ve = res_all["views"]["speedEnd"]["noSocCondition"]; vi = res_all["views"]["speed"]["noSocCondition"]
    for mid, eff, n in A["regenCaptureMeasured"]:
        lab = "%d-%d" % (int(mid) - 5, int(mid) + 5)
        speed[lab] = {"legacy": {"n": n, "eff": eff}, "bridge": {k: {"n": b["bySpeed"].get(lab, {}).get("n"), "eff": b["bySpeed"].get(lab, {}).get("eff")} for k, b in br.items() if k not in ("S5_instantaneousBinning",)},
                      "v2EndSpeed": {"n": ve.get(lab, {}).get("n"), "eff": ve.get(lab, {}).get("eff")}, "v2Instantaneous": {"n": vi.get(lab, {}).get("n"), "eff": vi.get(lab, {}).get("eff"), "ci95": vi.get(lab, {}).get("ci95"), "status": vi.get(lab, {}).get("status")}}
    mb = {}
    try:
        M = json.load(open("analyses/M440_result.json", encoding="utf-8"))
        va = M["cohorts"]["all"]["variants"]["VCa_combined"]
        mb = {"note": "stage MB variant VCa (RPM known + contiguous rows + ages <= 5 s + full probes + start-speed binning on the speed view) on the legacy extractor; step S1 of the bridge",
              "temperature": {k: {"n": r["n"], "eff": r["eff"], "delta": r["delta"]} for k, r in va["temp"].items()}, "speedStart": {k: {"n": r["n"], "eff": r["eff"], "delta": r["delta"]} for k, r in va["speed"].items()}}
    except Exception as e:                                                 # the file is part of the repo; absence is reported, not hidden
        mb = {"error": str(e)}
    return {"temperature": temp, "speed": speed, "stageMB_S1": mb,
            "bridgeNote": "S0 = published legacy; S1 = stage MB fixes on the legacy extractor; S2 = v2 intervals, strict drops only, end speed > 0, END-speed bins; S3 = + intervals ending at standstill; S4 = + inner plateaus (KE 0, charge kept); S5 = + instantaneous-speed binning (the v2 primary table). "
                          "S2-S5 are masks over the v2 intervals; they are not a decomposition into independent effects (the steps interact) and not corrections."}


def compact(res_all):
    t = res_all["views"]["temperature"]["allSoc"]; s = res_all["views"]["speed"]["allSoc"]
    return {"total": {k: res_all["totals"].get(k) for k in ("n", "eff", "effOffset")}, "temperature": {k: {"n": v.get("n"), "eff": v.get("eff")} for k, v in t.items() if v.get("n")},
            "speed": {k: {"n": v.get("n"), "eff": v.get("eff")} for k, v in s.items() if v.get("n")}}


def sensitivities(base_all, workers):
    out = {"note": "sensitivity of the v2 estimate to declared conventions: I/V time shifted by +1 s / -1 s (BMS versus speed polling lag) and a 2 s ceiling on the speed interval and on the I/V bracket gap; differences are ranges over conventions, not confidence intervals"}
    b = compact(base_all)
    for name in ("lagP1", "lagM1", "ceil2"):
        r, _ = G.run(variant=name, cohorts=("all",), workers=workers)
        c = compact(r["cohorts"]["all"])
        d = {"total": {"n": c["total"]["n"], "eff": c["total"]["eff"], "delta": None if c["total"]["eff"] is None else round(c["total"]["eff"] - b["total"]["eff"], 2)}, "temperature": {}, "speed": {}}
        for view in ("temperature", "speed"):
            for lab, v in c[view].items():
                bb = b[view].get(lab)
                d[view][lab] = {"n": v["n"], "eff": v["eff"], "delta": None if (bb is None or v["eff"] is None or bb["eff"] is None) else round(v["eff"] - bb["eff"], 2)}
        out[name] = d
    return out


def common_support_mask(Tfull, Tdec):
    """Rows of Tfull whose mid-point lies inside a kept (non-trimmed) interval of Tdec, and the converse. Time is relative to each drive's first sample, so a composite drive*1e6 + t key is used."""
    def spans(T):
        m = ~T["iv_trimmed"]
        k0 = T["drive"][m].astype(np.float64) * 1e6 + T["iv_t0"][m]
        o = np.argsort(k0); return k0[o], (k0 + T["iv_dt"][m])[o]
    def inside(T, k0, k1):
        mid = T["drive"].astype(np.float64) * 1e6 + T["iv_t0"] + T["iv_dt"] / 2.0
        i = np.searchsorted(k0, mid, side="right") - 1
        return (i >= 0) & (mid <= k1[np.clip(i, 0, None)])
    f0, f1 = spans(Tfull); d0, d1 = spans(Tdec)
    return inside(Tfull, d0, d1), inside(Tdec, f0, f1)


def paired_draws(co_a, co_b, view, sel, mask_a=None, mask_b=None):
    """Draw-level paired difference of the pooled ratio (a minus b, percentage points) per cell, plus the point values."""
    ma, labels = co_a.mats(view); mb, _ = co_b.mats(view)
    ka = co_a.sel[sel] if mask_a is None else (co_a.sel[sel] & mask_a)
    kb = co_b.sel[sel] if mask_b is None else (co_b.sel[sel] & mask_b)
    Ca, _, Ka = co_a.sums(ma, ka)[:3]; Cb, _, Kb = co_b.sums(mb, kb)[:3]
    out = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        ra = 100.0 * (co_a.counts @ Ca) / (co_a.counts @ Ka); rb = 100.0 * (co_b.counts @ Cb) / (co_b.counts @ Kb)
        pa = 100.0 * Ca.sum(0) / Ka.sum(0); pb = 100.0 * Cb.sum(0) / Kb.sum(0)
    return labels, ra - rb, pa - pb, (Ca, Ka)


def decimation_study(dm, reg, workers):
    fast = (dm["ev_rpm_dt_med_s"] < 1.0).values
    files = list(dm["file"])
    A = json.load(open("summary_arrays.json", encoding="utf-8")); i_off = float(A["offsetUncertainty"]["pointEstimateA"])
    Tfull, _ = K.load(files, "base")
    stats = {}
    Tdec = {}
    for ph, v in ((0, "dec0"), (1, "dec1")):
        stats[v] = {k: val for k, val in K.ensure(files, i_off, variant=v, workers=workers).items() if k not in ("rawSha", "codeHashes")}
        Tdec[ph], _ = K.load(files, v)
    co_full = G.Cohort(Tfull, dm, fast, "fast-full")
    days = list(co_full.days)
    out = {"nFastDrives": int(fast.sum()), "nDays": len(days), "extraction": stats,
           "rule": "per cell: the paired difference (full minus decimated), mean of the two phases, with a day-clustered 95 % interval from the same resamples; a cell FAILS cadence invariance if the interval excludes zero AND |difference| exceeds the half-width of the cell's assumed-mass range; "
                   "if any SUPPORTED cell (full-run fast subset) of a decision view (temperature all-SOC, speed all-SOC, SOC-band totals) fails, stage ME is blocked until the Director rules; other cells are reported only",
           "views": {}, "commonSupport": {}}
    views = [("temperature", "allSoc"), ("speed", "allSoc")] + [("all", s) for s in G.SOC_SELS[2:-1]]
    variants = {"allIntervals": None, "commonSupport": "cs"}
    for vname, mode in variants.items():
        blk = {}
        for view, sel in views:
            diffs, points, labels = [], [], None
            for ph in (0, 1):
                if mode == "cs":
                    mfull, mdec = common_support_mask(Tfull, Tdec[ph])
                    ca = G.Cohort(Tfull, dm, fast, "f", days=days, row_mask=mfull); cb = G.Cohort(Tdec[ph], dm, fast, "d", days=days, row_mask=mdec)
                else:
                    ca = co_full if ph == 0 else ca
                    cb = G.Cohort(Tdec[ph], dm, fast, "d", days=days)
                labels, dd, pp, _ = paired_draws(ca, cb, view, sel)
                diffs.append(dd); points.append(pp)
            dmean = (diffs[0] + diffs[1]) / 2.0; pmean = (points[0] + points[1]) / 2.0
            cells = {}
            base_cells = co_full.cell_block(view, co_full.sel[sel]) if view != "all" else co_full.cell_block("all", co_full.sel[sel])
            for j, lab in enumerate(labels):
                bc = base_cells.get(lab, {})
                if not bc.get("n"):
                    continue
                fin = np.isfinite(dmean[:, j])
                ci = [round(float(np.percentile(dmean[fin, j], 2.5)), 3), round(float(np.percentile(dmean[fin, j], 97.5)), 3)] if fin.mean() >= 1 - G.UNID_MAX else None
                hw = (bc["massRange"][1] - bc["massRange"][0]) / 2.0 if bc.get("massRange") else None
                pt = float(pmean[j]) if np.isfinite(pmean[j]) else None
                fails = bool(ci is not None and pt is not None and hw is not None and (ci[0] > 0 or ci[1] < 0) and abs(pt) > hw)
                cells[lab] = {"fullEff": bc.get("eff"), "n": bc.get("n"), "status": bc.get("status"), "diffPp": None if pt is None else round(pt, 3), "phase0": None if not np.isfinite(points[0][j]) else round(float(points[0][j]), 3),
                              "phase1": None if not np.isfinite(points[1][j]) else round(float(points[1][j]), 3), "ci95": ci, "massHalfWidth": None if hw is None else round(hw, 2), "failsInvariance": fails}
            blk["%s|%s" % (view, sel)] = cells
        out["views" if mode is None else "commonSupport"] = blk
    # diagnostic (not a decision view): where does the residual sit? Same paired design on the TOTAL under three populations: strict-drop intervals only; the estimator population (kept = strict + inner plateaus); every interval inside an episode (kept + trimmed plateaus)
    diag = {}
    cds = [G.Cohort(Tdec[ph], dm, fast, "d", days=days) for ph in (0, 1)]
    for pop in ("strictOnly", "kept", "keptPlusTrimmed"):
        def setpop(co, pop=pop):
            n = len(co.drive)
            co.est = (np.ones(n, bool) if pop == "keptPlusTrimmed" else ~co.d["iv_trimmed"]); co.strict = (~co.d["iv_plateau"]) & (co.est if pop != "keptPlusTrimmed" else np.ones(n, bool))
            if pop == "strictOnly":
                co.est = co.est & ~co.d["iv_plateau"]
        saved = [(c.est, c.strict) for c in [co_full] + cds]
        for c in [co_full] + cds:
            setpop(c)
        pts, dd = [], []
        for ph in (0, 1):
            _, d_, p_, (Ca, Ka) = paired_draws(co_full, cds[ph], "all", "noSocCondition")
            pts.append(float(p_[0])); dd.append(d_[:, 0])
        dm_ = (dd[0] + dd[1]) / 2.0
        fin = np.isfinite(dm_)
        full_eff = 100.0 * float(co_full.sums(co_full.mats("all")[0], co_full.sel["noSocCondition"])[0].sum() / co_full.sums(co_full.mats("all")[0], co_full.sel["noSocCondition"])[2].sum())
        diag[pop] = {"fullEff": round(full_eff, 2), "diffPpPhase0": round(pts[0], 3), "diffPpPhase1": round(pts[1], 3), "diffPpMean": round((pts[0] + pts[1]) / 2, 3),
                     "ci95": [round(float(np.percentile(dm_[fin], 2.5)), 3), round(float(np.percentile(dm_[fin], 97.5)), 3)] if fin.mean() >= 1 - G.UNID_MAX else None}
        for c, (e_, s_) in zip([co_full] + cds, saved):
            c.est, c.strict = e_, s_
    out["plateauDiagnostic"] = {"note": "paired full-minus-half-rate difference of the pooled ratio on the fast-cadence drives under three interval populations; a difference that appears only when plateau intervals are included points at the plateau / episode rule, not at the interpolation", "populations": diag}
    fails = [(k, lab) for k, c in out["views"].items() for lab, v in c.items() if v["failsInvariance"] and v["status"] == "supported"]
    out["decision"] = {"supportedCellsFailing": [list(x) for x in fails], "nSupportedCells": int(sum(1 for c in out["views"].values() for v in c.values() if v["status"] == "supported")),
                       "blocksStageME": bool(fails)}
    return out


def main():
    t0 = time.time()
    workers = 5
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "analyses/M441_result.json"
    dm, reg = G.load_master()
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    base, st = G.run(workers=workers)
    out = {"_provenance": {"spec": "analyses/M441_spec.md", "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "extractorVersion": R.EXTRACTOR_VERSION, "policy": R.POLICY, "policyHash": R.POLICY_HASH,
                           "codeHashes": st["codeHashes"], "offsetA": float(A["offsetUncertainty"]["pointEstimateA"]), "bootstrap": {"B": G.B_DRAWS, "seed": G.SEED, "cluster": "calendar day"},
                           "socEdges": G.SOC_EDGES, "support": {"minStrictIntervals": G.MIN_N, "minDrives": G.MIN_DRIVES, "minDays": G.MIN_DAYS},
                           "label": "raw/ = sha256-verified originals (M366); apparent battery-side KE recovery with assumed masses (observed, not SOC-standardized); interval-based extractor v2; not a correction of the legacy values"},
           "extraction": base["extraction"], "cohorts": base["cohorts"], "sensitivityEnsClean": base.get("sensitivityEnsClean")}
    out["legacyComparison"] = legacy_block(A, base["cohorts"]["all"])
    out["sensitivities"] = sensitivities(base["cohorts"]["all"], workers)
    out["cadenceInvariance"] = decimation_study(dm, reg, workers)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(json.dumps({"seconds": round(time.time() - t0), "decision": out["cadenceInvariance"]["decision"]}))


if __name__ == "__main__":
    main()
