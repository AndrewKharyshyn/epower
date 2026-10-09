#!/usr/bin/env python3
"""M396 (analyses/M396_spec.md): REPORT-ONLY flag for the logger PID polling cadence. The owner re-activated fast polling of the HV-current channel after the app setting changed on
2026-10-08 (from 10:15 the median interval was about 1.47 s, slower than the earlier slow regime, see M379a / M393); this monitor tells the owner as soon as a NEW drive is slow again.
Reads the sidecar cadence_regime.csv (stage cadence_regime, M379a rule: fast = master I_sample_period_s < 1.05 s, slow otherwise, null = no HV-current samples) and keeps
analyses/cadence_monitor.json: the last drive seen, the expected regime, the flag history. First run BOOTSTRAPS (records the last drive, no flags); every later run looks only at drives after it:
  cadence_slow_while_fast_expected  one or more new drives are slow: first slow drive, how many of the new drives, their median interval, the reference medians of the fast and slow regimes
                                    taken from the sidecar before the batch, and whether the interval is slower than the earlier slow regime (the Oct-8 'third setting')
  fast_polling_confirmed (info)     every new drive with a regime is fast
  cadence_unknown (info)            new drives without a regime (fewer than three HV-current samples)
Never stops an ingestion (main() prints monitor_error and exits 0 on an unexpected failure); a run with no new drives leaves the file untouched; a flag is recorded in flag_history once per first slow drive.
Usage: python tools/cadence_monitor.py update [--state PATH] [--sidecar PATH]"""
import argparse, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pandas as pd

STATE = os.path.join(ROOT, "analyses", "cadence_monitor.json")
SIDECAR = os.path.join(ROOT, "cadence_regime.csv")
EXPECTED, EXPECTED_SINCE = "fast", "2026-10-09"           # owner re-activated fast polling (chat, 2026-10-09); applies to drives ingested after the bootstrap
SLOWER_FACTOR = 1.10                                       # 'slower than the earlier slow regime' = batch median > 1.10 x the reference slow median
RULE = ("regime per drive from the sidecar (fast: master I_sample_period_s < 1.05 s, M379a); flag = a new drive is slow while fast polling is expected (owner re-activated it 2026-10-09); "
        "report-only; thresholds fixed and not tuned (analyses/M396_spec.md)")


def key_of(r):
    return [str(r["date"]), str(r["time_start"]), str(r["file"])]


def _med(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return round(float(s.median()), 3) if len(s) else None


def update(side, state_path=STATE):
    """side: sidecar frame (file, date, time_start, I_sample_period_s, regime). Returns the state (written when something changed)."""
    state = json.load(open(state_path, encoding="utf-8")) if os.path.exists(state_path) else None
    s = side.copy()
    s["date"], s["time_start"], s["file"] = s["date"].astype(str), s["time_start"].astype(str), s["file"].astype(str)
    s = s.sort_values(["date", "time_start", "file"], kind="stable").reset_index(drop=True)
    keys = list(zip(s["date"], s["time_start"], s["file"]))
    if state is None:                                           # bootstrap: baseline = the corpus as it is now, no flags
        last = s.iloc[-1]
        out = {"rule": RULE, "expected_regime": EXPECTED, "expected_since": EXPECTED_SINCE, "bootstrap": True, "n_drives_at_bootstrap": int(len(s)),
               "last_seen": key_of(last), "last_regime": None if pd.isna(last["regime"]) else str(last["regime"]),
               "last_update": {"n_new_drives": int(len(s)), "flags": [], "n_flags": 0}, "flag_history": []}
        _write(out, state_path)
        return out
    last_key = tuple(state["last_seen"])
    new = s[[k > last_key for k in keys]]
    if not len(new):
        return state                                            # nothing new: file untouched (a pipeline rerun cannot erase an alert)
    old = s[[k <= last_key for k in keys]]
    ref_fast = _med(old[old["regime"] == "fast"].tail(30)["I_sample_period_s"])
    ref_slow = _med(old[old["regime"] == "slow"]["I_sample_period_s"])
    flags = []
    slow, fast, unk = new[new["regime"] == "slow"], new[new["regime"] == "fast"], new[new["regime"].isna()]
    if len(slow):
        f0 = slow.iloc[0]
        med = _med(slow["I_sample_period_s"])
        flags.append({"flag": "cadence_slow_while_fast_expected", "first_slow_file": str(f0["file"]), "first_slow_date": str(f0["date"]), "first_slow_time": str(f0["time_start"]),
                      "n_slow_new": int(len(slow)), "n_new": int(len(new)), "n_fast_new": int(len(fast)), "median_interval_new_slow_s": med,
                      "reference_fast_median_s": ref_fast, "reference_slow_median_s": ref_slow,
                      "slower_than_reference_slow": bool(med is not None and ref_slow is not None and med > SLOWER_FACTOR * ref_slow),
                      "after_fast_in_batch_or_before": bool(len(fast) > 0 and fast.index.min() < slow.index.min()) or state.get("last_regime") == "fast",
                      "action": "check the app PID / polling settings (HV-current channel); fast polling was re-activated on 2026-10-09 and is expected"})
    elif len(fast):
        flags.append({"flag": "fast_polling_confirmed", "info": True, "n_new": int(len(new)), "n_fast_new": int(len(fast)), "median_interval_new_s": _med(fast["I_sample_period_s"])})
    if len(unk):
        flags.append({"flag": "cadence_unknown", "info": True, "n": int(len(unk)), "note": "no regime (fewer than three HV-current samples): not evaluable, not a pass"})
    last = new.iloc[-1]
    history = list(state.get("flag_history", []))
    for x in flags:
        if not x.get("info") and not any(h.get("flag") == x["flag"] and h.get("first_slow_file") == x["first_slow_file"] for h in history):
            history.append(dict(x, recorded_with_last_file=str(last["file"])))
    out = dict(state, bootstrap=False, last_seen=key_of(last), last_regime=None if pd.isna(last["regime"]) else str(last["regime"]),
               last_update={"n_new_drives": int(len(new)), "flags": flags, "n_flags": len([x for x in flags if not x.get("info")])}, flag_history=history)
    _write(out, state_path)
    return out


def _write(out, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True, ensure_ascii=False, default=float)


def main():
    """Report-only: an unexpected failure is printed as monitor_error and the stage still exits 0 (it can never stop an ingestion)."""
    try:
        return _main()
    except SystemExit:
        raise
    except Exception as ex:
        print(json.dumps({"status": "monitor_error", "error": repr(ex)[:300], "note": "report-only stage: ingestion continues; the cadence monitor did not update"}))
        return 0


def _main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["update"]); ap.add_argument("--state", default=STATE); ap.add_argument("--sidecar", default=SIDECAR); a = ap.parse_args()
    out = update(pd.read_csv(a.sidecar), a.state)
    lu = out["last_update"]
    print(json.dumps({"bootstrap": out["bootstrap"], "expected_regime": out["expected_regime"], "n_new": lu["n_new_drives"], "n_flags": lu["n_flags"], "last_regime": out["last_regime"]}))
    for x in lu["flags"]:
        print(("INFO " if x.get("info") else "FLAG ") + json.dumps(x, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
