#!/usr/bin/env python3
"""M347: exact-leaf edit of summary_arrays.json fuelStates: adds f03SpeedHvCheck (script-written, tools/f03_speed_hv_block.py) and replaces the two F03 'unchecked' note leaves
(strata.f03Note, chargingSubState.note). Idempotent; asserts old/new text; touches no other leaf. Usage: python tools/m347_f03_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import f03_speed_hv_block as B
ARR = os.path.join(ROOT, "summary_arrays.json")
A = json.load(open(ARR, encoding="utf-8")); fs = A["fuelStates"]
changed = []
OLD_F03 = "not a paired test: date-confounded; speed/HV columns raw-vs-originals unchecked (needs Andrii's permission)"
OLD_CHG = ("fuel consumed during net pack charging: a temporal state, not a fuel-source allocation; battery offset is estimated; hash-passing trips are the primary basis, hash-failing trips have rounded raw/ current (F03-unchecked)")
PREV_F03 = "not a paired test: date-confounded; speed, SoC and engine-speed columns of the hash-failing raw/ files are cell-identical to the sha256-verified originals; HV current and voltage in raw/ are rounded (measured effect in f03SpeedHvCheck)"
PREV_CHG = ("fuel consumed during net pack charging: a temporal state, not a fuel-source allocation; battery offset is estimated; hash-passing trips are the primary basis; hash-failing trips have "
            "rounded raw/ current (measured effect on pack energy in f03SpeedHvCheck)")
for d, k, old, new, lab in ((fs["strata"], "f03Note", OLD_F03, B.NOTE_F03, "strata.f03Note"), (fs["chargingSubState"], "note", OLD_CHG, B.NOTE_CHG, "chargingSubState.note")):
    if d[k] in (old, PREV_F03, PREV_CHG):
        d[k] = new; changed.append(lab)
    else:
        assert d[k] == new, (lab, d[k][:80])
blk = B.build()
if fs.get("f03SpeedHvCheck") != blk:
    fs["f03SpeedHvCheck"] = blk; changed.append("f03SpeedHvCheck")
if "--dry-run" not in sys.argv and changed:
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
print(json.dumps({"changed": changed, "n": len(changed)}))
