"""M416 (audit F20) failure-injection tests for the journaled release (tools/release_journal.py + tools/run_ingest.py).
A throw-away tree is built with copies of the runner, the journal and a tiny stage list; stages write, create and delete files and fail on demand.
Checks: a green run commits and records its write set; an injected failure at any stage leaves the previous file set byte-identical (changed files restored, created files removed, deleted files back);
raw/ is never touched; a killed runner leaves an open journal that blocks the next run (exit 5) until --recover; --keep-on-failure keeps the mixed state; a second release cannot start while one is running;
a rollback that cannot restore a file is reported as rollback_failed, never as success."""
import json, os, shutil, signal, subprocess, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PY = sys.executable


def stage(sid, code, outputs=None):
    return {"id": sid, "title": sid, "cmd": ["python3", "-c", code], "verified": True, "outputs": outputs or []}


def make_root(fail_at=None, crash_at=None, extra_raw_at=None):
    t = tempfile.mkdtemp(prefix="rj_")
    os.makedirs(os.path.join(t, "tools"))
    for f in ("run_ingest.py", "release_journal.py", "run_fingerprint.py"):
        shutil.copy(os.path.join(ROOT, "tools", f), os.path.join(t, "tools", f))
    os.makedirs(os.path.join(t, "raw")); os.makedirs(os.path.join(t, "sub"))
    for n, c in (("a.txt", "A1"), ("b.txt", "B1"), ("c.txt", "C1"), ("sub/d.txt", "D1")):
        open(os.path.join(t, n), "w", encoding="utf-8", newline="").write(c)
    open(os.path.join(t, "raw", "r1.csv"), "w", encoding="utf-8", newline="").write("raw1")
    bad = "import sys; sys.exit(1)"
    crash = "import os, signal; os.kill(os.getppid(), getattr(signal, 'SIGKILL', signal.SIGTERM))"
    s1 = "open('a.txt','w',newline='').write('A2')"
    s2 = "import os; open('b.txt','w',newline='').write('B2'); open('new.txt','w',newline='').write('N'); os.remove('c.txt'); open('sub/d.txt','w',newline='').write('D2')"
    if extra_raw_at == "s2":
        s2 += "; open('raw/r2.csv','w',newline='').write('raw2')"
    s3 = "open('late.txt','w',newline='').write('L')"
    codes = {"s1": s1, "s2": s2, "s3": s3}
    if fail_at:
        codes[fail_at] = codes[fail_at] + "; " + bad
    if crash_at:
        codes[crash_at] = codes[crash_at] + "; " + crash
    stages = [stage("s1", codes["s1"], ["a.txt"]), stage("s2", codes["s2"], ["b.txt"]), stage("s3", codes["s3"], ["late.txt"])]
    json.dump({"stages": stages}, open(os.path.join(t, "tools", "ingest_stages.json"), "w", encoding="utf-8"))
    return t


def snap(t):
    out = {}
    for d, dirs, files in os.walk(t):
        dirs[:] = [x for x in dirs if x not in ("runs", "__pycache__")]
        for f in files:
            if f.endswith(".pyc"):
                continue
            p = os.path.join(d, f)
            out[os.path.relpath(p, t).replace(os.sep, "/")] = open(p, "rb").read()
    return out


def run(t, *args):
    r = subprocess.run([PY, os.path.join(t, "tools", "run_ingest.py")] + list(args), cwd=t, capture_output=True, text=True, encoding="utf-8")
    return r


def run_dirs(t):
    rd = os.path.join(t, "runs")
    return sorted(n for n in os.listdir(rd) if os.path.isdir(os.path.join(rd, n)))


def last_status(t):
    name = run_dirs(t)[-1]
    sp = os.path.join(t, "runs", name, "status.json")
    return (json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else None), name


def journal_of(t, name):
    return json.load(open(os.path.join(t, "runs", name, "journal", "journal.json"), encoding="utf-8"))


cleanup = []
try:
    # 1. green run commits and records its write set (a.txt / b.txt / sub/d.txt changed, new.txt / late.txt created, c.txt deleted; undeclared = files outside the declared outputs)
    t = make_root(); cleanup.append(t); before = snap(t)
    r = run(t); assert r.returncode == 0, r.stderr[-400:] + r.stdout[-400:]
    st, name = last_status(t); assert st["result"] == "ok" and st["journal"]["state"] == "committed", st
    after = snap(t)
    assert after["a.txt"] == b"A2" and after["b.txt"] == b"B2" and "c.txt" not in after and after["new.txt"] == b"N" and after["late.txt"] == b"L"
    jd = journal_of(t, name)
    assert jd["writeSet"] == {"changed": ["a.txt", "b.txt", "sub/d.txt"], "created": ["late.txt", "new.txt"], "deleted": ["c.txt"]}, jd["writeSet"]
    assert sorted(jd["undeclaredWrites"]) == ["c.txt", "new.txt", "sub/d.txt"], jd["undeclaredWrites"]
    assert not os.path.exists(os.path.join(t, "runs", ".release.lock")) and not os.path.isdir(os.path.join(t, "runs", name, "journal", "files"))

    # 2. injected failure at each stage: the previous file set comes back byte-identical, raw/ untouched
    for fail in ("s1", "s2", "s3"):
        t = make_root(fail_at=fail); cleanup.append(t); before = snap(t)
        r = run(t); assert r.returncode == 1, (fail, r.returncode, r.stderr[-300:])
        st, name = last_status(t)
        assert st["result"] == "gate_failed" and st["journal"]["state"] == "rolled_back", (fail, st)
        assert snap(t) == before, "tree differs after rollback at " + fail
        assert os.path.exists(os.path.join(t, "runs", name, "failure.json")) and not os.path.exists(os.path.join(t, "runs", ".release.lock"))
        assert run(t).returncode == 1 and snap(t) == before          # a second attempt is accepted (no open journal) and rolls back again

    # 3. raw files added by a failing run are reported, never deleted
    t = make_root(fail_at="s3", extra_raw_at="s2"); cleanup.append(t); before = snap(t)
    r = run(t); st, name = last_status(t)
    assert st["journal"]["state"] == "rolled_back" and st["journal"]["rawAdded"] == ["r2.csv"] and os.path.exists(os.path.join(t, "raw", "r2.csv"))
    assert {k: v for k, v in snap(t).items() if not k.startswith("raw/")} == {k: v for k, v in before.items() if not k.startswith("raw/")}

    # 4. the runner is killed after stage 2: the journal stays open, the next run refuses (exit 5), --recover restores the tree, then a run works
    t = make_root(crash_at="s2"); cleanup.append(t); before = snap(t)
    r = run(t)
    st, name = last_status(t)
    jd = journal_of(t, name)
    if jd["state"] == "started":                                          # hard kill: no handler ran
        print("  crash scenario: hard-kill path (journal left open, refuse, recover)")
        assert snap(t) != before
        r2 = run(t); assert r2.returncode == 5, (r2.returncode, r2.stderr[-300:])
        r3 = run(t, "--recover"); assert r3.returncode == 0, r3.stderr[-300:]
        assert snap(t) == before and journal_of(t, name)["state"] == "rolled_back"
    else:                                                                 # SIGTERM handler ran the rollback
        print("  crash scenario: signal-handler path (rolled back by the runner)")
        assert jd["state"] == "rolled_back" and snap(t) == before
    t = make_root(); cleanup.append(t)
    assert run(t).returncode == 0                                         # a clean tree runs after a recovery elsewhere

    # 5. --keep-on-failure keeps the mixed state, blocks the next run, --recover restores
    t = make_root(fail_at="s3"); cleanup.append(t); before = snap(t)
    r = run(t, "--keep-on-failure"); st, name = last_status(t)
    assert r.returncode == 1 and st["journal"]["state"] == "kept_for_debug" and snap(t) != before and os.path.exists(os.path.join(t, "runs", ".release.lock"))
    assert run(t).returncode == 5
    assert run(t, "--recover").returncode == 0 and snap(t) == before and not os.path.exists(os.path.join(t, "runs", ".release.lock"))

    # 6. a second release cannot start while a live process holds the lock
    t = make_root(); cleanup.append(t)
    os.makedirs(os.path.join(t, "runs"), exist_ok=True)
    holder = subprocess.Popen([PY, "-c", "import time; time.sleep(60)"])
    try:
        json.dump({"run": "other", "pid": holder.pid, "startedAt": "x"}, open(os.path.join(t, "runs", ".release.lock"), "w", encoding="utf-8"))
        r = run(t); assert r.returncode == 5 and "in progress" in r.stderr, (r.returncode, r.stderr[-300:])
    finally:
        holder.kill()

    # 7. --no-journal leaves the mixed state (development switch)
    t = make_root(fail_at="s3"); cleanup.append(t); before = snap(t)
    r = run(t, "--no-journal"); assert r.returncode == 1 and snap(t) != before

    # 8. a rollback that cannot restore a file is rollback_failed (verification is by re-hashing the tree, never by assumption)
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import release_journal as RJ
    t = make_root(); cleanup.append(t)
    j = RJ.Journal(t, os.path.join(t, "runs", "manual")); j.begin()
    open(os.path.join(t, "a.txt"), "w", encoding="utf-8", newline="").write("CHANGED")
    orig = RJ._atomic_copy
    RJ._atomic_copy = lambda src, dst: None
    try:
        rep = j.rollback("test")
    finally:
        RJ._atomic_copy = orig
    assert rep["state"] == "rollback_failed" and "a.txt" in rep["rollbackMismatches"] and os.path.exists(os.path.join(t, "runs", ".release.lock"))
    rep = j.rollback("retry"); assert rep["state"] == "rolled_back" and open(os.path.join(t, "a.txt"), encoding="utf-8").read() == "A1" and not os.path.exists(os.path.join(t, "runs", ".release.lock"))

    # 9. tree(): the excluded directories are not part of the snapshot
    tr = RJ.tree(t)
    assert "a.txt" in tr and not any(k.startswith(("raw/", "runs/")) for k in tr)
    print("OK test_release_journal")
finally:
    for t in cleanup:
        shutil.rmtree(t, ignore_errors=True)
