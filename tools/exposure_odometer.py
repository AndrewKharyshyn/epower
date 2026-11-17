#!/usr/bin/env python3
"""M713b (spec analyses/M712_spec.md Rev 1.1, sections 4 and 5, item S4): logged share of the dashboard odometer and the unlogged-day classifier.

The master "odometer" is the logger-app counter and cannot see driving while the app is off; the DASHBOARD odometer readings the owner gives at each ingestion ("ODO: <km>", as of the end of the newest ingested
drive, CLAUDE.md) are the ground truth. Between two readings: unlogged km = dash km - logged km (speed-integral km of the exposure frame on the days after the first reading up to and including the second).
Rules (pre-registered in the spec, section 4):
  * an interval with a logged share below SHARE_UNLOGGED (0.5) is an UNLOGGED interval: its days (after the first reading up to and including the second) without any logged drive are UNLOGGED days (excluded from the replay pools, never parked time);
  * every other day without a logged drive is a TRUE zero-drive day (kept in the pools as an empty day);
  * f_s / f_a = dash km / logged km of the summer window (intervals ending on or before SUMMER_END) / of the later intervals without the unlogged intervals (ASSUMPTION ranged in analyses/M712_ranges.json).
Readings live in a tracked sidecar (analyses/M713/odometer_readings.json: asOf, km, source), extended at each ingestion from summary_config.json (`--extend`); `--backfill-git` mines the history of the
config (development tool; the CI checkout has no history). Reading dates are as-of end of day (about one day of ambiguity).
Usage: python tools/exposure_odometer.py [--dir analyses/M713] [--extend] [--backfill-git]   writes <dir>/odometer_check.json"""
import argparse, json, os, subprocess, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SHARE_UNLOGGED = 0.5
SUMMER_END = "2026-09-09"


def load_readings(path):
    r = json.load(open(path, encoding="utf-8"))["readings"]
    return sorted(r, key=lambda x: x["asOf"])


def extend_from_config(path, cfg_path=None):
    """Append the current summary_config.json vehicle reading (odometerKm, odometerAsOf) when it is new. Returns the number of readings added (0 or 1)."""
    cfg = json.load(open(cfg_path or os.path.join(ROOT, "summary_config.json"), encoding="utf-8")).get("vehicle", {})
    km, asof = cfg.get("odometerKm"), cfg.get("odometerAsOf")
    if km is None or not asof:
        return 0
    d = json.load(open(path, encoding="utf-8"))
    if any(x["asOf"] == asof for x in d["readings"]):
        have = [x for x in d["readings"] if x["asOf"] == asof][0]
        if have["km"] != km:
            raise RuntimeError("odometer reading for %s differs: sidecar %s, config %s" % (asof, have["km"], km))
        return 0
    d["readings"].append({"asOf": asof, "km": km, "source": "summary_config.json vehicle.odometerKm (owner, ingestion)"})
    d["readings"].sort(key=lambda x: x["asOf"])
    json.dump(d, open(path, "w", encoding="utf-8"), indent=1)
    return 1


def backfill_git(path):
    hs = subprocess.check_output(["git", "log", "--format=%H", "-G\"odometerKm\"", "--", "summary_config.json"], cwd=ROOT).decode().split()
    d = json.load(open(path, encoding="utf-8"))
    have = {x["asOf"]: x for x in d["readings"]}
    n = 0
    for h in hs:
        try:
            v = json.loads(subprocess.check_output(["git", "show", "%s:summary_config.json" % h], cwd=ROOT, stderr=subprocess.DEVNULL).decode("utf-8")).get("vehicle", {})
        except Exception:
            continue
        if v.get("odometerAsOf") and v.get("odometerKm") and v["odometerAsOf"] not in have:
            have[v["odometerAsOf"]] = {"asOf": v["odometerAsOf"], "km": v["odometerKm"], "source": "git history of summary_config.json (%s)" % h[:7]}
            n += 1
    d["readings"] = sorted(have.values(), key=lambda x: x["asOf"])
    json.dump(d, open(path, "w", encoding="utf-8"), indent=1)
    return n


def check(D, readings, share_unlogged=SHARE_UNLOGGED, summer_end=SUMMER_END, first_day=None, last_day=None):
    """D: exposure frame (columns day, km). readings: sorted list of {asOf, km}. Returns the check dict (intervals, unlogged days, zero-drive days, factors)."""
    daykm = D.groupby("day")["km"].sum()
    rows = []
    for a, b in zip(readings[:-1], readings[1:]):
        m = (daykm.index > a["asOf"]) & (daykm.index <= b["asOf"])
        odo = b["km"] - a["km"]
        lg = float(daykm[m].sum())
        rows.append({"from": a["asOf"], "to": b["asOf"], "odoKm": odo, "loggedKm": round(lg, 1), "share": round(lg / odo, 3) if odo > 0 else None, "unloggedKm": round(odo - lg, 1)})
    first = first_day or (D["day"].min() if len(D) else None)
    last = last_day or (D["day"].max() if len(D) else None)
    alldays = pd.date_range(first, last).strftime("%Y-%m-%d")
    withdrive = set(D.loc[D["km"] > 0, "day"]) | set(D["day"])
    unl, zero, unc = [], [], []
    low = [r for r in rows if r["share"] is not None and r["share"] < share_unlogged]
    first_read, last_read = readings[0]["asOf"], readings[-1]["asOf"]
    for dday in alldays:
        if dday in withdrive:
            continue
        if dday <= first_read or dday > last_read:               # no odometer cover: the data rule cannot tell zero-drive from unlogged -> ambiguous, listed, excluded by the engine (spec Q5)
            unc.append(dday)
            continue
        inside_low = any(r["from"] < dday <= r["to"] for r in low)       # the interval is (from, to]: the day of the later reading belongs to it
        (unl if inside_low else zero).append(dday)
    summer = [r for r in rows if r["to"] <= summer_end]
    later = [r for r in rows if r["from"] >= summer_end and r not in low]
    f = lambda rs: round(sum(r["odoKm"] for r in rs) / sum(r["loggedKm"] for r in rs), 4) if rs and sum(r["loggedKm"] for r in rs) > 0 else None
    tot = [r for r in rows]
    return {"rows": rows, "unloggedIntervals": [[r["from"], r["to"]] for r in low], "unloggedDays": unl, "zeroDriveDays": zero, "noOdometerCoverDays": unc,
            "factors": {"f_s_summerWindow": f(summer), "f_a_laterIntervalsWithoutUnlogged": f(later), "summerIntervals": len(summer), "laterIntervals": len(later)},
            "total": {"odoKm": sum(r["odoKm"] for r in tot), "loggedKm": round(sum(r["loggedKm"] for r in tot), 1),
                      "share": round(sum(r["loggedKm"] for r in tot) / max(sum(r["odoKm"] for r in tot), 1), 3)},
            "rule": "interval share < %.2f -> days without a logged drive inside it are UNLOGGED; other empty days are true zero-drive days" % share_unlogged,
            "label": "dashboard odometer readings (owner, as of end of day) against speed-integral km of the exposure frame; the logger-app counter is NOT used"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "analyses", "M713"))
    ap.add_argument("--extend", action="store_true")
    ap.add_argument("--backfill-git", action="store_true")
    a = ap.parse_args(argv)
    rp = os.path.join(a.dir, "odometer_readings.json")
    if a.backfill_git:
        print("backfilled", backfill_git(rp))
    if a.extend:
        print("extended", extend_from_config(rp))
    D = pd.read_csv(os.path.join(a.dir, "exposure_drives.csv"), dtype={"key": str}, usecols=["key", "day", "km"])
    out = check(D, load_readings(rp))
    json.dump(out, open(os.path.join(a.dir, "odometer_check.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({"total": out["total"], "factors": out["factors"], "unloggedDays": [out["unloggedDays"][0], out["unloggedDays"][-1], len(out["unloggedDays"])] if out["unloggedDays"] else [], "nZeroDriveDays": len(out["zeroDriveDays"]), "nNoCoverDays": len(out["noOdometerCoverDays"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
