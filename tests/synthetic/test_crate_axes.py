"""M358 known-answer test of compute_summary_arrays._crate_axes (spec analyses/M358_spec.md Rev 2) on a scripted master."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np, pandas as pd
import compute_summary_arrays as C
fails = 0
def ok(l, c, e=""):
    global fails
    print(("PASS " if c else "FAIL ") + l + ((" - " + str(e)) if (not c and e) else "")); fails += 0 if c else 1
nan = np.nan
cls = C.CLASS_ORDER[0]
dm = pd.DataFrame({
    "file": ["a.csv", "b.csv", "c.csv", "d.csv"],
    "drive_type": [cls, cls, cls, "unknown"],
    "eng_charge_peak_Crate": [10.0, nan, 5.0, 9.0], "eng_charge_peak_A": [-60.0, nan, -30.0, -50.0],
    "dual_peak_Crate": [12.0, 8.0, nan, 9.0], "dual_peak_A": [-70.0, -47.0, nan, -50.0],
    "regen_peak_Crate": [nan, 9.0, 4.0, 9.0], "regen_peak_A": [nan, -52.0, -23.0, -50.0],
    "T1_at_peak_Crate": [21.4, 30.0, nan, 25.0], "T1_peak": [30.0, 35.0, 40.0, 25.0],
    "peak_charge_kw": [-25.0, nan, -11.0, -20.0], "V_pack_median": [350.0, 350.0, 360.0, 350.0],
    "ens_outlier_v2": [False, False, False, False]})
arrays = {"cRatePoints": [[21.0, 12.0, "city"], [30.0, 9.0, "city"], [40.0, 5.0, "city"]]}
pts, ref, ax = C._crate_axes(dm, arrays)
ok("unknown drive_type row excluded, same count as the reference point set", len(pts) == 3, len(pts))
ok("A is |A| of the channel with the largest C (a: dual 70, b: regen 52, c: eng 30)", [p[3] for p in pts] == [70.0, 52.0, 30.0], [p[3] for p in pts])
ok("C is the max over channels", [p[1] for p in pts] == [12.0, 9.0, 5.0])
ok("T is T1 at peak, falling back to T1_peak when missing (c)", [p[0] for p in pts] == [21.0, 30.0, 40.0], [p[0] for p in pts])
ok("kW is |peak_charge_kw|, null kept as None (b)", [p[4] for p in pts] == [25.0, None, 11.0], [p[4] for p in pts])
ok("first three columns equal the reference cRatePoints", all(p[:3] == q for p, q in zip(pts, arrays["cRatePoints"])))
ok("diagnostics count the missing kW and the screens", ax["diagnostics"]["nKwMissing"] == 1 and ax["diagnostics"]["nAOver300A"] == 0 and ax["diagnostics"]["nPoints"] == 3)
ok("C per A median over rows (12/70, 9/52, 5/30)", abs(ax["cPerA"]["median"] - round(float(np.median([12/70, 9/52, 5/30])), 5)) < 1e-9, ax["cPerA"])
iv = [25000 / 70 / 350, 11000 / 30 / 360]
ok("implied voltage over V_pack_median uses only rows with A, kW and V (n=2)", ax["diagnostics"]["impliedVoltageOverVmed"]["n"] == 2 and abs(ax["diagnostics"]["impliedVoltageOverVmed"]["median"] - round(float(np.median(iv)), 3)) < 1e-9, ax["diagnostics"]["impliedVoltageOverVmed"])
by = {l["kind"]: l for l in ref["lines"]}
ok("peak line = the max-C dual drive with its own A and kW; regen line from regen column", by["peak"]["A"] == 70.0 and by["peak"]["kW"] == 25.0 and by["peak"]["drive"] == "a.csv" and by["regen"]["A"] == 52.0 and by["regen"]["kW"] is None)
ok("typical line is a per-axis median over the ens-clean dual_peak rows (a, b, d)", by["typical"]["C"] == 9.0 and by["typical"]["A"] == 50.0 and by["typical"]["n"] == 3 and by["typical"]["kW"] == 20.0, by["typical"])
ok("secondary-axis mode reflects the pre-registered 3% rule", ax["cPerA"]["secondaryAxisMode"] == ("axis" if ax["cPerA"]["halfIqrRel"] <= 0.03 else "tickAnnotations"))
print("FAILS:", fails); sys.exit(1 if fails else 0)
