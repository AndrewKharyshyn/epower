"""M539 wave 1 (analyses/M539_spec.md Rev 2): the engine-on rule module, the site registry and the grep tripwire. Known answers (299, 300, 350, 400, 400.5, NaN); engine_on | band == the former >= 300 on-time (T2 in miniature);
every *_ENG_ON / RPM_ON constant equals the rule threshold; the stored rpmDistribution edges are defined once and copies are equal (T1); the regeneration proxy is still 300 (T5); the grep tripwire finds no unregistered
rpm threshold site; registry hygiene; no existing producer is changed by wave 1 (the master MD5 is the anchor)."""
import hashlib, json, os, re, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import engine_on_rule as R
import engine_on_sites as S

x = np.array([299, 300, 350, 400, 400.5, np.nan, 0, 2000.0])
assert R.engine_on(x).tolist() == [False, False, False, False, True, False, False, True]
assert R.low_rpm_band(x).tolist() == [False, True, True, True, False, False, False, False]
assert R.legacy_ge300(x).tolist() == (R.engine_on(x) | R.low_rpm_band(x)).tolist()                       # ge300 == on | band (exact complement)
assert R.THRESHOLD_RPM == 400.0 and R.BOUNDARY == "gt" and R.BAND_LO_RPM == 300.0
rng = np.random.default_rng(0)
y = rng.uniform(0, 3500, 5000); y[::17] = np.nan; y[::23] = 400.0; y[::29] = 300.0
assert (R.legacy_ge300(y) == (R.engine_on(y) | R.low_rpm_band(y))).all() and not (R.engine_on(y) & R.low_rpm_band(y)).any()

# every *_ENG_ON / RPM_ON constant equals the rule threshold (T1 for the rule)
import compute_summary_arrays as cs
import engine_runtime as ER
for name in ("_RSYNC_ENG_ON", "_DST_ENG_ON", "_DA_ENG_ON", "_VGT_ENG_ON", "_ESH_ENG_ON", "_OF_ENG_ON"):
    assert getattr(cs, name) == R.THRESHOLD_RPM, name
assert ER.RPM_ON == R.THRESHOLD_RPM
# the stored histogram edges are defined once; copies are equal and bin 1 still starts at 300 (wave 1 changes no bin)
assert cs.RPM_HIST_EDGES[:3] == [0, 300, 1400]
src = open("rpm_opt_pass.py", encoding="utf-8").read()
m = re.search(r"RPM_HIST_EDGES\s*=\s*\[([^\]]*)\]", src)
assert [int(v) for v in re.findall(r"\d+", m.group(1))] == list(cs.RPM_HIST_EDGES), "rpm_opt_pass.py edge copy differs"
src2 = open("tools/engine_on_optband_check.py", encoding="utf-8").read()
m2 = re.search(r"HIST_EDGES\s*=\s*\[([^\]]*)\]", src2)
assert [int(v) for v in re.findall(r"\d+", m2.group(1))] == list(cs.RPM_HIST_EDGES), "engine_on_optband_check.py edge copy differs"
# the regeneration proxy is still 300 (decision (g))
reg_src = open("compute_summary_arrays.py", encoding="utf-8").read()
assert reg_src.count("nan=9999.0) <= 300") >= 2 and "<= 300" in open("tools/m440_regen_sens.py", encoding="utf-8").read()
assert "RPM <= 300" in open("tools/regen_v2_stage.py", encoding="utf-8").read()

# registry hygiene and the grep tripwire
reg = json.load(open("analyses/M539_site_registry.json", encoding="utf-8"))
fams = {"rule-400", "rule-400-constant", "regen-proxy-300", "doc-400", "doc-300", "legacy-300-grid", "event-onset-300"}
assert all(s["family"] in fams and s["file"] and s["anchor"] and s["rule"] and s["migration"] for s in reg["sites"])
for s in reg["sites"]:
    assert any(s["anchor"] in l for l in open(s["file"], encoding="utf-8", errors="replace")), ("anchor not found", s["file"], s["anchor"])
assert S.unregistered(reg) == [], S.unregistered(reg)
# the tripwire does catch a planted site
assert S.unregistered({"sites": [s for s in reg["sites"] if "_RSYNC_ENG_ON" not in s["anchor"]]}), "tripwire did not fire on a removed registry entry"
# every constant site in the registry is a rule-400 constant with the rule value
assert sum(1 for s in reg["sites"] if s["family"] == "rule-400-constant") == 7

# wave 1 changes no producer: the master anchor
assert hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest().startswith("5556a0c6")
print("OK test_engine_on_rule: known answers, constants, edge copies, regen proxy 300, registry and grep tripwire")
