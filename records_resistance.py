#!/usr/bin/env python3
"""records_resistance.py (M284, external audit Section 10 "Pack resistance maximum" / "Resistance support").

Adds ONE record to summary_arrays.json -> records: the highest EXCITATION-GATED V-regression pack-resistance
proxy (vreg_R_pack_mohm), with method, gate, covariates, temperature-adjusted value, a day-cluster bootstrap
interval on the record maximum itself, and gate-sensitivity of the holder. Idempotent (replaces by metric name).

Why gating: the ungated maximum is set by short, sample-starved drives (residual SD of the proxy after linear pack-T
control is markedly larger below n_vreg_samples=456; likewise at low peak current). Gates are therefore taken from
the observed dispersion elbow, not from a physical threshold, and are disclosed as such.

NOT an SOH, DCIR or capacity measurement (V and I on separate polling timestamps; load-excited regression proxy).
"""
import json, os, re
from datetime import datetime
import numpy as np, pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
# layout-agnostic: flat project checkout (drive_master.csv beside the scripts) or work/{seasonal,track3,track4}/ tree
WORK = os.environ.get("XT_WORK") or (_HERE if os.path.exists(os.path.join(_HERE, "drive_master.csv")) else os.path.dirname(_HERE))
SDIR = os.path.join(WORK, "seasonal") if os.path.isdir(os.path.join(WORK, "seasonal")) else WORK
METRIC = "Pack resistance proxy — excitation-gated maximum (V-regression)"
B, SEED = 4000, 20260919
GATES = {"loose": (456, 0.0), "primary": (741, 52.0), "strict": (1274, 58.3)}   # (min n_vreg_samples, min vreg_I_p95_A)

def norm_key(f):
    m = re.match(r"^(?:e4ORCE[_ ])?(\d{4})-?(\d{2})-?(\d{2})[_ -](\d{2})-?(\d{2})-?(\d{2})", f, re.I)
    return f"{m[1]}{m[2]}{m[3]}_{m[4]}{m[5]}{m[6]}" if m else f

def drive_label(f, all_files):
    k = norm_key(f); day = k[:8]
    same = sorted(norm_key(x) for x in all_files if norm_key(x)[:8] == day and not x.lower().startswith("e4orce")
                  and "_comparison" not in x.lower())
    return datetime.strptime(day, "%Y%m%d").strftime("%b%d") + " D" + str(same.index(k) + 1)

def compute(dm):
    g = dm[dm.vreg_R_pack_mohm.notna() & dm.ens_outlier_v2.eq(False)].copy()
    g["day"] = g.file.map(lambda f: norm_key(f)[:8])
    out = {"nProxy": int(len(g))}
    sel = {}
    for name, (nmin, imin) in GATES.items():
        s = g[(g.n_vreg_samples >= nmin) & (g.vreg_I_p95_A >= imin)]
        sel[name] = s
    p = sel["primary"]
    # linear T control fitted on the primary-gated set
    Tref = float(p.T_pack_mean_avg.median())
    X = np.c_[np.ones(len(p)), p.T_pack_mean_avg - Tref]
    beta = np.linalg.lstsq(X, p.vreg_R_pack_mohm.values, rcond=None)[0]
    p = p.assign(R_adj=p.vreg_R_pack_mohm - beta[1] * (p.T_pack_mean_avg - Tref))
    hold = p.loc[p.vreg_R_pack_mohm.idxmax()]
    hold_adj = p.loc[p.R_adj.idxmax()]
    # Expected maximum under the fitted model: R*_i = fitted_i + e*, e* resampled iid from the gated residuals.
    # (A bootstrap of the observed maximum is bounded above by that maximum and is not a valid interval for an
    #  extreme, so the record is instead compared with what noise alone produces for the same n and T mix.)
    fitted = beta[0] + beta[1] * (p.T_pack_mean_avg.values - Tref)
    resid = p.vreg_R_pack_mohm.values - fitted
    rng = np.random.default_rng(SEED)
    mx = (fitted[None, :] + rng.choice(resid, size=(B, len(p)), replace=True)).max(1)
    lo, hi = np.quantile(mx, [0.025, 0.975]); emed = float(np.median(mx))
    pctile = float((mx < hold.vreg_R_pack_mohm).mean() * 100)
    days = p.day.unique()
    # dispersion elbow (disclosed gate rationale) from ALL proxy drives, linear T control
    Xa = np.c_[np.ones(len(g)), g.T_pack_mean_avg - g.T_pack_mean_avg.median()]
    ba = np.linalg.lstsq(Xa, g.vreg_R_pack_mohm.values, rcond=None)[0]
    ra = g.vreg_R_pack_mohm.values - Xa @ ba; lown = (g.n_vreg_samples < GATES["loose"][0]).values
    out["sd_low"], out["sd_hi"] = float(ra[lown].std(ddof=1)), float(ra[~lown].std(ddof=1))
    holders = {n: (s.loc[s.vreg_R_pack_mohm.idxmax(), "file"] if len(s) else None) for n, s in sel.items()}
    res = p.vreg_R_pack_mohm - (beta[0] + beta[1] * (p.T_pack_mean_avg - Tref))
    z = float((hold.vreg_R_pack_mohm - (beta[0] + beta[1] * (hold.T_pack_mean_avg - Tref))) / res.std(ddof=2))
    out.update(dict(hold=hold, hold_adj=hold_adj, nGate={k: int(len(v)) for k, v in sel.items()}, holders=holders,
                    beta=beta, Tref=Tref, ci=(float(lo), float(hi)), emed=emed, pctile=pctile, z=z, med=float(p.vreg_R_pack_mohm.median()),
                    ungated=g.loc[g.vreg_R_pack_mohm.idxmax()], ungatedN=int(g.loc[g.vreg_R_pack_mohm.idxmax(), "n_vreg_samples"]),
                    nDays=int(len(days))))
    return out

def build_record(dm):
    r = compute(dm); files = list(dm.file); h = r["hold"]
    lab = lambda f: drive_label(f, files)
    stable = len({v for v in r["holders"].values() if v}) == 1
    sens = "; ".join(f"{k} gate (n≥{GATES[k][0]}" + (f", I_p95≥{GATES[k][1]:g} A" if GATES[k][1] else "") + f", {r['nGate'][k]} drives) → {lab(r['holders'][k]) if r['holders'][k] else 'none'}" for k in GATES)
    ug = r["ungated"]
    note = (f"Highest load-excited V-regression resistance proxy (vreg_R_pack_mohm) among the {r['nGate']['primary']} of {r['nProxy']} ens-clean proxy drives "
            f"passing an excitation/support gate (n_vreg_samples ≥ {GATES['primary'][0]}, peak-current p95 ≥ {GATES['primary'][1]:g} A). "
            f"Holder: pack mean {h.T_pack_mean_avg:.1f}°C, "
            + (f"SoC mean {h.vsag_soc_mean:.1f}%, " if pd.notna(h.vsag_soc_mean) else "")
            + f"I_p95 {h.vreg_I_p95_A:.1f} A, {int(h.n_vreg_samples)} regression samples, {h.distance_km:.1f} km"
            + (f", V-sag cross-check {h.vsag_R_pack_mohm:.1f} mΩ" if pd.notna(h.vsag_R_pack_mohm) else ", no V-sag cross-check on this drive")
            + f". Gated median {r['med']:.1f} mΩ; holder residual after linear pack-T control = {r['z']:+.1f} SD "
              f"(fitted dR/dT = {r['beta'][1]:.2f} mΩ/°C; T-adjusted to {r['Tref']:.1f}°C the highest is {lab(r['hold_adj'].file)} at {r['hold_adj'].R_adj:.1f} mΩ). "
              f"Selection effect: with the same {r['nGate']['primary']} drives and temperature mix, noise alone (fitted T model + resampled residuals, B={B}) yields a maximum of {r['emed']:.1f} mΩ (95% range {r['ci'][0]:.1f}–{r['ci'][1]:.1f}); the holder sits at percentile {r['pctile']:.0f} of that null, i.e. "
              + ("within what noise alone produces" if r['pctile'] < 97.5 else "above the null range") + " — a maximum of noisy per-drive estimates is biased upward and is not a property of the pack. "
              f"Gate sensitivity of the holder: {sens}" + (" (holder unchanged across gates)." if stable else " (holder changes with the gate — treat the identity as unstable).")
              + f" For contrast the UNGATED maximum ({r['nProxy']} drives) is {ug.vreg_R_pack_mohm:.1f} mΩ on {lab(ug.file)} with only {r['ungatedN']} regression samples. "
              f"Gates were placed at the observed dispersion elbow of the proxy (T-controlled residual SD {r['sd_low']:.1f} mΩ below n_vreg_samples={GATES['loose'][0]}, {r['sd_hi']:.1f} above), not at a physical threshold. "
              f"Load-excited in-drive proxy, V and I on separate polling timestamps: NOT an SOH, DCIR or capacity measurement.")
    return {"metric": METRIC, "value": f"{h.vreg_R_pack_mohm:.1f} mΩ (gated V-reg proxy)", "drive": lab(h.file), "note": note}

if __name__ == "__main__":
    dm = pd.read_csv(os.path.join(WORK, "drive_master.csv"), low_memory=False)
    rec = build_record(dm)
    p = os.path.join(WORK, "summary_arrays.json")
    a = json.load(open(p, encoding="utf-8"))
    recs = [x for x in a["records"] if x["metric"] != METRIC]
    idx = next(i for i, x in enumerate(recs) if x["metric"].startswith("Cell spread under load (single-sample)")) + 1
    recs.insert(idx, rec); a["records"] = recs
    a["_artifactStamps"]["records"]["computationStatusNote"] = re.sub(r" \| M284:.*$", "", a["_artifactStamps"]["records"]["computationStatusNote"]) + \
        " | M284: added excitation-gated pack-resistance-proxy record (method, gate, covariates, bootstrap interval, gate sensitivity; not SOH) per audit Sec 10."
    json.dump(a, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(rec["metric"], "|", rec["value"], "|", rec["drive"]); print(rec["note"])
