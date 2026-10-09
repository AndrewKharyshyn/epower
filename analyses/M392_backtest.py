#!/usr/bin/env python3
"""M392 back-test (script-written JSON analyses/M392_backtest.json): the recalibration gate (tools/recal_gate.evaluate, M392 rules) on the real ingestions M376 (489 -> 524) and
M388 (524 -> 554) and M310 (446 -> 489): old = the master before the ingestion, new = the master after. Reports hard / soft / not-evaluable flags per quantity, the window-null
p-values and the minimum detectable shifts, next to what the pre-M392 rules flagged at M376 and M388 (CHANGELOG: I_offset_A, I_offset_2p_A, both block nulls).
Usage: python analyses/M392_backtest.py"""
import io, json, os, subprocess, sys
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import recal_gate as rg


def master_at(rev):
    return pd.read_csv(io.StringIO(subprocess.check_output(["git", "show", f"{rev}:drive_master.csv"]).decode("utf8")), low_memory=False)


cases = {"M310 (446->489)": ("23d0397", "a9f4733"), "M376 (489->524)": ("ff8fc2c", "3431d08"), "M388 (524->554)": ("3431d08", "533000e")}
out = {}
for name, (a, b) in cases.items():
    old, new = master_at(a), master_at(b)
    rep, hard = rg.evaluate(old, new, {})
    rows = []
    for t in rep["tests"]:
        w = t.get("window_null") or {}
        rows.append({"quantity": t["quantity"], "hard_new_outside_old_ci": t.get("hard_new_outside_old_ci"), "new_only_outside_old_ci_informational": t.get("new_only_outside_old_ci"),
                     "window_p": w.get("p", t.get("p")), "n_windows": w.get("n_windows", t.get("n_valid_blocks")), "mdd95": w.get("mdd95", t.get("mdd95_per_coef")),
                     "hard_drift": t.get("hard_drift_window_null", t.get("hard_drift_block_null")), "soft": t.get("soft_flag"), "not_evaluable": t.get("not_evaluable")})
    out[name] = {"n_old": len(old), "n_new_drives": rep["n_new_drives"], "hard_flags": hard, "soft_flags": rep["soft_flags"], "not_evaluable": rep["not_evaluable"], "tests": rows}
    print(name, "hard:", hard, "| soft:", rep["soft_flags"], "| not evaluable:", rep["not_evaluable"])
    for r in rows:
        if r["quantity"] in ("I_offset_A", "I_offset_2p_A") or "joint" in r["quantity"]:
            print("   ", r["quantity"], "p", None if r["window_p"] is None else round(r["window_p"], 3), "windows", r["n_windows"], "mdd95", r["mdd95"] if not isinstance(r["mdd95"], float) else round(r["mdd95"], 4))
json.dump(out, open("analyses/M392_backtest.json", "w", encoding="utf-8", newline="\n"), indent=1, default=float)
