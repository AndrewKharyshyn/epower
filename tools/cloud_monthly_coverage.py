#!/usr/bin/env python3
"""M776: monthly OBD distance beside speed-supported cloud movement outside the OBD logs (auxiliary, aggregates only).
Spec: analyses/M776_spec.md Rev 2 (rules frozen there; nothing here changes a threshold). Writes analyses/M776_cloud_monthly.json.
Usage: python tools/cloud_monthly_coverage.py [--store DIR] [--raw-dir DIR] [--master CSV] [--out analyses/M776_cloud_monthly.json]"""
import argparse, bisect, csv, glob, hashlib, itertools, json, os, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

KYIV = ZoneInfo("Europe/Kyiv")
PINNED_MD5 = "d514d6009d6d9a0a168ad4fb09b9bb98"
MAX_KMH = 180.0
PRIMARY = {"pad": 45.0, "shift": 0.0, "near": 25.0, "floor": 2.0, "gap": 35.0}
GRID = {"pad": (30.0, 45.0, 60.0), "shift": (-16.0, 0.0, 16.0), "near": (20.0, 25.0), "floor": (0.0, 2.0), "gap": (25.0, 35.0, 45.0)}
SMALL_KM = 50.0
RESOLUTION_KM = 5.0


# ------------------------------------------------------------------ pure functions (known-answer tested)
def local_month(t):
    return datetime.fromtimestamp(t, KYIV).strftime("%Y-%m")


def local_date(t):
    return datetime.fromtimestamp(t, KYIV).strftime("%Y-%m-%d")


def parse_local(date_s, time_s):
    """Kyiv wall time -> (utc epoch, ambiguous). Full local timestamp to UTC before any interval arithmetic (spec section 1)."""
    naive = datetime.strptime(date_s + " " + time_s[:8], "%Y-%m-%d %H:%M:%S")
    a, b = naive.replace(tzinfo=KYIV, fold=0), naive.replace(tzinfo=KYIV, fold=1)
    return a.timestamp(), a.utcoffset() != b.utcoffset()


def merge_windows(windows, pad):
    """windows: list of (t0, t1) epochs. Returns merged padded (starts, ends)."""
    iv = sorted((a - pad, b + pad) for a, b in windows)
    out = []
    for a, b in iv:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [a for a, _ in out], [b for _, b in out]


def overlaps(starts, ends, t1, t2):
    i = bisect.bisect_right(starts, t2) - 1
    return i >= 0 and ends[i] >= t1


def speed_supported(st, sv, t, near, floor):
    """Spec section 3: a speed sample within `near` s of the step midpoint with speed above `floor` (ANY such sample, not only the nearest)."""
    i = bisect.bisect_left(st, t - near)
    while i < len(st) and st[i] <= t + near:
        if sv[i] > floor:
            return True
        i += 1
    return False


def classify(odo, spd, windows, p):
    """odo, spd: sorted lists of (epoch_utc, value). windows: raw (t0, t1) pairs. p: parameter dict. Returns a list of records
    {t1, t2, km, cls} with cls in: step_outside, step_inside, g1, g2, rej_negative, rej_speed, rej_nosupport."""
    starts, ends = merge_windows(windows, p["pad"])
    st = [t for t, _ in spd]
    sv = [v for _, v in spd]
    out = []
    for (t1, o1), (t2, o2) in zip(odo, odo[1:]):
        dt, d = t2 - t1, o2 - o1
        if dt <= 0 or d < 0:
            out.append({"t1": t1, "t2": t2, "km": d, "cls": "rej_negative"})
            continue
        if d == 0:
            continue
        a, b = t1 + p["shift"], t2 + p["shift"]
        ov = overlaps(starts, ends, a, b)
        if dt > p["gap"]:
            out.append({"t1": t1, "t2": t2, "km": d, "cls": "g2" if ov else "g1"})
            continue
        if d / dt * 3600.0 > MAX_KMH:
            out.append({"t1": t1, "t2": t2, "km": d, "cls": "rej_speed"})
            continue
        if not speed_supported(st, sv, (t1 + t2) / 2.0, p["near"], p["floor"]):
            out.append({"t1": t1, "t2": t2, "km": d, "cls": "rej_nosupport"})
            continue
        out.append({"t1": t1, "t2": t2, "km": d, "cls": "step_inside" if ov else "step_outside"})
    return out


def month_of(rec):
    m1, m2 = local_month(rec["t1"]), local_month(rec["t2"])
    return m1 if m1 == m2 else "month unknown"


def aggregate(recs, t_lo, t_hi):
    """Per Kyiv month: km and counts of each class, inside [t_lo, t_hi]. Month-spanning records go to 'month unknown'."""
    months = {}
    for r in recs:
        if r["t1"] < t_lo or r["t2"] > t_hi:
            continue
        m = months.setdefault(month_of(r), {})
        c = m.setdefault(r["cls"], {"km": 0.0, "n": 0, "days": set()})
        c["km"] += r["km"]
        c["n"] += 1
        c["days"].add(local_date(r["t1"]))
    return months


def obd_by_month(master_rows, t_lo, t_hi):
    """master_rows: dicts with t0, km, file. E1: km, drives, days by Kyiv month of the drive start, inside the export span."""
    m = {}
    for r in master_rows:
        if not (t_lo <= r["t0"] <= t_hi):
            continue
        k = local_month(r["t0"])
        x = m.setdefault(k, {"km": 0.0, "drives": 0, "days": set()})
        x["km"] += r["km"]
        x["drives"] += 1
        x["days"].add(local_date(r["t0"]))
    return m


def summarise(months):
    return {k: {c: {"km": round(v["km"], 3), "n": v["n"], "days": len(v["days"])} for c, v in cl.items()} for k, cl in months.items()}


# ------------------------------------------------------------------ data loading
def raw_windows(raw_dir):
    """[start, end] of EVERY raw OBD csv (file name start in Kyiv time + first/last time-of-day, midnight rollover handled)."""
    out, notes = [], {"files": 0, "ambiguous_start": 0, "unparsed": []}
    for f in sorted(glob.glob(os.path.join(raw_dir, "*.csv"))):
        base = os.path.basename(f)
        try:
            d, tm = base[:10], base[11:19].replace("-", ":")
            t0, amb = parse_local(d, tm)
        except ValueError:
            notes["unparsed"].append(base)
            continue
        try:
            with open(f, "rb") as fh:
                fh.readline()
                first = fh.readline().decode("utf-8", "ignore").split(",")[0]
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - 4096))
                lines = [x for x in fh.read().decode("utf-8", "ignore").splitlines() if x.strip()]
            last = lines[-1].split(",")[0]
            tf = datetime.strptime(first[:8], "%H:%M:%S")
            tl = datetime.strptime(last[:8], "%H:%M:%S")
            dur = (tl - tf).total_seconds()
            if dur < 0:
                dur += 86400.0
        except (ValueError, IndexError):
            notes["unparsed"].append(base)
            continue
        out.append((t0, t0 + dur, base))
        notes["files"] += 1
        notes["ambiguous_start"] += int(amb)
    return out, notes


def master_rows(path):
    rows = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig", newline="")):
        try:
            t0, _ = parse_local(r["date"], r["time_start"])
            rows.append({"file": r["file"], "t0": t0, "t1": t0 + float(r["duration_s"]), "km": float(r.get("distance_km") or 0.0)})
        except (ValueError, KeyError):
            continue
    rows.sort(key=lambda x: x["t0"])
    return rows


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def reporting_gaps(odo, spd, t_lo, t_hi):
    """Calendar dates (Kyiv) inside the span with no odometer and no speed sample, and holes of at least 24 h between odometer samples."""
    have = {local_date(t) for t, _ in odo} | {local_date(t) for t, _ in spd}
    d = datetime.fromtimestamp(t_lo, KYIV).date()
    end = datetime.fromtimestamp(t_hi, KYIV).date()
    missing = []
    while d <= end:
        if d.isoformat() not in have:
            missing.append(d.isoformat())
        d += timedelta(days=1)
    holes = [{"from": local_date(a), "to": local_date(b), "hours": round((b - a) / 3600.0, 1)} for (a, _), (b, _) in zip(odo, odo[1:]) if b - a >= 86400.0]
    return missing, holes


# ------------------------------------------------------------------ main
def run(store, raw_dir, master_path, out_path):
    import mynissan_unlogged as mu
    odo, spd, _ = mu.load_streams(store)
    t_lo, t_hi = odo[0][0], odo[-1][0]
    rows = master_rows(master_path)
    wins_all, wnotes = raw_windows(raw_dir)
    windows = [(a, b) for a, b, _ in wins_all]
    digits = lambda n: "".join(ch for ch in n[:19] if ch.isdigit())   # master names come as 20260511_185709 and 2026-11-20_09-02-32
    master_keys = {digits(r["file"]) for r in rows}
    extra = [n for _, _, n in wins_all if digits(n) not in master_keys]   # raw OBD files that are not master drives (comparison-only): still OBD windows
    study_lo = max(t_lo, min(a for a, _ in windows))

    def agg_for(p):
        recs = classify(odo, spd, windows, p)
        return recs, aggregate(recs, study_lo, t_hi)

    recs, base = agg_for(PRIMARY)
    obd = obd_by_month(rows, study_lo, t_hi)
    months = sorted(set(base) | set(obd))
    # full-factorial sensitivity of E2 per month
    keys = list(GRID)
    lo, hi = {}, {}
    lo2, hi2 = {}, {}   # same grid without the step-gap point below the nominal 30 s cadence (see "gridNote")
    n_comb = 0
    for combo in itertools.product(*(GRID[k] for k in keys)):
        p = dict(zip(keys, combo))
        _, a = agg_for(p)
        n_comb += 1
        for m in months:
            v = a.get(m, {}).get("step_outside", {"km": 0.0})["km"]
            lo[m] = min(lo.get(m, v), v)
            hi[m] = max(hi.get(m, v), v)
            if p["gap"] >= 35.0:
                lo2[m] = min(lo2.get(m, v), v)
                hi2[m] = max(hi2.get(m, v), v)
    ofat = {}
    for k in keys:
        for val in GRID[k]:
            p = dict(PRIMARY)
            p[k] = val
            _, a = agg_for(p)
            ofat.setdefault(k, {})[str(val)] = {m: round(a.get(m, {}).get("step_outside", {"km": 0.0})["km"], 3) for m in months}
    # per-month table
    out_m = []
    first_m, last_m = months[0], months[-1]
    for m in months:
        c = base.get(m, {})
        e2 = c.get("step_outside", {"km": 0.0, "n": 0, "days": set()})
        g1 = c.get("g1", {"km": 0.0, "n": 0, "days": set()})
        g2 = c.get("g2", {"km": 0.0, "n": 0, "days": set()})
        ins = c.get("step_inside", {"km": 0.0})
        o = obd.get(m, {"km": 0.0, "drives": 0, "days": set()})
        e2km = e2["km"]
        out_m.append({
            "month": m, "partial": m in (first_m, last_m) and m != "month unknown",
            "obdKm": round(o["km"], 1), "obdDrives": o["drives"], "obdDays": len(o["days"]),
            "cloudOutsideKm": round(e2km, 1), "cloudOutsideSteps": e2["n"], "cloudOutsideDays": len(e2["days"]),
            "e2SensitivityMinKm": round(lo.get(m, 0.0), 1), "e2SensitivityMaxKm": round(hi.get(m, 0.0), 1),
            "e2SensitivityMinKmGap35Plus": round(lo2.get(m, 0.0), 1), "e2SensitivityMaxKmGap35Plus": round(hi2.get(m, 0.0), 1),
            "small": e2km <= SMALL_KM,
            "g1Km": round(g1["km"], 1), "g1N": g1["n"], "g2Km": round(g2["km"], 1), "g2N": g2["n"],
            "definitionRangeKm": [round(e2km, 1), round(e2km + g1["km"], 1)],
            "cloudInsideLogsKm": round(ins["km"], 1),
            "captureInsideLogs": round(ins["km"] / o["km"], 3) if o["km"] > 0 else None,
        })
    # per-day listing for days with movement outside the logs and the D4 cases
    byday = {}
    for r in recs:
        if r["cls"] in ("step_outside", "g1", "g2") and study_lo <= r["t1"] and r["t2"] <= t_hi:
            x = byday.setdefault(local_date(r["t2"]), {"e2": 0.0, "g1": 0.0, "g2": 0.0})
            x[{"step_outside": "e2", "g1": "g1", "g2": "g2"}[r["cls"]]] += r["km"]
    obd_days = {}
    for r in rows:
        if study_lo <= r["t0"] <= t_hi:
            obd_days[local_date(r["t0"])] = obd_days.get(local_date(r["t0"]), 0.0) + r["km"]
    days = [{"date": d, "obdKm": round(obd_days.get(d, 0.0), 1), "e2Km": round(v["e2"], 1), "g1Km": round(v["g1"], 1), "g2Km": round(v["g2"], 1)} for d, v in sorted(byday.items())]
    missing, holes = reporting_gaps(odo, spd, study_lo, t_hi)
    rej = {}
    for r in recs:
        if r["cls"].startswith("rej_") and study_lo <= r["t1"] and r["t2"] <= t_hi:
            rej[r["cls"]] = rej.get(r["cls"], 0) + 1
    result = {
        "milestone": "M776", "spec": "analyses/M776_spec.md Rev 2", "specSha256": sha256(os.path.join(os.path.dirname(HERE), "analyses", "M776_spec.md")),
        "role": "auxiliary; not an article figure", "masterMd5": md5(master_path), "pinnedMd5": PINNED_MD5,
        "privacy": "aggregates only; no coordinates or per-drive tracks",
        "toolSha256": sha256(os.path.abspath(__file__)),
        "exportSpanKyiv": [datetime.fromtimestamp(t_lo, KYIV).isoformat(), datetime.fromtimestamp(t_hi, KYIV).isoformat()],
        "studySpanStartKyiv": datetime.fromtimestamp(study_lo, KYIV).isoformat(),
        "gridNote": "the pre-registered step-gap grid {25, 35, 45} s contains a value below the nominal 30 s cloud cadence, so at 25 s almost every step is reclassified as a gap increment; the e2Sensitivity*Gap35Plus fields repeat the full factorial without that point (a recorded deviation from spec Rev 2, for the Director)",
        "primaryRule": PRIMARY, "grid": {k: list(v) for k, v in GRID.items()}, "gridCombinations": n_comb,
        "windows": {"rawFiles": wnotes["files"], "ambiguousStarts": wnotes["ambiguous_start"], "notObdDriveNames": wnotes["unparsed"], "notInMaster": extra},
        "months": out_m,
        "totals": {k: round(sum(x[k] for x in out_m), 1) for k in ("obdKm", "cloudOutsideKm", "g1Km", "g2Km", "cloudInsideLogsKm")},
        "rejected": rej, "oneFactorAtATime": ofat, "days": days,
        "cloudReportingGapDates": missing, "cloudHoles24h": holes,
        "scope": "E1/E2 are censuses under a stated rule (n steps, days); definition range is not a bound or an interval",
    }
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, indent=1, ensure_ascii=False)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser()
    root = os.path.dirname(HERE)
    ap.add_argument("--store", default=os.environ.get("XT_CLOUD_STORE") or os.path.join(root, "cloud_store"))
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(root, "raw"))
    ap.add_argument("--master", default=os.path.join(root, "drive_master.csv"))
    ap.add_argument("--out", default=os.path.join(root, "analyses", "M776_cloud_monthly.json"))
    a = ap.parse_args(argv)
    if not os.path.isdir(os.path.join(a.store, "streams")):
        print("cloud_monthly_coverage: no cloud store at %s; skipped" % a.store)
        return 0
    before = md5(a.master)
    res = run(a.store, a.raw_dir, a.master, a.out)
    assert md5(a.master) == before
    print("wrote", a.out, res["totals"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
