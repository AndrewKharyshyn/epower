"""M717 known-answer tests for tools/winter_freeze.py: the frozen winter predictions equal a fresh derivation from their (hashed) source files, the derived numbers follow their stated formulas, every prediction carries a rule,
and the file's sha256 is recorded in the CHANGELOG (frozen by value and CHANGELOG hash before 2026-12-01)."""
import hashlib, json, math, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_freeze as WF

assert WF.main(["--check"]) == 0, "the frozen file differs from a fresh derivation or a source hash changed"
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
