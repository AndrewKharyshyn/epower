#!/usr/bin/env python3
"""M427 (external audit F16): metric-specific reasons for master rows that carry no gross-energy integral, computed from the master (never typed) with their support.

Reason codes (a row is counted once, in the first matching reason):
  no_pairs         the builder recorded energy_null_reason = no_integrable_iv_pairs (current and voltage samples exist, none paired within the tolerance)
  no_current       n_I_samples is 0: no HV-current samples were logged
  too_few_current  n_I_samples is 1 or 2: the production rule needs more than two current samples
  unclassified     none of the above (kept explicit so that an unknown reason is visible, never merged into another)
no_voltage and parse_failure are producer-level reasons that the master does not record; they are not inferred here. Other metrics of these drives stay usable where observed.
Usage: python tools/energy_reasons.py   (prints the block)"""
import json, os, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def energy_missing_reasons(dm):
    gt = pd.to_numeric(dm["gross_throughput_kwh"], errors="coerce")
    miss = dm[gt.isna()]
    ni = pd.to_numeric(miss["n_I_samples"], errors="coerce")
    rs = miss["energy_null_reason"].astype("object") if "energy_null_reason" in miss.columns else pd.Series([None] * len(miss), index=miss.index, dtype="object")
    out = {}
    for i in miss.index:
        r = rs.loc[i]
        n = ni.loc[i]
        if isinstance(r, str) and r == "no_integrable_iv_pairs":
            code = "no_pairs"
        elif pd.isna(n) or n <= 0:
            code = "no_current"
        elif n <= 2:
            code = "too_few_current"
        else:
            code = "unclassified"
        out.setdefault(code, []).append(i)
    order = ("no_pairs", "no_current", "too_few_current", "unclassified")
    reasons = {}
    for code in order:
        idx = out.get(code, [])
        sub = dm.loc[idx]
        reasons[code] = {"n": int(len(idx)), "km": round(float(pd.to_numeric(sub["distance_km"], errors="coerce").sum()), 1),
                         "days": int(sub["date"].astype(str).nunique()) if len(idx) else 0, "files": [str(f) for f in sub["file"]]}
    return {"nTotal": int(len(dm)), "nWithoutGrossEnergy": int(len(miss)), "reasons": reasons,
            "definition": ("master rows without a gross-energy integral, split by the first matching reason: no_pairs = current and voltage samples exist but none paired within the tolerance; "
                           "no_current = no HV-current samples logged; too_few_current = one or two current samples (the production rule needs more than two); unclassified = none of these. "
                           "no_voltage and parse_failure are producer-level reasons the master does not record and are not inferred here. These drives remain usable for every metric observed on them.")}


if __name__ == "__main__":
    print(json.dumps(energy_missing_reasons(pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)), indent=1))
