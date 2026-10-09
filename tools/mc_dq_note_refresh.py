#!/usr/bin/env python3
"""M388: re-apply the M382 F03 step to the freshly rebuilt energyUncertaintyMC.grossThroughputMC.dataQualityNote.
The MC producer writes each contributor's nominalKwh_1500ms from its own 1500 ms curve; M382 (audit F03) replaced it by the master value
(gross_throughput_kwh, 4 decimals) and regenerated the finding text with energy_uncertainty_mc.data_quality_finding(). That step was a one-off splice
(tools/m382_splice.py) that no ingestion stage repeats, so the first ingestion after M382 fails semantic_gate A4 G3. Same two operations as m382_splice
(nothing typed); deep-diff: only dataQualityNote may change. Idempotent. drive_master.csv is read only.
Usage: python tools/mc_dq_note_refresh.py [--dry-run]"""
import copy, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import pandas as pd
import energy_uncertainty_mc as MC

DRY = "--dry-run" in sys.argv
raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
A = json.loads(raw)
new = copy.deepcopy(A)
mg = pd.read_csv("drive_master.csv").set_index("file")["gross_throughput_kwh"]
dq = new["energyUncertaintyMC"]["grossThroughputMC"]["dataQualityNote"]
for c in dq["topContributors"]:
    c["nominalKwh_1500ms"] = round(float(mg[c["file"]]), 4)
tot = float(re.search(r"\(([0-9.]+) kWh corpus-wide\)", dq["finding"]).group(1))
dq["finding"] = MC.data_quality_finding(tot, dq["topContributors"])


def paths(a, b, p=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [x for k in sorted(set(a) | set(b)) for x in (paths(a.get(k), b.get(k), f"{p}/{k}") if (k in a and k in b) else [f"{p}/{k}"])]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [x for i, (u, v) in enumerate(zip(a, b)) for x in paths(u, v, f"{p}/{i}")]
    return [] if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else [p]


ch = paths(A, new)
bad = [p for p in ch if not p.startswith("/energyUncertaintyMC/grossThroughputMC/dataQualityNote")]
print(json.dumps({"changed": ch, "outsideAllowList": bad}))
if bad:
    sys.exit(1)
if not DRY and ch:
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
