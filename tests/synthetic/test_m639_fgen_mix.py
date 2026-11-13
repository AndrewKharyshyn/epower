"""M639 known-answer tests (analyses/M639_spec.md Rev 1): E0 reproduction, exact E1 and E2 on synthetic strata, support flags, empty-stratum drops, determinism."""
import os, sys
import numpy as np
import pandas as pd
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools")); sys.path.insert(0, REPO)
import m639_fgen_mix as M

# two strata with known per-km rates: a (G 0.2, T 0.4 per km -> f 0.5), b (G 0.9, T 1.0 per km -> f 0.9); the closure set is 80 % a by km, the corpus is 25 % a
rows = []
for i in range(40):
    rows.append(dict(file="a%d" % i, date="2026-06-%02d" % (1 + i % 20), drive_type="a", km=2.0, g2t=0.4, trac=0.8))
for i in range(10):
    rows.append(dict(file="b%d" % i, date="2026-06-%02d" % (1 + i), drive_type="b", km=2.0, g2t=1.8, trac=2.0))
fuel = pd.DataFrame(rows)
ref_km = pd.Series({"a": 25.0, "b": 75.0})
e = M.estimates(fuel, ref_km, "drive_type")
want_e1 = (0.25 * 0.2 + 0.75 * 0.9) / (0.25 * 0.4 + 0.75 * 1.0)
want_e2 = 0.25 * 0.5 + 0.75 * 0.9
assert abs(e["E1"] - want_e1) < 1e-12 and abs(e["E2"] - want_e2) < 1e-12
e0 = fuel.g2t.sum() / fuel.trac.sum()
assert abs(e0 - (40 * 0.4 + 10 * 1.8) / (40 * 0.8 + 10 * 2.0)) < 1e-12 and e0 != e["E1"]
# when the reference mix equals the closure-set mix, E1 equals the headline ratio of sums
ref_same = fuel.groupby("drive_type")["km"].sum()
assert abs(M.estimates(fuel, ref_same, "drive_type")["E1"] - e0) < 1e-12
# a reference stratum absent from the closure set: not estimable (None), never silently dropped
assert M.estimates(fuel, pd.Series({"a": 1.0, "b": 1.0, "c": 1.0}), "drive_type") is None
# support flags: 10 drives on 5 days is supported; fewer drives or days is not
sup = M.support(fuel, "drive_type")
assert bool(sup.loc["a", "supported"]) and bool(sup.loc["b", "supported"]) and sup.loc["b", "nDays"] == 10
thin = fuel[fuel.drive_type == "b"].head(4)
assert not bool(M.support(thin, "drive_type").loc["b", "supported"])
# collapse
assert M.collapse("urban") == "urban" and M.collapse("mixed_highway") == "non-urban" and M.collapse("highway") == "non-urban"
# bootstrap: deterministic with the seed; fixed-weight and joint run; a stratum present on few days produces dropped replicates that are counted
ref = pd.DataFrame([dict(file="r%d" % i, date="2026-06-%02d" % (1 + i % 28), drive_type="a" if i % 4 == 0 else "b", km=3.0) for i in range(120)])
b1 = M.boot(fuel, ref, "drive_type", nb=300, fixed=True)
b2 = M.boot(fuel, ref, "drive_type", nb=300, fixed=True)
assert b1 == b2 and b1["ci95"]["E1"][0] < want_e1 < b1["ci95"]["E1"][1] + 0.2
bj = M.boot(fuel, ref, "drive_type", nb=300)
assert bj["draws"] == 300 and bj["ci95"]["E1"] is not None
few = fuel[(fuel.drive_type == "a") | (fuel.file.isin(["b0", "b1"]))]                  # b on 2 days only: many replicates lack b
bf = M.boot(few, ref, "drive_type", nb=300, fixed=True)
assert bf["nDroppedReplicates"] > 0 and abs(bf["dropRate"] - bf["nDroppedReplicates"] / 300) < 1e-4
# the published payload block: E0 equals the headline and the block is a sibling of fGen
import json
A = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
G = A["generatorTractionRecon"]["gtrClosure"]
blk = G["fGenMixStandardised"]
assert abs(blk["E0"]["est"] - G["fGen"]["est"]) < 5e-5 and "fGenMixStandardised" not in G["fGen"]
assert blk["fourTypes"]["unsupportedStrataAbove5pct"] and blk["displayedPrimary"] == "urbanNonUrban" and blk["urbanNonUrban"]["joint"]["ci95"]["E1"] is not None
assert "within-stratum exchangeability" in blk["meaning"] and "Not an article figure" in blk["meaning"]
import language_gate as LG
assert "M639-fgen-mix-wording" in LG.scan_text("This is the corrected f_gen for the corpus.") and not LG.scan_text("Drive-type-mix-standardised (corpus km mix) f_gen, model-derived (Path B), sensitivity.")
print("PASS test_m639_fgen_mix")
