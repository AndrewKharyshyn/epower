#!/usr/bin/env python3
"""M336 step 1 (spec analyses/M336_gtr_repair_spec.md rev 2): read-only generator-node closure diagnostic.
Writes analyses/M336_closure_diag.json and analyses/M336_closure_perdrive.csv only; never touches drive_master.csv or fuel_recon_master.csv.
Per fuel-instrumented, canonical-clean drive (ens_outlier_v2 == False, distance > 0) re-runs recon_engine.central_estimate_v2_persample and reports,
on ONE common mask, ratio-of-sums totals (kWh/100 km) and day-clustered percentile-bootstrap CIs (seed 42, 4000 draws).
Provenance: reads raw/ via XT_RAW_DIR exactly as fuel_recon.py does (F03: 333/489 raw/ copies are lower-precision re-exports; this is the published-pipeline basis).
Usage: XT_RAW_DIR=$PWD/raw python tools/gtr_closure_diag.py [--limit N]"""
import os, sys, json, argparse
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
import numpy as np, pandas as pd
import recon_engine as RE
import fuel_recon as FR

NB, SEED = 4000, 42

def _norm(fn):
    import re
    m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})[ _](\d{2})-?(\d{2})-?(\d{2})\.csv$", fn)
    return "%s%s%s_%s%s%s.csv" % m.groups() if m else fn

def _raw_names():
    """canonical master key (YYYYMMDD_HHMMSS.csv) -> on-disk file name in raw/ (separators vary: spaces, dashes, underscores)."""
    import re
    out = {}
    for fn in os.listdir(os.path.join(ROOT, "raw")):
        m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})[ _](\d{2})-?(\d{2})-?(\d{2})\.csv$", fn)
        if m: out["%s%s%s_%s%s%s.csv" % m.groups()] = fn
    return out

def per_drive(f, mrow, raw):
    off = float(mrow.get("I_offset_A_applied", 0.0) or 0.0)
    g = RE.load_drive(raw, off)
    if g is None: return None
    pc = RE.precompute(g)
    agg, ps = RE.central_estimate_v2_persample(pc, mrow, "central")
    dt = ps["dt"]; Pg = ps["Pgen_t"]
    E_gen_ps = float(np.sum(Pg * dt) / 3600.0)
    eo = float(mrow.get("charge_eng_only_kwh", 0) or 0); du = float(mrow.get("charge_dual_kwh", 0) or 0)
    rg = float(mrow.get("charge_pure_regen_kwh", 0) or 0)
    dist = float(mrow["distance_km"])
    return dict(file=f, date=str(mrow["date"]), drive_type=mrow["drive_type"], km=dist,
                E_gen=agg["E_gen"], E_gen_ps=E_gen_ps, g2t=agg["E_gen_to_trac"], trac=agg["E_trac_gross"], b2t=agg["E_batt_to_trac"],
                eng_only=eo, dual=du, regen=rg, gross_chg=float(mrow.get("gross_charge_kwh", np.nan)),
                soc_start=float(mrow.get("soc_start", np.nan)), soc_end=float(mrow.get("soc_end", np.nan)))

def ratio(d, num, den="km", scale=100.0):
    return float(d[num].sum() / d[den].sum() * scale)

def dayboot(d, fn, nb=NB, seed=SEED):
    days = d["date"].unique(); idx = {k: g for k, g in d.groupby("date")}
    rng = np.random.default_rng(seed); out = []
    for _ in range(nb):
        pick = rng.choice(len(days), len(days))
        out.append(fn(pd.concat([idx[days[i]] for i in pick])))
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0); a = ap.parse_args()
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"))
    names = _raw_names()
    rows, skipped = [], {"no_file": 0, "no_fuel": 0, "outlier": 0, "none": 0}
    for _, m in dm.iterrows():
        f = m["file"]
        raw = names.get(_norm(f))
        if raw is None or not os.path.exists(RE.BASE + raw): skipped["no_file"] += 1; continue
        if m.get("ens_outlier_v2") is True or str(m.get("ens_outlier_v2")) == "True" or not (float(m["distance_km"]) > 0): skipped["outlier"] += 1; continue
        if not FR._has_fuel(RE.BASE + raw): skipped["no_fuel"] += 1; continue
        r = per_drive(f, m, raw)
        if r is None: skipped["none"] += 1; continue
        rows.append(r)
        if a.limit and len(rows) >= a.limit: break
    d = pd.DataFrame(rows)
    d["g2b_master"] = d.eng_only + d.dual
    d["g2b_model"] = d.E_gen_ps - d.g2t            # closes by construction (diagnostic only)
    d["excess"] = d.g2t + d.g2b_master - d.E_gen   # F04 quantity (spec definition: master charge columns)
    d["excess_engonly"] = d.g2t + d.eng_only - d.E_gen   # H1 variant: dual (engine-on torque-verified regen) removed from the generator branch
    d["gen_def_gap"] = d.E_gen_ps - d.E_gen        # H4: regime-volume vs per-sample node
    d["excess_ps"] = d.g2t + d.g2b_master - d.E_gen_ps
    d["batt_in"] = d.g2b_master + d.regen
    d["batt_resid"] = d.batt_in - d.b2t
    d["batt_resid_modelg2b"] = d.g2b_model + d.regen - d.b2t
    d.round(5).to_csv(os.path.join(ROOT, "analyses", "M336_closure_perdrive.csv"), index=False, lineterminator="\n")
    tot = {c: ratio(d, c) for c in ["E_gen", "E_gen_ps", "g2t", "g2b_master", "g2b_model", "eng_only", "dual", "regen", "b2t", "trac",
                                    "excess", "excess_engonly", "excess_ps", "gen_def_gap", "batt_resid", "batt_resid_modelg2b"]}
    rel = lambda x: float(x.excess.sum() / x.E_gen.sum())
    relv = {"excess": rel, "excess_engonly": lambda x: float(x.excess_engonly.sum() / x.E_gen.sum()),
            "excess_ps": lambda x: float(x.excess_ps.sum() / x.E_gen_ps.sum()),
            "gen_def_gap": lambda x: float(x.gen_def_gap.sum() / x.E_gen.sum())}
    res = {"milestone": "M336", "step": 1, "basis": "raw/ via XT_RAW_DIR (F03: lower-precision re-exports; published-pipeline basis); canonical-clean (ens_outlier_v2 False), distance>0, fuel PID",
           "n_drives": int(len(d)), "n_days": int(d.date.nunique()), "km": float(d.km.sum()), "skipped": skipped,
           "per100km_totals": {k: round(v, 3) for k, v in tot.items()},
           "relative_to_generator": {}, "closure_rule": "95% day-clustered CI of excess/E_gen inside +/-5% overall and per drive-type stratum with n>=10",
           "strata": {}}
    for k, fn in relv.items():
        ci = dayboot(d, fn); est = fn(d)
        res["relative_to_generator"][k] = {"est": round(est, 4), "ci95": [round(ci[0], 4), round(ci[1], 4)], "closed": bool(ci[0] >= -0.05 and ci[1] <= 0.05)}
    for t, g in d.groupby("drive_type"):
        s = {"n": int(len(g)), "days": int(g.date.nunique())}
        if len(g) >= 10:
            ci = dayboot(g, rel); s["excess_rel"] = {"est": round(rel(g), 4), "ci95": [round(ci[0], 4), round(ci[1], 4)], "closed": bool(ci[0] >= -0.05 and ci[1] <= 0.05)}
        else:
            s["excess_rel"] = "n<10: not evaluated"
        res["strata"][t] = s
    dd = d.assign(dual_share=d.dual / d.g2b_master.replace(0, np.nan), gen_per_km=d.E_gen / d.km)
    cols = ["excess", "dual_share", "gen_per_km", "gen_def_gap"]
    res["exploratory_corr_with_excess_per_km"] = {c: round(float(np.corrcoef((dd.excess / dd.km).fillna(0), (dd[c] / (dd.km if c in ("excess", "gen_def_gap") else 1)).fillna(0))[0, 1]), 3) for c in cols[1:]}
    res["share_drives_excess_positive"] = round(float((d.excess > 0).mean()), 3)
    res["share_dual_in_g2b_master"] = round(float(d.dual.sum() / d.g2b_master.sum()), 4)
    with open(os.path.join(ROOT, "analyses", "M336_closure_diag.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False); fh.write("\n")
    print(json.dumps({k: res[k] for k in ("n_drives", "n_days", "per100km_totals", "relative_to_generator", "strata", "share_dual_in_g2b_master")}, indent=1))

if __name__ == "__main__":
    main()
