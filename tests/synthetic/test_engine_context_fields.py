"""M559 (analyses/M559_spec.md Rev 2): known-answer tests for the field classifier in tools/engine_context_fields.py."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import engine_context_fields as E

FL = {"hasBoost": True, "hasLoad": True, "fuelOk": True, "hasCool": True, "hasRpm": True}


def frame(rows):
    """rows: dicts with rpm, I (discharge-positive), boost, load, fuel, soc, speed; 1 s apart, a lead-in of 6 s with the engine running so no spin-up flag falls on the rows of interest."""
    n = len(rows)
    idx = pd.date_range("2026-01-01 12:00:00", periods=n, freq="1s")
    g = pd.DataFrame({k: [r.get(k, np.nan) for r in rows] for k in ("rpm", "I", "boost", "load", "fuel", "soc", "speed")}, index=idx)
    return g


def run(rows, cool=90.0, age=5.0, flags=FL, p=None):
    g = frame(rows)
    q = dict(E.BASE); q.update(p or {})
    r = E.classify(g, np.full(len(g), cool), np.full(len(g), age), flags, q)
    return r


def steady(**kw):
    base = dict(rpm=2500.0, I=0.0, boost=-0.3, load=30.0, fuel=2.0, soc=60.0, speed=60.0); base.update(kw)
    return [dict(base) for _ in range(12)]


# Rev 3: thermal_context is cold coolant only; warming stays a field value
rr = run(steady(), cool=70.0); assert set(rr["thermal"]) == {"warming"} and not rr["thermal_context"].any()
assert run(steady(), cool=60.0)["thermal_context"].all()
# rpm exactly 2000: rotation level high (>=), dissipation candidate needs rpm > 2000 (legacy strict operator)
r2 = run(steady(rpm=2000.0, boost=-0.9, load=3.0, fuel=0.0, soc=90.0)); assert set(r2["rot"]) == {"high"} and not r2["dissipation_candidate"].any()
r2 = run(steady(rpm=2000.5, boost=-0.9, load=3.0, fuel=0.0, soc=90.0)); assert r2["dissipation_candidate"].all()
# KA1 boundaries: rpm 400 is not rotating; I = +-2 A is neutral; coolant 60 / 80 are cold / warming
assert len(run(steady(rpm=400.0))) == 0 and len(run(steady(rpm=401.0))) == 12
r = run(steady(I=2.0)); assert set(r["flow"]) == {"neutral"}
r = run(steady(I=2.01)); assert set(r["flow"]) == {"discharging"}
r = run(steady(I=-2.01)); assert set(r["flow"]) == {"charging"}
assert set(run(steady(), cool=60.0)["thermal"]) == {"cold"} and set(run(steady(), cool=60.1)["thermal"]) == {"warming"}
assert set(run(steady(), cool=80.0)["thermal"]) == {"warming"} and set(run(steady(), cool=80.1)["thermal"]) == {"warm"}
# KA6 coolant age: 29 s valid, 31 s unknown; no coolant value is unknown, never warm
assert set(run(steady(), cool=90.0, age=29.0)["thermal"]) == {"warm"} and set(run(steady(), cool=90.0, age=31.0)["thermal"]) == {"unknown"}
assert set(run(steady(), cool=np.nan)["thermal"]) == {"unknown"}
# KA3 combustion classes with the legacy operators: boost exactly -0.70 is not motored, -0.55 is fuelled; load exactly 8 is not low
assert set(run(steady(boost=-0.70))["comb"]) == {"ambiguous"} and set(run(steady(boost=-0.7001))["comb"]) == {"motored"} and set(run(steady(boost=-0.55))["comb"]) == {"fuelled"}
assert set(run(steady(boost=-0.8, load=8.0))["lowLoad"]) == {False} and set(run(steady(boost=-0.8, load=7.84))["lowLoad"]) == {True}
# a missing boost channel or all-zero fuel gives no_signal / no fuel flag
assert set(run(steady(), flags={**FL, "hasBoost": False})["comb"]) == {"no_signal"}
assert not run(steady(), flags={**FL, "fuelOk": False})["fuelFlag"].any()
# KA2 orthogonality: a cold, charging, fuelled rotating sample carries generation_net_charge and thermal_context together; labels are not exclusive
r = run(steady(I=-10.0), cool=40.0)
assert r["generation_net_charge"].all() and r["thermal_context"].all() and not r["dissipation_candidate"].any()
# generation with pack discharge needs speed > 5
assert run(steady(I=10.0, speed=6.0))["generation_with_pack_discharge"].all() and not run(steady(I=10.0, speed=5.0))["generation_with_pack_discharge"].any()
# high-SoC probe: rotating at SoC 90, I = 0, motored boost, low load, high rpm, warm -> dissipation_candidate only (a candidate, not a purpose); the same with a fuel proxy stays without it
dis = steady(rpm=2500.0, I=0.0, boost=-0.9, load=3.0, fuel=0.0, soc=90.0, speed=30.0)
r = run(dis); assert r["dissipation_candidate"].all() and r["socHi"].all()
r = run(steady(rpm=2500.0, I=0.0, boost=-0.3, load=30.0, fuel=2.0, soc=90.0, speed=30.0)); assert not r["dissipation_candidate"].any() and not r[list(E.LABELS)].to_numpy().any()
# the summary: unresolved with and without the thermal label, label-set counts, probe
s = E.summarize(run(steady(I=0.0, boost=-0.3, load=30.0, fuel=2.0, soc=90.0), cool=40.0), E.BASE)
assert s["unresolvedNoCandidate"] == 0 and s["unresolvedExceptThermal"] == 12 and s["labelSets"] == {"thermal_context": 12} and s["counts"]["unres_other"] == 0 and s["probe"]["socHiNonCharging"] == 12
# unresolved reasons: all-zero fuel file with fuelled boost -> fuelMissing; no boost channel -> noSignal
sm = E.summarize(run(steady(I=0.0), flags={**FL, "fuelOk": False}), E.BASE); assert sm["counts"]["unres_fuelMissing"] == 12 and sm["counts"]["unres_noSignal"] == 0
sm = E.summarize(run(steady(I=0.0), flags={**FL, "hasBoost": False}), E.BASE); assert sm["counts"]["unres_noSignal"] == 12
# spin-up flag: the first rotating second after a stop is flagged, a steady sample far from a crossing is not
rows = [dict(rpm=0.0, I=0.0)] * 5 + steady()[:12]
r = run(rows); assert r["spin"].iloc[0] and not r["spin"].iloc[-1]
# sign check: the stored current is discharge-positive after the loader flip (charging braking has I < 0)
assert set(run(steady(I=-20.0, rpm=450.0, boost=-0.3))["flow"]) == {"charging"}
# coolant_age: last NON-NULL sample, no grid fill
t = np.array([10, 20, 30, 100], dtype="int64") * 10**9
v, a = E.coolant_age(t, np.array([15, 25], dtype="int64") * 10**9, np.array([50.0, 60.0]))
assert np.isnan(v[0]) and v[1] == 50.0 and a[1] == 5.0 and v[2] == 60.0 and a[2] == 5.0 and v[3] == 60.0 and a[3] == 75.0
# KA4 legacy reconciliation (real files, when the cache exists): the independent legacy rule equals the classifier's motored rows in every cached drive
import glob, json
for cp in glob.glob(os.path.join(E.CACHE, "*.json"))[:300]:
    rec = json.load(open(cp, encoding="utf-8"))
    if rec.get("ok"):
        v = rec["variants"]["base"]
        assert v["legacyMot"] == v["newMot"], (cp, v["legacyMot"], v["newMot"])
print("test_engine_context_fields OK")
