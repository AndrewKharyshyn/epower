"""M610a (spec R3): tools/ingest_static_preflight.py known answers on a toy root: each pre-run check passes on a good tree and fails on exactly the mistake it targets."""
import copy, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, REPO)
os.environ.pop("XT_RAW_DIR", None)
for k in [k for k in os.environ if k.startswith("XT_ACK_")]:
    del os.environ[k]
import ingest_static_preflight as SP
import language_gate as LG


def w(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8", newline="\n").write(s)


def names(res):
    return {c["name"]: c for c in res["checks"]}


def main():
    tmp = tempfile.mkdtemp(prefix="xt_pre_")
    try:
        shutil.copy(os.path.join(REPO, "language_gate.py"), os.path.join(tmp, "language_gate.py"))
        w(os.path.join(tmp, "tools", "a.py"), "pass\n")
        w(os.path.join(tmp, "tools", "b.py"), "pass\n")
        stages = [{"id": "a", "cmd": ["python3", "tools/a.py"], "outputs": []}, {"id": "b", "cmd": ["python3", "tools/b.py"], "outputs": [], "needs": ["a"]}]
        w(os.path.join(tmp, "tools", "ingest_stages.json"), json.dumps({"stages": stages}))
        cfg = {"vehicle": {"odometerKm": 100, "odometerAsOf": "2026-11-09"}, "ambientByDrive": {"2026-11-09_07-45-26.csv": [2, 2], "2026-11-09_08-04-01.csv": [2, 3, 2]}, "note": "plain text"}
        w(os.path.join(tmp, "summary_config.json"), json.dumps(cfg))
        w(os.path.join(tmp, "xtrail_summary.jsx"), "const x = 'plain';\n")
        w(os.path.join(tmp, "raw_manifest.json"), json.dumps({"files": []}))
        for f in ("2026-11-09 07-45-26.csv", "2026-11-09 08-04-01.csv"):
            w(os.path.join(tmp, "raw", f), "t\n")
        res = SP.run(tmp)
        assert res["ok"] and res["nNewRawFiles"] == 2 and all(c["ok"] for c in res["checks"]), res
        assert set(res["notPrerunnable"]) == set(SP.NOT_PRERUNNABLE)
        # 1. missing ambient entry
        c1 = copy.deepcopy(cfg); del c1["ambientByDrive"]["2026-11-09_08-04-01.csv"]
        w(os.path.join(tmp, "summary_config.json"), json.dumps(c1))
        r = names(SP.run(tmp))["ambients"]
        assert not r["ok"] and "no ambientByDrive entry for 2026-11-09_08-04-01.csv" in r["problems"][0], r
        # 2. non-canonical ambient (single value)
        c2 = copy.deepcopy(cfg); c2["ambientByDrive"]["2026-11-09_08-04-01.csv"] = [3]
        w(os.path.join(tmp, "summary_config.json"), json.dumps(c2))
        assert "not canonical" in names(SP.run(tmp))["ambients"]["problems"][0]
        # 3. ODO as-of date not the newest new drive date
        c3 = copy.deepcopy(cfg); c3["vehicle"]["odometerAsOf"] = "2026-11-05"
        w(os.path.join(tmp, "summary_config.json"), json.dumps(c3))
        r = names(SP.run(tmp))["ambients"]
        assert not r["ok"] and "odometerAsOf" in r["problems"][0] and "2026-11-09" in r["problems"][0], r
        # 4. forbidden wording in config strings and in the jsx
        rule = next(x for x in LG.RULES if x.phrase and "config" in x.scope and "jsx" in x.scope)
        c4 = copy.deepcopy(cfg); c4["note"] = "this is " + rule.phrase
        w(os.path.join(tmp, "summary_config.json"), json.dumps(c4))
        r = names(SP.run(tmp))["language_sources"]
        assert not r["ok"] and any(rule.rid in p and p.startswith("config") for p in r["problems"]), r
        w(os.path.join(tmp, "summary_config.json"), json.dumps(cfg))
        w(os.path.join(tmp, "xtrail_summary.jsx"), "const x = '%s';\n" % rule.phrase)
        r = names(SP.run(tmp))["language_sources"]
        assert not r["ok"] and any(p.startswith("jsx") for p in r["problems"]), r
        w(os.path.join(tmp, "xtrail_summary.jsx"), "const x = 'plain';\n")
        # 5. stage list: needs after, missing script
        bad = copy.deepcopy(stages); bad[0]["needs"] = ["b"]
        w(os.path.join(tmp, "tools", "ingest_stages.json"), json.dumps({"stages": bad}))
        assert not names(SP.run(tmp))["stage_list"]["ok"]
        bad = copy.deepcopy(stages); bad[1]["cmd"] = ["python3", "tools/missing.py"]
        w(os.path.join(tmp, "tools", "ingest_stages.json"), json.dumps({"stages": bad}))
        assert "script tools/missing.py not found" in names(SP.run(tmp))["stage_list"]["problems"][0]
        w(os.path.join(tmp, "tools", "ingest_stages.json"), json.dumps({"stages": stages}))
        # 6. acks: missing file, cited ruling missing, good ack
        os.environ["XT_ACK_TEST"] = os.path.join(tmp, "analyses", "x_ack.json")
        try:
            assert "not found" in names(SP.run(tmp))["ack_inputs"]["problems"][0]
            w(os.environ["XT_ACK_TEST"], json.dumps({"ruling": "analyses/x_ruling.json"}))
            assert "cited ruling analyses/x_ruling.json not found" in names(SP.run(tmp))["ack_inputs"]["problems"][0]
            w(os.path.join(tmp, "analyses", "x_ruling.json"), "{}")
            assert names(SP.run(tmp))["ack_inputs"]["ok"]
            os.environ["XT_ACK_ESTIMATOR_CHANGE"] = "a reason string, not a path"
            assert names(SP.run(tmp))["ack_inputs"]["ok"]
        finally:
            os.environ.pop("XT_ACK_TEST", None); os.environ.pop("XT_ACK_ESTIMATOR_CHANGE", None)
        # 7. leaf guard rules that do not parse; a check that cannot run is a failure, not a pass
        w(os.path.join(tmp, "analyses", "leaf_guard_rules.json"), "{not json")
        assert not names(SP.run(tmp))["leaf_guard_rules"]["ok"]
        os.remove(os.path.join(tmp, "summary_config.json"))
        assert "could not run" in names(SP.run(tmp))["ambients"]["problems"][0] or not names(SP.run(tmp))["ambients"]["ok"]
        # 8. no new raw files: ambient check is vacuous
        w(os.path.join(tmp, "summary_config.json"), json.dumps(cfg))
        w(os.path.join(tmp, "raw_manifest.json"), json.dumps({"files": [{"canonical": "20261109_074526.csv"}, {"canonical": "20261109_080401.csv"}]}))
        r = SP.run(tmp)
        assert r["nNewRawFiles"] == 0 and names(r)["ambients"]["ok"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_ingest_static_preflight OK")


if __name__ == "__main__":
    main()
