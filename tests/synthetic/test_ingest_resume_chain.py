"""M722: resume chain of tools/run_ingest.py. Known-answer test on synthetic stages (no real ingestion).
Root cause reproduced: a stage whose command line names its own output (or any data file, e.g. `--out data/a.txt`) used to hash that file's CONTENT into its code hash.
The key was saved after the stage had written the file and recomputed on resume before it was restored, so the key never matched and the chain stopped at the first such stage.
Stages a, b, c here all name their outputs on the command line; c fails until fixed."""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_ingest_checkpoint as T


def setup(root):
    T.setup(root)
    stages = [{"id": i, "title": i, "cmd": ["python3", "tools/%s.py" % i, "--out", "data/%s.txt" % i], "outputs": ["data/%s.txt" % i]} for i in "abc"]
    T.write(os.path.join(root, "tools", "ingest_stages.json"), json.dumps({"stages": stages}))


def main():
    tmp = tempfile.mkdtemp(prefix="xt_rc_")
    try:
        root, logd = os.path.join(tmp, "root"), os.path.join(tmp, "log")
        os.makedirs(logd)
        setup(root)
        L = lambda n: os.path.join(logd, n + ".log")
        rc, st, _ = T.run(root, L("1"))
        assert rc == 1 and T.executed(L("1")) == ["a", "b", "c"], (rc, T.executed(L("1")))
        # fix ONLY stage c's code; plain run (resume is the default) restores a and b and executes c
        T.write(os.path.join(root, "tools", "c.py"), "import toylib\ntoylib.run('c', 'data/b.txt', 'data/c.txt', False)\n")
        rc, st, _ = T.run(root, L("2"))
        assert rc == 0 and T.executed(L("2")) == ["c"], (rc, T.executed(L("2")), st.get("checkpoint"))
        assert [s["status"] for s in st["stages"]] == ["restored_from_checkpoint", "restored_from_checkpoint", "ok"], st["stages"]
        assert open(os.path.join(root, "data", "c.txt"), encoding="utf-8").read() == "c:b:a:in"
        # edit ONLY stage b's code with c failing again: a restored, b and c executed
        shutil.rmtree(os.path.join(root, "data")); T.write(os.path.join(root, "data", "in.txt"), "in")
        T.write(os.path.join(root, "tools", "c.py"), "import toylib\ntoylib.run('c', 'data/b.txt', 'data/c.txt', True)\n")
        rc, st, _ = T.run(root, L("3"), "--fresh")
        assert rc == 1 and T.executed(L("3")) == ["a", "b", "c"]
        T.write(os.path.join(root, "tools", "b.py"), "import toylib, toylib2\ntoylib.run('b', 'data/a.txt', 'data/b.txt')  # edited\n")
        T.write(os.path.join(root, "tools", "c.py"), "import toylib\ntoylib.run('c', 'data/b.txt', 'data/c.txt', False)\n")
        rc, st, _ = T.run(root, L("4"))
        assert T.executed(L("4")) == ["b", "c"] and rc == 0, (T.executed(L("4")), st.get("checkpoint"))
        # --keep-on-failure leaves the journal open (next plain run -> exit 5); --recover rolls back and the chain is still there: a plain run continues at c
        shutil.rmtree(os.path.join(root, "data")); T.write(os.path.join(root, "data", "in.txt"), "in")
        shutil.rmtree(os.path.join(root, "runs"), ignore_errors=True)
        T.write(os.path.join(root, "tools", "c.py"), "import toylib\nfail = open('tools/c_flag.txt').read().strip() == 'FAIL'\ntoylib.run('c', 'data/b.txt', 'data/c.txt', fail)\n")
        T.write(os.path.join(root, "tools", "c_flag.txt"), "FAIL")
        rc, st, _ = T.run(root, L("5"), "--keep-on-failure")
        assert rc == 1 and st["journal"]["state"] != "rolled_back", st.get("journal")
        rc, st, _ = T.run(root, L("6"))
        assert rc == 5, rc
        rc, st, _ = T.run(root, L("7"), "--recover")
        assert rc == 0, rc
        T.write(os.path.join(root, "tools", "c.py"), "import toylib\ntoylib.run('c', 'data/b.txt', 'data/c.txt', False)\n")
        rc, st, _ = T.run(root, L("8"))
        assert rc == 0 and T.executed(L("8")) == ["c"], (rc, T.executed(L("8")))
        # a ci.yml edit between runs does not discard the chain: only the anchor stage (and later ones) rerun; the user's edit survives
        stages = [{"id": "a", "title": "a", "cmd": ["python3", "tools/a.py"], "outputs": ["data/a.txt"]},
                  {"id": "ci_anchor", "title": "ci", "cmd": ["python3", "tools/b.py"], "outputs": ["data/b.txt", ".github/workflows/ci.yml"], "rerun_on_resume": True},
                  {"id": "c", "title": "c", "cmd": ["python3", "tools/c.py"], "outputs": ["data/c.txt"]}]
        T.write(os.path.join(root, "tools", "ingest_stages.json"), json.dumps({"stages": stages}))
        ci = os.path.join(root, ".github", "workflows", "ci.yml")
        T.write(ci, "run: verify --expect-master-md5 " + "0" * 32 + "\n# t1\n")
        T.write(os.path.join(root, "tools", "b.py"), "import toylib, re\ntoylib.run('b', 'data/a.txt', 'data/b.txt')\np = '.github/workflows/ci.yml'\nt = open(p).read()\nopen(p, 'w', newline='').write(re.sub('(--expect-master-md5 )[0-9a-f]{32}', lambda m: m.group(1) + '1' * 32, t))\n")
        shutil.rmtree(os.path.join(root, "data")); T.write(os.path.join(root, "data", "in.txt"), "in")
        T.write(os.path.join(root, "tools", "c_flag.txt"), "FAIL")
        T.write(os.path.join(root, "tools", "c.py"), "import toylib\nfail = open('tools/c_flag.txt').read().strip() == 'FAIL'\ntoylib.run('c', 'data/b.txt', 'data/c.txt', fail)\n")
        rc, st, _ = T.run(root, L("9"))
        assert rc == 1 and T.executed(L("9")) == ["a", "b", "c"], (rc, T.executed(L("9")))
        assert open(ci).read() == "run: verify --expect-master-md5 " + "0" * 32 + "\n# t1\n", "rolled back"
        T.write(ci, "run: verify --expect-master-md5 " + "0" * 32 + "\n# t1\n# a new test line\n")
        rc, st, _ = T.run(root, L("10"))
        assert rc == 1 and T.executed(L("10")) == ["b", "c"] and st["checkpoint"]["restoredStages"] == 1, (T.executed(L("10")), st["checkpoint"])
        T.write(os.path.join(root, "tools", "c_flag.txt"), "OK")        # data change: whole chain invalid, fine; now a green run keeps the user's edit and sets the anchor
        rc, st, _ = T.run(root, L("10b"))
        assert rc == 0 and "# a new test line" in open(ci).read() and "1" * 32 in open(ci).read()
        # a discovery pass records a plain gate failure and goes on to the next stage, never commits
        T.write(os.path.join(root, "tools", "c_flag.txt"), "FAIL")
        stages.append({"id": "d", "title": "d", "cmd": ["python3", "tools/d.py"], "outputs": ["data/d.txt"]})
        T.write(os.path.join(root, "tools", "ingest_stages.json"), json.dumps({"stages": stages}))
        T.write(os.path.join(root, "tools", "d.py"), "import toylib\ntoylib.run('d', 'data/a.txt', 'data/d.txt')\n")
        shutil.rmtree(os.path.join(root, "data"), ignore_errors=True); T.write(os.path.join(root, "data", "in.txt"), "in")
        pre = T.tree_hash(root)
        rc, st, _ = T.run(root, L("11"), "--collect-stops", "--continue-on-gate-failure")
        assert rc == 7 and st["result"] == "collect_done_with_gate_failures", (rc, st["result"])
        assert [x["status"] for x in st["stages"]][-2:] == ["gate_failed_collected", "ok"] and T.executed(L("11"))[-2:] == ["c", "d"], (st["stages"], T.executed(L("11")))
        assert st["collect"]["gateFailures"][0]["stage"] == "c" and T.tree_hash(root) == pre, "collect pass rolls back"
        print("OK test_ingest_resume_chain")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
