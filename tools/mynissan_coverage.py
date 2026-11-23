#!/usr/bin/env python3
"""M729 report-only side tables: cloud coverage per drive and per drive gap, cloud-only movement, export facts.
AUXILIARY source; never writes drive_master.csv or any payload. Drive windows: master date + time_start + duration_s
as Europe/Kyiv local time; cloud timestamps are UTC. Definitions are pre-registered in analyses/M729_spec.md.
Usage: python tools/mynissan_coverage.py [--store DIR] [--out-dir analyses] [--pad 60]
"""
import argparse, bisect, collections, csv, hashlib, json, math, os, sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mynissan_import as mi

ROOT = mi.ROOT
KYIV = ZoneInfo("Europe/Kyiv")
# M750 (owner, 2026-11-23): the physical car limit is 180 km/h; a cloud speed between 130 and 180 km/h is a valid reading in any export (the current export's display is clipped at exactly 130.0, measured, but no tool may assume 130 as a limit); only a reading above 180 km/h or below 0 is implausible and is dropped
PHYSICAL_MAX_KMH = 180.0
STEP_MAX_S, STEP_MAX_KMH, BURST_GAP_S = 35, PHYSICAL_MAX_KMH, 120
BOX = (44.0, 52.5, 22.0, 40.5)  # provisional lat/lon box; Ukraine polygon screen is a later milestone


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def speed_kmh(x):
    """A cloud displayed-speed reading in km/h, or None when it is not a number, is negative or exceeds the physical limit (PHYSICAL_MAX_KMH); 130 to 180 km/h is accepted."""
    v = fnum(x)
    return v if v is not None and 0.0 <= v <= PHYSICAL_MAX_KMH else None


def hav_m(a, b):
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


class Series:
    def __init__(self, pairs):
        self.t = [a for a, _ in pairs]
        self.v = [b for _, b in pairs]

    def __len__(self):
        return len(self.t)

    def between(self, lo, hi):
        i, j = bisect.bisect_left(self.t, lo), bisect.bisect_right(self.t, hi)
        return list(zip(self.t[i:j], self.v[i:j]))

    def nearest(self, t, w):
        i = bisect.bisect_left(self.t, t)
        c = [k for k in (i - 1, i) if 0 <= k < len(self.t) and abs(self.t[k] - t) <= w]
        if not c:
            return None
        k = min(c, key=lambda k: abs(self.t[k] - t))
        return self.t[k], self.v[k]


def load_master(path):
    rows = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig", newline="")):
        try:
            ts = datetime.strptime(r["date"] + " " + r["time_start"][:8], "%Y-%m-%d %H:%M:%S").replace(tzinfo=KYIV).timestamp()
            dur = float(r["duration_s"])
        except (ValueError, KeyError):
            continue
        rows.append({"file": r["file"], "date": r["date"], "t0": ts, "t1": ts + dur, "km": fnum(r.get("distance_km")) or 0.0})
    rows.sort(key=lambda x: x["t0"])
    return rows


def build(store, master, pad, outdir):
    st = {s: [(t, collections.defaultdict(str, x)) for t, x in mi.load_stream(store, s)] for s in mi.STREAMS}  # absent column -> blank
    if not st["Odometer"]:
        return None
    conflicts = set()
    cp = os.path.join(store, "conflicts.csv")
    if os.path.exists(cp):
        for r in csv.DictReader(open(cp, encoding="utf-8", newline="")):
            conflicts.add((r["stream"], r["timestamp_utc"]))
    conf_t = {mi.to_epoch(t) for s, t in conflicts if s == "Odometer"}
    odo = Series([(t, fnum(x["StatusDistanceTotalizerComputed"])) for t, x in st["Odometer"]
                  if x["StatusDistanceTotalizerComputed"] != "" and t not in conf_t])
    spd = Series([(t, speed_kmh(x["SpeedDisplayedValueinkmh"])) for t, x in st["Trip_Information"] if speed_kmh(x["SpeedDisplayedValueinkmh"]) is not None])
    veh = st["Vehicle_Information"]
    pos = []
    for t, x in st["Geolocation"]:
        la, lo = fnum(x["LocationLatitude"]), fnum(x["LocationLongitude"])
        if la is None or lo is None or (la == 0 and lo == 0):
            continue
        pos.append((t, (la, lo)))
    pos_ok = Series([(t, p) for t, p in pos if BOX[0] <= p[0] <= BOX[1] and BOX[2] <= p[1] <= BOX[3]])
    n_pos_out = len(pos) - len(pos_ok)
    amb = Series([(t, fnum(x["ExternalTempDisplayValue"])) for t, x in veh if x["ExternalTempDisplayValue"] != ""])
    cool = Series([(t, fnum(x["EngineCoolantTemp"])) for t, x in veh if x["EngineCoolantTemp"] != ""])
    pedal = Series([(t, fnum(x["AcceleratorPedalOpeningRatio"])) for t, x in st["Trip_Information"] if x["AcceleratorPedalOpeningRatio"] != ""])
    tyre_keys = ["StatusWheelPressureFrontLeft", "StatusWheelPressureFrontRight", "StatusWheelPressureRearLeft", "StatusWheelPressureRearRight"]
    tyre = Series([(t, [fnum(x[k]) for k in tyre_keys]) for t, x in veh if all(x[k] != "" for k in tyre_keys)])
    # accepted odometer steps
    steps = []  # (t_start, t_end, km, speed_positive)
    for (t1, o1), (t2, o2) in zip(zip(odo.t, odo.v), zip(odo.t[1:], odo.v[1:])):
        dt, dk = t2 - t1, o2 - o1
        if 0 < dt <= STEP_MAX_S and 0 < dk <= dt * STEP_MAX_KMH / 3600.0:
            sp = [spd.nearest(t, 20) for t in (t1, t2)]
            if any(s and s[1] > 0 for s in sp):
                steps.append((t1, t2, dk))
    st_t = [s[1] for s in steps]
    def moving(t):
        n = spd.nearest(t, 20)
        return bool(n and n[1] >= 10)
    def odo_anchor(t):
        n = odo.nearest(t, 60)
        return n
    exp_t0, exp_t1 = odo.t[0], odo.t[-1]
    # export break: largest hole between consecutive odometer samples
    holes = [(b - a, a, b) for a, b in zip(odo.t, odo.t[1:]) if b - a >= 24 * 3600]
    msrc = json.load(open(os.path.join(store, "manifest.json"), encoding="utf-8"))["sources"].values()
    s_end = [mi.to_epoch(v["tmax"]) for v in msrc if v.get("tmax")]
    s_beg = [mi.to_epoch(v["tmin"]) for v in msrc if v.get("tmin")]
    # an export break = a hole of >= 24 h that sits exactly on a boundary between two supplied export slices
    bk = [h for h in holes if any(abs(h[1] - e) < 60 for e in s_end) and any(abs(h[2] - b) < 60 for b in s_beg)]
    hole = bk[0] if bk else (0, 0, 0)
    iso = lambda t: datetime.fromtimestamp(t, KYIV).isoformat()
    brk = {"slice_boundary_hole": ({"hours": round(hole[0] / 3600, 2), "from_kyiv": iso(hole[1]), "to_kyiv": iso(hole[2]),
                                    "odo_before": odo.nearest(hole[1], 1)[1], "odo_after": odo.nearest(hole[2], 1)[1]} if bk else None),
           "odometer_holes_ge_24h": [{"hours": round(h[0] / 3600, 1), "from_kyiv": iso(h[1]), "to_kyiv": iso(h[2]),
                                      "odo_equal_across": odo.nearest(h[1], 1)[1] == odo.nearest(h[2], 1)[1]} for h in holes]}
    drives = []
    for d in master:
        lo, hi = d["t0"] - pad, d["t1"] + pad
        row = {"file": d["file"], "date": d["date"], "master_km": d["km"], "in_export_range": int(lo >= exp_t0 and hi <= exp_t1)}
        sp = spd.between(lo, hi); am = amb.between(d["t0"], d["t1"]); am3 = [a for a in am if a[0] >= d["t0"] + 180]
        row.update(n_speed=len(sp), n_pedal=len(pedal.between(lo, hi)), n_ambient=len(am), n_ambient_after3min=len(am3),
                   ambient_mean_after3min=round(sum(v for _, v in am3) / len(am3), 2) if am3 else "")
        c = cool.between(d["t1"] - 30, d["t1"] + 60)
        row["coolant_end_c"] = c[-1][1] if c else ""
        ty = tyre.between(lo, hi)
        row["tyre_4corner_n"] = len(ty)
        if ty:
            row["tyre_raw_fl_fr_rl_rr_last"] = "/".join(f"{v:g}" for v in ty[-1][1])
        o1, o2 = odo_anchor(d["t0"]), odo_anchor(d["t1"])
        if o1 and o2:
            row.update(cloud_odo_start=o1[1], cloud_odo_end=o2[1], cloud_km=round(o2[1] - o1[1], 3),
                       cloud_minus_master_km=round(o2[1] - o1[1] - d["km"], 3), odo_endpoint_age_s=round(max(abs(o1[0] - d["t0"]), abs(o2[0] - d["t1"])), 1))
        pw = pos_ok.between(lo, hi)
        row["n_pos_ok"] = len(pw)
        if pw:
            row.update(pos_first_lat=round(pw[0][1][0], 6), pos_first_lon=round(pw[0][1][1], 6), pos_last_lat=round(pw[-1][1][0], 6), pos_last_lon=round(pw[-1][1][1], 6))
        # state shares over moving samples (speed >= 10 km/h)
        vw = [(t, x) for t, x in veh if lo <= t <= hi and moving(t)]
        tw = [(t, x) for t, x in st["Trip_Information"] if lo <= t <= hi and moving(t)]
        def share(rows, f):
            vals = [f(x) for _, x in rows]
            vals = [v for v in vals if v is not None]
            return round(sum(vals) / len(vals), 3) if vals else ""
        one = lambda k: (lambda x: None if x[k] == "" else float(fnum(x[k]) not in (None, 0.0)))
        row.update(moving_n_veh=len(vw), wiper_nonzero_share=share(vw, one("StatusWipingFront")), lowbeam_share=share(vw, one("LightningLowBeam")),
                   highbeam_share=share(vw, one("LightningHighBeam")), drl_share=share(vw, one("LightningExternalDRL")),
                   position_lamp_share=share(vw, one("PositionLightsStatus")), front_fog_share=share(vw, one("LightningFrontFogLight")),
                   rear_fog_share=share(vw, one("RearFogLightsStatus")), moving_n_trip=len(tw))
        code2 = lambda k: (lambda x: None if x[k] == "" else float(fnum(x[k]) == 2.0))
        rear = lambda x: None if x["SeatBeltSecondRowLeft"] == "" else float(any(fnum(x[k]) == 2.0 for k in ("SeatBeltSecondRowLeft", "SeatBeltSecondRowCenter", "SeatBeltSecondRowRight")))
        row.update(belt_front_passenger_latched_share=share(tw, code2("SeatBeltFirstRowPassenger")), belt_rear_any_latched_share=share(tw, rear))
        drives.append(row)
    # gaps between consecutive master drives
    gaps = []
    for a, b in zip(master, master[1:]):
        g0, g1 = a["t1"], b["t0"]
        row = {"prev": a["file"], "next": b["file"], "gap_h": round((g1 - g0) / 3600, 3)}
        if g1 <= g0:
            row["class"] = "overlap_or_zero"; gaps.append(row); continue
        lo, hi = g0 + pad, g1 - pad
        covered = g0 >= exp_t0 and g1 <= exp_t1
        spans_break = bool(bk) and lo < hole[2] and hi > hole[1]
        i, j = bisect.bisect_right([s[0] for s in steps], lo - 1e-9), bisect.bisect_right([s[1] for s in steps], hi)
        sel = [s for s in steps if s[0] >= lo and s[1] <= hi] if hi > lo else []
        mv_km = sum(s[2] for s in sel)
        row.update(steps=len(sel), moved_km=round(mv_km, 3), last_move_to_next_h="")
        if sel:
            row["last_move_to_next_h"] = round((g1 - sel[-1][1]) / 3600, 3)
        oa, ob = odo_anchor(g0), odo_anchor(g1)
        pa, pb = pos_ok.nearest(g0, 60), pos_ok.nearest(g1, 60)
        if oa and ob:
            row["odo_delta_km"] = round(ob[1] - oa[1], 3)
        if pa and pb:
            row["endpoint_m"] = round(hav_m(pa[1], pb[1]), 1)
        if not covered:
            cls = "no_cloud_data"
        elif spans_break:
            cls = "export_break"
        elif len(sel) >= 2 and mv_km >= 1.0:
            cls = "driving_observed"
        elif mv_km < 0.1 and oa and ob and abs(ob[1] - oa[1]) <= 0.1 and pa and pb and hav_m(pa[1], pb[1]) <= 75:
            cls = "stationary_consistent"
        elif oa and ob and ob[1] - oa[1] > 0.1:
            cls = "odometer_increase_only"
        else:
            cls = "uncertain"
        row["class"] = cls
        gaps.append(row)
    # cloud-only movement outside all padded drive windows
    wins = [(d["t0"] - pad, d["t1"] + pad) for d in master]
    ws = [w[0] for w in wins]
    def in_win(t):
        k = bisect.bisect_right(ws, t) - 1
        for q in range(k, max(-1, k - 6), -1):
            if wins[q][0] <= t <= wins[q][1]:
                return True
        return False
    out = [s for s in steps if not in_win(s[0]) and not in_win(s[1])]
    bursts, cur = [], []
    for s in out:
        if cur and s[0] - cur[-1][1] > BURST_GAP_S:
            bursts.append(cur); cur = []
        cur.append(s)
    if cur:
        bursts.append(cur)
    strict = [b for b in bursts if len(b) >= 2 and sum(s[2] for s in b) >= 1.0]
    # export facts (Kyiv dates)
    alld = set()
    for s in mi.STREAMS:
        alld |= {datetime.fromtimestamp(t, KYIV).date() for t, _ in st[s]}
    d0, d1 = min(alld), max(alld)
    span = [d0 + timedelta(days=k) for k in range((d1 - d0).days + 1)]
    missing = [d.isoformat() for d in span if d not in alld]
    man = json.load(open(os.path.join(store, "manifest.json"), encoding="utf-8"))
    cls_count = {}
    for g in gaps:
        cls_count[g["class"]] = cls_count.get(g["class"], 0) + 1
    covd = [d for d in drives if d["in_export_range"]]
    brief = {
        "milestone": "M729", "role": "auxiliary", "source_store_digest": man["store_digest"], "pad_s": pad,
        "export": {"rows": {s: man["streams"][s]["rows"] for s in mi.STREAMS if s in man["streams"]}, "rows_total": sum(v["rows"] for v in man["streams"].values()),
                   "range_kyiv": [datetime.fromtimestamp(exp_t0, KYIV).isoformat(), datetime.fromtimestamp(exp_t1, KYIV).isoformat()],
                   "dates_observed": len(alld), "dates_in_span": len(span), "dates_without_rows": len(missing), "dates_without_rows_list": missing,
                   "holes": brk, "populated_study_fields": sum(len(v["populated"]) for v in man["streams"].values()),
                   "blank_columns": sum(len(v["blank"]) for v in man["streams"].values()), "conflicts": man["conflicts"],
                   "positions_outside_box_or_zero_rows": n_pos_out},
        "drives": {"n": len(drives), "in_export_range": len(covd), "with_speed_ge3": sum(d["n_speed"] >= 3 for d in drives),
                   "with_ambient_after3min_ge5": sum(d["n_ambient_after3min"] >= 5 for d in drives),
                   "with_coolant_end": sum(d["coolant_end_c"] != "" for d in drives), "with_tyre_4corner": sum(d["tyre_4corner_n"] > 0 for d in drives),
                   "with_cloud_odometer_ends": sum("cloud_km" in d for d in drives), "with_position": sum(d["n_pos_ok"] > 0 for d in drives),
                   "without_any_cloud_speed": sum(d["n_speed"] == 0 for d in drives)},
        "gaps": {"n": len(gaps), "classes": cls_count, "driving_observed_km": round(sum(g.get("moved_km", 0) for g in gaps if g["class"] == "driving_observed"), 1)},
        "cloud_odometer": {"first": odo.v[0], "last": odo.v[-1], "net_gain_km": round(odo.v[-1] - odo.v[0], 1)},
        "cloud_only_movement_km": {"crude_all_steps_outside_windows": round(sum(s[2] for s in out), 1), "strict_bursts_km": round(sum(s[2] for b in strict for s in b), 1),
                                   "strict_burst_count": len(strict), "step_rule": f"gap<={STEP_MAX_S}s, positive, <= {STEP_MAX_KMH} km/h, speed>0 at an end"},
        "master_logged_km": round(sum(d["km"] for d in master), 1),
    }
    dd = [d["cloud_minus_master_km"] for d in drives if "cloud_km" in d and d["master_km"] >= 2 and d["odo_endpoint_age_s"] <= 30]
    if dd:
        dd.sort()
        brief["odometer_check"] = {"n": len(dd), "median_cloud_minus_master_km": dd[len(dd) // 2],
                                   "p90_abs_km": sorted(abs(x) for x in dd)[int(0.9 * len(dd))], "endpoint_age_le_s": 30}
    return drives, gaps, brief


def write_csv(path, rows):
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store())
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--pad", type=float, default=60.0)
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.store, "manifest.json")):
        print("mynissan_coverage: no cloud store, stage skipped (optional)")
        return 0
    before = md5(a.master)
    res = build(a.store, load_master(a.master), a.pad, a.out_dir)
    if res is None:
        print("mynissan_coverage: empty store"); return 0
    drives, gaps, brief = res
    os.makedirs(a.out_dir, exist_ok=True)
    write_csv(os.path.join(a.out_dir, "M729_cloud_coverage.csv"), drives)
    write_csv(os.path.join(a.out_dir, "M729_cloud_gaps.csv"), gaps)
    after = md5(a.master)
    brief["drive_master_md5_before"], brief["drive_master_md5_after"] = before, after
    brief["drive_master_unchanged"] = before == after
    json.dump(brief, open(os.path.join(a.out_dir, "M729_cloud_brief.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: brief[k] for k in ("drives", "gaps", "cloud_only_movement_km", "drive_master_unchanged")}, indent=1))
    return 0 if before == after else 1


if __name__ == "__main__":
    sys.exit(main())
