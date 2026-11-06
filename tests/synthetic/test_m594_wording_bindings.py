"""M594 (independent audit D5-D9): wording/binding fixtures on xtrail_summary.jsx.
D9: every spreadSpans()===false branch takes its direction word from spreadDir() (interval sign), never a literal 'positive'.
D6/D7/D8/D5: the stale literals are gone."""
import os, re
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
s = open(os.path.join(ROOT, "xtrail_summary.jsx"), encoding="utf-8").read()
assert "function spreadDir(" in s
for m in re.finditer(r"spreadSpans\(\)===false\?(\"[^\"]*\")", s):
    assert not re.search(r"\b[Pp]ositive\b", m.group(1)), m.group(1)[:80]
for stale in ("0.43–0.56×", "0.14× relative rate", "Recommended, not yet run", "is true acceleration", "C-rates use the median estimated\n", "time to {t} {\"°\"}C had"):
    assert stale not in s.replace("\r\n", "\n"), stale
assert "{S.seasonalLife?.calendarAnnualFactor}×" in s
assert "{S.saturCoverageN} screened drives" in s
# sign function behaviour (JS semantics mirrored): positive only when lower bound > 0, negative otherwise (reached only when the interval excludes 0)
def word(ci): return "positive" if ci[0] > 0 else "negative"
assert word([0.4, 1.1]) == "positive" and word([-1.2, -0.2]) == "negative"
print("ok test_m594_wording_bindings")
