"""M568 (analyses/M568_spec.md Rev 2): the officialDisclosureCorrelation peak-power notes equal the generator helpers' output (with the discharge-peak entry of the corpus-peak drive), carry the tier and age, and none of the retired phrases; the discharge peak identity holds."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import pandas as pd
import compute_summary_arrays as C
import language_gate as L

A = json.load(open("summary_arrays.json", encoding="utf-8")); P = A["powerPeakTemperature"]; od = A["officialDisclosureCorrelation"]
dm = pd.read_csv("drive_master.csv", low_memory=False)
pkf = dm.loc[dm["peak_discharge_kw"].idxmax(), "file"]
e = dict(P["dischargePeak"][pkf], file=pkf)
assert od["power"]["note"] == C._od_power_note(od["power"], e), od["power"]["note"][:120]
assert od["rows"][1]["note"] == C._od_power_row_note(od["power"])
assert "%s C, " % format(e["x"], "g") in od["power"]["note"] and "the T1 sample is %s s " % format(abs(e["ageS"]), "g") in od["power"]["note"] and e["tier"] in ("cotimed", "nearby", "late")
assert od["rows"][1]["verdict"] == "not_comparable"              # Director final ruling: no pulse duration is stated
assert abs(e["kw"] - od["power"]["measuredPeakKw"]) < 0.051                      # the peak sample is the corpus peak
for t in (od["power"]["note"], od["rows"][1]["note"]):
    assert not L.scan_text(t), L.scan_text(t)
for old in ["whereas the corpus peak is a warm-pack (median 28.0 C) instantaneous extremum", "Warm/instantaneous peak exceeds the derated rating as expected", "the rating is a sustained/derated figure", "which must be sourced directly from the generator", "the rated traction demand of the motor", "Observed instantaneous peak battery discharge"]:
    assert "M568-N07-peak-pairing" in L.scan_text(old), old
# generator without the temperature clause (full rebuild before the stage) carries the same sentences without a temperature
g = C._od_power_note(od["power"])
assert "Sensor-1" not in g and g.startswith("Single-sample peak battery discharge") and "no pulse duration is stated" in g
# a drive without a T1 sample within 10 s
n = C._od_power_note(od["power"], {"file": "x", "x": None, "tier": "none", "ageS": None})
assert "No Sensor-1 sample lies within 10 s of the peak sample." in n
# discharge peak identity (KD1) is part of the stored known answers
assert P["knownAnswer"]["misses"]["peakDis"] == 0 and P["knownAnswer"]["n"]["peakDis"] > 500
assert sum(P["summary"]["dischargePeak"]["tiersDis"].values()) == len(P["dischargePeak"])
print("test_od_power_note OK")
