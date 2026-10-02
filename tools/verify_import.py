#!/usr/bin/env python3
"""Verify that the migrated tree is complete and byte-identical to the manifests.

Usage: python tools/verify_import.py [--raw-dir DIR] [--quick] [--expect-master-md5 MD5]
Checks: (1) required scripts/data present; (2) raw CSVs vs raw_manifest.json sha256 (name variants tolerated:
'YYYYMMDD HHMMSS.csv' as stored in Project Knowledge, 'YYYYMMDD_HHMMSS.csv', 'YYYY-MM-DD HH-MM-SS.csv', archive-native names); (3) drive_master.csv
row count / MD5 (optionally against --expect-master-md5); (4) project_paths import. Exit 0 only if nothing required is missing
and no hash mismatches."""
import argparse, hashlib, json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P = lambda *a: os.path.join(ROOT, *a)

REQUIRED = """xtrail_summary.jsx summary_arrays.json summary_config.json build_html.js validate_jsdom.js test_cold_fixture.js
package.json package-lock.json drive_master.csv soc_patterns.json seasonal_core.py seasonal_adjust.py test_seasonal_adjust.py
cohort_arrays.py cohort_arrays.json seasonal_drive_master.csv seasonal_dependency.json raw_temperature_triplets.csv
project_paths.py derived_literals.py build_assumptions_registry.py model_constants.py patch_m284_data.py
test_assumptions_registry.py refresh_seasonal_kpis.py records_resistance.py records_rainflow.py cohort_distributions.py
test_track4.py apply_m284_post.sh dump_tabs.js semantic_gate.py test_cohort_rates.py records_disclosure.py release_check.py
compute_summary_arrays.py compute_drive_summary_v6.py m119v2_model.py energy_mc_precompute.py energy_uncertainty_mc.py
determinism_check.py ml16_determinism_check.py drive_raw_cache.py degradation_trends.py ingest_e4orce.py crosscheck_vehicles.py
crosscheck_events.py corpus_manifest.py raw_manifest.json CHANGELOG.md requirements.txt f03_provenance_flag.py f03_provenance.json language_gate.py""".split()
OPTIONAL = """warm_baseline_freeze.json event_ledger.json compute_seasonal.py seasonal_config.json seasonal_arrays.json test_seasonal.py
xtrail_dashboard.html e4orce_master.csv e4orce_ambient.csv fuel_recon_master.csv fuel_recon.py recon_engine.py""".split()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def variants(name):
    v = [name, re.sub(r"^(\d{8}|\d{4}-\d{2}-\d{2})_", r"\1 ", name), re.sub(r"^(\d{8}|\d{4}-\d{2}-\d{2}) ", r"\1_", name)]
    return list(dict.fromkeys(v))


_DIGITS_INDEX = {}


def _digits(name):
    return re.sub(r"\D", "", name.rsplit(".", 1)[0])


def find(root, name):
    for v in variants(name):
        p = os.path.join(root, v)
        if os.path.isfile(p):
            return p
    # Fallback: match on the digits of the timestamp, so 'YYYY-MM-DD HH-MM-SS.csv' == 'YYYYMMDD_HHMMSS.csv'.
    if root not in _DIGITS_INDEX:
        _DIGITS_INDEX[root] = {_digits(f): f for f in os.listdir(root) if f.lower().endswith(".csv")}
    f = _DIGITS_INDEX[root].get(_digits(name)) if re.match(r"^\d{8}", _digits(name)) else None
    return os.path.join(root, f) if f else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir")
    ap.add_argument("--quick", action="store_true", help="skip raw sha256 (presence only)")
    ap.add_argument("--expect-master-md5")
    ap.add_argument("--originals-dir", help="folder of the external originals listed in originals_manifest.json (default: the manifest's relative location)")
    a = ap.parse_args()
    raw = a.raw_dir or os.environ.get("XT_RAW_DIR") or (P("raw") if os.path.isdir(P("raw")) else ROOT)
    rep = {"missing_required": [], "missing_optional": [], "raw": {}, "master": {}}

    for f in REQUIRED:
        if not os.path.exists(P(f)):
            rep["missing_required"].append(f)
    for f in OPTIONAL:
        if not os.path.exists(P(f)):
            rep["missing_optional"].append(f)

    dm = P("drive_master.csv")
    if os.path.exists(dm):
        h = hashlib.md5(open(dm, "rb").read()).hexdigest()
        n = sum(1 for _ in open(dm, encoding="utf-8")) - 1
        rep["master"] = {"rows": n, "md5": h}
        if a.expect_master_md5:
            rep["master"]["matches_expected"] = h.lower().startswith(a.expect_master_md5.lower())

    mp = P("raw_manifest.json")
    if os.path.exists(mp):
        man = json.load(open(mp, encoding="utf-8"))
        missing, mismatch, ok = [], [], 0
        for r in man.get("files", []):
            p = find(raw, r["raw_name"]) or (P(r["raw_name"]) if os.path.isfile(P(r["raw_name"])) else None)
            if p is None:
                missing.append(r["raw_name"]); continue
            if a.quick:
                ok += 1; continue
            if sha256(p) == r["sha256"]:
                ok += 1
            else:
                mismatch.append(r["raw_name"])
        rep["raw"] = {"raw_dir": raw, "manifest_files": len(man.get("files", [])), "ok": ok,
                      "missing": missing, "sha256_mismatch": mismatch, "sha_checked": not a.quick}
    # M325: optional, report-only check of the external originals inventory (never affects the exit status; absent folder = "not checked", never "ok")
    omp = P("originals_manifest.json")
    if os.path.exists(omp):
        om = json.load(open(omp, encoding="utf-8"))
        odir = a.originals_dir or os.path.normpath(os.path.join(ROOT, om["location"].split(": ", 1)[-1]))
        if a.quick:
            rep["originals"] = {"status": "not checked (quick mode)", "nRecords": om["nRecords"]}
        elif not os.path.isdir(odir):
            rep["originals"] = {"status": "not checked (originals folder absent)", "nRecords": om["nRecords"]}
        else:
            bad = [r["record_id"] for r in om["records"]
                   if not os.path.isfile(os.path.join(odir, r["record_id"])) or sha256(os.path.join(odir, r["record_id"])) != r["sha256"]]
            rep["originals"] = {"status": "ok" if not bad else "mismatch", "nRecords": om["nRecords"], "bad": bad}
    fail = bool(rep["missing_required"] or rep["raw"].get("sha256_mismatch") or rep["raw"].get("missing")
                or (a.expect_master_md5 and not rep["master"].get("matches_expected", False)))
    rep["status"] = "FAIL" if fail else "OK"
    print(json.dumps(rep, indent=1))
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
