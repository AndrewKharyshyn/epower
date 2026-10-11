"""M404: language-gate rules have known-answer hits, no rule pattern contains a control character (a stray backspace from a mis-escaped \b silently disabled M401-N06-hardlevel), and the
payload carries the corrected Article-10 wording."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

bad = [r.rid for r in G.RULES if r.rx is not None and any(ord(c) < 32 for c in r.rx.pattern)]
assert not bad, "control character in the pattern of rule(s): %s" % bad
R = {r.rid: r for r in G.RULES}
assert R["M401-N06-hardlevel"].hits("overlapping windows make the effective hard level about 1/(n_eff+1) = 1/9")
assert not R["M401-N06-hardlevel"].hits("the rank resolution is about 1/(n_eff+1); not a calibrated false-alarm rate")
assert R["M404-percell"].hits("the separate, OEM-disclosed 5.0 Ah per-cell figure (EU Battery Regulation 2023/1542 Art. 10)")
assert not R["M404-percell"].hits("the separate Nissan-disclosed rated capacity of 5 Ah (X-Trail e-POWER T33, EU Battery Regulation 2023/1542 Art. 10)")
a = json.load(open("summary_arrays.json", encoding="utf-8"))
cp = a["constantProvenance"]
assert not R["M404-percell"].hits(cp["CAP_KWH"]["note"]) and "CAP_AH_RATED" in cp["CAP_KWH"]["note"]
assert "Wh divided by the nominal" in cp["CAP_AH_RATED"]["quantity"] or "divided by the nominal battery voltage" in cp["CAP_AH_RATED"]["quantity"]
print("OK test_m404_wording")
