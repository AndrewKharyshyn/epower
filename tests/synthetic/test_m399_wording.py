"""M399 (audits 2026-10-11): the replaced statements are forbidden by the language gate (known-answer: OLD wording hits, NEW wording does not),
the JSX has no silent numeric capacity fallback, and the MC refresh module is import-safe."""
import os, re, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import language_gate as G

OLD = {
    "M399-N09-gross2x": "The two answer different questions and must not be mixed; gross runs ~2× net.",
    "M399-N09-auditfooter": "the audit could not verify raw-stream results because the 1 Hz corpus was not in the audit package.",
    "M399-D3-hz": "Sub-5 s relaxation is not resolvable at the ~1.3 Hz cadence; accel(g) sensor (~1.26 Hz)",
    "M399-F16-linear": "All three figures scale linearly with the unverified 2.1 kWh capacity. Every GTC / FCE / C-rate figure scales linearly with this constant. scales linearly with the assumed pack capacity; scales linearly with this value; Every figure here scales linearly with CAP_KWH; scales linearly with it",
    "M399-F16-nooem": "assumed normalization constant (press-cited planning figure, not a published OEM spec); unverified and not an OEM nameplate figure; do not publish a cell/pack energy-capacity spec",
    "M399-F16-uniquealt": "CAP_KWH has exactly one credible alternative reference point, not a distribution",
    "M399-archaeology": "M58 (2026-07-27): this paragraph previously quoted; the prior hand-typed figure; refreshed at M373 per-second",
}
rules = {r.rid: r for r in G.RULES}
for rid, text in OLD.items():
    assert rid in rules and rules[rid].hits(text), rid
for t in ("Generator energy scales linearly with density.",                       # a correct statement elsewhere in the payload
          "GTC and FCE scale inversely with the selected reference capacity.",
          "HV-current PID median update interval 1.28 s, ≈0.78 Hz",
          "Nissan Australia publishes 2.1 kWh for the e-4ORCE model; gross versus usable is undefined and FWD applicability is unverified.",
          "recomputed on the live corpus at ingestion"):
    hit = [rid for rid, r in rules.items() if rid.startswith("M399-") and r.hits(t)]
    assert not hit, (t, hit)

# JSX: no silent numeric fallback on a payload constant, no Hz-first cadence statement
jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
bad = re.findall(r"CAP_KWH\?\.value\s*\?\?\s*[0-9.]+|cap\.value\s*\?\?\s*[0-9.]+", jsx)
assert not bad, bad

# N08: importing the MC note refresher writes nothing and exposes a pure refresh()
import hashlib
h0 = hashlib.sha256(open("summary_arrays.json", "rb").read()).hexdigest()
import mc_dq_note_refresh as R, pandas as pd
assert hashlib.sha256(open("summary_arrays.json", "rb").read()).hexdigest() == h0 and callable(R.refresh)
# pure refresh on a tiny object: numeric corpus total preferred over parsing prose; nothing outside dataQualityNote changes
A = {"x": 1, "energyUncertaintyMC": {"grossThroughputMC": {"dataQualityNote": {"corpusTotalKwh": 0.077, "finding": "stale prose (999 kWh corpus-wide)",
     "topContributors": [{"file": "a.csv", "nominalKwh_1500ms": 0.0, "deltaKwh_1500to2000ms": 0.0376, "cumulativePctOfTotalWidening": 49.0}]}}}}
new, ch, bad = R.refresh(A, pd.Series({"a.csv": 9.9051}))
assert not bad and new["energyUncertaintyMC"]["grossThroughputMC"]["dataQualityNote"]["topContributors"][0]["nominalKwh_1500ms"] == 9.9051
assert "999" not in new["energyUncertaintyMC"]["grossThroughputMC"]["dataQualityNote"]["finding"] and A["x"] == 1
print("OK test_m399_wording")
