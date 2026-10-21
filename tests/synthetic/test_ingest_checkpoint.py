"""M464: stage checkpoints of tools/run_ingest.py (spec analyses/M464_spec.md, component A), end to end on a toy chain in a temp root.
Toy chain: a (data/a.txt from data/in.txt), b (data/b.txt from a), c (data/c.txt from b; fails while tools/c_flag.txt says FAIL). Each stage appends a line to an
execution log OUTSIDE the root so executions can be counted."""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
STAGE = '''import os, sys
LOG = os.environ["TOY_LOG"]
def run(name, src, dst, fail=False):
    open(LOG, "a").write(name + "\\n")
    if fail:
        sys.exit(1)
    os.makedirs("data", exist_ok=True)
    open(dst, "w").write(name + ":" + open(src).read())
'''


def write(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8", newline="\n").write(s)


def tree_hash(root):
    import hashlib
    h = hashlib.sha256()
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in ("runs", "__pycache__"))
        for f in sorted(files):
            if f.endswith(".pyc"):
                continue
            p = os.path.join(d, f)
            h.update(os.path.relpath(p, root).encode() + open(p, "rb").read())
    return h.hexdigest()


def setup(root):
    os.makedirs(os.path.join(root, "tools"))
    for f in ("run_ingest.py", "release_journal.py", "ingest_checkpoint.py", "run_fingerprint.py"):
        shutil.copy(os.path.join(REPO, "tools", f), os.path.join(root, "tools", f))
    shutil.copytree(os.path.join(REPO, "tools", "eol_shim"), os.path.join(root, "tools", "eol_shim"))
    write(os.path.join(root, "tools", "toylib.py"), STAGE)
    write(os.path.join(root, "tools", "toylib2.py"), "X = 1\n")
    write(os.path.join(root, "tools", "a.py"), "import toylib\ntoylib.run('a', 'data/in.txt', 'data/a.txt')\n")
    write(os.path.join(root, "tools", "b.py"), "import toylib, toylib2\ntoylib.run('b', 'data/a.txt', 'data/b.txt')\n")
    write(os.path.join(root, "tools", "c.py"), "import toylib\nfail = open('tools/c_flag.txt').read().strip() == 'FAIL'\ntoylib.run('c', 'data/b.txt', 'data/c.txt', fail)\n")
    write(os.path.join(root, "tools", "c_flag.txt"), "FAIL")
    write(os.path.join(root, "data", "in.txt"), "in")
    stages = [{"id": i, "title": i, "cmd": ["python3", "tools/%s.py" % i], "outputs": ["data/%s.txt" % i]} for i in "abc"]
    write(os.path.join(root, "tools", "ingest_stages.json"), json.dumps({"stages": stages}))


def run(root, log, *args):
    env = dict(os.environ, TOY_LOG=log, PYTHONPATH=os.path.join(root, "tools"))
    env.pop("XT_RAW_DIR", None)
    r = subprocess.run([sys.executable, os.path.join(root, "tools", "run_ingest.py")] + list(args), cwd=root, env=env, capture_output=True, text=True)
    runs = sorted(os.listdir(os.path.join(root, "runs")))
    st = None
    for n in reversed(runs):
        p = os.path.join(root, "runs", n, "status.json")
        if os.path.isfile(p):
            st = json.load(open(p, encoding="utf-8")); break
    return r.returncode, st, r


def executed(log):
    return open(log, encoding="utf-8").read().split() if os.path.exists(log) else []


def main():
    tmp = tempfile.mkdtemp(prefix="xt_cp_")
    try:
        root, logd = os.path.join(tmp, "root"), os.path.join(tmp, "log")
        os.makedirs(logd)
        setup(root)
        base = tree_hash(root)
        L = lambda n: os.path.join(logd, n + ".log")
        # 1. run fails in c: rolled back to the exact pre-run bytes, a and b checkpointed
        rc, st, _ = run(root, L("1"))
        assert rc == 1 and st["result"] == "gate_failed", (rc, st)
        assert executed(L("1")) == ["a", "b", "c"]
        assert tree_hash(root) == base, "rollback must restore the pre-run bytes"
        assert not os.path.exists(os.path.join(root, "data", "a.txt"))
        # 2. fix c (code of stage c only) and --resume: only c executes, a and b restored
        write(os.path.join(root, "tools", "c_flag.txt"), "OK")        # data-like file read by c (not source): changes the data state
        rc, st, _ = run(root, L("2"), "--resume")
        assert rc == 0, (rc, st)
        assert executed(L("2")) == ["a", "b", "c"], "a data-file change invalidates the whole chain: %s" % executed(L("2"))
        # restart the scenario with a pure code fix
        shutil.rmtree(os.path.join(root, "data")); write(os.path.join(root, "data", "in.txt"), "in")
        write(os.path.join(root, "tools", "c_flag.txt"), "FAIL")
        shutil.rmtree(os.path.join(root, "runs"))
        base = tree_hash(root)
        rc, st, _ = run(root, L("3"))
        assert rc == 1 and executed(L("3")) == ["a", "b", "c"]
        write(os.path.join(root, "tools", "c.py"), "import toylib\ntoylib.run('c', 'data/b.txt', 'data/c.txt', False)\n")   # code fix of c
        base_fixed = tree_hash(root)
        rc, st, _ = run(root, L("4"), "--resume")
        assert rc == 0, (rc, st)
        assert executed(L("4")) == ["c"], executed(L("4"))
        assert [s["status"] for s in st["stages"]] == ["restored_from_checkpoint", "restored_from_checkpoint", "ok"], st["stages"]
        assert st["checkpoint"]["restoredStages"] == 2 and st["checkpoint"]["resumed"], st["checkpoint"]
        assert open(os.path.join(root, "data", "c.txt"), encoding="utf-8").read() == "c:b:a:in"
        cpd = os.path.join(root, "runs", ".checkpoints")
        assert not (os.path.isdir(cpd) and os.listdir(cpd)), "a green full run discards its chain"
        # 3. code fix of stage b (through its imported helper) invalidates b and c, not a
        shutil.rmtree(os.path.join(root, "data")); write(os.path.join(root, "data", "in.txt"), "in")
        write(os.path.join(root, "tools", "c.py"), "import toylib\nfail = open('tools/c_flag.txt').read().strip() == 'FAIL'\ntoylib.run('c', 'data/b.txt', 'data/c.txt', fail)\n")
        rc, st, _ = run(root, L("5"))
        assert rc == 1
        write(os.path.join(root, "tools", "toylib2.py"), "X = 2\n")                           # imported by b only
        write(os.path.join(root, "tools", "c_flag.txt"), "FAIL")
        pre = tree_hash(root)
        rc, st, _ = run(root, L("6"), "--resume")
        assert executed(L("6")) == ["b", "c"], executed(L("6"))
        assert st["checkpoint"]["restoredStages"] == 1, st["checkpoint"]
        # 4. a failure after a restore still rolls back to the exact pre-run bytes
        assert rc == 1 and tree_hash(root) == pre, "rollback after a resumed run must restore the pre-run bytes"
        # 5. a stage-definition change in a (code of the first stage) invalidates everything
        write(os.path.join(root, "tools", "a.py"), "import toylib\ntoylib.run('a', 'data/in.txt', 'data/a.txt')  # edited\n")
        rc, st, _ = run(root, L("7"), "--resume")
        assert executed(L("7")) == ["a", "b", "c"], executed(L("7"))
        assert not st["checkpoint"]["resumed"], st["checkpoint"]
        # 6. --resume without any chain behaves as a normal run
        shutil.rmtree(os.path.join(root, "runs", ".checkpoints"), ignore_errors=True)
        write(os.path.join(root, "tools", "c_flag.txt"), "OK")
        rc, st, _ = run(root, L("8"), "--resume")
        assert rc == 0 and executed(L("8")) == ["a", "b", "c"] and st["checkpoint"]["resumed"] is False, (rc, st.get("checkpoint"))
        # 7. --only / --from never use checkpoints
        rc, st, r = run(root, L("9"), "--only", "b")
        assert "checkpoint" not in st and executed(L("9")) == ["b"]
        # 8. a dynamic import by bare string constant is part of the code hash
        write(os.path.join(root, "tools", "dyn.py"), "V = 1\n")
        write(os.path.join(root, "tools", "b.py"), "import toylib\nm = __import__('dyn')\ntoylib.run('b', 'data/a.txt', 'data/b.txt')\n")
        write(os.path.join(root, "tools", "c_flag.txt"), "FAIL")
        shutil.rmtree(os.path.join(root, "runs"), ignore_errors=True); shutil.rmtree(os.path.join(root, "data")); write(os.path.join(root, "data", "in.txt"), "in")
        rc, st, _ = run(root, L("10"))
        assert rc == 1 and executed(L("10")) == ["a", "b", "c"]
        write(os.path.join(root, "tools", "dyn.py"), "V = 2\n")
        rc, st, _ = run(root, L("11"), "--resume")
        assert executed(L("11")) == ["b", "c"], executed(L("11"))
        # 9. rerun_on_resume: the flagged stage is re-executed after its restore, later restored stages stay restored
        cfgp = os.path.join(root, "tools", "ingest_stages.json")
        cfg = json.load(open(cfgp, encoding="utf-8")); cfg["stages"][0]["rerun_on_resume"] = True; json.dump(cfg, open(cfgp, "w", encoding="utf-8"))
        shutil.rmtree(os.path.join(root, "runs"), ignore_errors=True); shutil.rmtree(os.path.join(root, "data")); write(os.path.join(root, "data", "in.txt"), "in")
        rc, st, _ = run(root, L("12"))
        assert rc == 1
        write(os.path.join(root, "tools", "c_flag.txt"), "FAIL")
        rc, st, _ = run(root, L("13"), "--resume")
        assert executed(L("13")) == ["a", "c"], executed(L("13"))          # a re-executed (flag), b restored, c executed
        print("OK test_ingest_checkpoint")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
