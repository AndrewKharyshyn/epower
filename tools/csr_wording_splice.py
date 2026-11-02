#!/usr/bin/env python3
"""M564 (Director wording ruling AUD29-N12): leaf-level splice of the regenerated cell-spread interpretation strings into summary_arrays.json (cellSpreadRelaxation, its four seasonal copies and fullCellCaseStudy). Computes nothing else: the helpers are the generator's own (`_csr_interpretation`, `_fcs_interpretation`), every other leaf is asserted byte-identical (deep diff).
Usage: python tools/csr_wording_splice.py [--check]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import compute_summary_arrays as C

ARR = "summary_arrays.json"


def leaves(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, p + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, p + "/%d" % i)
    else:
        yield p, o


def main():
    raw = open(ARR, encoding="utf-8").read()
    A = json.loads(raw)
    assert json.dumps(A, ensure_ascii=False, indent=1) == raw.rstrip("\n") or json.dumps(A, ensure_ascii=False, indent=1) + "\n" == raw, "serialisation round trip differs: stop"
    before = dict(leaves(A))
    targets = [A["cellSpreadRelaxation"]] + [A["seasonalCharts"]["charts"]["CellSpreadRelaxation"]["data"][k] for k in ("all", "warm", "shoulder", "cold")]
    for t in targets:
        t["interpretation"] = C._csr_interpretation(t)
    A["fullCellCaseStudy"]["interpretation"] = C._fcs_interpretation(A["fullCellCaseStudy"]["examples"])
    after = dict(leaves(A))
    changed = sorted(k for k in after if after[k] != before.get(k))
    assert set(after) == set(before) and all(k.endswith("/interpretation") for k in changed), changed
    print(json.dumps({"changedLeaves": changed, "nChanged": len(changed)}, indent=1))
    if "--check" in sys.argv:
        return
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))


if __name__ == "__main__":
    main()
