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
            "test_cold_fixture.js", "test_ambient_table.js", "test_gtr_gate.js", "test_fuel_tab.js", "package.json", "package-lock.json", "drive_master.csv", "battery_temp_extremes.csv", "originals_manifest.json", "raw_manifest.json", "soc_patterns.json",
            "seasonal_core.py", "seasonal_adjust.py", "test_seasonal_adjust.py", "cohort_arrays.py", "cohort_arrays.json",
            "seasonal_drive_master.csv", "seasonal_dependency.json", "raw_temperature_triplets.csv",
            "project_paths.py", "derived_literals.py", "build_assumptions_registry.py", "model_constants.py",
            "patch_m284_data.py", "test_assumptions_registry.py", "refresh_seasonal_kpis.py", "records_resistance.py",
            "records_rainflow.py", "cohort_distributions.py", "test_track4.py", "apply_m284_post.sh",
            "dump_tabs.js", "semantic_gate.py", "test_cohort_rates.py", "records_disclosure.py", "f03_provenance_flag.py", "f03_provenance.json", "language_gate.py", "eligibility.py", "precision_gate.py", "precision_allowlist.json", "fuel_contract_flag.py", "fuel_contract.json", "fuel_recon_master.csv"]
TOOLS_REQUIRED = ["refresh_meta_sources.py", "intake_air_block.py"]   # called by apply_m284_post.sh (M355; M361 imports intake_air_block)
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
    exe = shutil.which(str(cmd[0])) if sys.platform == "win32" else None       # Windows: npm/node resolve to .cmd/.exe shims
    env = None
    if sys.platform == "win32":     # repo bytes are LF; Windows text-mode writes would make byte-identity checks (post-step no-op) fail on CRLF
        shim = str(Path(__file__).resolve().parent / "tools" / "eol_shim")
        env = dict(os.environ, PYTHONPATH=shim + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
                   PYTHONUTF8="1")
    r = subprocess.run([exe, *cmd[1:]] if exe else cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
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

    # (5) M313 standing rule: new drives are added to the "Sessions (grouped by phase)" ledgers (sessionGroups and sessions) on EVERY
    #     ingestion (tools/extend_session_ledgers.py). The newest corpus date must be covered in both ledgers and no ledger row may
    #     disagree with the master (the historical Sep 04-11 window was backfilled in M313).
    import datetime as _dt
    sla = sa.get("sessionLedgerAudit") or {}
    try:
        newest = _dt.datetime.strptime(sa["meta"]["dateRange"].split("–")[-1].strip(), "%b %d, %Y").date().isoformat()
    except Exception:
        newest = None
    checks["session ledgers cover the newest drive date and agree with the master (M313)"] = bool(
        newest and sla and all(newest not in ((sla.get(k) or {}).get("datesUncovered") or []) and (sla.get(k) or {}).get("nMismatched") == 0
                               for k in ("sessions", "sessionGroups")))

    # (6) M314: the Thermal-tab ambient table lists EVERY drive (count == corpus), each with a valid [start, *interim, end] list, and reaches the newest date.
    at = sa.get("ambientTable") or {}
    arows = at.get("rows") or []
    checks["ambient table covers every drive with [start, *interim, end] and a thermal class (M314/M315)"] = bool(
        arows and len(arows) == at.get("nDrives") == (sa.get("meta") or {}).get("totalDrives")
        and all(isinstance(r.get("a"), list) and len(r["a"]) >= 2 and all(isinstance(x, (int, float)) for x in r["a"]) for r in arows)
        and all(r.get("c") in ("warm", "shoulder", "cold") for r in arows) and sum((at.get("cohortCounts") or {}).values()) == len(arows)   # M315: thermal class per drive
        and all(isinstance(r.get("ow"), list) and len(r["ow"]) == 5 and isinstance(r.get("cw"), list) and len(r["cw"]) == 5
                and r.get("cs") in ("not_cold_soaked", "probable", "cold_soaked", "unknown") for r in arows)                # M316: warm-up series + cold-soak status per drive
        and at.get("nWithStartTemps") == sum(1 for r in arows if r.get("p") is not None and r.get("o") is not None and r.get("w") is not None)
        and newest and max(r["d"] for r in arows) == newest)

    # (7) M317: Huber spread-fit provenance (append-only history) agrees with the published cellHealthTrend numbers (n and the interval are the SAME object).
    sfp = sa.get("spreadFitProvenance") or {}
    lat, cht = sfp.get("latest") or {}, sa.get("cellHealthTrend") or {}
    hist = sfp.get("history") or []
    pci = ((lat.get("slopeII") or {}).get("S1") or {}).get("ci95")          # Amendment 1: S1 (two-stage) is the published interval
    checks["spread-fit provenance consistent with cellHealthTrend (n, Huber slope interval, history) (M317)"] = bool(
        lat and hist and sfp.get("nRecords") == len(hist) and hist[-1].get("masterMd5") == lat.get("masterMd5")
        and len(((lat.get("data") or {}).get("keepSetSha256")) or "") == 64
        and (lat.get("data") or {}).get("nClean") == cht.get("nHuber")
        and ((cht.get("huberSlopeCi95") is None) == (pci is None or ((lat.get("slopeII") or {}).get("S1") or {}).get("inconclusive") is True))
        and (pci is None or (cht.get("huberSlopeCi95") and all(abs(round(x, 2) - y) < 1e-9 for x, y in zip(pci, cht["huberSlopeCi95"]))))
        and all(((sfp.get("calibration") or {}).get(d) or {}).get("S1PassBand") is True for d in ("design1", "design2")))   # S1 calibrated in both simulation designs (Amendment 1)

    # (8) M321: the M119-v2 pack-temperature ladder drift monitor is present, current and consistent with the ladder basis; a V2 refit without a
    #     re-derived ladder, a stale cache or changed selection code, or an unacknowledged W2/W3 (new-spec trigger) FAILS here (spec analyses/M321_spec.md).
    #     Evaluated against the repository tree (SRC), because it hashes tools/ and analyses/ files that the clean-environment copy does not carry.
    try:
        sys.path.insert(0, str(SRC / "tools"))
        import m321_ladder_monitor as _m321
        _f, _w = _m321.gate(sa, root=str(SRC))
    except Exception as _e:
        _f = [f"M321: ladder-monitor gate could not run: {_e}"]
    for _x in _f:
        checks["M321: " + _x.replace("M321: ", "")] = False
    checks["ladder drift monitor present, current and consistent with the ladder basis (M321)"] = not _f

    # (9) M340 (audit F07): the raw side-pass CSV that feeds the native intake-air extrema rows covers EXACTLY the master files (same order) and carries
    #     intake_max: a stale side-pass is a release failure, never a silent omission of the rows (the in-builder fallback stays, but is no longer the only guard).
    try:
        import csv as _csv
        _d = Path(arrays_path).parent
        _mf = [r["file"] for r in _csv.DictReader(open(_d / "drive_master.csv", encoding="utf-8"))]
        _tr = _csv.DictReader(open(_d / "battery_temp_extremes.csv", encoding="utf-8"))
        _tf = [r["file"] for r in _tr]
        _te_ok = _mf == _tf and "intake_max" in (_tr.fieldnames or [])
    except Exception:
        _te_ok = False
    checks["battery_temp_extremes.csv covers exactly the master files and carries intake_max (M340: stale side-pass fails, never silent)"] = bool(_te_ok)

    # (10) M346: the originals manifest (second sha256-manifested archive, option 2) is internally consistent and never claims to be the archive of record:
    #      every record id is a canonical raw_manifest record with the SAME sha256, ids unique, counts equal, archiveOfRecord False, owner decision recorded.
    try:
        _d = Path(arrays_path).parent
        _om = json.loads((_d / "originals_manifest.json").read_text(encoding="utf-8"))
        _rm = {x["record_id"]: x["sha256"] for x in json.loads((_d / "raw_manifest.json").read_text(encoding="utf-8"))["files"] if x["role"] == "canonical"}
        _ids = [x["record_id"] for x in _om["records"]]
        _om_ok = (_om["archiveOfRecord"] is False and _om["allVerifiedAgainstManifest"] is True and len(_ids) == len(set(_ids)) == _om["nRecords"] == _om["expectedCount"]
                  and all(_rm.get(x["record_id"]) == x["sha256"] and len(x["sha256"]) == 64 for x in _om["records"])
                  and (_om.get("ownerDecision") or {}).get("option") == 2 and "second sha256-manifested archive" in _om["status"])
    except Exception:
        _om_ok = False
    checks["originals_manifest.json is a consistent second archive (not the archive of record; sha256 equal to raw_manifest; owner decision recorded) (M346)"] = bool(_om_ok)
    # (11) M366 (F03 re-anchoring): raw/ holds the sha256-verified originals: every canonical raw file matches its raw_manifest.json sha256, and the 333 removed re-exports are recorded (sha256 list)
    try:
        import hashlib as _h, re as _re
        _root = Path(__file__).resolve().parent
        _man = [x for x in json.loads((_root / "raw_manifest.json").read_text(encoding="utf-8"))["files"] if x["role"] == "canonical"]
        _dig = lambda n: _re.sub(r"\D", "", n.rsplit(".", 1)[0])
        _idx = {_dig(n): n for n in os.listdir(_root / "raw") if n.lower().endswith(".csv") and not n.startswith("e4ORCE")}
        _bad = [x["record_id"] for x in _man if _dig(x["raw_name"]) not in _idx or _h.sha256((_root / "raw" / _idx[_dig(x["raw_name"])]).read_bytes()).hexdigest() != x["sha256"]]
        _arch = json.loads((_root / "analyses" / "F03_originals" / "archived_reexports_sha256.json").read_text(encoding="utf-8"))
        _raw_ok = (not _bad) and len(_man) == 489 and _arch["n"] == 333 and len(_arch["files"]) == 333
    except Exception:
        _raw_ok = False
    checks["every canonical raw file matches raw_manifest.json sha256 (raw/ = sha256-verified originals; 333 removed re-exports recorded) (M366)"] = bool(_raw_ok)
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
    # M307 (Director, F5): degenerate mixed-effects fits are reported (the released estimator is then the cluster-robust OLS).
    for m, d in (sa.get("degradationTrends") or {}).items():
        if isinstance(d, dict) and (d.get("mixedEffects") or {}).get("degenerate"):
            warns.append(f"degradationTrends.{m}: mixed-effects degenerate -> primaryEstimator={d.get('primaryEstimator')} "
                         f"(fallback is disclosed; ingest_core aborts if it CHANGES vs the previous arrays)")
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
    try:
        sys.path.insert(0, str(SRC / "tools"))
        import m321_ladder_monitor as _m321
        warns.extend(_m321.gate(sa, root=str(SRC))[1])     # M321: W1 / W3-info / W4 / F03 flags are WARN (W2 / W3 are gated by acknowledgement)
    except Exception:
        pass
    return warns

def main():
    tmp = Path(tempfile.mkdtemp(prefix="xt_release_"))
    try:
        for f in REQUIRED:
            s = find(f)
            if s is None: fails.append(f"missing declared input {f}")
            else: shutil.copy2(s, tmp / f)
        for f in TOOLS_REQUIRED:          # M355: post-step helpers kept under tools/ (new tooling lives there)
            s = SRC / "tools" / f
            if not s.is_file(): fails.append(f"missing declared input tools/{f}")
            else: (tmp / "tools").mkdir(exist_ok=True); shutil.copy2(s, tmp / "tools" / f)
        for f in OPTIONAL:
            s = find(f)
            if s is not None: shutil.copy2(s, tmp / f)
        if fails: return
        run(["npm", "ci", "--no-audit", "--no-fund"], tmp)
        if fails: return
        run(["node", "build_html.js"], tmp); run(["node", "validate_jsdom.js"], tmp); run(["node", "test_cold_fixture.js"], tmp); run(["node", "test_ambient_table.js"], tmp); run(["node", "test_gtr_gate.js"], tmp); run(["node", "test_fuel_tab.js"], tmp)   # M333: GTR accounting gate in every mode; M314: ambient table section (Thermal tab)
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
