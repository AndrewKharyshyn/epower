"""M649 (P-03): each gate fires at the earlier stage in a synthetic failure test.
(1) unacknowledged M321 W2/W3 stops at the ladder-monitor stage, (2) a stopped estimator gate keeps the arrays as a candidate, (3) the shared S1 fidelity check fires on each point mismatch,
(4) the language/semantic gate and the S1 check are ingestion stages in the right order, (5) the early leaf_guard is non-blocking and the final one still blocks. Run: python tests/synthetic/test_m649_early_gates.py"""
import json, os, subprocess, sys, tempfile, shutil
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import m321_ladder_monitor as M
import s1_fidelity as S1
import ingest_core as IC

# (1) M321: the acknowledgement part alone
mon = {"status": "warn-newspec", "warningSetHash": "a" * 64, "selectionCodeSha256": "b" * 64, "basisNDrives": 7, "warnings": ["W2 start x"]}
tmp = tempfile.mkdtemp(prefix="m649_")
try:
    os.makedirs(os.path.join(tmp, "analyses"))
    bad = M.ack_failure(mon, tmp)
    assert bad and "without a valid acknowledgement" in bad, bad
    assert M.ack_failure({**mon, "status": "ok"}, tmp) is None and M.ack_failure(None, tmp) is None
    open(os.path.join(tmp, "analyses", "M777_spec.md"), "w").write("spec")
    json.dump([{"warningSetHash": "a" * 64, "ref": "analyses/M777_spec.md", "selectionCodeSha256": "b" * 64, "basisNDrives": 7}], open(os.path.join(tmp, "analyses", "M321_acknowledgements.json"), "w"))
    assert M.ack_failure(mon, tmp) is None, "a valid acknowledgement must clear the stop"
    src = open(os.path.join(ROOT, "tools", "m321_ladder_monitor.py"), encoding="utf-8").read()
    assert src.count("ack_failure(block)") == 1 and "sys.exit(1)" in src.split("ack_failure(block)")[1][:400], "cmd_update must exit 1 on an unacknowledged W2/W3"

    # (2) estimator gate: candidate kept on a stop, none on a pass
    prev = {"degradationTrends": {"m": {"primaryEstimator": "A", "headlineEstimatorRule": "r"}}}
    new = {"degradationTrends": {"m": {"primaryEstimator": "B", "headlineEstimatorRule": "r"}}, "marker": 1}
    try:
        IC.estimator_gate_keep(prev, new, None, tmp); raise SystemExit("estimator change without ack must stop")
    except IC.Gate:
        pass
    cand = os.path.join(tmp, "candidate_summary_arrays.json")
    assert os.path.isfile(cand) and json.load(open(cand))["marker"] == 1
    os.remove(cand)
    assert IC.estimator_gate_keep(prev, new, "reason", tmp) and not os.path.exists(cand)
    assert IC.estimator_gate_keep(prev, prev, None, tmp) == [] and not os.path.exists(cand)

    # (5) leaf_guard report-only vs gate
    pv, cu, rules = [os.path.join(tmp, n) for n in ("prev.json", "cur.json", "rules.json")]
    json.dump({"a": 1, "b": 2}, open(pv, "w")); json.dump({"a": 1}, open(cu, "w")); json.dump([], open(rules, "w"))
    base = [sys.executable, os.path.join(ROOT, "tools", "leaf_guard.py"), "--previous", pv, "--current", cu, "--rules", rules]
    assert subprocess.run(base, capture_output=True).returncode == 1, "the final guard must still fail on a lost leaf"
    r = subprocess.run(base + ["--report-only"], capture_output=True, text=True)
    assert r.returncode == 0 and "EARLY REPORT" in r.stdout, (r.returncode, r.stdout)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# (3) S1 fidelity point checks
ok0 = {"slopeUnrounded": 1.0, "publishedSlopeConverted": 1.00002, "tol": 5.5e-5, "n": 10, "publishedN": 10, "nDays": 5, "publishedNDays": 5, "bT": 0.1234, "publishedBT": 0.12341}
assert S1.evaluate(ok0) == (True, [])
for k, v in (("slopeUnrounded", 1.01), ("n", 11), ("nDays", 6), ("bT", 0.2)):
    ok, why = S1.evaluate({**ok0, k: v})
    assert not ok and len(why) == 1, (k, why)

# (4) stage order in the shipped list
st = [x["id"] for x in json.load(open(os.path.join(ROOT, "tools", "ingest_stages.json"), encoding="utf-8"))["stages"]]
ix = st.index
assert ix("ingest_core") < ix("leaf_guard_early") < ix("stage_raw") and ix("leaf_guard_early") + 1 == ix("ingest_core") + 2
assert ix("powerfade_equivalence") < ix("s1_fidelity") < ix("powerfade_temperature_specs") < ix("winter_temperature_controls")
assert ix("build_html") < ix("dump_tabs") < ix("semantic_gate") < ix("jsdom") < ix("release_check") and ix("leaf_guard") < ix("build_html")
assert ix("leaf_guard_early") < ix("m321_ladder_monitor") < ix("leaf_guard")
print("PASS test_m649_early_gates")
