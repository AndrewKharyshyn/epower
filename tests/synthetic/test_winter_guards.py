"""M726 known-answer tests (analyses/M726_spec.md Rev 2): G1 the path guard blocks edits of the frozen winter files, G2 the scoring framework fails closed, G3 the exposure monitor counts exposure and support only."""
import json, os, subprocess, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_score as WS
import winter_exposure_monitor as WM

# ---- G1: guard_paths.py blocks Edit / Write on the frozen files and passes other analyses files
def hook(path):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "guard_paths.py")], input=json.dumps({"tool_input": {"file_path": path}}), capture_output=True, text=True)
    return r.returncode
assert hook("C:/x/analyses/M717_winter_predictions.json") == 2
assert hook("analyses/M717_frozen_sources/analyses__M713__state_params.json") == 2
assert hook("analyses/M717_frozen_sources/index.json") == 2
assert hook("analyses/M726_spec.md") == 0 and hook("analyses/M713/state_params.json") == 0 and hook("raw/2026-11-20 09-17-51.csv") == 2

# ---- the real freeze: file sha256 in the CHANGELOG, every source readable from live (sha equal) or a verified frozen copy
F = WS.load_freeze()
for k in F["sources"]:
    if k == "prototypeThermalParams" and not os.path.exists(F["sources"][k]["path"]):
        continue
    assert isinstance(WS.read_source(F, k), bytes)
assert WS.main() == 0

# ---- G2: refusals
for bad in ("analyses/M713/state_params.json", "summary_arrays.json", "C:/repo/analyses/M713/scenario_gates.json"):
    try:
        WS.refuse_live(bad)
        raise AssertionError("live path not refused: " + bad)
    except WS.Refused:
        pass
assert WS.refuse_live("analyses/M717_frozen_sources/analyses__M713__state_params.json")
try:
    WS.read_source(F, "notASource")
    raise AssertionError("unknown source accepted")
except WS.Refused:
    pass
try:                                                        # a freeze file whose hash is not in the CHANGELOG is refused
    WS.load_freeze(changelog_text="no hash here")
    raise AssertionError("freeze accepted without a CHANGELOG hash")
except WS.Refused:
    pass
tampered = json.loads(json.dumps(F))
tampered["sources"]["stateParams"]["sha256"] = "0" * 64     # neither the live file nor the frozen copy matches the record
try:
    WS.read_source(tampered, "stateParams")
    raise AssertionError("tampered record accepted")
except WS.Refused:
    pass

# ---- G2: cells
c = WS.evaluate_cell("P4", 9, 9)
assert c["status"] == "not evaluable" and "estimate" not in c and "ci95" not in c               # below the drive rule: no number
c = WS.evaluate_cell("P4", 12, 4)
assert c["status"] == "not evaluable" and "estimate" not in c                                   # below the day rule
c = WS.evaluate_cell("P4", 12, 6)
assert c["status"] == "not evaluable" and c["reason"].startswith("extractor not frozen")
# no extractor registry exists: even a full cell with an estimate prints NO number (Director M726 decision)
assert WS.extractors_frozen()[0] is False
c = WS.evaluate_cell("P3", 12, 6, 0.5, [0.4, 0.6], [0.3, 0.7], cell_min=1.0, basis_min=1.0)
assert c["status"] == "not evaluable" and "estimate" not in c and "no extractor registry" in c["reason"]
# with a registry whose sha256 is recorded in the CHANGELOG and whose modules match, the comparison runs (simulated)
_orig = WS.extractors_frozen
WS.extractors_frozen = lambda changelog_text=None: (True, "frozen")
c = WS.evaluate_cell("P3", 12, 6, 0.5, [0.4, 0.6], [0.3, 0.7], cell_min=1.0, basis_min=1.0)
assert c["status"] == "within the band" and c["region"] == "interpolation check"
c = WS.evaluate_cell("P3", 12, 6, 1.5, [1.4, 1.6], [0.3, 0.7], cell_min=-3.0, basis_min=1.0)
assert c["status"] == "outside the band" and c["region"] == "extrapolation test"
assert WS.evaluate_cell("P3", 12, 6, 0.5, [0.2, 0.9], [0.3, 0.7])["status"] == "inconclusive"
WS.extractors_frozen = _orig
# registry rules: a registry whose hash is not in the CHANGELOG, or whose module differs, is not frozen
import tempfile as _t
_reg = os.path.join(ROOT, WS.REGISTRY)
try:
    json.dump({"modules": {"tools/winter_score.py": "0" * 64}}, open(_reg, "w", encoding="utf-8"))
    assert WS.extractors_frozen(changelog_text="")[1].startswith("the extractor registry sha256 is not recorded")
    assert WS.extractors_frozen(changelog_text=WS.sha(WS.REGISTRY))[1].startswith("an extractor module differs")
finally:
    os.remove(_reg)

# ---- G3: sets, events, counts (synthetic frame)
rows = []
def drive(key, day, start, tlo, hlt0=0.0, hlt5=0.0, hlt10=0.0, tstart=10.0):
    rows.append(dict(key=key, day=day, start=start, T_start=tstart, Tlo_min=tlo, h_lt0=hlt0, h_lt5=hlt5, h_lt10=hlt10))
drive("20261108100000", "2026-11-08", "2026-11-08 10:00:00", 1.0, 0.0, 0.01, 0.1, 1.5)           # frozen basis
drive("20261112100000", "2026-11-12", "2026-11-12 10:00:00", 4.0, 0.0, 0.02, 0.1)               # post-basis, pre-freeze
drive("20261117183000", "2026-11-17", "2026-11-17 18:30:00", 3.0)                                # inside the F +- 1 h window: in no set
drive("20261117203000", "2026-11-17", "2026-11-17 20:30:00", 2.0, 0.0, 0.03, 0.2)               # scoring set, cold drive (E2)
for i in range(12):                                                                              # scoring set, 12 drives on 6 days with ambient below 20 C
    drive("202611%02d080000" % (18 + i // 2), "2026-11-%02d" % (18 + i // 2), "2026-11-%02d 08:00:00" % (18 + i // 2), 9.0)
fr = pd.DataFrame(rows)
b, p, s = WM.sets(fr)
assert b.sum() == 1 and p.sum() == 1 and s.sum() == 13 and not (b & s).any() and not (p & s).any()
amb = {k: 8.0 for k in fr["key"]}
r = WM.compute_record(fr, amb, "md5x", 17, 1.0)
assert r["scoringSet"]["nDrives"] == 13 and r["postBasisPreFreeze"]["nDrives"] == 1 and r["frozenBasis"]["nDrives"] == 1
assert r["events"]["E2_postFreezeColdDrives"] == 1 and r["events"]["E1_firstSubZero"] is False and r["events"]["E3_liveRefitAfterF"] is True
assert r["support"]["P5_P7_ambientBelow20"] == {"nDrives": 13, "nDays": 7, "meetsSupportRule": True}
assert r["support"]["P3_P4_P6_probeWindow"]["nDrives"] == 1 and r["support"]["P3_P4_P6_probeWindow"]["meetsSupportRule"] is False
assert not any(k in json.dumps(r) for k in ("estimate", "ci95", "within the band"))             # exposure and support only
# E1: a drive with >= 10 grid samples (20 s) below 0 C and a finite probe resolution; a single sample is a flag only; no resolution = no event
drive("20261125080000", "2026-11-25", "2026-11-25 08:00:00", -1.0, 25.0 / 3600.0, 0.01, 0.1)
fr1 = pd.DataFrame(rows)
assert WM.compute_record(fr1, amb, "m", 18, 1.0)["events"]["E1_firstSubZero"] is True
assert WM.compute_record(fr1, amb, "m", 18, None)["events"]["E1_firstSubZero"] is False
rows[-1]["h_lt0"] = 2.0 / 3600.0
fr2 = pd.DataFrame(rows)
e = WM.compute_record(fr2, amb, "m", 18, 1.0)["events"]
assert e["E1_firstSubZero"] is False and e["E1_singleSampleFlagOnly"] is True
# the log keeps one record per master md5
log = WM.merge_log(None, {"masterMd5": "a", "v": 1})
log = WM.merge_log(log, {"masterMd5": "b", "v": 1})
log = WM.merge_log(log, {"masterMd5": "a", "v": 2})
assert [x["v"] for x in log["records"] if x["masterMd5"] == "a"] == [2] and len(log["records"]) == 2
print("OK test_winter_guards")
