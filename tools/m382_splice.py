#!/usr/bin/env python3
"""M382 splice (analyses/M382_spec.md Rev 1): leaf-level, deep-diff-allow-listed update of summary_arrays.json after the producer fixes.
Every changed leaf is produced by the (fixed) producer functions, never typed:
  eligibility                       <- compute_summary_arrays._audit_eligibility(drive_master.csv)   (EV family predicate F05; additive dataCoverage F08/F09)
  generatorTractionRecon.glossary   <- refresh_gtr_headline.refresh() on a deep copy                    (eta rows bound to corpus F04)
  energyUncertaintyMC.grossThroughputMC.dataQualityNote
                                    <- energy_uncertainty_mc.data_quality_finding() + nominal energy of each contributor from the master (F03)
  masterRefitProvenance             <- strings of tools/build_refit_provenance.py (historical status, F01)
  _artifactStamps.generatorTractionRecon.computationStatusNote <- tools/stamp_notes.gtr_stamp_note() (F07)
STOP on any other changed path. drive_master.csv is read only. Usage: M382_ARRAYS_SHA16=<sha16> python tools/m382_splice.py [--dry-run]"""
import copy, hashlib, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd

DRY = "--dry-run" in sys.argv
raw = open("summary_arrays.json", "rb").read()
exp = os.environ.get("M382_ARRAYS_SHA16")
if not exp or hashlib.sha256(raw).hexdigest()[:16] != exp:
    raise SystemExit("summary_arrays.json changed since the run started (or M382_ARRAYS_SHA16 not set)")
A = json.loads(raw.decode("utf-8"))
new = copy.deepcopy(A)
dm = pd.read_csv("drive_master.csv")

# ---- F05 / F08 / F09: eligibility from the fixed producer ----
import compute_summary_arrays as C
new["eligibility"] = C._audit_eligibility(dm)

# ---- F04: glossary through the real refresh() on a deep copy ----
import refresh_gtr_headline as R
import wire_gtr_seasonal as W
B = R.refresh(copy.deepcopy(A), W.load_merged())[0]
for i, g in enumerate(B["generatorTractionRecon"]["glossary"]):
    new["generatorTractionRecon"]["glossary"][i]["value"] = g["value"]

# ---- F03: MC data-quality finding ----
import energy_uncertainty_mc as MC
dq = new["energyUncertaintyMC"]["grossThroughputMC"]["dataQualityNote"]
mg = dm.set_index("file")["gross_throughput_kwh"]
for c in dq["topContributors"]:
    c["nominalKwh_1500ms"] = round(float(mg[c["file"]]), 4)
tot = float(re.search(r"\(([0-9.]+) kWh corpus-wide\)", dq["finding"]).group(1))
dq["finding"] = MC.data_quality_finding(tot, dq["topContributors"])

# ---- F01: masterRefitProvenance wording (single source: tools/refit_provenance_text.py) ----
import refit_provenance_text as RT
mp = new["masterRefitProvenance"]
mp["basisStatus"] = RT.BASIS_STATUS
mp["interpretation"] = RT.INTERPRETATION
mp["limits"][0] = RT.LIMIT_0
assert RT.PROVENANCE_OLD in mp["_provenance"]
mp["_provenance"] = mp["_provenance"].replace(RT.PROVENANCE_OLD, RT.PROVENANCE_NEW)

# ---- F07: stamp note ----
from stamp_notes import gtr_stamp_note
new["_artifactStamps"]["generatorTractionRecon"]["computationStatusNote"] = gtr_stamp_note(new, "M382")

# ---- deep-diff allow-list ----
ALLOWED = ["/eligibility/families[3]/n", "/eligibility/families[3]/km", "/eligibility/families[3]/basis", "/eligibility/dataCoverage",
           "/generatorTractionRecon/glossary[3]/value", "/generatorTractionRecon/glossary[4]/value",
           "/energyUncertaintyMC/grossThroughputMC/dataQualityNote/finding",
           "/energyUncertaintyMC/grossThroughputMC/dataQualityNote/topContributors",
           "/masterRefitProvenance/basisStatus", "/masterRefitProvenance/interpretation", "/masterRefitProvenance/limits[0]",
           "/masterRefitProvenance/_provenance",
           "/_artifactStamps/generatorTractionRecon/computationStatusNote"]


def walk(a, b, path="", out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            walk(a.get(k), b.get(k), f"{path}/{k}", out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for k, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{k}]", out)
    elif a != b:
        out.append(path)
    return out


changed = walk(A, new)
bad = [c for c in changed if not any(c == p or c.startswith(p + "/") or c.startswith(p + "[") for p in ALLOWED)]
if bad:
    raise SystemExit("STOP: unexpected changed paths: %s" % bad[:10])
print(json.dumps({"changedPaths": changed, "n": len(changed)}, indent=1))
if not DRY:
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(new, ensure_ascii=False, indent=1))
    print("summary_arrays.json updated")
