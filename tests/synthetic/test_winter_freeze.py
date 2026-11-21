"""M717 known-answer tests for tools/winter_freeze.py: the frozen winter predictions equal a fresh derivation from their (hashed) source files, the derived numbers follow their stated formulas, every prediction carries a rule,
and the file's sha256 is recorded in the CHANGELOG (frozen by value and CHANGELOG hash before 2026-12-01)."""
import hashlib, json, math, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_freeze as WF

# M721 (Director ruling): the freeze is verified against its OWN inputs. The live files of three sources (state_params, scenario_results_production, scenario_gates) are regenerated at each ingestion (scenario_refresh) and may differ;
# every source is taken from the live tree when its sha256 equals the freeze record, else from the byte-exact frozen copy in analyses/M717_frozen_sources/ (its sha256 must equal the record; no other fallback), and `--check` runs in a temp tree.
import shutil, subprocess, tempfile
_F0 = json.load(open(WF.OUT, encoding="utf-8"))
assert _F0["scriptSha256"] == hashlib.sha256(open("tools/winter_freeze.py", "rb").read()).hexdigest(), "tools/winter_freeze.py changed since the freeze"
_idx = json.load(open("analyses/M717_frozen_sources/index.json", encoding="utf-8"))
_td = tempfile.mkdtemp()
try:
    os.makedirs(os.path.join(_td, "tools")); os.makedirs(os.path.join(_td, "analyses"))
    shutil.copy("tools/winter_freeze.py", os.path.join(_td, "tools")); shutil.copy(WF.OUT, os.path.join(_td, WF.OUT))
    _live_differs = []
    for _k, _v in _F0["sources"].items():
        _dst = os.path.join(_td, _v["path"]); os.makedirs(os.path.dirname(_dst), exist_ok=True)
        if os.path.exists(_v["path"]) and hashlib.sha256(open(_v["path"], "rb").read()).hexdigest() == _v["sha256"]:
            shutil.copy(_v["path"], _dst)
        else:
            assert _k in _idx and _idx[_k]["sha256"] == _v["sha256"] and _idx[_k]["path"] == _v["path"], "no frozen copy for " + _k
            _b = open(_idx[_k]["frozenCopy"], "rb").read()
            assert hashlib.sha256(_b).hexdigest() == _v["sha256"], "frozen copy differs from the freeze record: " + _k
            open(_dst, "wb").write(_b); _live_differs.append(_k)
    assert set(_live_differs) <= {"stateParams", "scenarioResults", "scenarioGates"}, _live_differs
    _r = subprocess.run([sys.executable, os.path.join("tools", "winter_freeze.py"), "--check"], cwd=_td, capture_output=True, text=True, encoding="utf-8")
    assert _r.returncode == 0, "the frozen file differs from a fresh derivation from its own frozen inputs: " + _r.stdout[-600:] + _r.stderr[-300:]
finally:
    shutil.rmtree(_td, ignore_errors=True)
F = json.load(open(WF.OUT, encoding="utf-8"))
P, prm = F["predictions"], F["params"]
assert set(P) == {"P1", "P2", "P3", "P4", "P5", "P6", "P7"} and all(v.get("rule") for v in P.values())
# formulas
ea = prm["R_T"]["EaR_kJmol"]
assert abs(P["P3"]["ratio_R_0C_vs_25C"] - round(math.exp(ea * 1000 / 8.314462618 * (1 / 273.15 - 1 / 298.15)), 3)) < 1e-12 and P["P3"]["interval"][0] < P["P3"]["ratio_R_0C_vs_25C"] < P["P3"]["interval"][1]
b0, bT = prm["limitMap"]["b0_kW_at_0C_soc60"], prm["limitMap"]["bT_kW_perC"]
assert abs(P["P4"]["kW_at_minus10C"] - round(b0 - 10 * bT, 2)) < 1e-12 and P["P4"]["envelope_at_minus10C"][0] < P["P4"]["kW_at_minus10C"] < P["P4"]["envelope_at_minus10C"][1]
assert abs(P["P6"]["C_at_0C_soc60"] - round(b0 * 1000 / 360 / 5, 2)) < 1e-12
assert P["P2"]["bandAhShareBelow10C"][0] < P["P2"]["bandAhShareBelow10C"][1]
assert P["P7"]["points_per_C_cooling_ambientBelow20C"][1] < P["P7"]["points_per_C_cooling_ambientBelow20C"][0] < P["P7"]["points_per_C_cooling_ambientBelow20C"][2]
# the frozen park constants are the M709 fit (one offset), the freeze is dated before the first winter drive
pk = json.load(open("analyses/M709/park_model.json", encoding="utf-8"))["M2_fullSample_nonFlagged"]
assert prm["park"]["tau_h"] == pk["tau_h"] and prm["park"]["offset_C"] == pk["offset_C"] and prm["park"]["oneOffsetAllSeasons"] and prm["park"]["offsetBracketForSensitivity"] == [0.0, 2.7]
assert "2026-12-01" in F["status"] and F["evaluation"]["cells"].startswith("each evaluation cell needs >= 10")
# the CHANGELOG records the sha256 of the frozen file
h = hashlib.sha256(open(WF.OUT, "rb").read()).hexdigest()
head = open("CHANGELOG.md", encoding="utf-8").read(400000)
assert h in head, "the sha256 of analyses/M717_winter_predictions.json must be recorded in the CHANGELOG (M717 entry)"
print("test_winter_freeze: ok")
