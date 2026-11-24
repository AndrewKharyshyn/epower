"""M746 known-answer tests (analyses/M746_spec.md Rev 3 to Rev 5, section 3): tools/cloud_stage.py with planted tools in a temporary root.
(a) no store: every tool skipped_no_store, exit 0; (b) a planted failing tool and a planted timeout are recorded, later tools still run, exit 0; (c) an unchanged second run skips as up to date and leaves the promoted outputs untouched;
(d) a planted tool that changes a protected file is an integrity breach: the rest abort, exit 2, and nothing is promoted for it; (e) pinned tools are skipped_pinned_master; (f) the registered result files are never written;
(g) a missing DEM directory skips grade_shares; (h) a stale lock skips everything (skipped_locked); (i) the status prose never uses the word 'gap' for uncovered drives; (j) the stage never writes summary_arrays.json."""
import json, os, shutil, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cloud_stage as C

work = tempfile.mkdtemp(prefix="cs746_")
try:
    def mk_root(name):
        r = os.path.join(work, name)
        os.makedirs(os.path.join(r, "tools"))
        os.makedirs(os.path.join(r, "analyses"))
        open(os.path.join(r, "drive_master.csv"), "w", encoding="utf-8").write("file\na\n")
        open(os.path.join(r, "summary_arrays.json"), "w", encoding="utf-8").write("{}")
        return r

    def planted(r, mode_for):
        src = {
            "ok": "import sys,os\nout=sys.argv[1]\nopen(os.path.join(out,'o.txt'),'w').write('x')\n",
            "fail": "import sys\nsys.exit(1)\n",
            "hang": "import time\ntime.sleep(60)\n",
            "breach": "import sys,os\nout=sys.argv[1]\nopen(os.path.join(out,'o.txt'),'w').write('x')\nopen(os.path.join(%r,'drive_master.csv'),'a').write('z')\n" % r,
            "touch_registered": "import sys,os\nout=sys.argv[1]\nopen(os.path.join(out,'o.txt'),'w').write('x')\n",
        }
        tools = []
        for tid, mode, needs, pinned in mode_for:
            script = "t_%s.py" % tid
            open(os.path.join(r, "tools", script), "w", encoding="utf-8").write(src[mode])
            tools.append((tid, script, needs, ["o.txt"], pinned))
        return tools

    def configure(r, tools):
        C.ROOT = r
        C.P = lambda *a: os.path.join(r, *a)
        C.TOOLS = tools
        C.tool_cmd = lambda tid, script, scratch, master_md5, store, cov_dir: [sys.executable, os.path.join(r, "tools", script), scratch]
        C.dem_complete = lambda: os.path.isdir(os.path.join(r, "dem"))

    # (a) no store
    r = mk_root("a")
    configure(r, planted(r, [("coverage", "ok", [], False), ("clock_offset", "ok", [], False)]))
    os.environ["XT_CLOUD_STORE"] = os.path.join(r, "nostore")
    assert C.main(["--out-root", os.path.join(r, "ret"), "--status", os.path.join(r, "st.json")]) == 0
    st = json.load(open(os.path.join(r, "st.json"), encoding="utf-8"))
    assert all(v["status"] == "skipped_no_store" for v in st["tools"].values()) and not os.path.exists(os.path.join(r, "ret"))

    # store present
    store = os.path.join(work, "store")
    os.makedirs(store)
    open(os.path.join(store, "manifest.json"), "w", encoding="utf-8").write('{"n":1}')
    os.environ["XT_CLOUD_STORE"] = store
    os.environ.pop("XT_CLOUD_EXPORTS", None)

    # (b) fail + timeout + later tool still runs; (e) pinned skipped
    r = mk_root("b")
    tools = planted(r, [("coverage", "ok", [], False), ("clock_offset", "fail", [], False), ("tyre", "hang", [], False), ("thermal", "ok", [], True), ("grade_shares", "ok", [], False)])
    configure(r, tools)
    rc = C.main(["--timeout", "3", "--out-root", os.path.join(r, "ret"), "--status", os.path.join(r, "st.json")])
    st = json.load(open(os.path.join(r, "st.json"), encoding="utf-8"))["tools"]
    assert rc == 0 and st["coverage"]["status"] == "ok" and st["clock_offset"]["status"] == "failed" and st["tyre"]["status"] == "timeout"
    assert st["thermal"]["status"] == "skipped_pinned_master" and st["grade_shares"]["status"] == "skipped_no_dem"
    # (g) with a DEM dir the shares tool runs
    os.makedirs(os.path.join(r, "dem"))
    rc = C.main(["--timeout", "3", "--only", "grade_shares", "--out-root", os.path.join(r, "ret"), "--status", os.path.join(r, "st2.json")])
    assert json.load(open(os.path.join(r, "st2.json"), encoding="utf-8"))["tools"]["grade_shares"]["status"] == "ok"

    # (c) unchanged rerun: skipped_up_to_date, outputs untouched
    cov_out = os.path.join(r, "ret", [d for d in os.listdir(os.path.join(r, "ret")) if d.startswith("coverage_")][0], "o.txt")
    m0 = os.path.getmtime(cov_out)
    C.main(["--timeout", "3", "--out-root", os.path.join(r, "ret"), "--status", os.path.join(r, "st.json")])
    st = json.load(open(os.path.join(r, "st.json"), encoding="utf-8"))["tools"]
    assert st["coverage"]["status"] == "skipped_up_to_date" and os.path.getmtime(cov_out) == m0

    # (d) integrity breach
    r = mk_root("d")
    configure(r, planted(r, [("coverage", "ok", [], False), ("clock_offset", "breach", [], False), ("tyre", "ok", [], False)]))
    rc = C.main(["--timeout", "5", "--out-root", os.path.join(r, "ret"), "--status", os.path.join(r, "st.json")])
    st = json.load(open(os.path.join(r, "st.json"), encoding="utf-8"))["tools"]
    assert rc == 2 and st["clock_offset"]["status"] == "integrity_breach" and st["tyre"]["status"] == "integrity_breach"
    assert not [d for d in os.listdir(os.path.join(r, "ret")) if d.startswith("clock_offset_")]

    # (j) summary_arrays and registered results untouched in a normal run
    r = mk_root("j")
    open(os.path.join(r, "analyses", "M767_grade_class_shares.json"), "w", encoding="utf-8").write("{}")
    configure(r, planted(r, [("coverage", "ok", [], False)]))
    before = (open(os.path.join(r, "summary_arrays.json"), encoding="utf-8").read(), open(os.path.join(r, "analyses", "M767_grade_class_shares.json"), encoding="utf-8").read())
    C.main(["--out-root", os.path.join(r, "ret"), "--status", os.path.join(r, "st.json")])
    assert before == (open(os.path.join(r, "summary_arrays.json"), encoding="utf-8").read(), open(os.path.join(r, "analyses", "M767_grade_class_shares.json"), encoding="utf-8").read())

    # (h) stale lock
    r = mk_root("h")
    configure(r, planted(r, [("coverage", "ok", [], False)]))
    open(os.path.join(store, ".cloud_stage.lock"), "w", encoding="utf-8").write("1")
    assert C.main(["--out-root", os.path.join(r, "ret"), "--status", os.path.join(r, "st.json")]) == 0
    assert json.load(open(os.path.join(r, "st.json"), encoding="utf-8"))["tools"]["coverage"]["status"] == "skipped_locked"
    os.remove(os.path.join(store, ".cloud_stage.lock"))

    # audit M746: skipped_up_to_date twice in a row; --only keeps the other tools' records; upstream failure; stale lock takeover; failed promotion keeps the previous outputs
    r = mk_root("k")
    configure(r, planted(r, [("coverage", "ok", [], False), ("tyre", "ok", ["coverage"], False)]))
    args = ["--timeout", "5", "--out-root", os.path.join(r, "ret"), "--status", os.path.join(r, "st.json")]
    C.main(args)
    C.main(args)
    C.main(args)
    st = json.load(open(os.path.join(r, "st.json"), encoding="utf-8"))["tools"]
    assert st["coverage"]["status"] == "skipped_up_to_date" and st["tyre"]["status"] == "skipped_up_to_date" and st["coverage"]["outputs"]
    C.main(args + ["--only", "tyre"])
    st = json.load(open(os.path.join(r, "st.json"), encoding="utf-8"))["tools"]
    assert st["coverage"]["status"] == "skipped_up_to_date" and st["coverage"]["fingerprint"]
    r = mk_root("m")
    configure(r, planted(r, [("coverage", "fail", [], False), ("tyre", "ok", ["coverage"], False)]))
    C.main(["--timeout", "5", "--out-root", os.path.join(r, "ret"), "--status", os.path.join(r, "st.json")])
    st = json.load(open(os.path.join(r, "st.json"), encoding="utf-8"))["tools"]
    assert st["coverage"]["status"] == "failed" and st["tyre"]["status"] == "skipped_upstream_failed"
    lk = os.path.join(store, ".cloud_stage.lock")
    open(lk, "w", encoding="utf-8").write("1")
    old = os.path.getmtime(lk) - 7 * 3600
    os.utime(lk, (old, old))
    r = mk_root("n")
    configure(r, planted(r, [("coverage", "ok", [], False)]))
    C.main(["--out-root", os.path.join(r, "ret"), "--status", os.path.join(r, "st.json")])
    assert json.load(open(os.path.join(r, "st.json"), encoding="utf-8"))["tools"]["coverage"]["status"] == "ok" and not os.path.exists(lk)
    # promotion keeps the old destination when copying fails
    d0 = os.path.join(work, "dest")
    os.makedirs(d0)
    open(os.path.join(d0, "o.txt"), "w", encoding="utf-8").write("old")
    sc = os.path.join(work, "sc")
    os.makedirs(sc)
    try:
        C.promote(sc, d0, ["o.txt"])
        raise SystemExit("promotion of a missing output must fail")
    except OSError:
        pass
    assert open(os.path.join(d0, "o.txt"), encoding="utf-8").read() == "old"

    # (i) status vocabulary has no 'gap' wording; (real tool list) order and pinned flags
    assert not any("gap" in x for x in C.STATUSES)
    import importlib
    importlib.reload(C)
    ids = [t[0] for t in C.TOOLS]
    assert ids == ["import", "coverage", "clock_offset", "tyre", "thermal", "grade", "grade_shares", "unlogged"]
    assert {t[0] for t in C.TOOLS if t[4]} == {"thermal", "grade", "unlogged"}
    assert "summary_arrays.json" in C.PROTECTED and "analyses/M767_grade_class_shares.json" in C.PROTECTED
finally:
    shutil.rmtree(work, ignore_errors=True)
print("test_cloud_stage: OK")
