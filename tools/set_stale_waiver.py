#!/usr/bin/env python3
"""Record an operator-signed stale-carry waiver in a carried-forward block of summary_arrays.json (build_html.js release-provenance gate, M285).
A block that is carried forward at an older drive basis fails the build unless it carries a non-empty `staleWaiver` string. The waiver is a per-release OWNER
decision (never written by an ingestion stage): run this tool only after the owner's decision, with the decision quoted in --reason. Exactly one leaf is added or
replaced (deep-diff asserted). The next ingestion rebuild drops the leaf (the lost-leaf guard flags it), so the waiver has to be signed again for the new basis.
Usage: python tools/set_stale_waiver.py --block socHysteresisV2 --reason "<owner decision, date, basis>" """
import argparse, copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
ap = argparse.ArgumentParser()
ap.add_argument("--block", required=True)
ap.add_argument("--reason", required=True)
a = ap.parse_args()
if not a.reason.strip():
    sys.exit("empty reason")
A = json.load(open("summary_arrays.json", encoding="utf-8"))
if not isinstance(A.get(a.block), dict):
    sys.exit(f"block {a.block!r} is absent or not an object")
new = copy.deepcopy(A)
new[a.block]["staleWaiver"] = a.reason.strip()
chk = copy.deepcopy(new); chk[a.block].pop("staleWaiver"); base = copy.deepcopy(A); base[a.block].pop("staleWaiver", None)
assert chk == base, "only the staleWaiver leaf may change"
with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(new, ensure_ascii=False, indent=1))
print(f"{a.block}.staleWaiver set")
