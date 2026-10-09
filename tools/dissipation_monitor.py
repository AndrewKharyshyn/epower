#!/usr/bin/env python3
"""M394 (analyses/M394_spec.md): ingestion monitor for the unfuelled (motored) dissipation mode. REPORT-ONLY: never stops an ingestion, never touches the master or the payload.
State file analyses/dissipation_monitor.json = one record per drive (additive, deterministic, no timestamps) + coverage by pack-temperature band + the flags of the last update.
First run (no state) BOOTSTRAPS the baseline from the whole corpus without flags; every later run records the drives it has not seen and flags each new drive against the records of all EARLIER drives:
  first_sustained_in_band   a sustained event in a pack-temperature band that had none before (bands <5, 5-10, 10-15, 15-25, >=25 C): the first winter observation
  below_baseline_soc        a sustained event whose mean SoC is more than 5 pp below every earlier sustained event (cold packs accept less charge: expected winter shift)
  fuel_event_not_in_census  a sustained FUEL-confirmed unfuelled event the published classifier does not see (detector gap)
  census_event_not_fuel_confirmed  a sustained census event with a logged fuel rate >= 0.2 L/h on a drive that carries the fuel channel (possible false positive)
  channel_gap               the drive lacks rpm / boost / load / SoC: not evaluable (never a pass); fuel_indicator_unavailable (info) when only the fuel channels are missing
  sustained_event_unknown_temperature  a sustained event on a drive without a pack temperature (band 'unknown'): no band logic is applied (never counted as a cold or warm band)
  read_error                a raw file that cannot be parsed: the drive is NOT recorded (retried at the next run) and the batch continues; raw_file_missing (info) when the file is absent
  census_event_fuel_unknown (info)  a sustained census event with no logged fuel rate inside the event on a drive that carries the fuel channel
'Earlier' = drives with (date, file) before this drive's (date, file), so a backfilled older drive is compared with older drives only. A recorded drive is never recomputed: its pack-temperature
band is the one at first recording (a later master with a changed T_pack_mean_avg does not move it). Event duration counts grid rows after dropping rows with a missing needed channel (a run can
bridge short channel gaps). The 1 s grid bins are aligned to the wall-clock second (pandas resample on the time-of-day index), NOT to the first row: the counts depend on that phase.
The grid is anchored at 1900-01-01: a drive crossing midnight would wrap (no corpus drive does).
Events and detectors: tools/dissipation_events.py. Wording: 'logged / app-calculated', hypothesis not observation until a cold drive has a sustained event; never 'proven'.
Usage: python tools/dissipation_monitor.py update [--state PATH] [--raw-dir DIR]"""
import argparse, glob, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import dissipation_events as DE

STATE = os.path.join(ROOT, "analyses", "dissipation_monitor.json")
BANDS = [("<5C", -1e9, 5.0), ("5-10C", 5.0, 10.0), ("10-15C", 10.0, 15.0), ("15-25C", 15.0, 25.0), (">=25C", 25.0, 1e9)]
SOC_MARGIN_PP = 5.0
RULE = ("PUB = rpm>2000 & boost<-0.70 & load<8; FUEL = rpm>1200 & logged fuel<0.2 L/h & throttle B<10%; event >= 3 s; sustained = >= 10 s and |rpm slope| < 30 rpm/s; "
        "flags are report-only, thresholds fixed and not tuned (analyses/M394_spec.md); thresholds were set on data with pack temperature >= 9.7 C: unvalidated for cold")


def band_of(t):
    if t is None or t != t:
        return "unknown"
    return next(n for n, lo, hi in BANDS if lo <= t < hi)


def record_for(file, date, t_pack, csv_bytes):
    g = DE.grid_from_csv_bytes(csv_bytes)
    pub, fuel = DE.detect(g, "PUB"), DE.detect(g, "FUEL")
    rec = {"file": file, "date": str(date), "T_pack": None if t_pack is None or t_pack != t_pack else round(float(t_pack), 1), "band": band_of(t_pack),
           "channels": DE.channels(g), "pub_evaluable": pub is not None, "fuel_evaluable": fuel is not None,
           "pub_events": pub or [], "fuel_only_sustained": [], "pub_sustained_unconfirmed": []}
    if pub is not None and fuel is not None:
        rec["fuel_only_sustained"] = [e for e in fuel if e["sustained"] and not any(DE.overlaps(e, p) for p in pub)]
        rec["pub_sustained_unconfirmed"] = [p for p in pub if p["sustained"] and p["fuel_mean"] is not None and p["fuel_mean"] >= DE.FUEL_MAX_LH]
    elif pub is None and fuel is not None:
        rec["fuel_only_sustained"] = [e for e in fuel if e["sustained"]]            # census channels missing: the fuel indicator is the only detector
    return rec


def sustained_events(rec):
    return [dict(e, source="PUB") for e in rec["pub_events"] if e["sustained"]] + [dict(e, source="FUEL") for e in rec["fuel_only_sustained"]]


def flags_for(rec, earlier):
    """earlier: records of all drives before this one (time order)."""
    fl = []
    if not rec["pub_evaluable"]:
        fl.append({"flag": "channel_gap", "file": rec["file"], "note": "rpm / boost / load / SoC missing: census classifier not evaluable (not a pass)"})
    if not rec["fuel_evaluable"]:
        fl.append({"flag": "fuel_indicator_unavailable", "file": rec["file"], "info": True})
    prior = [e for r in earlier for e in sustained_events(r)]
    prior_bands = {r["band"] for r in earlier if sustained_events(r) and r["band"] != "unknown"}
    min_soc = min((e["soc_mean"] for e in prior), default=None)
    for e in sustained_events(rec):
        if rec["band"] == "unknown":
            fl.append({"flag": "sustained_event_unknown_temperature", "file": rec["file"], "source": e["source"], "dur_s": e["dur_s"], "rpm_mean": e["rpm_mean"], "soc_mean": e["soc_mean"]})
        elif rec["band"] not in prior_bands:
            fl.append({"flag": "first_sustained_in_band", "file": rec["file"], "band": rec["band"], "T_pack": rec["T_pack"], "source": e["source"], "dur_s": e["dur_s"],
                       "rpm_mean": e["rpm_mean"], "soc_mean": e["soc_mean"]})
            prior_bands = prior_bands | {rec["band"]}
        if min_soc is not None and e["soc_mean"] < min_soc - SOC_MARGIN_PP:
            fl.append({"flag": "below_baseline_soc", "file": rec["file"], "soc_mean": e["soc_mean"], "baseline_min_soc_mean": min_soc, "band": rec["band"], "source": e["source"], "dur_s": e["dur_s"]})
    for e in rec["fuel_only_sustained"]:
        if rec["pub_evaluable"]:
            fl.append({"flag": "fuel_event_not_in_census", "file": rec["file"], "dur_s": e["dur_s"], "rpm_mean": e["rpm_mean"], "soc_mean": e["soc_mean"], "band": rec["band"],
                       "note": "fuel-indicated unfuelled (unconfirmed by census; low-power fuelled generation not ruled out)"})
    for p in rec["pub_sustained_unconfirmed"]:
        fl.append({"flag": "census_event_not_fuel_confirmed", "file": rec["file"], "dur_s": p["dur_s"], "fuel_mean_Lh": p["fuel_mean"], "band": rec["band"]})
    if rec["fuel_evaluable"] and rec["pub_evaluable"]:
        for p in rec["pub_events"]:
            if p["sustained"] and p["fuel_mean"] is None:
                fl.append({"flag": "census_event_fuel_unknown", "file": rec["file"], "dur_s": p["dur_s"], "info": True})
    return fl


def summarise(records):
    cov = {n: {"drives": 0, "drives_pub_evaluable": 0, "drives_with_sustained": 0, "sustained_events": 0} for n, _, _ in BANDS}
    cov["unknown"] = dict(cov[">=25C"])
    for k in cov["unknown"]:
        cov["unknown"][k] = 0
    for r in records:
        c = cov[r["band"]]
        c["drives"] += 1; c["drives_pub_evaluable"] += int(r["pub_evaluable"])
        s = sustained_events(r)
        c["drives_with_sustained"] += int(bool(s)); c["sustained_events"] += len(s)
    allsus = [e for r in records for e in sustained_events(r)]
    return {"n_drives": len(records), "coverage_by_pack_temperature_band": cov,
            "validation_gap_bands_without_sustained_event": [n for n, _, _ in BANDS if cov[n]["sustained_events"] == 0],
            "n_sustained_events": len(allsus), "sustained_soc_mean_min": min((e["soc_mean"] for e in allsus), default=None),
            "sustained_soc_mean_max": max((e["soc_mean"] for e in allsus), default=None),
            "sustained_rpm_mean_range": [min((e["rpm_mean"] for e in allsus), default=None), max((e["rpm_mean"] for e in allsus), default=None)],
            "drives_with_fuel_channels": sum(1 for r in records if r["fuel_evaluable"])}


def update(dm, loader, state_path=STATE):
    """dm: master frame (file, date, time_start, T_pack_mean_avg); loader(file) -> csv bytes or None. Returns the new state (also written)."""
    state = json.load(open(state_path, encoding="utf-8")) if os.path.exists(state_path) else None
    seen = (state or {}).get("drives", {})
    order = dm.sort_values(["date", "time_start"], kind="stable") if "time_start" in dm.columns else dm.sort_values("date", kind="stable")
    drives, flags, new_files = dict(seen), [], []
    bootstrap = state is None
    for _, row in order.iterrows():
        f = str(row["file"])
        if f in seen:
            continue
        b = loader(f)
        if b is None:
            if not bootstrap:
                flags.append({"flag": "raw_file_missing", "file": f, "info": True})
            continue
        try:
            rec = record_for(f, row["date"], row.get("T_pack_mean_avg"), b)
        except Exception as ex:                                  # report-only: one unreadable file never stops the batch; not recorded, retried at the next run
            flags.append({"flag": "read_error", "file": f, "error": repr(ex)[:200], "note": "not evaluable (not a pass); not recorded"})
            continue
        if not bootstrap:
            earlier = [drives[k] for k in sorted(drives, key=lambda k: (drives[k]["date"], k)) if (drives[k]["date"], k) < (rec["date"], rec["file"])]
            flags += flags_for(rec, earlier)
        drives[f] = rec
        new_files.append(f)
    if state is not None and not new_files and not any(not x.get("info") for x in flags):
        return state                                    # nothing new: leave the file (and the last run's flags) untouched, so a pipeline rerun cannot erase an alert
    recs = [drives[k] for k in sorted(drives, key=lambda k: (drives[k]["date"], k))]
    history = list((state or {}).get("flag_history", []))
    strip = lambda d: {k: v for k, v in d.items() if k != "recorded_with_n_drives"}
    for x in flags:
        same = (lambda h: h.get("flag") == x["flag"] and h.get("file") == x.get("file")) if x["flag"] == "read_error" else (lambda h: strip(h) == x)
        if not x.get("info") and not any(same(h) for h in history):          # a persistent read_error is recorded once per file, whatever its message
            history.append(dict(x, recorded_with_n_drives=len(recs)))
    out = {"rule": RULE, "note": "report-only; hypothesis (cold pack => more unfuelled dissipation) not yet observed until a cold drive has a sustained event; fuel rate is logged / app-calculated; thresholds set on data >= 9.7 C pack temperature, unvalidated for cold; pack temperature is the temperature axis (intake-air channel unavailable since 2026-08-24)",
           "bootstrap": bootstrap, "summary": summarise(recs), "last_update": {"n_new_drives": len(new_files), "new_files": new_files if len(new_files) <= 60 else new_files[:60] + ["..."],
                                                                              "flags": flags, "n_flags": len([x for x in flags if not x.get("info")])},
           "flag_history": history, "drives": drives}
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True, ensure_ascii=False, default=float)
    return out


def main():
    """Report-only: an unexpected failure (unreadable master or state file) is printed as monitor_error and the stage still exits 0, so the monitor can never stop an ingestion.
    The message is loud in the run log; the state file is left as it was."""
    try:
        return _main()
    except SystemExit:
        raise
    except Exception as ex:
        print(json.dumps({"status": "monitor_error", "error": repr(ex)[:300], "note": "report-only stage: ingestion continues; the dissipation monitor did not update"}))
        return 0


def _main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["update"]); ap.add_argument("--state", default=STATE)
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")); a = ap.parse_args()
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    stage = os.path.join(ROOT, "raw_only")
    idx = {re.sub(r"\D", "", os.path.basename(p)): p for p in glob.glob(os.path.join(a.raw_dir, "*.csv"))}

    def loader(f):
        p = os.path.join(stage, f)
        if not os.path.exists(p):
            p = idx.get(re.sub(r"\D", "", f))
        return open(p, "rb").read() if p and os.path.exists(p) else None
    out = update(dm, loader, a.state)
    s, lu = out["summary"], out["last_update"]
    print(json.dumps({"bootstrap": out["bootstrap"], "n_drives": s["n_drives"], "n_new": lu["n_new_drives"], "n_flags": lu["n_flags"],
                      "sustained_events": s["n_sustained_events"], "validation_gap_bands": s["validation_gap_bands_without_sustained_event"]}))
    for x in lu["flags"]:
        print("FLAG", json.dumps(x, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
