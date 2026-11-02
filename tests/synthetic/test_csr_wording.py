"""M564 (AUD29-N12): the cell-spread interpretation strings in the payload equal the generator helpers' output from the block's own leaves; every old claim fires the wording rule; the new text is silent."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import compute_summary_arrays as C
import language_gate as L

A = json.load(open("summary_arrays.json", encoding="utf-8"))
blocks = [A["cellSpreadRelaxation"]] + [A["seasonalCharts"]["charts"]["CellSpreadRelaxation"]["data"][k] for k in ("all", "warm", "shoulder", "cold")]
for b in blocks:
    assert b["interpretation"] == C._csr_interpretation(b), b["interpretation"][:80]
    assert "M564-N12-csr-wording" not in L.scan_text(b["interpretation"]) and not L.scan_text(b["interpretation"]), L.scan_text(b["interpretation"])
f = A["fullCellCaseStudy"]
assert f["interpretation"] == C._fcs_interpretation(f["examples"]) and not L.scan_text(f["interpretation"])
assert "<= %s mV" % format(max(e["spreadMv"] for e in f["examples"]), "g") in f["interpretation"]
for old in ["relaxes within ~1-2 s", "a well-balanced pack", "shallow-cycled buffer", "never deeply stresses the cells", "barely stresses the cells", "consistent with the power-buffer picture", "tight balance",
            "5 s relaxation dynamics are minimal", "a stable ~10-11 mV baseline", "a small-effect/near-null result, reported honestly"]:
    assert "M564-N12-csr-wording" in L.scan_text(old), old
for ok in ["a missing share is reported honestly", "the power buffer is sized by peak power", "cells are polled in a cycle", "the spread is 10 mV at rest"]:
    assert "M564-N12-csr-wording" not in L.scan_text(ok), ok
print("test_csr_wording OK")
