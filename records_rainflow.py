#!/usr/bin/env python3
"""records_rainflow.py (M284, audit Section 10 additional record: "Rainflow exposure").
Adds two records derived from the per-drive rainflow columns (ASTM-style rainflow on raw SoC, 1.0 % amplitude floor).
k=2 damage is deliberately NOT used (kept separate, as the audit requires). Idempotent; replaces by metric name."""
import json, os, re
import numpy as np, pandas as pd
import importlib.util
_HERE = os.path.dirname(os.path.abspath(__file__))
# layout-agnostic: flat project checkout (drive_master.csv beside the scripts) or work/{seasonal,track3,track4}/ tree
WORK = os.environ.get("XT_WORK") or (_HERE if os.path.exists(os.path.join(_HERE, "drive_master.csv")) else os.path.dirname(_HERE))
SDIR = os.path.join(WORK, "seasonal") if os.path.isdir(os.path.join(WORK, "seasonal")) else WORK
spec = importlib.util.spec_from_file_location("rr", os.path.join(os.path.dirname(os.path.abspath(__file__)), "records_resistance.py"))
RR = importlib.util.module_from_spec(spec); spec.loader.exec_module(RR)
M1 = "Rainflow — most counted cycles in one drive"
M2 = "Rainflow — largest equivalent-full-cycle (EFC) drive"

def build(dm):
    files = list(dm.file); lab = lambda f: RR.drive_label(f, files)
    ok = dm[dm.rf_n_cycles.notna() & dm.distance_km.gt(0)].copy()
    ok["cyc100"] = 100 * ok.rf_n_cycles / ok.distance_km
    med100 = float(100 * ok.rf_n_cycles.sum() / ok.distance_km.sum())          # ratio-of-sums
    wid = dm.loc[dm.rf_dod_max_pct.idxmax()]
    h1 = dm.loc[dm.rf_n_cycles.idxmax()]; h2 = dm.loc[dm.rf_efc.idxmax()]
    common = ("Rainflow on the raw SoC trace, cycles with a range below 1.0 pp dropped (twice the PID quantisation step); half-cycles count 0.5. "
              "Counts scale with drive length and SoC-PID sampling, so read together with distance. k=2 damage is a separate, non-fitted proxy and is not used here. "
              f"Corpus ratio-of-sums cycle density {med100:.1f} cycles/100 km over {len(ok)} drives.")
    r1 = {"metric": M1, "value": f"{h1.rf_n_cycles:g} cycles", "drive": lab(h1.file),
          "note": f"Set on a {h1.distance_km:.1f} km drive ({h1.rf_n_cycles/h1.distance_km*100:.0f} cycles/100 km, {h1.rf_efc:.2f} EFC, deepest cycle {h1.rf_dod_max_pct:g}% DoD). " + common}
    r2 = {"metric": M2, "value": f"{h2.rf_efc:.2f} EFC", "drive": lab(h2.file),
          "note": f"Set on a {h2.distance_km:.1f} km drive ({h2.rf_n_cycles:g} cycles, deepest cycle {h2.rf_dod_max_pct:g}% DoD" + (f", coulometric FCE {h2.fce:.2f}" if pd.notna(h2.get('fce')) else "") + "). "
            + common + (f" The deepest single rainflow cycle in the corpus ({wid.rf_dod_max_pct:g}% DoD) is on {lab(wid.file)}; it coincides with the 'Widest SoC excursion' record." if wid.file == dm.loc[dm.soc_max.sub(dm.soc_min).idxmax(), 'file'] else
                        f" The deepest single rainflow cycle ({wid.rf_dod_max_pct:g}% DoD) is on {lab(wid.file)}.")}
    return [r1, r2]

if __name__ == "__main__":
    dm = pd.read_csv(os.path.join(WORK, "drive_master.csv"), low_memory=False)
    p = os.path.join(WORK, "summary_arrays.json"); a = json.load(open(p, encoding="utf-8"))
    new = build(dm); names = {x["metric"] for x in new}
    recs = [x for x in a["records"] if x["metric"] not in names]
    idx = next(i for i, x in enumerate(recs) if x["metric"].startswith("Widest SoC excursion")) + 1
    recs[idx:idx] = new; a["records"] = recs
    n = a["_artifactStamps"]["records"]["computationStatusNote"]
    if "rainflow-exposure records" not in n:
        a["_artifactStamps"]["records"]["computationStatusNote"] = n + " | M284: added two rainflow-exposure records (cycle count, EFC); k=2 damage kept separate (audit Sec 10)."
    json.dump(a, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for r in new: print(r["metric"], "|", r["value"], "|", r["drive"], "\n ", r["note"])
