"""M535 (analyses/M535_spec.md Rev 4): observedMixDetail. A2 independent recomputation from drive_master.csv (no producer helper): shares, km, n, day-clustered interval (seed 42, 4000 draws); tie-out with the unchanged observedMix;
exclusion accounting; payload/stage/stamp plumbing; the displayed paragraph binds S.observedMixDetail; the retired note carries no typed percentages and the rule fires on them; splice idempotent."""
import json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
A = json.load(open("summary_arrays.json", encoding="utf-8")); C = json.load(open("summary_config.json", encoding="utf-8"))
B = A["observedMixDetail"]; P = B["primary"]
m = pd.read_csv("drive_master.csv", low_memory=False)
ens = m["ens_outlier_v2"].astype(str).str.lower().isin(["true", "1", "1.0"])
T = ("urban", "mixed", "mixed_highway", "highway")
d = m[m["drive_type"].isin(T) & ~ens & (m["distance_km"] > 0)]
assert len(d) == P["nDrives"] == A["observedMix"]["n"] and abs(d["distance_km"].sum() - P["km"]) < 0.06
tot = d["distance_km"].sum()
sh = {t: 100 * d[d["drive_type"] == t]["distance_km"].sum() / tot for t in T}
for t in T:
    assert abs(sh[t] - P["byType"][t]["pct"]) < 6e-4, t
hw = sh["mixed_highway"] + sh["highway"]
assert abs(hw - P["byClass"]["highway"]["pct"]) < 6e-4 and abs(round(hw, 1) - A["observedMix"]["observedShare"]["highway"]) <= 0.1 and abs(round(sh["urban"], 1) - A["observedMix"]["observedShare"]["city"]) <= 0.1
# independent interval: per-day km sums, whole days resampled, seed 42, 4000 draws
g = d.groupby("date")
dd = pd.DataFrame({"hw": g.apply(lambda x: x[x["drive_type"].isin(["mixed_highway", "highway"])]["distance_km"].sum()), "all": g["distance_km"].sum()})
idx = np.random.default_rng(42).integers(0, len(dd), (4000, len(dd)))
draw = 100 * dd["hw"].values[idx].sum(1) / dd["all"].values[idx].sum(1)
lo, hi = np.percentile(draw, [2.5, 97.5])
assert P["nDays"] == len(dd) and abs(lo - P["byClass"]["highway"]["ci95Pct"][0]) < 1e-3 and abs(hi - P["byClass"]["highway"]["ci95Pct"][1]) < 1e-3
# exclusion accounting reconciles (606 -> 601)
acc = B["exclusionAccounting"]
assert acc["masterDrives"] == len(m) and acc["reconciles"] and acc["nPrimary"] == len(d)
assert acc["excluded"]["ensOutlierV2"]["nDrives"] + acc["excluded"]["invalidDistance"]["nDrives"] + acc["excluded"]["unknownDriveType"]["nDrives"] == len(m) - len(d)
assert B["tieOut"]["passed"] and not B["tripwires"]["unknownOver2PctOfKm"] and B["tripwires"]["typeUnder10Days"] == []
# observedMix itself is byte-unchanged in shape (tie-out source) and the detail key is not an estimate in the declared stamps beyond its own entry
assert set(A["observedMix"]) >= {"observedShare", "typedKm", "n", "note"}
sd = json.load(open("tools/stamp_dependencies.json", encoding="utf-8"))["blocks"]["observedMixDetail"]
assert sd["readsRaw"] is False and sd["producer"] == "tools/driving_mix.py"
assert "driving_mix" in [s["id"] for s in json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]]
# display binding: the paragraph reads S.observedMixDetail (no literal interval) and the highway interval is rendered
j = open("xtrail_summary.jsx", encoding="utf-8").read()
assert "S.observedMixDetail?.primary?.byClass?.highway?.ci95Pct?.[0]" in j and "not a test of the trips statement" in j
# retired note: no typed percentages; framing kept; rule
import language_gate as G
R = {r.rid: r for r in G.RULES}["M535-retired-mix-note"]
note = C["drivingMixNote"]
assert "typed percentages retired in M535" in note and "observedMixDetail" in note and note.startswith("Dataset distance mix at the 2026-07-14 audit:")
assert R.hits("~19% pure-highway and ~58% mixed_highway (\u2248 77% highway-blended km), ~16% urban, ~6% mixed") and not R.hits(note)
def strings(o):
    if isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)
    elif isinstance(o, str): yield o
assert not [s for s in strings(A) if R.hits(s)] and not [s for s in strings(C) if R.hits(s)]
import driving_mix as M
assert M.main(["--check"]) == 0
print("OK test_m535_driving_mix: independent shares / interval, tie-out, accounting, binding, retired note, rule")
