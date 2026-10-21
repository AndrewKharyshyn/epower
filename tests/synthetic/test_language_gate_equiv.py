"""M470 (audit speed): language_gate normalises each text once, precompiles per-rule data and caches results per distinct text. The decisions must be EXACTLY the former per-rule, per-call ones: the oracle below is the
former implementation (hit_phrase / norm+regex / hit_ctx, which are unchanged module functions). Compared on every distinct string of the live payload and config, the JSX source (code and comments), all rendered tab dumps
when present, and the rule fixtures; the ordered rule-hit lists and the payload-location reports (duplicates kept) must be identical. Timing is printed, not asserted."""
import glob, json, os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G


def ref_hits(r, text):
    if r.kind == "phrase":
        return G.hit_phrase(r.phrase, text)
    if r.kind == "regex":
        return bool(r.rx.search(G.norm(text)))
    return G.hit_ctx(r.term, r.near, text, r.window)


def ref_scan_text(text):
    return [r.rid for r in G.RULES if ref_hits(r, text)]


def ref_scan_payload(obj):
    out = {}
    for s in G.payload_strings(obj):
        for rid in ref_scan_text(s):
            out.setdefault(rid, []).append(s[:80])
    return out


A = json.load(open("summary_arrays.json", encoding="utf-8")); C = json.load(open("summary_config.json", encoding="utf-8"))
jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
code, comm = G.split_jsx(jsx)
pay = list(dict.fromkeys(list(G.payload_strings(A)) + list(G.payload_strings(C))))[::4]      # deterministic quarter of the distinct strings keeps the oracle run short
texts = pay + [code, comm]
for f in sorted(glob.glob("tabtext/*.txt"))[:6]:
    texts.append(open(f, encoding="utf-8").read())
texts += ["", "no fuel-rate PID", "the great majority of drives carry no fuel", "raw +0.61 mV/month flips to −0.39 mV/month", "NO CAPACITY OBSERVABLE", "x" * 5000]
t0 = time.time(); ref = [ref_scan_text(t) for t in texts]; t_ref = time.time() - t0
t0 = time.time(); new = [G.scan_text(t) for t in texts]; t_new = time.time() - t0
assert ref == new, [i for i, (a, b) in enumerate(zip(ref, new)) if a != b][:5]
assert [G.scan_text(t) for t in texts] == ref, "cached second pass must agree"
for t in texts[:50]:
    r1 = G.scan_text(t); r1.append("mutation"); assert "mutation" not in G.scan_text(t), "cache must hand out copies"
dup = pay[:300] + pay[:300]      # duplicate locations stay reported even though the classification is cached
assert G.scan_payload(dup) == ref_scan_payload(dup), "payload location reports (with duplicates) must agree"
refd = dict(zip(texts, ref))
assert G.scan_jsx(jsx) == (refd[code], refd[comm])
tmp = [G.Rule("T1", "phrase", "x", phrase="alpha beta gamma delta"), G.Rule("T2", "ctx", "x", term="alpha", near=("beta",), window=2)]      # a caller-supplied rule list is never cached
assert G.scan_text("alpha beta", tmp) == ["T2"] and G.scan_text("alphabetagammadelta", tmp) == ["T1"] and G.scan_text("alpha beta", tmp) == ["T2"]
print("OK test_language_gate_equiv (%d texts, %d rules; former %.2f s, now %.2f s)" % (len(texts), len(G.RULES), t_ref, t_new))
