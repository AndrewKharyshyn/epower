"""M325 tests: provenance block and dashboard wording (analyses/M325_spec.md rev 2, rule 3) and originals_manifest.json consistency (rule 2)."""
import json, os, re
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..", "..")
J = lambda f: json.load(open(os.path.join(ROOT, f), encoding="utf-8"))
FORBIDDEN = ["originals unavailable", "originals are unavailable", "proven", "reproducible from raw data", "corrections", "410/410", "re-serializ",
             "authenticated"]

def strings(o):
    if isinstance(o, str): yield o
    elif isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)

prov, om, rm = J("f03_provenance.json"), J("originals_manifest.json"), J("raw_manifest.json")
arr_prov = J("summary_arrays.json")["provenanceSensitivity"]
assert arr_prov == prov, "summary_arrays.json provenanceSensitivity must equal f03_provenance.json (run f03_provenance_flag.py)"

# every string of the provenance block: no forbidden wording. 'corrections' / 'proven' occur only inside the NEGATIVE guidance bullets of `wording`.
body = {k: v for k, v in prov.items() if k != "wording"}
for t in strings(body):
    for f in FORBIDDEN:
        assert not re.search(r"(?<![A-Za-z])" + re.escape(f) + r"(?![A-Za-z])", t), (f, t[:120])   # word-bounded: 'provenance' contains 'proven'
assert any("never 'proven'" in t and "sha256-verified originals is consistent with the published raw-derived non-ML" in t for t in prov["wording"])
_rp = os.path.join(ROOT, "tabtext", "conclusions__all.txt")
if os.path.exists(_rp):    # rendered footer (written by dump_tabs.js; git-ignored, so only checked when present)
    assert not re.search(r"re-?serializ", open(_rp, encoding="utf-8").read()), "rendered footer must not carry the re-serialization wording"

# counts come from the manifests, not from typing
canon = [r for r in rm["files"] if r["role"] == "canonical"]
nc, fc = prov["raw"]["nCanonical"], prov["raw"]["nCanonicalHashFailing"]
assert nc == len(canon) and prov["raw"]["originalsAvailable"] is True
assert f"{fc}/{nc} canonical raw copies in raw/ do not match recorded hashes" in prov["disclosure"]
assert f"for all {fc}" in prov["disclosure"] and "non-ML" in prov["disclosure"] and "F03 is open" in prov["disclosure"]
assert prov["originals"]["nRecovered"] == fc == om["nRecords"] == om["expectedCount"] and prov["originals"]["archiveOfRecord"] is False
assert "computed from raw/ re-exports" in prov["sensitivityStatement"] and "from the originals" in prov["sensitivityStatement"]

# originals_manifest: inventory, every sha equals raw_manifest, unique ids, canonical only
assert om["archiveOfRecord"] is False and om["status"].startswith("inventory of external files") and om["allVerifiedAgainstManifest"] is True
sha = {r["record_id"]: r["sha256"] for r in canon}
ids = [r["record_id"] for r in om["records"]]
assert len(ids) == len(set(ids)) == om["nRecords"] and all(sha[r["record_id"]] == r["sha256"] and r["verified_against_manifest"] for r in om["records"])
assert not os.path.isabs(om["location"].split(": ", 1)[-1]), "location note must be relative"

# dashboard source and built HTML carry no hard-coded 410/410 or the re-serialization explanation
for f in ("xtrail_summary.jsx", "xtrail_dashboard.html"):
    t = open(os.path.join(ROOT, f), encoding="utf-8").read()
    for bad in ("410/410", "to confirm data identity independently of byte-level transfer artifacts"):
        assert bad not in t, (f, bad)
    assert not re.search(r"re-?serializ", t), (f, "re-serialization wording")
print("OK f03 provenance wording and originals manifest")
