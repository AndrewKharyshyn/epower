#!/usr/bin/env python3
"""M528 A3 (analyses/M528_spec.md Rev 2): read-only pattern sweep for dated history read as current ('current', 'now', 'freshly', 'pending', 'live' within a short window of a drive count N,
100 <= N < 606) in the string leaves of summary_arrays.json and summary_config.json and in xtrail_summary.jsx string text. Writes analyses/M528_a3_sweep.json (counts, patterns, hits).
In scope = the two M528 leaves (config drivingMixNote, payload generatorTractionRecon._provenance); every other hit is an out-of-scope follow-up. A pattern sweep cannot find other wording."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
LIVE = 606
PAT = re.compile(r"(?:\bcurrent(?:ly)?\b|\bnow\b|\bfreshly\b|\bpending\b|\blive\b)[^.;]{0,80}?\b(\d{2,3})[- ]drives?\b|\b(\d{2,3})[- ]drives?\b[^.;]{0,60}?(?:\bcurrent(?:ly)?\b|\bnow\b|\bfreshly\b|\blive\b)", re.I)
IN_SCOPE = {("config", "/drivingMixNote"), ("payload", "/generatorTractionRecon/_provenance")}
hits, counts = [], {"payload": 0, "config": 0, "jsx": 0}

def scan(text, src, path):
    for m in PAT.finditer(text):
        n = int(m.group(1) or m.group(2))
        if 100 <= n < LIVE:
            hits.append({"src": src, "path": path, "n": n, "fragment": text[max(0, m.start() - 30):m.end() + 30].replace("\n", " ")})

def walk(o, p, src):
    if isinstance(o, dict):
        for k, v in o.items(): walk(v, p + "/" + k, src)
    elif isinstance(o, list):
        for i, v in enumerate(o): walk(v, p + "/" + str(i), src)
    elif isinstance(o, str):
        counts[src] += 1; scan(o, src, p)

walk(json.load(open("summary_arrays.json", encoding="utf-8")), "", "payload")
walk(json.load(open("summary_config.json", encoding="utf-8")), "", "config")
for i, line in enumerate(open("xtrail_summary.jsx", encoding="utf-8"), 1):
    s = line.strip()
    if s.startswith("//") or s.startswith("{/*") or s.startswith("*"):
        continue
    counts["jsx"] += 1; scan(line, "jsx", "line %d" % i)
for h in hits:
    h["inScope"] = (h["src"], re.sub(r"^(/[^/]+(?:/[^/]+)?).*", r"\1", h["path"]) if h["src"] == "payload" else "/" + h["path"].strip("/").split("/")[0]) in IN_SCOPE
in_scope = [h for h in hits if h["inScope"]]
# in-scope leaves must not carry the OLD wording (the then-current / at-that-date wording is the point); report them for the record
old_wording = ["Current dataset distance mix (audit 2026-07-14)", "corrects the DISTANCE mix", "recomputed on the current 194-drive corpus", "freshly recomputed from the current 374-drive rpmDistribution"]
cfg_txt = json.load(open("summary_config.json", encoding="utf-8"))["drivingMixNote"]
prov = json.load(open("summary_arrays.json", encoding="utf-8"))["generatorTractionRecon"]["_provenance"]
old_left = [o for o in old_wording if o in cfg_txt or o in prov]
out = {"patterns": "current|currently|now|freshly|pending|live within 80 chars before / 60 after 'N-drive(s)', 100 <= N < %d" % LIVE, "stringsScanned": counts, "nHits": len(hits),
       "inScopeResidualOldWording": old_left, "hits": hits, "outOfScope": [h for h in hits if not h["inScope"]]}
json.dump(out, open(os.path.join("analyses", "M528_a3_sweep.json"), "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
print(json.dumps({"stringsScanned": counts, "nHits": len(hits), "inScopeResidualOldWording": old_left, "nOutOfScope": len(out["outOfScope"])}))
sys.exit(1 if old_left else 0)
