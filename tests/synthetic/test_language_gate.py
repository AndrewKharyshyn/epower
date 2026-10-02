"""M326 known-answer tests for language_gate.py (matching rules per Director rev 2) and a regression check on the existing semantic_gate FORBIDDEN list."""
import ast, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, ROOT)
import language_gate as lg

# normalisation: arrows/hyphens/slashes/case/NFKC collapse
assert lg.norm("Tank→Traction") == "tank traction" and lg.norm("fuel-rate  PID") == "fuel rate pid" and lg.norm("410/410") == "410 410"
# positive hits: plural, case, hyphen, concatenated-words (jsdom dump) variants
assert lg.hit_phrase("no fuel-rate PID", "There is NO Fuel Rate PID on this drive")
assert lg.hit_phrase("amplitude floor", "a 1.0% Amplitude Floors rule") and lg.hit_phrase("amplitude floor", "amplitudefloor")      # plural + stripped form
assert lg.scan_text("not transfer re-serializations") == ["M325-reserialize"], lg.scan_text("not transfer re-serializations")
assert "M325-reserialize" in lg.scan_text("a transfer re-serialization (BOM)")
assert "M325-410" in lg.scan_text("byte-identical within the study archive, 410/410")
assert "W0-zerogtc" in lg.scan_text("early logs that contribute 0.0 GTC") and "W0-zerogtc" in lg.scan_text("this contributes 0.0 gtc")
assert "W0-fuelflow-avail" in lg.scan_text("fuel-flow / injector data are not available to confirm it.")
assert "W0-fuelflow-avail" in lg.scan_text("would require fuel-flow data, which the OBD logger does not provide.")
assert "W0-fuelflow-avail" in lg.scan_text("that would require fuel-flow data the logger does not provide.") and "W0-fuelflow-avail" in lg.scan_text("the OBD stream carries no fuel-flow channel.")
assert lg.scan_text("85 of those drives carry the fuel-flow PID.") == [] and lg.scan_text("no injector data are logged, and the logged fuel rate is app-calculated (air-flow based)") == []
assert "W0-zerogtc" in lg.scan_text("they contribute zero GTC") and "W0-zerogtc" in lg.scan_text("contributes 0 GTC")
assert "W0-fuelflow" in lg.scan_text("There is no fuel-flow data in the corpus") and "W0-fuelflow" in lg.scan_text("no fuel flow channel")
assert "M325-originals" in lg.scan_text("originals unavailable") and "M325-originals" in lg.scan_text("the originals are unavailable")
# context rule: 'great majority' only with fuel/PID nearby; unrelated use passes
assert "W0-greatmajority" in lg.scan_text("no fuel-rate PID on the great majority of drives")
assert lg.scan_text("the great majority of cycles are shallow") == []
# negation allowance and window (generic ctx fixture, used by later waves, e.g. 'measured' near fuel/generator)
assert lg.hit_ctx("measured", ["fuel", "generator"], "fuel energy is measured by the shunt")
assert not lg.hit_ctx("measured", ["fuel", "generator"], "fuel energy is not measured here")
assert not lg.hit_ctx("measured", ["fuel", "generator"], "the odometer is measured and the weather was warm and the road long and fuel")   # outside the 4-token window
# hedged, correct text must NOT fail
for ok in ["engine brake thermal efficiency is therefore model-derived", "the logged fuel rate is calculated by the logger app and present on a subset of drives",
           "cycles with a range below 1.0 pp are dropped", "the remainder are excluded from GTC, not counted as zero", "156 of 489 canonical archived copies match the manifest"]:
    assert lg.scan_text(ok) == [], (ok, lg.scan_text(ok))
# payload: values only, never keys
assert lg.scan_payload({"amplitude floor": "ok", "RegenByTempMeasured": {"x": "fine"}}) == {}
assert "W0-amplitude" in lg.scan_payload({"a": [{"b": "1.0% amplitude floor"}]})
# jsx: strings FAIL, comments WARN
code, warn = lg.scan_jsx("const a = 1; // no fuel-rate PID in comment\n/* amplitude floor block comment */\nconst t = 'ok';")
assert code == [] and set(warn) == {"W0-fuelpid", "W0-amplitude"}, (code, warn)
code, warn = lg.scan_jsx("<p>byte-identical, 410/410</p>")
assert code == ["M325-410"] and warn == []
# regression: every existing semantic_gate FORBIDDEN phrase is detectable by the new matcher (migration safety)
src = open(os.path.join(ROOT, "semantic_gate.py"), encoding="utf-8").read()
tree = ast.parse(src)
fb = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "FORBIDDEN"][0]
phrases = [e.elts[0].value for e in fb.value.elts if isinstance(e.elts[1], ast.Constant) and e.elts[1].value is not None]
assert len(phrases) >= 26, len(phrases)
for p in phrases:
    if not lg._words(p):
        continue                                       # purely symbolic entries cannot be word-matched; they stay on the exact-substring check A
    assert lg.hit_phrase(p, "xx " + p + " yy"), p
print("OK language_gate: normalisation, plural/stripped/ctx/negation rules, payload-values-only, jsx comments WARN, %d legacy phrases still detectable" % len(phrases))
