"""M426: the MC producer writes dataQualityNote.corpusTotalKwh itself and it equals the corpus-wide number stated in the generated finding text
(same rounding), so the field is never a 'lost leaf' of the arrays build."""
import os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import energy_uncertainty_mc as MC
from perf_baseline import synthetic_precompute

out = MC.build(synthetic_precompute(), rng=np.random.default_rng(MC.SEED), offset_point_a=-0.38, ci95a=(-0.42, -0.35), net_correction_kwh=21.0)
dq = out["grossThroughputMC"]["dataQualityNote"]
assert "corpusTotalKwh" in dq and isinstance(dq["corpusTotalKwh"], float), dq.keys()
m = re.search(r"\(([0-9.]+) kWh corpus-wide\)", dq["finding"])
assert m and float(m.group(1)) == dq["corpusTotalKwh"], (m and m.group(1), dq["corpusTotalKwh"])
assert dq["corpusTotalKwh"] == round(dq["corpusTotalKwh"], 3)
print("OK test_mc_dq_corpus_total: corpusTotalKwh = %s" % dq["corpusTotalKwh"])
