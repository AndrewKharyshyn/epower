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
# W2a rules
assert "W2-nocold" in lg.scan_text("(Warm/Shoulder; no Cold)") and "W2-nocold" in lg.scan_text("regimes; No Cold) winter")
assert lg.scan_text("no cold-pack thermal behaviour observed") == [] and lg.scan_text("no cold soak was verified") == []      # near-misses must pass
assert "W2-sub15" in lg.scan_text("No sub-15°C pack data exists") and "W2-sub15" in lg.scan_text("no sub-15 °C ambient data")
assert "W2-seasonlabel" in lg.scan_text("All-data reference · season filter does not apply") and lg.scan_text("thermal-cohort filter does not apply") == []
assert "W2-warmseason-corpus" in lg.scan_text("the whole corpus is warm-season, so pack") and "W2-warmseason-corpus" in lg.scan_text("Warm-season data only.")
assert lg.scan_text("Cold: 2 observed drives on 1 date (2026-09-30), below the minimum support") == []
# W3a rules
assert "W3-measuredfade" in lg.scan_text("Power fade is measured (M25)") and "W3-measuredfade" in lg.scan_text("the measured power-fade trend")
assert lg.scan_text("a proxy, not a power-fade measurement") == []
assert "W3-nodetectable" in lg.scan_text("No detectable cell-spread trend at 8741 km") and lg.scan_text("Cell-spread trend not resolved at 8741 km") == []
assert "W3-nofade" in lg.scan_text("zero — no fade") and lg.scan_text("zero trend") == []
assert "W3-mde" in lg.scan_text("MDE ±1.7%/yr") and "W3-mde" in lg.scan_text("the minimum detectable effect") and "W3-mde" in lg.scan_text("read with its detection limit")
assert lg.scan_text("95% CI half-width ±1.7%/yr (precision, not a power calculation)") == []
assert "W3-mde" in lg.scan_text("minimum detectable fade") and "W3-mde" in lg.scan_text("not yet resolvable now") and "W3-mde" in lg.scan_text("would need a 24-month window")
assert lg.scan_text("equals the half-width after ~24 months (planning figure, ~50% power)") == []
assert lg.scan_text("gap detection and the PID cadence") == []
assert "W3-wikner" in lg.scan_text("(5%, protective per Wikner)") and "W3-wikner" in lg.scan_text("elevated per Wikner") and lg.scan_text("lower-weight rung: assumed, Wikner cross-check") == []
assert "W3-sharedcoolant" in lg.scan_text("ambient, tracking the shared coolant loop and sustained load") and lg.scan_text("tracking sustained load") == []
# W4a rules
assert "W4-measuredcapture" in lg.scan_text("= measured capture efficiency — the fraction") and "W4-measuredcapture" in lg.scan_text("measured capture by pack temperature (M22)")
assert lg.scan_text("apparent kinetic-energy recovery proxy") == [] and lg.scan_text("apparent KE recovery by pack temperature") == []
assert "W4-fulldod" in lg.scan_text("the cumulative damage is only 99 full-DoD-equivalents") and "W4-fulldod" in lg.scan_text("full-DoD-equivalent cycles")
assert lg.scan_text("a full-DoD cycle unchanged") == [] and lg.scan_text("depth-squared weighted cycle sum (generic k=2, uncalibrated)") == []
assert "W4-10x" in lg.scan_text("roughly a 10× depth mitigation") and "W4-10x" in lg.scan_text("(~10× mitigation).") and "W4-10x" in lg.scan_text("roughly a 10x mitigation")
assert lg.scan_text("a depth-weighting scenario, not a measured mitigation") == [] and lg.scan_text("10 drives were mitigated") == []
assert "W4-ambientbin" in lg.scan_text("Apparent KE recovery proxy by ambient bin (%)") and lg.scan_text("recovery proxy by pack-temperature bin") == []
assert "W4-pureregenkpi" in lg.scan_text("peak charging ceiling (pure regen)") and lg.scan_text("peak charging ceiling (engine-off braking; classifier-conditional)") == []
assert lg.scan_text("high-SoC reduction (pure regen)") == ["W4-pureregenkpi"]
assert "W4-startproxy" in lg.scan_text("Engine-start proxy per 100 km") and lg.scan_text("Current-direction reversals per 100 km, not a counted engine start") == []
# W5a rules
assert "W5-preinstr" in lg.scan_text("is the pre-instrumentation-era files with no pack-temperature channel at all, unrelated to ambient coverage")
assert lg.scan_text("is drives that do not enter the ambient rows (no parseable recorded ambient value, or no Sensor-1 pack-temperature trajectory)") == []
assert "W5-novel" in lg.scan_text("the first-ever study") and "W5-novel" in lg.scan_text("a novel method") and lg.scan_text("the first drives of May") == []
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
