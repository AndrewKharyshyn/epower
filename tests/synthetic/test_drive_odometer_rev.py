"""M766 known-answer tests (analyses/M766_spec.md Rev 2): tools/drive_odometer_rev.py applies a jump rule per estimator, reproduces the M752 drive_endpoints under rule B, uses the shifted endpoint rows for the +16 s sensitivity under rule P,
compares results leaf by leaf (tolerance 0), defines the S1 / S2 excursion spans, recomputes the agreement blocks from a per-drive frame, and keeps absolute cloud odometer values out of the result. No store is needed."""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import drive_odometer as dm
import odometer_jump_audit as J
import drive_odometer_rev as R


def stream(rows):
    rows = sorted(rows)
    return np.array([r[0] for r in rows], float), np.array([r[1] for r in rows], float)


# rule B passes the tool's flag to every estimator and reproduces drive_endpoints exactly
ts, vs = stream([(300, 100.0), (400, 100.0), (470, 100.0), (500, 100.0), (550, 101.0), (600, 102.0), (640, 102.0), (700, 102.0)])
t0, t1 = 500.0, 600.0
fm, fs = R.flags_for_rule("B", t0, t1, ts, vs)
assert (fm, fs) == (False, False)
mine = R.endpoints_with_flags(t0, t1, ts, vs, fm, fs)
tool = dm.drive_endpoints(t0, t1, ts, vs)
assert R.leaf_equal(json.loads(json.dumps(mine, default=float)), json.loads(json.dumps(tool, default=float))) == []
# a flagged drive: every estimator unavailable with the reason odometer_jump (rule B on a stream with a step at the extra edge rows)
ts2, vs2 = stream([(300, 100.0), (400, 100.0), (470, 10.0), (500, 10.0), (550, 11.0), (600, 12.0), (640, 12.0), (700, 12.0)])
fm, fs = R.flags_for_rule("B", t0, t1, ts2, vs2)
assert fm and fs
ep = R.endpoints_with_flags(t0, t1, ts2, vs2, fm, fs)
assert all(e["dist"] is None and e["reasonStart"] == "odometer_jump" for e in ep.values())
assert R.leaf_equal(json.loads(json.dumps(ep, default=float)), json.loads(json.dumps(dm.drive_endpoints(t0, t1, ts2, vs2), default=float))) == []
# rule P keeps that drive (the step lies outside the stretch the endpoints use) for every estimator
fmP, fsP = R.flags_for_rule("P", t0, t1, ts2, vs2)
assert not fmP and not fsP
epP = R.endpoints_with_flags(t0, t1, ts2, vs2, fmP, fsP)
assert all(epP[k]["dist"] is not None for k in ("E_int", "E_br", "E_near", "E_near60")) and epP["E_int_shift16"]["reasonStart"] != "odometer_jump"
# the +16 s sensitivity uses the shifted endpoint rows under P: a step that only the shifted stretch contains flags E_int_shift16 alone
ts3, vs3 = stream([(300, 10.0), (470, 10.0), (484, 10.0), (484.5, 4.0), (500, 4.0), (560, 5.0), (600, 5.5), (640, 5.5), (700, 5.5)])
fm3, fs3 = R.flags_for_rule("P", 500.0, 600.0, ts3, vs3)
assert (fm3, fs3) == (False, True), (fm3, fs3)
ep3 = R.endpoints_with_flags(500.0, 600.0, ts3, vs3, fm3, fs3)
assert ep3["E_int"]["dist"] is not None and ep3["E_int_shift16"]["dist"] is None and ep3["E_int_shift16"]["reasonStart"] == "odometer_jump"

# leaf-by-leaf comparison with tolerance 0
assert R.leaf_equal({"a": {"b": [1, 2.5]}}, {"a": {"b": [1, 2.5]}}) == []
assert R.leaf_equal({"a": {"b": [1, 2.5]}}, {"a": {"b": [1, 2.5000001]}}) == ["/a/b[1]"]
assert R.leaf_equal({"a": 1}, {"a": 1, "c": 2}) == ["/c"]
assert R.leaf_equal({"a": [1]}, {"a": [1, 2]}) == ["/a"]

# excursion spans: strict = first to last row below the running maximum; wide = the row before and the row after
tse, vse = stream([(0, 100.0), (10, 100.0), (20, 50.0), (30, 50.0), (40, 100.0), (50, 101.0)])
assert J.excursion_spans(tse, vse) == [(20.0, 30.0)] and R.excursion_spans_wide(tse, vse) == [(10.0, 40.0)]
assert not J.in_excursion(15.0, J.excursion_spans(tse, vse)) and J.in_excursion(15.0, R.excursion_spans_wide(tse, vse))

# blocks() from a per-drive frame: coverage by reason, the agreement block equals a hand computation, the wording function is applied
rng = np.random.default_rng(3)
n = 60
days = ["2026-05-%02d" % (1 + i % 15) for i in range(n)]
logged = rng.uniform(3.0, 20.0, n)
delta = 0.012 * logged + rng.normal(0, 0.05, n)
df = pd.DataFrame({"date": days, "month": ["2026-05"] * n, "t0": np.arange(n) * 1000.0, "t1": np.arange(n) * 1000.0 + 500.0, "logged": logged, "identity": [True] * n, "clean": [True] * n})
for name in R.ESTIMATORS:
    df[name + "_dist"] = logged + delta
    df[name + "_reason"] = "ok"
df.loc[:4, "E_int_dist"] = np.nan
df.loc[:4, "E_int_reason"] = "odometer_jump"
df["stratum"] = df["logged"].map(dm.stratum_of)
b = R.blocks(df, np.array([0.0, 1.0]), np.array([0.0, 1.0]), 400, J.verdict_three)
assert b["P0_coverage"]["E_int"] == {"available": 55, "unavailableByReason": {"odometer_jump": 5}} and b["P0_coverage"]["E_br"]["available"] == 60
sel = df[df["E_int_dist"].notna()]
d = sel["E_int_dist"] - sel["logged"]
est = float(d.sum() / sel["logged"].sum())
assert abs(b["P1_agreement"]["E_int"]["primary_identity_ge2km"]["relative"]["est"] - round(est, 5)) < 1e-9, (est, b["P1_agreement"]["E_int"]["primary_identity_ge2km"]["relative"])
w = b["P1_verdict_wording"]["primary_E_int_identity_ge2km"]
assert "interval" in w["within1pct"] or "consistent within" in w["within1pct"], w

# sensitivity: drives with an endpoint inside the spans are dropped from the primary agreement
dfs = df.copy()
sens = R.sensitivity(dfs, [(0.0, 2000.0)], [(0.0, 4000.0)], 200)
assert sens["S1_strict"]["drives_with_an_endpoint_inside_an_excursion"] == 3 and sens["S2_wide"]["drives_with_an_endpoint_inside_an_excursion"] == 5
assert sens["S2_wide"]["available_all_drives_after"] <= sens["S1_strict"]["available_all_drives_after"]

# privacy: the M752 absolute anchor keys are refused; the scan fails closed on an odometer-range value
assert R.forbidden_present({"P3_anchor": {"cloudLastOdoKm": 1.0}}) and R.forbidden_present({"x": {"dashOdoKm": 1}}) and not R.forbidden_present({"P3_anchor": {"differenceKm": -0.41, "n": 1}})
assert J.scan_privacy({"P3_anchor": {"x": 48104.8}}) and not J.scan_privacy({"P3_anchor": {"differenceKm": -0.409, "n": 1}})
assert R.EXPECTED_S1 == 22 and R.EXPECTED_S2 == 31
print("test_drive_odometer_rev: OK")
