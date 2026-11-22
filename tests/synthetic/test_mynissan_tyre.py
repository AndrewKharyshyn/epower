"""M733 known-answer tests (analyses/M733_spec.md Rev 1): planted temperature response, puncture exclusion, step detection, absent store is non-blocking."""
import csv, io, os, sys, tempfile, zipfile, json
from datetime import datetime, timezone, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mynissan_import as mi
import mynissan_tyre as ty

assert abs(ty.ideal_gas_slope(230.0) - (230 + 101.3) / 293.15) < 1e-9
tmp = tempfile.mkdtemp()
assert ty.main(["--store", os.path.join(tmp, "nostore"), "--out-dir", tmp]) == 0     # optional stage: no store -> skipped

# planted data: 40 days, one drive of 12 minutes per day at 08:00 Kyiv (UTC+2 in Nov), snapshot at minute 10 of the drive.
# pressure = 230 + 0.5 * (ambient - 15) on every corner (+30 raw units of quantisation ignored); a +30 kPa inflation step on day 25.
def csvb(h, rows):
    b = io.StringIO(newline=""); w = csv.writer(b, lineterminator="\n"); w.writerow(h); w.writerows(rows); return b.getvalue().encode()
veh, master = [], []
base = datetime(2026, 11, 1, 6, 0, 0, tzinfo=timezone.utc)
import random
random.seed(1)
for k in range(40):
    t0 = base + timedelta(days=k)
    amb = 10 + 8 * ((k * 7) % 11) / 10.0 - 4          # varies 6..14 degrees
    step = 30.0 if k >= 25 else 0.0
    p = 230 + 0.5 * (amb - 15) + step
    for sec in range(0, 720, 30):
        t = t0 + timedelta(seconds=sec)
        veh.append(["VIN", t.strftime("%Y-%m-%d %H:%M:%S.000"), amb, "", "", "", ""])
    t = t0 + timedelta(seconds=600)
    veh.append(["VIN", t.strftime("%Y-%m-%d %H:%M:%S.000"), amb, round(p * 10), round(p * 10), round(p * 10), round(p * 10)])
    loc = t0.astimezone(ty.mc.KYIV)
    master.append({"file": f"d{k}.csv", "date": loc.strftime("%Y-%m-%d"), "time_start": loc.strftime("%H:%M:%S") + ".000", "duration_s": 720, "distance_km": 5.0})
z = os.path.join(tmp, "x.zip")
with zipfile.ZipFile(z, "w") as zf:
    zf.writestr("Vehicle_Information.csv", csvb(["VIN", "Timestamp", "ExternalTempDisplayValue", "StatusWheelPressureFrontLeft", "StatusWheelPressureFrontRight", "StatusWheelPressureRearLeft", "StatusWheelPressureRearRight"], sorted(veh, key=lambda r: r[1])))
    zf.writestr("System_Safety_Alerts.csv", csvb(["VIN", "Timestamp", "StatusWheelStateFrontRight"], [["VIN", (base + timedelta(days=5, seconds=10)).strftime("%Y-%m-%d %H:%M:%S.000"), 2]]))
store = os.path.join(tmp, "store"); mi.import_sources([z], store)
mp = os.path.join(tmp, "drive_master.csv")
with open(mp, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(master[0]), lineterminator="\n"); w.writeheader(); w.writerows(master)
out = os.path.join(tmp, "out")
assert ty.main(["--store", store, "--out-dir", out, "--master", mp, "--coverage", os.path.join(tmp, "none.csv")]) == 0
r = json.load(open(os.path.join(out, "M733_tyre_pressure.json"), encoding="utf-8"))
assert r["snapshots_excluded_puncture"] == 1 and r["puncture_window_kyiv"] is not None
# the planted slope is 0.5 kPa/C but the inflation step on day 25 biases a plain regression; the step must be detected on all four corners
assert r["E3_steps"]["n"] == 4 and all(s["date"] == "2026-11-26" for s in r["E3_steps"]["list"]), r["E3_steps"]
assert abs(r["E1_level"]["front_axle"]["median_ratio"] - 1.0) < 0.2
print("test_mynissan_tyre: OK")
