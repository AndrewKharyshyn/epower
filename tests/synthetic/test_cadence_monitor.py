"""M396 known-answer test: the report-only PID polling-cadence flag (tools/cadence_monitor.py, analyses/M396_spec.md)."""
import contextlib, io, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import numpy as np, pandas as pd
import cadence_monitor as CM


def drive(i, day, t, iv):
    regime = None if iv is None else ("fast" if iv < 1.05 else "slow")
    return {"file": f"{day}_{i:02d}.csv", "date": day, "time_start": t, "I_sample_period_s": np.nan if iv is None else iv, "regime": regime}


hist = [drive(1, "2026-10-07", "07:00:00.0", 0.85), drive(2, "2026-10-07", "18:00:00.0", 0.86), drive(3, "2026-10-08", "08:30:00.0", 0.81),
        drive(4, "2026-10-08", "10:15:00.0", 1.47), drive(5, "2026-10-08", "21:20:00.0", 1.55)]
old_slow = [drive(0, "2026-09-10", "09:00:00.0", 1.25), drive(0, "2026-09-11", "09:00:00.0", 1.25)]
base = pd.DataFrame(old_slow + hist)
with tempfile.TemporaryDirectory() as td:
    sp = os.path.join(td, "cm.json")
    # bootstrap: baseline = the corpus as it is (including the Oct-8 slow drives), no flags
    st = CM.update(base, sp)
    assert st["bootstrap"] is True and st["last_update"]["flags"] == [] and st["last_seen"][2] == hist[-1]["file"] and st["expected_regime"] == "fast" and st["last_regime"] == "slow"
    # nothing new: the file is untouched
    before = open(sp, encoding="utf-8").read()
    CM.update(base, sp)
    assert open(sp, encoding="utf-8").read() == before
    # new drives, all fast: confirmation (info), no flag
    b1 = pd.concat([base, pd.DataFrame([drive(1, "2026-10-10", "07:00:00.0", 0.84), drive(2, "2026-10-10", "18:00:00.0", 0.86)])], ignore_index=True)
    st = CM.update(b1, sp)
    assert st["last_update"]["n_flags"] == 0 and [x["flag"] for x in st["last_update"]["flags"]] == ["fast_polling_confirmed"] and st["last_regime"] == "fast" and st["flag_history"] == []
    # a slow drive after fast ones: the flag, with first slow drive, counts, medians and the 'slower than earlier slow' comparison
    b2 = pd.concat([b1, pd.DataFrame([drive(1, "2026-10-11", "07:00:00.0", 0.85), drive(2, "2026-10-11", "12:00:00.0", 1.50), drive(3, "2026-10-11", "13:00:00.0", 1.52), drive(4, "2026-10-11", "20:00:00.0", 0.84)])], ignore_index=True)
    st = CM.update(b2, sp)
    fl = [x for x in st["last_update"]["flags"] if not x.get("info")]
    assert st["last_update"]["n_flags"] == 1 and fl[0]["flag"] == "cadence_slow_while_fast_expected"
    f = fl[0]
    assert f["first_slow_file"] == "2026-10-11_02.csv" and f["first_slow_time"] == "12:00:00.0" and f["n_slow_new"] == 2 and f["n_new"] == 4 and f["n_fast_new"] == 2
    assert f["median_interval_new_slow_s"] == 1.51 and f["reference_slow_median_s"] is not None and f["slower_than_reference_slow"] is True and f["after_fast_in_batch_or_before"] is True
    assert "app PID" in f["action"] and len(st["flag_history"]) == 1 and st["last_regime"] == "fast"
    # a rerun without new drives must not erase or duplicate the alert
    keep = open(sp, encoding="utf-8").read()
    CM.update(b2, sp)
    assert open(sp, encoding="utf-8").read() == keep
    # a batch of slow-only drives at the earlier slow level (1.2 s) is flagged but NOT 'slower than the earlier slow regime'
    b3 = pd.concat([b2, pd.DataFrame([drive(1, "2026-10-12", "07:00:00.0", 1.20)])], ignore_index=True)
    st = CM.update(b3, sp)
    f = [x for x in st["last_update"]["flags"] if not x.get("info")][0]
    assert f["slower_than_reference_slow"] is False and f["after_fast_in_batch_or_before"] is True and len(st["flag_history"]) == 2
    # drives without a regime are info (not evaluable), never a pass and never a flag
    b4 = pd.concat([b3, pd.DataFrame([drive(1, "2026-10-13", "07:00:00.0", None)])], ignore_index=True)
    st = CM.update(b4, sp)
    assert st["last_update"]["n_flags"] == 0 and [x["flag"] for x in st["last_update"]["flags"]] == ["cadence_unknown"]
    # ordering is by (date, time_start, file), not by row order in the sidecar
    sp2 = os.path.join(td, "cm2.json")
    CM.update(base, sp2)
    shuffled = pd.concat([base, pd.DataFrame([drive(9, "2026-10-14", "09:00:00.0", 1.5), drive(8, "2026-10-14", "07:00:00.0", 0.85)])]).sample(frac=1, random_state=3)
    st = CM.update(shuffled, sp2)
    assert [x["first_slow_file"] for x in st["last_update"]["flags"] if not x.get("info")] == ["2026-10-14_09.csv"] and st["last_update"]["flags"][0]["n_new"] == 2
    # main() never raises: an unreadable sidecar prints monitor_error and returns 0, the state is untouched
    bad = os.path.join(td, "bad.csv")
    open(bad, "w", encoding="utf-8").write("not,a,sidecar\n")
    old_argv, buf = sys.argv, io.StringIO()
    sys.argv = ["cadence_monitor.py", "update", "--state", sp2, "--sidecar", bad]
    keep2 = open(sp2, encoding="utf-8").read()
    try:
        with contextlib.redirect_stdout(buf):
            rc = CM.main()
    finally:
        sys.argv = old_argv
    assert rc == 0 and "monitor_error" in buf.getvalue() and open(sp2, encoding="utf-8").read() == keep2
print("OK cadence monitor: bootstrap, fast confirmed, slow flag with details, history once, unknown info, ordering, rerun-safe, never raises")
