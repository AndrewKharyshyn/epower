#!/usr/bin/env python3
"""M399 splice (analyses/M399_wording_spec.md Rev 1): leaf-level, allow-listed text update of summary_arrays.json after the producer/config fixes.
Only string leaves change; nothing numeric. Changes:
  * every string leaf: logged-cadence wording replaces '~1.3 Hz' / '~1.26 Hz' (same substitutions as the producers in compute_summary_arrays.py)
  * constantProvenance.CAP_KWH.{source,note}      <- summary_config.json auditMetadata.constantProvenance.CAP_KWH (single source)
  * assumptionsRegistry.entries[0].{source,sensitivity}, metricConvention.note, generatorTractionRecon.audit[8].basis,
    energyUncertaintyMC.capacityNote               <- the corrected wording of the producers
  * generatorTractionRecon.limitations[*]          'refreshed at M373' -> 'recomputed on the live corpus at ingestion'
STOP on any numeric change or any path outside the allow-list. drive_master.csv is not read.
Usage: M399_ARRAYS_SHA16=<sha16> python tools/m399_splice.py [--dry-run]"""
import copy, hashlib, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
DRY = "--dry-run" in sys.argv
raw = open("summary_arrays.json", "rb").read()
exp = os.environ.get("M399_ARRAYS_SHA16")
if not exp or hashlib.sha256(raw).hexdigest()[:16] != exp:
    raise SystemExit("summary_arrays.json changed since the run started (or M399_ARRAYS_SHA16 not set)")
A = json.loads(raw.decode("utf-8"))
if json.dumps(A, ensure_ascii=False, indent=1) != raw.decode("utf-8"):
    raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
new = copy.deepcopy(A)
cfg = json.load(open("summary_config.json", encoding="utf-8"))
cp = cfg["auditMetadata"]["constantProvenance"]["CAP_KWH"]

HZ = [(r"the ~1\.3 Hz cadence floor", "the logged-cadence floor"), (r"on the ~1\.26 Hz grid", "on the native logged-cadence grid"),
      (r"slim cache, ~1\.26 Hz, NOT", "slim cache, native logged cadence, NOT"), (r"the ~1\.26 Hz cadence", "the logged cadence"),
      (r"[Tt]he ~1\.3 Hz cadence", "the logged cadence")]


def fix_str(s):
    for a, b in HZ:
        s = re.sub(a, b, s)
    return s.replace("refreshed at M373", "recomputed on the live corpus at ingestion")


def walk_set(o):
    if isinstance(o, dict):
        return {k: walk_set(v) for k, v in o.items()}
    if isinstance(o, list):
        return [walk_set(v) for v in o]
    return fix_str(o) if isinstance(o, str) else o


new = walk_set(new)
new["constantProvenance"]["CAP_KWH"]["source"] = cp["source"]
new["constantProvenance"]["CAP_KWH"]["note"] = cp["note"]
e0 = new["assumptionsRegistry"]["entries"][0]
assert e0["id"] == "cap_kwh"
e0["source"] = cp["source"]
assert "scales linearly with this value;" in e0["sensitivity"]
e0["sensitivity"] = e0["sensitivity"].replace("scales linearly with this value;", "scales inversely with this value (the selected reference capacity);")
mc = new["metricConvention"]
assert "scales linearly with CAP_KWH" in mc["note"]
mc["note"] = mc["note"].replace("scales linearly with CAP_KWH", "scales inversely with CAP_KWH")
au = new["generatorTractionRecon"]["audit"][8]
assert "not an OEM nameplate figure" in au["basis"]
au["basis"] = au["basis"].replace("CAP_KWH=2.1 assumed, not an OEM nameplate figure (verified:false)", "CAP_KWH=2.1 assumed (verified:false); the basis of the Nissan-published 2.1 kWh is undefined")
cn = new["energyUncertaintyMC"]["capacityNote"]
old_tail = "Not drawn randomly: CAP_KWH has exactly one credible alternative reference point, not a distribution to assume a shape for."
assert old_tail in cn
new["energyUncertaintyMC"]["capacityNote"] = cn.replace(old_tail, "Scenario scaling: 2.1 and 1.8 kWh are two reference scenarios, not a distribution to assume a shape for.")


def walk(a, b, path="", out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            walk(a.get(k), b.get(k), f"{path}/{k}", out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for k, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{k}]", out)
    elif a != b:
        out.append((path, a, b))
    return out


changed = walk(A, new)
nonstr = [p for p, x, y in changed if not (isinstance(x, str) and isinstance(y, str))]
if nonstr:
    raise SystemExit("STOP: non-string change: %s" % nonstr[:5])
print(json.dumps({"nChangedLeaves": len(changed), "paths": [p for p, _, _ in changed]}, indent=1))
if not DRY:
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(new, ensure_ascii=False, indent=1))
    print("summary_arrays.json updated")
