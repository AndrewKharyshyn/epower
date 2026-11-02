"""M567 (analyses/M567_spec.md Rev 2): known answers KA3 (tiers and boundaries) and R3 / KA5 (consistency with the legacy fallback flag) for the A / C views of the charge-rate risk map."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import power_peak_temp as PPT
import language_gate as L

def rec(age, v3=20.0, v10=21.0, tpeak="12:00:00"):
    return {"tPeakI": tpeak, "ageI_any": age, "T1AtPeakI": v3, "T1AtPeakI_10s": v10}
t = PPT._tier_ac
# KA3 tiers and inclusive boundaries
assert t(rec(0.8))["tier"] == "cotimed" and t(rec(0.8))["x"] == 20.0
assert t(rec(1.0))["tier"] == "cotimed" and t(rec(1.0 + 1e-6))["tier"] == "nearby"
assert t(rec(2.5))["tier"] == "nearby" and t(rec(3.0))["tier"] == "nearby" and t(rec(3.0 + 1e-6))["tier"] == "late"
assert t(rec(6.0))["tier"] == "late" and t(rec(6.0))["x"] == 21.0            # the late value is the 10 s sample
assert t(rec(10.0))["tier"] == "late" and t(rec(10.0 + 1e-6, v10=None))["tier"] == "none" and t(rec(10.0 + 1e-6, v10=None))["x"] is None
assert t(rec(-2.0))["tier"] == "nearby" and t(rec(-2.0))["ageS"] == -2.0 and t(rec(-5.0))["tier"] == "late"     # tiered by absolute age, signed age stored
assert t(rec(None, v3=None, v10=None))["tier"] == "none"                     # drive without T1 samples
assert t({"tPeakI": None})["tier"] == "none" and t(None)["tier"] == "none"   # drive with no current peak
# the extractor's nearest-sample rule: a tie in distance takes the earlier sample, no interpolation
t1 = pd.DataFrame({"t": pd.to_datetime(["2026-01-01 12:00:00", "2026-01-01 12:00:04"]), "v": [10.0, 30.0]})
v, a = PPT._near(t1, "2026-01-01 12:00:02", 10.0)
assert v == 10.0 and abs(a + 2.0) < 1e-9
# R3 / KA5 on the real payload and master: legacy fallback <=> late or none; every move is to an equal or lower temperature
A = json.load(open("summary_arrays.json", encoding="utf-8")); P = A["powerPeakTemperature"]
dm = pd.read_csv("drive_master.csv", low_memory=False).set_index("file")
ak = {p[5]: p for p in A["cRatePointsAK"]}
assert set(P["acViewX"]) == set(ak)
n = 0
for f, q in P["acViewX"].items():
    fb = dm.loc[f, "T1_at_peak_Crate_isFallback"]
    if pd.notna(fb):
        n += 1
        assert bool(fb) == (q["tier"] in ("late", "none")), (f, fb, q)
        if q["x"] is not None:
            assert q["x"] <= ak[f][0] + 1e-9, (f, q, ak[f][0])
    if q["tier"] in ("cotimed", "nearby"):
        assert abs(q["x"] - ak[f][0]) < 0.051, (f, q, ak[f][0])             # KA1: reproduces the master T1_at_peak_Crate
assert n >= 500
S = P["summary"]
assert sum(S["tiersAC"].values()) == len(ak) and S["acVsLegacy"]["movedNonFallbackDrives"]["nMoved"] == 0
# the old fallback wording is retired
for old in ["kept only for the small minority of drives", "toward the true co-timed reading", "pairs the peak with temperature at that exact sample"]:
    assert "M567-N07-timing" in L.scan_text(old), old
assert not L.scan_text("temperature at the sample nearest the peak charge current (within 1 s / 3 s; hollow = paired 3-10 s apart)")
print("test_ac_view_tiers OK")
