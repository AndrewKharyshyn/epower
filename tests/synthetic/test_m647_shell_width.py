"""M647 (UI-01 remainder): the page shell is wide enough for the Compare charts (inner maxWidth 1128, #root max-width 1160) and a square svg is capped in height (max-height 640 px).
The pixel measurement (no overflow, no text under 9 px, no overlap at 1024 and 1400 px) needs a real browser: tools/ui_scan_compare.js."""
import os
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
J = open(os.path.join(REPO, "xtrail_summary.jsx"), encoding="utf-8").read()
B = open(os.path.join(REPO, "build_html.js"), encoding="utf-8").read()
assert 'padding:16,maxWidth:1128,margin:"0 auto"' in J and "maxWidth:740" not in J
assert "#root{max-width:1160px;" in B and 'svg[width="100%"]{max-height:640px}' in B
print("PASS test_m647_shell_width")
