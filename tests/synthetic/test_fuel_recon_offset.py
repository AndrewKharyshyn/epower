"""M349 known-answer tests for the fuel_recon.py offset resolution (spec analyses/M349_spec.md rev 2).
Defect: float(NaN or 0.0) kept NaN -> NaN battery power -> zero in the traction sum -> f_gen = 1 by construction.
1 corpus_offset: single-valued -> the constant; two distinct values -> raises (fail-closed); empty -> raises.
2 resolve_offset: calibrated keeps its value; NaN/None/non-numeric -> constant; exclude flag -> None; never NaN.
3 synthetic drive: NaN offset gives NaN battery power, the resolved offset gives the exact discharge-positive -I - off.
4 (when staged raw files exist) the two published Aug 13 rows: f_gen no longer 1 and equals the pre-registered effect table."""
import os, sys, json, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
STAGED = os.path.join(ROOT, "raw_only")
os.environ["XT_RAW_DIR"] = STAGED if os.path.isdir(STAGED) else os.path.join(ROOT, "raw")
import numpy as np, pandas as pd
import fuel_recon as FR
import recon_engine as RE

fails = 0
def ok(label, c, extra=""):
    global fails
    print(("PASS " if c else "FAIL ") + label + ((" - " + str(extra)) if (not c and extra) else ""))
    fails += 0 if c else 1

nan = float("nan")
# 1
dm = pd.DataFrame({"I_offset_A_applied": [-0.3858, -0.3858, nan, -0.38580001]})
c, n, d = FR.corpus_offset(dm)
ok("corpus_offset single-valued (after round 4): constant, n=3, distinct=1", c == -0.3858 and n == 3 and d == 1, (c, n, d))
try:
    FR.corpus_offset(pd.DataFrame({"I_offset_A_applied": [-0.3858, -0.2, nan]})); ok("corpus_offset two distinct values raises", False)
except ValueError:
    ok("corpus_offset two distinct values raises (fail-closed)", True)
try:
    FR.corpus_offset(pd.DataFrame({"I_offset_A_applied": [nan, nan]})); ok("corpus_offset empty raises", False)
except ValueError:
    ok("corpus_offset with no calibrated drive raises", True)
# 2
ok("resolve calibrated keeps its value", FR.resolve_offset({"I_offset_A_applied": -0.1}, -0.3858) == (-0.1, False))
for lab, row in (("NaN", {"I_offset_A_applied": nan}), ("missing", {}), ("None", {"I_offset_A_applied": None}), ("text", {"I_offset_A_applied": "x"})):
    v, imp = FR.resolve_offset(row, -0.3858)
    ok(f"resolve {lab} -> constant, flagged imputed, not NaN", v == -0.3858 and imp is True, (v, imp))
ok("resolve NaN with exclude flag -> None (excluded)", FR.resolve_offset({"I_offset_A_applied": nan}, -0.3858, exclude_nan=True) == (None, True))
ok("resolve calibrated is not excluded by the flag", FR.resolve_offset({"I_offset_A_applied": -0.1}, -0.3858, exclude_nan=True) == (-0.1, False))
ok("the removed idiom float(NaN or 0.0) stays NaN (documents the defect)", float(nan or 0.0) != float(nan or 0.0))
# 3 synthetic drive through the real loader
with tempfile.TemporaryDirectory() as td:
    n = 60
    t = pd.date_range("2026-08-13 12:00:00", periods=n, freq="1s")
    df = pd.DataFrame({"time": t.strftime("%Y-%m-%d %H:%M:%S.%f"), RE.CH["flow"]: np.full(n, 3.6), RE.CH["I"]: np.full(n, -10.0),
                       RE.CH["V"]: np.full(n, 350.0), RE.CH["soc"]: np.full(n, 60.0), RE.CH["speed"]: np.full(n, 40.0),
                       RE.CH["rpm"]: np.full(n, 1500.0)})
    df.to_csv(os.path.join(td, "syn.csv"), index=False)
    old = RE.BASE; RE.BASE = td + os.sep
    try:
        gn = RE.load_drive("syn.csv", nan)
        gc = RE.load_drive("syn.csv", FR.resolve_offset({"I_offset_A_applied": nan}, -0.3858)[0])
    finally:
        RE.BASE = old
    ok("NaN offset -> battery power NaN (the defect)", gn is not None and bool(gn["Pbatt"].isna().all()))
    exp = 350.0 * (10.0 + 0.3858) / 1000.0     # discharge-positive: V*(-I - off)/1000, raw I is charge-positive
    ok("resolved offset -> Pbatt = V*(-I - off)/1000 exactly", gc is not None and bool(np.allclose(gc["Pbatt"].to_numpy(), exp)), None if gc is None else gc["Pbatt"].iloc[0])
# 4 published rows (staged raw only)
eff = os.path.join(ROOT, "analyses", "M349_effect.json")
if os.path.isfile(os.path.join(STAGED, "drive_master.csv")) and os.path.isfile(eff):
    dmm = pd.read_csv(os.path.join(STAGED, "drive_master.csv")); mm = {r["file"]: r for _, r in dmm.iterrows()}
    const = FR.corpus_offset(dmm)[0]; E = json.load(open(eff, encoding="utf-8"))["perDrive"]
    for f in ("20260813_145651.csv", "20260813_150341.csv"):
        off, imp = FR.resolve_offset(mm[f], const)
        r = FR.reconstruct(f, mm[f], off)
        k = E[f + "|offset_corpus_constant"]
        ok(f"{f}: imputed, f_gen != 1 and equals the effect table", imp and r is not None and r["f_gen"] != 1.0 and abs(r["f_gen"] - k["f_gen"]) < 1e-9 and abs(r["batt_to_traction_kWh_100"] - k["batt_to_traction_kWh_100"]) < 1e-9, None if r is None else r["f_gen"])
else:
    print("SKIP staged-raw known answers (raw_only/ not staged)")
print("FUEL_RECON_OFFSET FAILS =", fails)
sys.exit(1 if fails else 0)
