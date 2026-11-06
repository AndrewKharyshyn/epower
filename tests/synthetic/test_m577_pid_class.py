"""M577 Rev 2 (analyses/M577_spec_rev2.md) known-answer tests: Satterthwaite sensitivity, wider-interval rule, class-B indicator, floors (payload and in-frame), payload / sidecar mismatch STOP,
interim look without a ladder label, terminal evaluation (frozen, ledger idempotent), degenerate bootstrap draws, planted effect recovery."""
import json, os, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import m577_cell_spread_levels as M


# ---- A-sat: Satterthwaite interval and the one-way df-dependent flag
sa = M.sat_interval(1.0, 0.5, 4.0)
from scipy import stats
tc = float(stats.t.ppf(0.975, 4.0))
assert sa == [round(1.0 - tc * 0.5, 4), round(1.0 + tc * 0.5, 4)] and M.sat_interval(1.0, 0.5, float("nan")) is None and M.sat_interval(1.0, 0.5, None) is None
assert M.wider_interval([1.0, 3.0], [0.5, 2.5]) == [0.5, 3.0] and M.wider_interval(None, [1, 2]) == [1, 2] and M.wider_interval([1, 2], None) == [1, 2]


def synth(n_b=14, n_b_days=7, seed=3, b_effect=4.0, start_b="2026-11-03", early_b=True, cd=True, extra_a_after=True):
    rng = np.random.default_rng(seed)
    rows, side = [], []
    # non-B step = 1 fast drives, Oct 1 .. Nov 2
    for i, dte in enumerate(pd.date_range("2026-10-01", "2026-11-02", freq="D")):
        for j in range(2):
            rows.append((dte, "2026-%s_%02d-00-00.csv" % (dte.strftime("%m-%d"), 7 + j), "A", 0.0))
    # class B drives from start_b on
    bdays = pd.date_range(start_b, periods=n_b_days, freq="D")
    for k in range(n_b):
        dte = bdays[k % n_b_days]
        rows.append((dte, "2026-%s_%02d-%02d-00.csv" % (dte.strftime("%m-%d"), 15 if k == 0 and dte == pd.Timestamp("2026-11-03") else 9, k), "B", 1.0))
    if extra_a_after:                       # class A drives that come back after the run
        rows.append((bdays[-1] + pd.Timedelta(days=1), "2026-11-20_08-00-00.csv", "A", 0.0))
    if early_b:
        rows.append((pd.Timestamp("2026-05-13"), "20260513_182950.csv", "B", 0.0))
    if cd:
        rows.append((pd.Timestamp("2026-05-12"), "20260512_111617.csv", "C", 0.0))
        rows.append((pd.Timestamp("2026-08-13"), "20260813_144601.csv", "D", 0.0))
    df = pd.DataFrame(rows, columns=["date", "file", "cls", "Bflag"])
    df["_ts"] = df["date"] + pd.to_timedelta(df.groupby("date").cumcount() + 7, unit="h")
    if (df["file"] == M.FIRST_POST_STEP_B).any():
        df.loc[df["file"] == M.FIRST_POST_STEP_B, "_ts"] = pd.Timestamp("2026-11-03 15:07:48")
    n = len(df)
    df["day"] = df["date"].dt.strftime("%Y-%m-%d")
    df["wk"] = df["date"].dt.strftime("%G-%V")
    df["months"] = (df["date"] - pd.Timestamp("2026-05-15")).dt.days / 30.4375
    df["step"] = (df["date"] >= pd.Timestamp("2026-10-01")).astype(float)
    df["slow"] = 0.0
    df["T"] = rng.uniform(5, 15, n); df["I"] = rng.uniform(60, 140, n); df["soc"] = rng.uniform(40, 80, n); df["socr"] = rng.uniform(10, 30, n)
    df["lrest"] = rng.uniform(0, 3, n); df["first"] = (rng.random(n) < .3).astype(float)
    df["y"] = 20 + 0.1 * df["months"] + 0.02 * df["T"] + b_effect * (df["cls"].eq("B") & (df["_ts"] >= pd.Timestamp("2026-11-03 15:07:48"))) + rng.normal(0, 1.0, n)
    side = df[["file", "cls"]].rename(columns={"cls": "pidSetClass"})
    master = df[["file", "date"]]
    return df, side, master


# ---- indicator (R3): early class B and class C / D dropped; class A drives after the run stay 0
fr, side, master = synth()
ind, dropped = M.pid_indicator(fr, side)
assert dropped["earlyClassB"] == ["20260513_182950.csv"] and sorted(dropped["classCD"]) == ["20260512_111617.csv", "20260813_144601.csv"]
assert int(ind["B"].sum()) == 14 and "2026-11-20_08-00-00.csv" in set(ind[ind["B"] == 0]["file"]) and not ind["pidSetClass"].isin(["C", "D"]).any()
assert not ind["file"].isin(["20260513_182950.csv"]).any()

# ---- floors (payload and in-frame), mismatch STOP
ready_ok = {"runDrives": 14, "runDays": 7}
with tempfile.TemporaryDirectory() as tmp:
    lp = os.path.join(tmp, "looks.json")
    out, _ = M.pid_class_run(fr, side, {"runDrives": 14, "runDays": 3}, "md5-1", master=master, ledger_path=lp, spec_sha="s")
    assert out["status"] == "not identified (floors not met)" and "modelPrimary" not in out and not os.path.exists(lp)       # payload floor (days)
    fr2, side2, master2 = synth(n_b=8, n_b_days=4)
    out, _ = M.pid_class_run(fr2, side2, {"runDrives": 8, "runDays": 4}, "md5-1", master=master2, ledger_path=lp, spec_sha="s")
    assert out["status"] == "not identified (floors not met)" and out["inFrame"]["floorsMet"] is False
    try:
        M.pid_class_run(fr, side, {"runDrives": 12, "runDays": 7}, "md5-1", master=master, ledger_path=lp, spec_sha="s")
    except SystemExit as e:
        assert "differs" in str(e)
    else:
        raise AssertionError("a payload / sidecar mismatch must STOP")

    # ---- interim look: descriptive, no ladder label; ledger idempotent per master MD5
    o1, led1 = M.pid_class_run(fr, side, ready_ok, "md5-1", master=master, ledger_path=lp, spec_sha="s")
    assert o1["status"] == "descriptive look 1; no ladder label" and "label" not in o1 and o1["look"] == 1
    assert abs(o1["modelPrimary"]["est"] - 4.0) < 2.5 and o1["modelPrimary"]["labelInterval"][0] <= o1["modelPrimary"]["ci95"][0]
    assert o1["modelPrimary"]["ciSat"] is not None and "no PID-set effect and no cadence effect is claimed" in o1["interpretation"]
    o1b, led1b = M.pid_class_run(fr, side, ready_ok, "md5-1", master=master, ledger_path=lp, spec_sha="s")
    assert o1b["look"] == 1 and len(led1b["looks"]) == 1
    o2, led2 = M.pid_class_run(fr, side, ready_ok, "md5-2", master=master, ledger_path=lp, spec_sha="s")
    assert o2["look"] == 2 and len(led2["looks"]) == 2 and "label" not in o2

# ---- terminal evaluation: >= 20 class B drives on >= 10 days -> ladder label, then frozen
frt, sidet, mastert = synth(n_b=30, n_b_days=14, b_effect=6.0)
with tempfile.TemporaryDirectory() as tmp:
    lp = os.path.join(tmp, "looks.json")
    ot, ledt = M.pid_class_run(frt, sidet, {"runDrives": 30, "runDays": 14}, "md5-t", master=mastert, ledger_path=lp, spec_sha="s")
    assert ot["status"] == "terminal evaluation" and ot["label"] in ("distinguishable from zero", "procedure-dependent", "not distinguishable from zero (not equivalence)", "not separable", "not evaluable")
    assert ledt["terminal"]["label"] == ot["label"] and ledt["terminal"]["specRev2Sha256"] == "s"
    ot2, ledt2 = M.pid_class_run(frt, sidet, {"runDrives": 30, "runDays": 14}, "md5-t2", master=mastert, ledger_path=lp, spec_sha="s")
    assert ot2["status"] == "after the terminal evaluation; descriptive" and ledt2["terminal"] == ledt["terminal"]

# ---- degenerate bootstrap draws (R8): class B in one of ten day clusters -> share above the 10 % limit -> not evaluable
d = pd.DataFrame({"day": np.repeat(["d%d" % i for i in range(10)], 3), "B": [0.0] * 27 + [1.0] * 3})
d["y"] = np.arange(30.0) % 7 + 5 * d["B"]; d["x"] = np.arange(30.0) % 5
bb = M._boot_with_degenerate(d, ["B", "x"], "B", "day", n=400)
assert bb["degenerateShare"] > M.DEGENERATE_LIMIT and bb["evaluable"] is False
d2 = pd.DataFrame({"day": np.repeat(["d%d" % i for i in range(10)], 3), "B": [0.0, 1.0, 0.0] * 10})
d2["y"] = np.arange(30.0) % 7 + 5 * d2["B"]; d2["x"] = np.arange(30.0) % 5
assert M._boot_with_degenerate(d2, ["B", "x"], "B", "day", n=400)["evaluable"] is True
print("test_m577_pid_class: OK")
