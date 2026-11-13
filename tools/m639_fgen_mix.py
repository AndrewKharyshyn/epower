#!/usr/bin/env python3
"""M639 (implements analyses/M639_spec.md Rev 1, self-audit W1-14 / A-5): drive-type-mix-standardised f_gen as a labelled sensitivity beside the closure headline.

E0 (reproduced, never replaced): sum(g2t) / sum(trac) over the closure set (analyses/M377c_closure_perdrive.csv, the set behind gtrClosure.fGen).
E1: F* = sum_s w_s G_s / sum_s w_s T_s, G_s = sum g2t / sum km and T_s = sum trac / sum km in drive-type stratum s of the closure set; w_s = km share of s in the corpus
reference set (canonical-clean drives of drive_master.csv with distance_km > 0). E2: sum_s w_s f_s with f_s = sum g2t / sum trac in s (the audit's arithmetic, secondary).
Versions: four drive types (payload only, labelled extrapolative while a stratum above 5 % weight is unsupported) and the collapsed {urban, non-urban} version (displayed primary
in that case). Interval: joint day-clustered percentile bootstrap over corpus calendar days (weights and strata recomputed in the same replicate; seed 42, 4000 draws), the
fixed-weight interval beside it; replicates with an empty stratum are dropped and counted for every version. Model-derived (Path B), never measured.
Writes the sibling key generatorTractionRecon.gtrClosure.fGenMixStandardised (additive; nothing else changes). Usage: python tools/m639_fgen_mix.py [--dry-run]"""
import copy, json, os, sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
NB, SEED = 4000, 42
FLOOR_DRIVES, FLOOR_DAYS, WEIGHT_CUT = 10, 5, 0.05
TYPES = ["urban", "mixed", "mixed_highway", "highway"]


def collapse(t):
    return "urban" if t == "urban" else "non-urban"


def _agg(df, col):
    return df.groupby(col).agg(g=("g2t", "sum"), tr=("trac", "sum"), km=("km", "sum"))


def estimates(fuel, ref_km, col):
    """fuel: closure rows with columns g2t, trac, km, stratum col; ref_km: Series of corpus km by the same strata (the reference weights are its shares)."""
    a = _agg(fuel, col)
    w = ref_km / ref_km.sum()
    if not set(w.index) <= set(a.index) or (a.km <= 0).any():
        return None
    G = a.g / a.km
    T = a.tr / a.km
    ww = w.reindex(a.index).fillna(0.0)
    return {"E1": float((ww * G).sum() / (ww * T).sum()), "E2": float((ww * (a.g / a.tr)).sum())}


def boot(fuel, ref, col, nb=NB, seed=SEED, fixed=False):
    """Joint (fixed=False) or fixed-weight (fixed=True) day-clustered bootstrap. fuel/ref carry a 'date' column; returns CIs and the drop rate."""
    rng = np.random.default_rng(seed)
    ref_days = np.array(sorted(ref["date"].unique()))
    f_days = np.array(sorted(fuel["date"].unique()))
    ref_by = {d: g.groupby(col)["km"].sum() for d, g in ref.groupby("date")}
    f_by = {d: _agg(g, col) for d, g in fuel.groupby("date")}
    strata = sorted(set(ref[col]) | set(fuel[col]))
    ref0 = ref.groupby(col)["km"].sum()
    out = {"E1": [], "E2": []}
    dropped = 0
    for _ in range(nb):
        fd = f_days[rng.integers(0, len(f_days), len(f_days))] if fixed else None
        if not fixed:
            rd = ref_days[rng.integers(0, len(ref_days), len(ref_days))]
            # fuel days resampled from the corpus days drawn: a fuel day appears as often as its corpus day was drawn
            cnt = pd.Series(rd).value_counts()
            rk = pd.Series(0.0, index=strata)
            for d, k in cnt.items():
                rk = rk.add(ref_by[d] * int(k), fill_value=0.0)
            parts = [f_by[d] * int(k) for d, k in cnt.items() if d in f_by]
        else:
            rk = ref0.reindex(strata).fillna(0.0)
            parts = [f_by[d] for d in fd]
        if not parts:
            dropped += 1
            continue
        a = parts[0]
        for q in parts[1:]:
            a = a.add(q, fill_value=0.0)
        a = a.reindex(strata)
        w = rk / rk.sum() if rk.sum() > 0 else None
        if w is None or a[["g", "tr", "km"]].isna().any().any() or (a.km <= 0).any() or (w[w > 0].index.difference(a.index)).size:
            dropped += 1
            continue
        ww = w.reindex(a.index).fillna(0.0)
        out["E1"].append(float((ww * (a.g / a.km)).sum() / (ww * (a.tr / a.km)).sum()))
        out["E2"].append(float((ww * (a.g / a.tr)).sum()))
    ci = {k: ([round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)] if len(v) >= 0.95 * nb else None) for k, v in out.items()}
    return {"ci95": ci, "nDroppedReplicates": int(dropped), "dropRate": round(dropped / nb, 4), "draws": nb, "seed": seed}


def support(fuel, col):
    g = fuel.groupby(col).agg(nDrives=("file", "nunique"), nDays=("date", "nunique"), km=("km", "sum"))
    g["supported"] = (g.nDrives >= FLOOR_DRIVES) & (g.nDays >= FLOOR_DAYS)
    return g


def build(closure, dm):
    ref = dm[(~dm["ens_outlier_v2"].astype(bool)) & (dm["distance_km"] > 0)][["file", "date", "drive_type", "distance_km"]].rename(columns={"distance_km": "km"}).copy()
    ref["date"] = ref["date"].astype(str)
    fuel = closure.copy()
    fuel["date"] = fuel["date"].astype(str)
    # R2: one drive_type source (drive_master); the closure file must agree for every shared file
    m = fuel.merge(dm[["file", "drive_type"]], on="file", how="left", suffixes=("", "_dm"))
    assert m["drive_type_dm"].notna().all() and (m["drive_type"] == m["drive_type_dm"]).all(), "drive_type differs between the closure file and drive_master"
    e0 = float(fuel["g2t"].sum() / fuel["trac"].sum())
    blk = {"E0": {"est": round(e0, 4), "nDrives": int(len(fuel)), "nDays": int(fuel["date"].nunique()), "source": "analyses/M377c_closure_perdrive.csv (the closure set behind gtrClosure.fGen)",
                  "definition": "sum(g2t) / sum(trac) over the closure set; the headline, unchanged"},
           "referenceSet": {"definition": "canonical-clean drives of drive_master.csv (ens_outlier_v2 false) with distance_km > 0; one fixed all-corpus km mix by drive_type",
                            "nDrives": int(len(ref)), "nDays": int(ref["date"].nunique()), "closureDrivesInReference": int(fuel["file"].isin(ref["file"]).sum())}}
    ref["strat4"], fuel["strat4"] = ref["drive_type"], fuel["drive_type"]
    ref["strat2"], fuel["strat2"] = ref["drive_type"].map(collapse), fuel["drive_type"].map(collapse)
    for name, col in (("fourTypes", "strat4"), ("urbanNonUrban", "strat2")):
        rk = ref.groupby(col)["km"].sum()
        w = rk / rk.sum()
        sup = support(fuel, col)
        est = estimates(fuel, rk, col)
        unsupported_heavy = [s for s in w.index if w[s] > WEIGHT_CUT and not bool(sup["supported"].get(s, False))]
        v = {"strata": {s: {"referenceKmShare": round(float(w[s]), 4), "referenceDrives": int((ref[col] == s).sum()), "closureDrives": int(sup["nDrives"].get(s, 0)),
                            "closureDays": int(sup["nDays"].get(s, 0)), "closureKmShare": round(float(sup["km"].get(s, 0) / sup["km"].sum()), 4), "supported": bool(sup["supported"].get(s, False)),
                            "atFloor": bool(sup["nDrives"].get(s, 0) == FLOOR_DRIVES or sup["nDays"].get(s, 0) == FLOOR_DAYS)} for s in w.index},
             "E1": round(est["E1"], 4), "E2": round(est["E2"], 4),
             "unsupportedStrataAbove5pct": unsupported_heavy,
             "label": ("extrapolative: the corpus-mix share of an unsupported stratum is carried by a thin cell" if unsupported_heavy else "all strata above 5 % weight meet the floor of 10 drives on 5 days")}
        v["joint"] = boot(fuel, ref, col)
        v["fixedWeights"] = boot(fuel, ref, col, fixed=True)
        blk[name] = v
    prim = blk["urbanNonUrban"] if blk["fourTypes"]["unsupportedStrataAbove5pct"] else blk["fourTypes"]
    ci = prim["joint"]["ci95"]["E1"]
    blk["displayedPrimary"] = "urbanNonUrban" if blk["fourTypes"]["unsupportedStrataAbove5pct"] else "fourTypes"
    if ci is None:
        blk["verdict"] = "interval withheld (too many dropped replicates)"
    else:
        blk["verdict"] = ("the headline is mix-sensitive: the interval excludes the headline value" if not (ci[0] <= e0 <= ci[1])
                          else "not distinguished from the headline at this support: the interval includes the headline value")
    nonurb = fuel[fuel["strat2"] == "non-urban"]
    rnon = ref[ref["strat2"] == "non-urban"]
    blk["residualImbalanceWithinNonUrban"] = {"closureKmShare": {t: round(float(nonurb[nonurb.drive_type == t].km.sum() / nonurb.km.sum()), 4) for t in TYPES[1:]},
                                                "referenceKmShare": {t: round(float(rnon[rnon.drive_type == t].km.sum() / rnon.km.sum()), 4) for t in TYPES[1:]}}
    blk["meaning"] = ("Drive-type-mix-standardised (corpus km mix) f_gen, model-derived (Path B), sensitivity: the closure-set ratio re-weighted to the km mix of drive types in the canonical-clean corpus. "
                      "The headline is the closure-set ratio and is unchanged. Assumes within-stratum exchangeability (fuel-PID availability does not depend on season, SoC or period given drive type). "
                      "Not an article figure (Opus audit and owner sign-off required). M639, self-audit W1-14.")
    blk["method"] = ("E1 = sum_s w_s G_s / sum_s w_s T_s (G_s, T_s per-km generator-to-traction and gross traction energy in stratum s); E2 = sum_s w_s f_s (secondary). Joint day-clustered percentile bootstrap "
                     "over corpus calendar days (weights and strata recomputed per replicate; seed 42; 4000 draws), the fixed-weight interval beside it; replicates with an empty stratum are dropped and counted.")
    return blk


def main(argv):
    dry = "--dry-run" in argv
    closure = pd.read_csv(os.path.join(ROOT, "analyses", "M377c_closure_perdrive.csv"))
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    head = A["generatorTractionRecon"]["gtrClosure"]["fGen"]["est"]
    blk = build(closure, dm)
    if abs(blk["E0"]["est"] - head) > 5e-5:
        print("STOP: E0 %.4f does not reproduce the published headline %.4f (spec R1); nothing written" % (blk["E0"]["est"], head))
        return 3
    print(json.dumps(blk, indent=1)[:2500])
    if dry:
        return 0
    B = copy.deepcopy(A)
    B["generatorTractionRecon"]["gtrClosure"]["fGenMixStandardised"] = blk
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
