"""M729 known-answer tests for the MyNISSAN cloud importer and coverage tables (analyses/M729_spec.md): exact dedup across overlapping
exports, conflict log, idempotent re-import, optional stage (no export -> skipped), DST (Europe/Kyiv, 25 Oct 2026), a planted
stationary-consistent and a planted driving-observed gap, and that drive_master.csv is never written."""
import csv, io, json, os, sys, tempfile, zipfile, hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mynissan_import as mi
import mynissan_coverage as mc

V = "JN1TEST"
def csvb(header, rows):
    b = io.StringIO(newline=""); w = csv.writer(b, lineterminator="\n"); w.writerow(header); w.writerows(rows); return b.getvalue().encode()
def mkzip(path, odo=(), trip=(), geo=(), veh=()):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Odometer.csv", csvb(["VIN", "Timestamp", "StatusDistanceTotalizer", "StatusDistanceTotalizerComputed", "DistanceTotalizerUnit"], [[V, t, o, o, ""] for t, o in odo]))
        z.writestr("Trip_Information.csv", csvb(["VIN", "Timestamp", "SpeedDisplayedValueinkmh", "SeatBeltFirstRowPassenger"], [[V, t, s, 2] for t, s in trip]))
        z.writestr("Geolocation.csv", csvb(["VIN", "Timestamp", "LocationLatitude", "LocationLongitude"], [[V, t, la, lo] for t, la, lo in geo]))
        z.writestr("Vehicle_Information.csv", csvb(["VIN", "Timestamp", "ExternalTempDisplayValue"], [[V, t, a] for t, a in veh]))
        z.writestr("notes/readme.txt", b"ignored")

tmp = tempfile.mkdtemp()
T = lambda s: "2026-11-10 " + s + ".000"
odoA = [(T("08:00:00"), 100.0), (T("08:00:30"), 100.2), (T("08:01:00"), 100.4)]
zA = os.path.join(tmp, "a.zip"); zB = os.path.join(tmp, "b.zip")
mkzip(zA, odo=odoA, trip=[(T("08:00:00"), 50), (T("08:00:30"), 50), (T("08:01:00"), 50)], geo=[(T("08:00:00"), 50.0, 30.0)], veh=[(T("08:00:00"), 5)])
# overlapping export: repeats two odometer rows exactly, adds one new row, and a conflicting latitude at 08:00:00
mkzip(zB, odo=odoA[1:] + [(T("08:01:30"), 100.6)], geo=[(T("08:00:00"), 50.0001, 30.0)])
store = os.path.join(tmp, "store")
m = mi.import_sources([zA, zB], store)
assert m["streams"]["Odometer"]["rows"] == 4, m["streams"]["Odometer"]          # 3 + 4 - 2 exact duplicates
assert m["streams"]["Geolocation"]["rows"] == 2 and m["conflicts"] == 1          # same timestamp, different latitude: both kept, logged
assert m["role"] == "auxiliary" and m["archiveOfRecord"] is False
dig = m["store_digest"]
m2 = mi.import_sources([zA, zB], store)                                           # idempotent re-import
assert m2["store_digest"] == dig and m2["streams"]["Odometer"]["rows"] == 4
m3 = mi.import_sources([os.path.join(tmp, "nothing")], os.path.join(tmp, "s2"))   # optional stage: no export -> skipped, no store written
assert m3 == {"skipped": True} and not os.path.exists(os.path.join(tmp, "s2"))
assert [s for s in m["streams"]] and "Vehicle_Autonomy" not in m["streams"]       # absent streams tolerated

# DST: Kyiv 03:30 on 2026-10-25 occurs twice; UTC epochs must follow the cloud (UTC) timestamp, not local clock
K = ZoneInfo("Europe/Kyiv")
assert datetime.fromtimestamp(mi.to_epoch("2026-10-25 00:30:00.000"), K).strftime("%H:%M %z") == "03:30 +0300"
assert datetime.fromtimestamp(mi.to_epoch("2026-10-25 01:30:00.000"), K).strftime("%H:%M %z") == "03:30 +0200"
assert mi.to_epoch("2026-10-25 01:30:00.000") - mi.to_epoch("2026-10-25 00:30:00.000") == 3600

# coverage: two drives with a stationary gap, then a third after a moved gap (all in Kyiv local time = UTC+2 on 10 Nov)
zC = os.path.join(tmp, "c.zip")
def ts(h, mi_, s=0): return f"2026-11-10 {h:02d}:{mi_:02d}:{s:02d}.000"
odo, trip, geo = [], [], []
def run(h0, m0, o0, n, lat0=50.0):  # n samples 30 s apart, 0.25 km per step (30 km/h would be 0.25 km/30 s = 30 km/h)
    for k in range(n):
        t = ts(h0, m0 + (k * 30) // 60, (k * 30) % 60); odo.append((t, o0 + 0.25 * k)); trip.append((t, 30)); geo.append((t, lat0, 30.0))
run(6, 0, 1000.0, 8)    # drive 1 UTC 06:00-06:03:30 = Kyiv 08:00
odo.append((ts(6, 20), 1001.75)); geo.append((ts(6, 20), 50.0, 30.0))   # anchor after the stationary gap (same odometer, same place)
run(6, 21, 1001.75, 8, 50.0)  # drive 2 (stationary gap between 1 and 2)
run(7, 30, 1010.0, 12)  # drive 3: odometer jump 1003.5 -> 1010 happens through observed moving steps below
# driving between drive 2 and 3: steps of 0.25 km every 30 s
base = 1003.5
for k in range(0, 26):
    t = ts(6, 45 + (k * 30) // 60, (k * 30) % 60); odo.append((t, base + 0.25 * k)); trip.append((t, 30)); geo.append((t, 50.1 + 0.001 * k, 30.0))
mkzip(zC, odo=sorted(set(odo)), trip=sorted(set(trip)), geo=sorted(set(geo)))
st2 = os.path.join(tmp, "st2"); mi.import_sources([zC], st2)
master = os.path.join(tmp, "drive_master.csv")
def mrow(f, t0, dur, km): return {"file": f, "date": "2026-11-10", "time_start": t0, "duration_s": dur, "distance_km": km}
rows = [mrow("d1.csv", "08:00:00.000", 210, 1.75), mrow("d2.csv", "08:21:00.000", 210, 1.75), mrow("d3.csv", "09:30:00.000", 330, 2.75)]
with open(master, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)
before = hashlib.md5(open(master, "rb").read()).hexdigest()
drives, gaps, brief = mc.build(st2, mc.load_master(master), 60.0, tmp)
assert hashlib.md5(open(master, "rb").read()).hexdigest() == before               # the master is never written
assert [g["class"] for g in gaps] == ["stationary_consistent", "driving_observed"], [(g["class"], g.get("moved_km"), g.get("odo_delta_km"), g.get("endpoint_m")) for g in gaps]
assert abs(drives[0]["cloud_km"] - 1.75) < 1e-6 and abs(drives[0]["cloud_minus_master_km"]) < 1e-6
assert brief["role"] == "auxiliary" and brief["drives"]["n"] == 3
print("test_mynissan_import: OK")
