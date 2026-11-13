"""M644 (UI-01 layout part): the Compare renderers keep every SVG text at 9 px or more, use a fixed-width svg inside a scrolling wrapper, and the dot plot has its value column.
The pixel-level scan itself needs a real browser: tools/ui_scan_compare.js (see CHANGELOG M644 for the measured counts)."""
import os, re
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
J = open(os.path.join(REPO, "xtrail_summary.jsx"), encoding="utf-8").read().replace("\r\n", "\n")
def fn(name, end):
    i = J.index("function " + name + "("); j = J.index("function " + end + "(", i + 10); return J[i:j]
for name, end in (("CmpBox", "CmpKpi"), ("CmpKpi", "NotObservedRow"), ("NotObservedRow", "CmpBars"), ("CmpBars", "CmpLines"), ("CmpLines", "ColdConcentrationNote"), ("CmpEcdfPanel", "CmpViolinPanel"), ("CmpViolinPanel", "CompareMulti")):
    seg = fn(name, end)
    sizes = [float(x) for x in re.findall(r"fontSize=\{([0-9.]+)\}", seg)]
    assert sizes and min(sizes) >= 9, (name, sorted(set(sizes)))
for name, end in (("CmpBox", "CmpKpi"), ("CmpKpi", "NotObservedRow"), ("CmpBars", "CmpLines"), ("CmpLines", "ColdConcentrationNote")):
    seg = fn(name, end)
    assert 'overflowX:"auto"' in seg and "width={W}" in seg and 'width="100%" viewBox' not in seg, name
bars = fn("CmpBars", "CmpLines")
assert 'data-cmp-value="1"' in bars and "labelW=190" in bars and "const vx=" in bars and 'y={cy-6} textAnchor="middle" fontSize={7}' not in bars
assert 'data-cmp-frame="1"' in J and "data-cmp-kind={kind}" in J
assert os.path.exists(os.path.join(REPO, "tools", "ui_scan_compare.js"))
print("PASS test_m644_compare_layout")
