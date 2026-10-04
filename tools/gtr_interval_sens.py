#!/usr/bin/env python3
"""M336 step 2 (spec analyses/M336_step2_design.md rev 2): interval closure (2a) + pre-registered sensitivities (2b) + reconciliation (2c).
Read-only: writes analyses/M336_step2_result.json only. Same mask as step 1 (fuel PID, canonical-clean, distance>0), computed on the former raw/ re-exports (pre-M366); not refreshed on the originals,
fuel-PID subset only. Day-clustered percentile bootstrap (seed 42, 4000), corpus ratio-of-sums.
Offset variants carry +/-delta through gross anchors and the three charge classes by per-sample class-energy ratios (approximation: the main pipeline's
crossing-aware integration is not re-run; CLAUDE.md forbids routine reprocessing).
Usage: XT_RAW_DIR=$PWD/raw python tools/gtr_interval_sens.py [--limit N]"""
import os, sys, json, argparse
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
import numpy as np, pandas as pd
import recon_engine as RE, fuel_recon as FR, model_constants as MC
sys.path.insert(0, os.path.join(ROOT, "tools"))
from gtr_closure_diag import _norm, _raw_names

NB, SEED = 4000, 42
TQ_COL = "[VCM] Target Motor Torque (N⋅m)"


def load(raw, off):
    g = RE.load_drive(raw, off)
    if g is None:
        return None
    df = pd.read_csv(RE.BASE + raw, low_memory=False, usecols=lambda c: c in ("time", TQ_COL))
    g["tq"] = np.nan
    if TQ_COL in df.columns:
        t = pd.to_datetime(df["time"], errors="coerce")
        s = RE._ser(df, t, TQ_COL)
        if s is not None:
            gg = pd.merge_asof(g[["t"]], s.rename(columns={"v": "tq"}), on="t", direction="nearest", tolerance=pd.Timedelta("1500ms"))
            g["tq"] = gg["tq"].values
    return g


def classes(g, offset_extra=0.0):
    """per-sample charge-class energies (kWh) at offset (applied + extra); engine on = rpm>400, torque-verified regen = tq<-15."""
    P = g["V"] * (-g["I"] - (g.attrs["off"] + offset_extra)) / 1000.0
    pv = np.nan_to_num(P.values)
    chg = np.maximum(-pv, 0.0) * g["dt"].values / 3600.0
    dis = np.maximum(pv, 0.0) * g["dt"].values / 3600.0
    on = g["on_raw"]
    tqr = g["tq"].fillna(0).values < -15
    return dict(eo=chg[on & ~tqr].sum(), du=chg[on & tqr].sum(), rg=chg[~on & tqr].sum(), chg=chg.sum(), dis=dis.sum())


def run(g, m, scen="central", eta_gen=None, eta_pe=None, paux=None, anchor=True, lag=0.0, off_extra=0.0):
    g = g.copy()
    g.attrs = dict(g.attrs)
    if lag:
        ts = (g["t"] - g["t"].iloc[0]).dt.total_seconds().values
        g["flow"] = np.interp(ts - lag, ts, g["flow"].fillna(0).values, left=0.0)
    mr = m.copy()
    c0 = classes(g, 0.0)
    if off_extra:
        c1 = classes(g, off_extra)
        gg = g.attrs["off"] + off_extra
        g["Iadj"] = -g["I"] - gg
        g["Pbatt"] = g["V"] * g["Iadj"] / 1000.0
        for col, k in (("charge_eng_only_kwh", "eo"), ("charge_dual_kwh", "du"), ("charge_pure_regen_kwh", "rg"),
                       ("gross_charge_kwh", "chg"), ("gross_discharge_kwh", "dis")):
            mr[col] = float(mr[col]) * (c1[k] / c0[k] if c0[k] > 1e-9 else 1.0)
    if not anchor:
        mr["gross_discharge_kwh"] = np.nan
        mr["gross_charge_kwh"] = np.nan
    saved = (MC.ETA_GEN, MC.ETA_PE, MC.P_AUX_KW)
    try:
        if eta_gen is not None:
            MC.ETA_GEN = (eta_gen,) + saved[0][1:]
        if eta_pe is not None:
            MC.ETA_PE = (eta_pe,) + saved[1][1:]
        if paux is not None:
            MC.P_AUX_KW = (paux,) + saved[2][1:]
        pc = RE.precompute(g)
        agg, ps = RE.central_estimate_v2_persample(pc, mr, scen)
    finally:
        MC.ETA_GEN, MC.ETA_PE, MC.P_AUX_KW = saved
    return dict(km=float(m["distance_km"]), date=str(m["date"]), dt_=m["drive_type"], E_gen=agg["E_gen"], G=agg["E_gen_to_trac"],
                trac=agg["E_trac_gross"], L=float(mr["charge_eng_only_kwh"] or 0), dual=float(mr["charge_dual_kwh"] or 0),
                regen=float(mr["charge_pure_regen_kwh"] or 0))


def pool(rows):
    d = pd.DataFrame(rows)
    d["X_lo"] = d.G + d.L - d.E_gen
    d["X_hi"] = d.G + d.L + d.dual - d.E_gen
    return d


def stats(d, nb=NB, seed=SEED):
    """corpus ratio-of-sums + day-clustered bootstrap CIs (vectorised over per-day sums)."""
    cols = ["km", "E_gen", "G", "trac", "L", "dual", "regen", "X_lo", "X_hi"]
    day = d.groupby("date")[cols].sum()
    A = day.values
    n = len(A)
    rng = np.random.default_rng(seed)
    cnt = np.stack([np.bincount(rng.integers(0, n, n), minlength=n) for _ in range(nb)])
    S = cnt @ A
    ci = {c: S[:, i] for i, c in enumerate(cols)}

    def est(c):
        return float(day[c].sum())

    def f(num, den):
        e = est(num) / est(den)
        r = ci[num] / ci[den]
        return {"est": round(e, 4), "ci95": [round(float(np.percentile(r, 2.5)), 4), round(float(np.percentile(r, 97.5)), 4)]}

    al = (ci["E_gen"] - ci["G"] - ci["L"]) / np.where(ci["dual"] > 0, ci["dual"], np.nan)
    a0 = (est("E_gen") - est("G") - est("L")) / est("dual")
    out = {"f_gen": f("G", "trac"), "G_per100": round(est("G") / est("km") * 100, 3), "trac_per100": round(est("trac") / est("km") * 100, 3),
           "E_gen_per100": round(est("E_gen") / est("km") * 100, 3),
           "X_lo_rel": f("X_lo", "E_gen"), "X_hi_rel": f("X_hi", "E_gen"),
           "alpha_star": {"est": round(a0, 3), "ci95": [round(float(np.nanpercentile(al, 2.5)), 3), round(float(np.nanpercentile(al, 97.5)), 3)]}}
    out["zero_in_X_pointwise"] = bool(out["X_lo_rel"]["est"] <= 0.05 and out["X_hi_rel"]["est"] >= -0.05)
    out["zero_in_X_ci"] = bool(out["X_lo_rel"]["ci95"][0] <= 0.05 and out["X_hi_rel"]["ci95"][1] >= -0.05)
    out["f_gen_ci_contains_0p5"] = bool(out["f_gen"]["ci95"][0] <= 0.5 <= out["f_gen"]["ci95"][1])
    out["f_gen_point_vs_0p5"] = "below" if out["f_gen"]["est"] < 0.5 else "above"
    a_d = (d.E_gen - d.G - d.L) / d.dual.replace(0, np.nan)
    out["n_infeasible_alpha_drives"] = int(((a_d < 0) | (a_d > 1)).sum())
    out["n_drives_dual_zero"] = int((d.dual <= 0).sum())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"))
    names = _raw_names()
    drives = []
    excluded_no_battery = []
    for _, m in dm.iterrows():
        raw = names.get(_norm(m["file"]))
        if raw is None or str(m.get("ens_outlier_v2")) == "True" or not (float(m["distance_km"]) > 0):
            continue
        if not FR._has_fuel(RE.BASE + raw):
            continue
        if pd.isna(m.get("I_offset_A_applied")) or pd.isna(m.get("charge_eng_only_kwh")) or pd.isna(m.get("charge_dual_kwh")):
            excluded_no_battery.append(m["file"])   # M336 audit: NaN offset => zero battery power in the published recon (f_gen=1.0 by construction)
            continue
        off = float(m.get("I_offset_A_applied", 0.0) or 0.0)
        g = load(raw, off)
        if g is None:
            continue
        g.attrs["off"] = off
        g["on_raw"] = (g["rpm"].fillna(0) > 400).values
        drives.append((g, m))
        if a.limit and len(drives) >= a.limit:
            break
    sample_dt = float(np.median(np.concatenate([g["dt"].values[g["dt"].values > 0] for g, _ in drives])))
    V = {"baseline": {}, "bsfc_x0.94": {"scen": "optimistic"}, "bsfc_x1.09": {"scen": "conservative"},
         "eta_gen_0.93": {"eta_gen": 0.93}, "eta_gen_0.97": {"eta_gen": 0.97}, "eta_pe_0.96": {"eta_pe": 0.96}, "eta_pe_0.99": {"eta_pe": 0.99},
         "paux_0.2": {"paux": 0.2}, "paux_1.2": {"paux": 1.2}, "paux_0_nonphysical_bound": {"paux": 0.0}, "anchor_off": {"anchor": False},
         "lag_-5s": {"lag": -5.0}, "lag_-2s": {"lag": -2.0}, "lag_+2s": {"lag": 2.0}, "lag_+5s": {"lag": 5.0},
         "offset_-1A": {"off_extra": -1.0}, "offset_+1A": {"off_extra": 1.0},
         "lag_-5s_anchor_off": {"lag": -5.0, "anchor": False}, "lag_+5s_anchor_off": {"lag": 5.0, "anchor": False},
         "offset_-1A_anchor_off": {"off_extra": -1.0, "anchor": False}, "offset_+1A_anchor_off": {"off_extra": 1.0, "anchor": False},
         "corner_high_G": {"scen": "optimistic", "eta_gen": 0.97, "eta_pe": 0.99, "paux": 0.2},
         "corner_low_G": {"scen": "conservative", "eta_gen": 0.93, "eta_pe": 0.96, "paux": 1.2}}
    res = {"milestone": "M336", "step": 2, "scope": "fuel-PID subset only; computed on the former raw/ re-exports (pre-M366); not refreshed on the originals", "n_drives": len(drives), "excluded_no_battery_inputs": excluded_no_battery,
           "logger_median_dt_s": round(sample_dt, 3), "variants": {}, "strata": {}}
    base_rows = None
    for name, kw in V.items():
        d = pool([run(g, m, **kw) for g, m in drives])
        res["variants"][name] = stats(d)
        if name == "baseline":
            base_rows = d
            res["n_days"] = int(d.date.nunique())
            res["km"] = round(float(d.km.sum()), 1)
        print(name, res["variants"][name]["f_gen"], res["variants"][name]["alpha_star"]["est"], flush=True)
    for t, g in base_rows.groupby("dt_"):
        nd = int(g.date.nunique())
        res["strata"][t] = {"n_drives": int(len(g)), "n_days": nd, **(stats(g) if nd >= 10 else {"note": "<10 distinct days: not evaluable"})}
    # per-sample generator share inside dual samples (baseline)
    num = den = 0.0
    npos = ntot = 0
    for g, m in drives:
        pc = RE.precompute(g)
        agg, ps = RE.central_estimate_v2_persample(pc, m, "central")
        P = np.nan_to_num(g["Pbatt"].values)
        chg = np.maximum(-P, 0.0)
        dtv = ps["dt"]
        dual = g["on_raw"] & (g["tq"].fillna(0).values < -15) & (chg > 0)
        num += float(np.sum(np.minimum(ps["Pgen_t"][dual], chg[dual]) * dtv[dual]))
        den += float(np.sum(chg[dual] * dtv[dual]))
        npos += int(np.sum(ps["Pgen_t"][dual] > 0))
        ntot += int(dual.sum())
    res["dual_samples"] = {"gen_feasible_share_of_charge_energy": round(num / den, 4) if den > 0 else None,
                           "share_samples_with_Pgen_gt_0": round(npos / ntot, 4) if ntot else None, "n_samples": ntot}
    # per-drive lag descriptor: best lag (s, -10..10, 1 s grid) of corr(flow, rpm) (descriptive only)
    best = []
    for g, m in drives:
        ts = (g["t"] - g["t"].iloc[0]).dt.total_seconds().values
        if ts[-1] < 120:
            continue
        grid = np.arange(0, ts[-1], 1.0)
        fl = np.interp(grid, ts, g["flow"].fillna(0).values)
        rp = np.interp(grid, ts, g["rpm"].fillna(0).values)
        if fl.std() < 1e-9 or rp.std() < 1e-9:
            continue
        cs = {k: np.corrcoef(fl[max(0, -k):len(fl) - max(0, k)], rp[max(0, k):len(rp) - max(0, -k)])[0, 1] for k in range(-10, 11)}
        best.append(max(cs, key=lambda k: cs[k]))
    res["lag_descriptor_flow_vs_rpm_s"] = {"n": len(best), "median": float(np.median(best)),
                                           "p25_p75": [float(np.percentile(best, 25)), float(np.percentile(best, 75))]}
    # 2c: reconciliation (sensitivity only, circular weights): remove the upper-branch excess, share allocated to G by variance
    d = base_rows
    ex = float((d.G + d.L + d.dual - d.E_gen).sum())
    wG, wB = float(d.G.var()), float((d.L + d.dual).var())
    shareG = wG / (wG + wB) if (wG + wB) > 0 else 0.5
    res["reconciliation_2c"] = {"note": "circular weights (variance of the same data): sensitivity only, never primary",
                                "share_of_adjustment_on_G": round(shareG, 3),
                                "implied_f_gen": round((float(d.G.sum()) - shareG * ex) / float(d.trac.sum()), 4),
                                "baseline_f_gen": res["variants"]["baseline"]["f_gen"]["est"]}
    b = res["variants"]["baseline"]
    flags = {k: {"point_crosses_0.5": v["f_gen_point_vs_0p5"] != b["f_gen_point_vs_0p5"],
                 "ci_newly_contains_0.5": bool(v["f_gen_ci_contains_0p5"] and not b["f_gen_ci_contains_0p5"])} for k, v in res["variants"].items()}
    res["stop_condition_flags"] = flags
    res["stop_triggered"] = any(x["point_crosses_0.5"] or x["ci_newly_contains_0.5"] for x in flags.values())
    with open(os.path.join(ROOT, "analyses", "M336_step2_result.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("stop_triggered", res["stop_triggered"])


if __name__ == "__main__":
    main()
