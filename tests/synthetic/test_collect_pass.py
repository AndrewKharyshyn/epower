"""M610b (spec analyses/M610_spec.md Rev 1, T2 and R5/R6/R9): the collect pass end to end on a toy chain in a temp root.
Toy chain: e1, e2, e3 each stop on a ruling (exit 3) unless their ack file data/ack_eN.txt exists; in a collect pass each records a stop and withholds its splice instead; h fails hard while
tools/h_flag.txt says FAIL. Known answers:
 1. `--collect-stops` with the hard failure: finds the 3 stops, ends at h (gate_failed), tree bytes equal the pre-run bytes, no token left, no checkpoint saved;
 2. with the hard failure removed: result collect_done, exit code 6, stops.json = 3 records in stage order each carrying the hashes of the earlier ones, provisional label and 3 briefs, bytes equal the pre-run bytes;
 3. a real run (no flag) after the collect pass, with no acks, stops at the FIRST stop (e1): nothing is passed on the strength of a collect pass;
 4. the real run with the 3 acks is ok, every stage executed, final bytes equal a conventional run acknowledged stop by stop (stop, ack, rerun x3);
 5. `--collect-stops` is refused together with --only / --no-journal / --keep-on-failure (exit 2), and a stale token variable does not switch a normal run into collect mode;
 6. release_check's guard: a leftover runs/*/collect.token exists only while a pass is open."""
import glob, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_ingest_checkpoint as T

ESC = '''import os, sys
sys.path.insert(0, "tools")
import stop_protocol as SP, toylib
N = "%s"
if not os.path.exists("data/ack_%s.txt"):
    if SP.try_collect(N, "needs_ruling", {"stage": N, "value": 1}, ["ACK_" + N.upper()], {"ack": "file"}, withheld=["data/%s.txt"], artifacts=[]):
        open(os.environ["TOY_LOG"], "a").write("collect:" + N + "\\n")
        sys.exit(0)
    open(os.environ["TOY_LOG"], "a").write("stop:" + N + "\\n")
    sys.exit(3)
toylib.run(N, "data/in.txt", "data/%s.txt")
'''


def setup(root):
    T.setup(root)
    shutil.copy(os.path.join(HERE, "..", "..", "tools", "stop_protocol.py"), os.path.join(root, "tools", "stop_protocol.py"))
    for n in ("e1", "e2", "e3"):
        T.write(os.path.join(root, "tools", n + ".py"), ESC % (n, n, n, n))
    T.write(os.path.join(root, "tools", "h.py"), "import toylib\nfail = open('tools/h_flag.txt').read().strip() == 'FAIL'\ntoylib.run('h', 'data/in.txt', 'data/h.txt', fail)\n")
    T.write(os.path.join(root, "tools", "h_flag.txt"), "FAIL")
    stages = [{"id": i, "title": i, "cmd": ["python3", "tools/%s.py" % i], "outputs": ["data/%s.txt" % i]} for i in ("e1", "e2", "e3", "h")]
    T.write(os.path.join(root, "tools", "ingest_stages.json"), json.dumps({"stages": stages}))


def acks(root):
    for n in ("e1", "e2", "e3"):
        T.write(os.path.join(root, "data", "ack_%s.txt" % n), "ruling")


def tree_no_ack(root):
    return T.tree_hash(root)


def main():
    tmp = tempfile.mkdtemp(prefix="xt_collect_")
    try:
        root, logd = os.path.join(tmp, "root"), os.path.join(tmp, "log")
        os.makedirs(logd)
        L = lambda n: os.path.join(logd, n + ".log")
        setup(root)
        pre = T.tree_hash(root)
        # 1. collect pass with a hard failure at h
        rc, st, _ = T.run(root, L("1"), "--collect-stops")
        assert rc == 1 and st["result"] == "gate_failed" and st["collect"]["count"] == 3, (rc, st["result"], st.get("collect"))
        assert T.executed(L("1")) == ["collect:e1", "collect:e2", "collect:e3", "h"], T.executed(L("1"))
        assert T.tree_hash(root) == pre, "tree bytes equal the pre-run bytes after a collect pass"
        assert not glob.glob(os.path.join(root, "runs", "*", "collect.token")) and not os.path.isdir(os.path.join(root, "runs", ".checkpoints"))
        # 2. hard failure removed
        T.write(os.path.join(root, "tools", "h_flag.txt"), "OK")
        pre = T.tree_hash(root)
        rc, st, _ = T.run(root, L("2"), "--collect-stops")
        assert rc == 6 and st["result"] == "collect_done" and st["collect"]["stages"] == ["e1", "e2", "e3"], (rc, st["result"], st.get("collect"))
        rd = os.path.join(root, "runs", st["run"])
        recs = json.load(open(os.path.join(rd, "stops.json"), encoding="utf-8"))["records"]
        assert [r["stage"] for r in recs] == ["e1", "e2", "e3"] and recs[1]["upstream"] == [recs[0]["recordSha256"]] and recs[2]["upstream"] == [r["recordSha256"] for r in recs[:2]]
        assert len(os.listdir(os.path.join(rd, "briefs"))) == 3 and os.path.isfile(os.path.join(rd, "provisional", "PROVISIONAL_NEVER_PUBLISHED.txt"))
        assert T.tree_hash(root) == pre and st["journal"]["state"] == "rolled_back"
        # 3. real run, no acks: stops at the first stop
        rc, st, _ = T.run(root, L("3"))
        assert rc == 1 and st["result"] == "gate_failed" and T.executed(L("3")) == ["stop:e1"], (rc, T.executed(L("3")))
        # 4. real run with the acks == conventional stop/ack/rerun
        acks(root)
        rc, st, _ = T.run(root, L("4"))
        assert rc == 0 and st["result"] == "ok", (rc, st["result"])
        assert sorted(x for x in T.executed(L("4"))) == ["e1", "e2", "e3", "h"], T.executed(L("4"))
        final_collect_path = T.tree_hash(root)
        root2 = os.path.join(tmp, "root2")
        setup(root2)
        T.write(os.path.join(root2, "tools", "h_flag.txt"), "OK")
        for n in ("e1", "e2", "e3"):                              # conventional: stop, ack, rerun
            rc, st, _ = T.run(root2, L("c_" + n))
            assert rc == 1
            T.write(os.path.join(root2, "data", "ack_%s.txt" % n), "ruling")
        rc, st, _ = T.run(root2, L("c_final"))
        assert rc == 0 and st["result"] == "ok"
        assert T.tree_hash(root2) == final_collect_path, "collect pass + real run ends on the same bytes as the conventional sequence"
        # 5. refused combinations, stale variable
        for extra in (["--only", "e1"], ["--no-journal"], ["--keep-on-failure"]):
            rc, st, r = T.run(root, L("5"), "--collect-stops", *extra)
            assert rc == 2 and "needs a full journaled run" in r.stderr, (extra, rc, r.stderr[-200:])
        shutil.rmtree(os.path.join(root, "data"))
        T.write(os.path.join(root, "data", "in.txt"), "in")
        env_before = dict(os.environ)
        os.environ["INGEST_COLLECT_TOKEN"], os.environ["INGEST_COLLECT_DIR"] = "stale", os.path.join(root, "runs")
        try:
            rc, st, _ = T.run(root, L("6"))
            assert rc == 1 and T.executed(L("6")) == ["stop:e1"], "a stale token variable must not switch a normal run into collect mode: %s" % T.executed(L("6"))
        finally:
            os.environ.clear(); os.environ.update(env_before)
        # 7. a hard kill in the middle of a collect pass (Director required test): the journal stays open and the token stays; --recover restores the bytes and removes the token
        root3 = os.path.join(tmp, "root3")
        setup(root3)
        T.write(os.path.join(root3, "tools", "k.py"), "import os, signal, time\nos.kill(os.getppid(), getattr(signal, 'SIGKILL', signal.SIGTERM))\ntime.sleep(30)\n")
        stages = [{"id": i, "title": i, "cmd": ["python3", "tools/%s.py" % i], "outputs": ["data/%s.txt" % i]} for i in ("e1", "k", "e2")]
        T.write(os.path.join(root3, "tools", "ingest_stages.json"), json.dumps({"stages": stages}))
        pre3 = T.tree_hash(root3)
        env3 = dict(os.environ, TOY_LOG=L("kill"), PYTHONPATH=os.path.join(root3, "tools"))
        env3.pop("XT_RAW_DIR", None)
        rk = subprocess.run([sys.executable, os.path.join(root3, "tools", "run_ingest.py"), "--collect-stops"], cwd=root3, env=env3, capture_output=True, text=True, timeout=120)
        assert rk.returncode != 0 and T.executed(L("kill")) == ["collect:e1"], (rk.returncode, T.executed(L("kill")))
        toks = glob.glob(os.path.join(root3, "runs", "*", "collect.token"))
        assert len(toks) == 1, "the token of the killed pass is still there"
        r2 = subprocess.run([sys.executable, os.path.join(root3, "tools", "run_ingest.py"), "--recover"], cwd=root3, env=env3, capture_output=True, text=True, timeout=120)
        assert r2.returncode == 0, (r2.returncode, r2.stdout[-300:], r2.stderr[-300:])
        assert not glob.glob(os.path.join(root3, "runs", "*", "collect.token")) and T.tree_hash(root3) == pre3, "recovery restores the bytes and removes the token"
        # 6. the release guard glob (leftover token exists only while a pass is open)
        assert not glob.glob(os.path.join(root, "runs", "*", "collect.token"))
        print("test_collect_pass OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
