#!/usr/bin/env python3
"""release_check.py (M284, hardened M290) - clean-environment release gate for the front-end / derived-artefact layer.

Stages the DECLARED input set FLAT (the project layout) into a fresh temp dir, then: `npm ci`, rebuild
xtrail_dashboard.html, validate_jsdom.js, test_cold_fixture.js, the Python suites, derived-artefact drift gates
(post-step is a no-op on shipped arrays; cohort_arrays.json regenerates byte-identically) and HTML assertions.

Scope (stated, not implied): it does NOT rebuild drive_master.csv from the 410 raw CSVs (raw->master clean-room
rebuild is an OPEN item) and does not run the ML16 determinism harness (see ml16_determinism_check.py).
Suites whose declared inputs are absent are reported SKIPPED - never PASS.
Run from the work tree or a flat project checkout:  python3 release_check.py

M290 (audit 2026-09-22) hardening - "make the release tests authoritative":
  * The old `"assumptions registry marker present": "data-assumptions-registry" in html` check was a FALSE-GREEN:
    build_html.js inlines the transpiled JSX component source into a <script>, so the `data-assumptions-registry`
    attribute string is present in xtrail_dashboard.html whether or not S.assumptionsRegistry has any entries
    (the component returns null at RUNTIME when empty). The gate therefore passed a release whose users saw no
    table. It is replaced by (a) a payload-SCHEMA assertion here and (b) a rendered-DOM row-count assertion in
    validate_jsdom.js (which actually executes React in jsdom).
  * Added payload data-integrity assertions that catch the two live defects this audit confirmed: a GTR glossary
    whose values disagree with generatorTractionRecon.corpus (stale f_gen 0.602 vs live 0.488), and malformed ISO
    date tokens produced by the fn[:8] day-key bug (fixed at source in compute_summary_arrays._day_key).
"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

SRC = Path(os.environ.get("XT_WORK", Path(__file__).resolve().parent))
SEARCH = [SRC, SRC / "claude", SRC / "seasonal", SRC / "track3", SRC / "track4"]
REQUIRED = ["xtrail_summary.jsx", "summary_arrays.json", "summary_config.json", "build_html.js", "validate_jsdom.js",
            "test_cold_fixture.js", "package.json", "package-lock.json", "drive_master.csv", "soc_patterns.json",
            "seasonal_core.py", "seasonal_adjust.py", "test_seasonal_adjust.py", "cohort_arrays.py", "cohort_arrays.json",
            "seasonal_drive_master.csv", "seasonal_dependency.json", "raw_temperature_triplets.csv",
            "project_paths.py", "derived_literals.py", "build_assumptions_registry.py", "model_constants.py",
            "patch_m284_data.py", "test_assumptions_registry.py", "refresh_seasonal_kpis.py", "records_resistance.py",
            "records_rainflow.py", "cohort_distributions.py", "test_track4.py", "apply_m284_post.sh",
            "dump_tabs.js", "semantic_gate.py", "test_cohort_rates.py", "records_disclosure.py"]
OPTIONAL = ["warm_baseline_freeze.json", "event_ledger.json", "compute_seasonal.py", "seasonal_config.json",
            "seasonal_arrays.json", "test_seasonal.py"]
LEGACY_NEEDS = ["test_seasonal.py", "compute_seasonal.py", "seasonal_config.json", "seasonal_arrays.json",
                "warm_baseline_freeze.json", "event_ledger.json"]
PY_TESTS = ["test_seasonal_adjust.py", "test_seasonal.py", "test_assumptions_registry.py", "test_track4.py", "test_cohort_rates.py"]
fails, notes = [], []

def find(name):
    for d in SEARCH:
        if (d / name).is_file(): return d / name
    return None

def run(cmd, cwd, label=None, must=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    ok = r.returncode == 0
    print(("PASS " if ok else "FAIL ") + (label or " ".join(map(str, cmd))))
    if not ok:
        print((r.stdout + r.stderr)[-1500:])
        if must: fails.append(label or " ".join(map(str, cmd)))
    return r

def md5(p): return hashlib.md5(Path(p).read_bytes()).hexdigest()

# ── M290: payload-integrity helpers (assert rendered CONTENT / schema, not source strings) ──
def _approx(a, b, tol=0.01):
    try: return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError): return False

def _bad_date_token(tok):
    # A year-prefixed date-like token is malformed if it has a doubled separator
    # ('2026--0-9-') or a trailing separator with no day ('2026-09-'). Numeric
    # ranges like '2000-2400' (rpm) are NOT flagged: they lack a second '-'.
    if "--" in tok: return True
    if re.fullmatch(r"20\d\d-\d\d-", tok): return True
    return False

def _scan_dates(o):
    out = []
    if isinstance(o, dict):
        for v in o.values(): out += _scan_dates(v)
    elif isinstance(o, list):
        for v in o: out += _scan_dates(v)
    elif isinstance(o, str):
        for tok in re.findall(r"20\d\d-[-0-9]{0,7}", o):
            if _bad_date_token(tok): out.append(tok)
    return out

def payload_checks(arrays_path):
    """Content/schema assertions on summary_arrays.json (M290). Returns {label: bool}."""
    sa = json.load(open(arrays_path, encoding="utf-8"))
    checks = {}

    # (1) assumptions registry: SCHEMA, not a source marker. 15 typed entries, each with the fields the
    #     AssumptionsRegistryTable renders. (Rendered-DOM row count is asserted in validate_jsdom.js.)
    reg = sa.get("assumptionsRegistry") or {}
    entries = reg.get("entries") or []
    checks["assumptions registry schema (15 typed entries in payload)"] = (
        reg.get("nEntries") == 15 and len(entries) == 15
        and all(all(k in e for k in ("id", "label", "value", "klass", "verified")) for e in entries))

    # (2) GTR glossary must agree with generatorTractionRecon.corpus (catches the stale f_gen 0.602 / buffer 0.398).
    gtr = sa.get("generatorTractionRecon") or {}
    corp = gtr.get("corpus") or {}
    gl = {g.get("term"): g.get("value") for g in gtr.get("glossary", [])}
    gloss_ok = True
    if "f_gen" in gl and not _approx(gl["f_gen"], corp.get("fGen")): gloss_ok = False
    tb = gl.get("η tank→bus")
    if tb is not None and not _approx(tb, corp.get("etaBus")): gloss_ok = False
    bb = gl.get("Battery-buffer share")
    if bb is not None and corp.get("fGen") is not None and not _approx(bb, 1 - float(corp["fGen"])): gloss_ok = False
    checks["GTR glossary consistent with corpus (no stale f_gen/buffer)"] = gloss_ok

    # (3) M291 audit B7: a zero-observation cohort must be null (or a status object) on every chart — never a
    #     non-null list of label-only entries (the EfficiencyBands.cold zero-as-real placeholder). A "label-only"
    #     cold entry is a dict that carries a label but no numeric datum and no explicit n/status.
    def _label_only(e):
        if not isinstance(e, dict): return False
        data_keys = set(e.keys()) - {"label", "key", "color", "name"}
        return not data_keys  # a bare {label:...} with nothing else
    b7_ok = True
    for name, chart in (sa.get("seasonalCharts", {}).get("charts", {}) or {}).items():
        if not isinstance(chart, dict): continue
        d = chart.get("data")
        cold = d.get("cold") if isinstance(d, dict) else None
        if isinstance(cold, list) and cold and all(_label_only(e) for e in cold):
            b7_ok = False
    checks["cold cohort null-with-reason everywhere (no label-only zero-as-real)"] = b7_ok

    # (4) M291 audit B8: every dataset-extremes record carries a disclosure contract (eligibility rule +
    #     excludedByCap), and any record that excluded drives by a cap also discloses the raw pre-cap extremum.
    recs = sa.get("records") or []
    b8_ok = bool(recs) and all(
        isinstance(r.get("disclosure"), dict)
        and "eligibilityRule" in r["disclosure"] and "excludedByCap" in r["disclosure"]
        and (r["disclosure"]["excludedByCap"] == 0 or "rawExtremum" in r["disclosure"])
        for r in recs)
    checks["records disclosure contract present (no silent sane_max drops)"] = b8_ok
    return checks

def payload_warnings(arrays_path):
    """M290 soft checks: disclosed-pending defects that need a raw-pass rebuild to clear.
    Malformed ISO date tokens are a symptom of the fn[:8] day-key bug (fixed at source in
    compute_summary_arrays._day_key); they clear on the next ThermalFuelPenalty raw regen,
    which also widens its (currently day-collapsed) bootstrap CIs. Reported, not failed."""
    sa = json.load(open(arrays_path, encoding="utf-8"))
    warns = []
    bad = sorted(set(_scan_dates(sa)))
    if bad:
        warns.append(f"malformed ISO date tokens present {bad} - fn[:8] day-key defect; source fixed "
                     f"(_day_key), clears on the next ThermalFuelPenalty raw-pass regen (also widens its CIs)")
    # M300 (Director): every stamp's fullConfigHash should equal md5(summary_config.json). WARN until the
    # 5fb4cded... (stamped) vs on-disk config mismatch is investigated; then promote to FAIL.
    import hashlib
    cfg = Path(arrays_path).with_name("summary_config.json")
    if cfg.exists():
        h = hashlib.md5(cfg.read_bytes()).hexdigest()
        stale = sorted({v.get("fullConfigHash") for v in sa.get("_artifactStamps", {}).values()
                        if isinstance(v, dict) and v.get("fullConfigHash") not in (None, h)})
        if stale:
            warns.append(f"_artifactStamps fullConfigHash {stale} != md5(summary_config.json) {h} - stamped under a "
                         f"different config revision; under investigation (M300)")
    return warns

def main():
    tmp = Path(tempfile.mkdtemp(prefix="xt_release_"))
    try:
        for f in REQUIRED:
            s = find(f)
            if s is None: fails.append(f"missing declared input {f}")
            else: shutil.copy2(s, tmp / f)
        for f in OPTIONAL:
            s = find(f)
            if s is not None: shutil.copy2(s, tmp / f)
        if fails: return
        run(["npm", "ci", "--no-audit", "--no-fund"], tmp)
        if fails: return
        run(["node", "build_html.js"], tmp); run(["node", "validate_jsdom.js"], tmp); run(["node", "test_cold_fixture.js"], tmp)
        # M299: semantic release gate — rendered prose (every tab x All/Warm/Shoulder/Compare) vs the one payload
        run(["node", "dump_tabs.js"], tmp, "render per-tab/per-mode text (dump_tabs.js)")
        run([sys.executable, "semantic_gate.py"], tmp, "semantic gate: forbidden wording + prose==payload + mode behaviour (M299)")
        for t in PY_TESTS:
            if t == "test_seasonal.py":
                miss = [n for n in LEGACY_NEEDS if not (tmp / n).exists()]
                if miss:
                    notes.append(f"SKIPPED test_seasonal.py: missing {', '.join(miss)} (legacy suite; run in the project checkout)"); continue
            run([sys.executable, t], tmp)
        # derived-artefact drift gates
        a0 = md5(tmp / "summary_arrays.json"); c0 = md5(tmp / "summary_config.json")
        run(["bash", "apply_m284_post.sh"], tmp, "post-step apply_m284_post.sh runs", must=True)
        for n, b in (("summary_arrays.json", a0), ("summary_config.json", c0)):
            same = md5(tmp / n) == b; print(("PASS " if same else "FAIL ") + f"post-step is a no-op on shipped {n}")
            if not same: fails.append(f"post-step changes shipped {n}")
        k0 = md5(tmp / "cohort_arrays.json"); run([sys.executable, "cohort_arrays.py"], tmp, "cohort_arrays.py regenerates")
        same = md5(tmp / "cohort_arrays.json") == k0; print(("PASS " if same else "FAIL ") + "cohort_arrays.json byte-identical after regeneration")
        if not same: fails.append("cohort_arrays.json drift")
        html = (tmp / "xtrail_dashboard.html").read_text(encoding="utf-8")
        h = md5(tmp / "drive_master.csv")
        # M290: HTML checks that are legitimately string-level (corpus-hash stamp, unresolved template tokens,
        # a specific gated-record label, KPI payload presence). The assumptions-registry check MOVED to the
        # payload-schema/DOM assertions below/in validate_jsdom.js (the old string check was a false-green).
        checks = {
            "stale '145/374' literal absent": "145/374" not in html,
            "corpus hash present in build": h in html,
            "no unresolved template tokens": "__XT_" not in html,
            "gated pack-resistance record present": "excitation-gated maximum" in html,
            "KPI interval payload present": '"ci95"' in html and "essDays" in html,
        }
        # M290: content/schema assertions on the shipped payload (authoritative, not source-marker).
        checks.update(payload_checks(tmp / "summary_arrays.json"))
        for k, v in checks.items():
            print(("PASS " if v else "FAIL ") + k)
            if not v: fails.append(k)
        # M290: disclosed-pending soft checks (do not fail the release; surfaced for the next rebuild).
        for w in payload_warnings(tmp / "summary_arrays.json"):
            print("WARN " + w); notes.append(w)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
    for n in notes: print("NOTE", n)
    print("NOT COVERED: raw CSV -> drive_master.csv rebuild (open item); ML16 determinism is a separate harness.")
    print("RELEASE CHECK " + ("FAILED: " + "; ".join(fails) if fails else "PASSED"))
    sys.exit(1 if fails else 0)
