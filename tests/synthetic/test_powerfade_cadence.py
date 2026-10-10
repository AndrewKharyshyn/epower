"""M395 known-answer test: the powerFade cadence-handling specifications (compute_drive_summary_v6._powerfade_cadence_specs) and the generated statement.
Synthetic drives with a TRUE time slope of zero and an injected logging-density bias on the fast-regime drives, which sit late in time: without a cadence adjustment the slope is levered positive by the
instrumentation; every adjusted specification recovers about zero; the 'latest fast run' cut ignores a trailing slow run; the statement is generated from the leaves (analyses/M395_spec.md)."""
import io, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import numpy as np, pandas as pd
import compute_drive_summary_v6 as V
import compute_summary_arrays as A

ICOL = '[BMS] HV Battery Current (A)'


def raw_bytes(every):
    """200 rows at a 0.2 s tick; the current channel carries a value every `every` rows (slow = 6 -> 1.2 s, fast = 4 -> 0.8 s)."""
    rows = []
    for i in range(200):
        tsec = i * 0.2
        rows.append({"time": f"00:{int(tsec // 60):02d}:{tsec % 60:06.3f}", ICOL: (1.0 if i % every == 0 else np.nan)})
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def make(n_slow1=40, n_fast=20, n_slow2=0, bias=8.0, seed=1):
    rng = np.random.default_rng(seed)
    n = n_slow1 + n_fast + n_slow2
    fast = np.array([0] * n_slow1 + [1] * n_fast + [0] * n_slow2)
    dates = pd.date_range("2026-01-01", periods=n).strftime("%Y-%m-%d")
    dm = pd.DataFrame({"file": [f"d{i:03d}.csv" for i in range(n)], "date": dates, "time_start": "10:00:00.0", "ens_outlier_v2": False,
                       "vreg_R_pack_mohm": 120.0 + bias * fast + rng.normal(0, 0.8, n), "vreg_I_p95_A": 120 + rng.normal(0, 8, n),
                       "T_pack_mean_avg": 25 + rng.normal(0, 3, n), "I_sample_period_s": np.where(fast == 1, 0.8, 1.2)})
    store = {f: raw_bytes(4 if fa else 6) for f, fa in zip(dm["file"], fast)}
    return dm, (lambda f: store[f])


dm, loader = make()
r = V._powerfade_cadence_specs(dm, loader)
assert r["status"] == "ok" and [s["id"] for s in r["specs"]] == ["S0", "S1", "S2", "S3", "S4", "S5", "S6"], [s["id"] for s in r["specs"]]
sl = {s["id"]: s for s in r["specs"]}
assert sl["S0"]["slope"] > 3.0, sl["S0"]                                              # no adjustment: instrumentation levers the slope
for k in ("S1", "S2", "S3", "S4", "S6"):
    assert abs(sl[k]["slope"]) < 1.5, (k, sl[k])                                      # every adjusted specification recovers about zero (true slope 0)
assert r["latestFastRunStart"] == dm["date"].iloc[40] and sl["S5"]["n"] == 40 and sl["S6"]["n"] == 40
assert r["slopeMin"] == min(s["slope"] for s in r["specs"]) and r["slopeMax"] == max(s["slope"] for s in r["specs"]) and r["nSpecs"] == 7
assert r["allIntervalsSpanZero"] is False                                              # S0's interval excludes zero here
# the regime flips back to slow at the end: the cut is the start of the latest FAST run, not of the trailing slow run
dm2, loader2 = make(n_slow2=8)
r2 = V._powerfade_cadence_specs(dm2, loader2)
assert r2["latestFastRunStart"] == dm2["date"].iloc[40] and {s["id"]: s for s in r2["specs"]}["S5"]["n"] == 40
# no raw access / too few drives: not available, never a silent empty block
assert V._powerfade_cadence_specs(dm, None)["status"] == "not_available" and V._powerfade_cadence_specs(dm.head(10), loader)["status"] == "not_available"
# a short fast run (< 5 drives) shares the 'other fast' dummy; with no run of >= 5 drives S4 still exists via that dummy
dm3, loader3 = make(n_slow1=50, n_fast=3, n_slow2=7)
r3 = V._powerfade_cadence_specs(dm3, loader3)
assert "S4" in [s["id"] for s in r3["specs"]]

# statement generated from the leaves
blk = A._powerfade_cadence_block(r, None)
assert f"across {r['nSpecs']} cadence-handling specifications the slope ranges from {r['slopeMin']} to {r['slopeMax']}" in blk["statement"] and "no fade rate is claimed" in blk["statement"]
assert "not every" in blk["statement"] and "Emulated" not in blk["statement"] and blk["emulation"] is None
emu = {"status": "ok", "study": "M393", "basis": {"nClean": 242, "seeds": 3, "slowPoolDrives": 40}, "stale": True, "nFastClean": 90, "nFastLoseProxy": 29, "nFastKeepProxy": 61,
       "pairedDiffEmulatedMinusOriginal": {"fast1": {"n": 52, "nDays": 20, "meanMohm": -1.545, "ci95": [-2.29, -0.658]}, "fast2": {"n": 9, "nDays": 5, "meanMohm": -1.738, "ci95": [-3.321, -0.59]}}}
st = A._powerfade_cadence_block(r, emu)["statement"]
assert "lowers the proxy by 1.5-1.7" in st and "on the 61 fast-regime drives that keep a proxy" in st and "removes it from 29 of 90" in st and "not a causal cadence effect" in st
assert "stale: the clean-drive count is now %d" % r["nClean"] in st
nstale = A._powerfade_cadence_block(r, dict(emu, stale=False))["statement"]
assert "stale" not in nstale
gone = A._powerfade_cadence_block(r, {"status": "not_available", "reason": "x"})
assert "emulation study is not available" in gone["statement"] and "Emulated slow-cadence" not in gone["statement"]
assert "emulation study is not available" in A._powerfade_cadence_block(r, None)["statement"]
# the snapshot is read from the committed M393 study, never typed; a different clean-drive count marks it stale
snap = A._powerfade_emulation_snapshot(242)
assert snap["status"] == "ok" and snap["nFastLoseProxy"] == 29 and snap["nFastClean"] == 90 and snap["basis"]["nClean"] == 242 and snap["stale"] is False and snap["nFastKeepProxy"] == 61
assert A._powerfade_emulation_snapshot(243)["stale"] is True
na = A._powerfade_cadence_block({"status": "not_available", "reason": "x"}, None)
assert na["status"] == "not_available" and "no fade rate is claimed" in na["statement"]
print("OK powerfade cadence: specification set, latest-fast-run cut, bias recovery, generated statement")
