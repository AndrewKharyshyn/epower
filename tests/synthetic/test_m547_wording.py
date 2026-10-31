"""M547 (analyses/M547_spec.md Rev 2.1): known-answer tests for the audit 2026-10-29 wording wave. Every OLD wording fires its rule; the NEW wording (and hedged correct forms) does not; the two payload leaves carry the new text; the Health conclusions are generated from the interval, not static."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

R = {r.rid: r for r in G.RULES if r.rid.startswith("M547")}
assert len(R) == 16, sorted(R)

OLD = {
    "M547-F02-altitude": ["altitude does not significantly predict the SoC ceiling itself", "The mechanism is solid; the terrain attribution is not."],
    "M547-F03-bound": ["the interval can only exclude resistance growth faster than its CI half-width", "The voltage-sag resistance proxy shows no trend over 5 months", "No resistance-proxy trend is detectable"],
    "M547-F04-static-spread": ["A cell-voltage-spread trend is not established in this window", "A cell-spread or resistance trend is not established in this window"],
    "M547-F06-boost": ["two unrelated sensors agreeing on the ceiling", "from the dedicated boost channel", "(~1.5 bar gauge)"],
    "M547-F07-cadence-immune": ["is therefore cadence-immune by construction"],
    "M547-F08-dissipation": ["gives the independent lower bound", "Publish as a range", "Diverted from the pack", "Bias-corrected excess", "Negative control (fuel-cut coast)"],
    "M547-F09-fuel-state": ["strictly boost-verified, no proxy", "engine spun unfuelled to dump surplus regen", "Fuelled generation only"],
    "M547-F10-bms-soc": ["BMS SoC - actual (hidden from driver)", "to look more reassuring", "above which it flatters"],
    "M547-F11-generator-headroom": ["the generator always has ample headroom", "is statistically identical to that of engine-on charging seconds", "The decisive null result", "the reserve measured above", "the generator still held"],
    "M547-F12-thermal-margin": ["Comfortably within typical limits."],
    "M547-F13-sensor-range": ["a single corrupted current reading (-200.25A, outside sensor's valid range)", "not a real cell event"],
    "M547-F14-one-filter": ["All aggregate statistics in this dashboard filter on ens_outlier_v2"],
    "M547-F16-capacity-fade-tab": ["Capacity fade — scenarios"],
    "M547-F18-risk-zones": ["plating zone", "lithium plating risk at high C-rate"],
    "M547-F19-cell-case": ["Full-Cell Array Worked Examples", "the drivetrain's full output ceiling"],
    "M547-S9-labels": ["Pure-electric traction support", "Car OFF standby"],
}
for rid, texts in OLD.items():
    for t in texts:
        assert rid in G.scan_text(t), (rid, t)

# NEW wording (the replacements) and hedged correct forms must not fire any M547 rule
NEW = [
    "The logged altitude proxy shows a weak association with dissipation time (rho=0.17, nominal unadjusted p) and with the trip maximum SoC; these p-values are not clustered by day or route and not multiplicity-adjusted.",
    "The conditional 95% slope interval extends up to 1.837 mOhm/month; its upper endpoint, not its half-width, limits the growth compatible with this model.",
    "Loaded cell-voltage spread rises under the published temperature/current adjustment; the lower bound is procedure-dependent; battery ageing is not identified",
    "A cell-voltage-spread trend is not resolved in this window",
    "Calculated boost is an app-derived channel related to manifold pressure, so this is an internal consistency check, not an independent sensor validation.",
    "evaluated on a common 1 Hz grid; residual native-cadence sensitivity is not removed",
    "separate unvalidated model scenarios with unknown errors, not a physical bound",
    "Fuelled proxy (boost-based); no injector or fuel-cut ground truth exists. Motoring-candidate seconds only.",
    "Reported BMS SoC (%). Neither is a calibration of physical SoC or of the manufacturer's design intent.",
    "No event meets the declared saturation screen; generator output and reserve are not metered; equivalence was not tested.",
    "No applicable pack-specific thermal margin is established by these logs.",
    "Each metric family declares its own eligible drives, days and distance",
    "Exposure scenarios", "Selected cell-channel snapshots", "peak commanded (target) motor torque",
    "Engine-off travel support", "Parked SoC-drift equivalent", "battery energy reference 2.1 kWh, assumed",
    "Cooler", "Intermediate", "Warmer", "generic reference context, not validated Nissan limits and not a damage or safety verdict",
]
for t in NEW:
    hit = [r for r in G.scan_text(t) if r.startswith("M547")]
    assert not hit, (hit, t)

# payload leaves carry the new text (spliced by tools/m547_splice.py)
a = json.load(open("summary_arrays.json", encoding="utf-8"))
assert not [r for r in G.scan_text(a["lowSpeedDissipation"]["relief"]["verdict"]) if r.startswith("M547")]
note = next(r for r in a["records"] if r["metric"] == "Peak motor torque")["note"]
assert "full output ceiling" not in note and "commanded" in note and not [r for r in G.scan_text(note) if r.startswith("M547")]

# fact-aware cell-spread check (M427) agrees with the new generated texts for a positive and a zero-spanning interval
pos = [0.2665, 0.7814]; zero = [-0.3, 1.2]
assert G.cell_spread_trend_violations(pos, {"t": "Loaded cell-voltage spread rises under the published adjustment; this conditional proxy trend does not establish battery ageing."}) == []
assert G.cell_spread_trend_violations(zero, {"t": "The loaded cell-voltage spread trend is not resolved."}) == []

# the Health conclusions are generated from the interval and the M477 rowsRule, not static titles
jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
assert "function spreadConclusion()" in jsx and "function resistanceConclusion()" in jsx
assert 'title="A cell-voltage-spread trend is not established' not in jsx
assert "title={spreadConclusion().title}" in jsx and "status={spreadConclusion().status}" in jsx and "caveat={spreadConclusion().caveat}" in jsx
assert 'rr?.classification==="procedure-dependent"' in jsx.split("function spreadConclusion()")[1].split("function resistanceConclusion()")[0]
# the half-width is never presented as the exclusion bound
assert "upper endpoint" in jsx.split("function resistanceConclusion()")[1][:1500]
print("test_m547_wording OK")
