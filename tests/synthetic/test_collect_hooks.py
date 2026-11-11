"""M613 / M610b (Director ruling 2026-11-11, required changes 2 and 3): the hooks of the four converted gates are inert outside a collect pass.
 1. structure (all four tools): every `try_collect(...)` call sits in a boolean expression behind `collect_active()` (so the default stop path evaluates nothing else) and its facts argument is
    a lambda (facts are built only in a valid pass);
 2. gtr_family_refresh_splice.main() with patched inputs: without a token a flip stop prints the byte-identical message and exits 3 and no record is built; with a token the same stop is recorded
    (facts: ack-bound hashes and the flipped set), nothing is spliced and main returns; a stop that is not acknowledgeable (O file binding) stays a hard stop with the same message and exit code
    even in a collect pass;
 3. an ack bound to a record is refused for the same stop with a changed fact (record hash differs)."""
import ast, contextlib, io, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
import stop_protocol as SP

TOOLS = ("gtr_family_refresh_splice", "gtr_closure_refresh", "urban_week_block", "urban_balance")


def parents(tree):
    par = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            par[c] = n
    return par


def structure(name):
    src = open(os.path.join(REPO, "tools", name + ".py"), encoding="utf-8").read()
    tree = ast.parse(src)
    par = parents(tree)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "try_collect"]
    assert len(calls) == 1, (name, len(calls))
    c = calls[0]
    assert len(c.args) >= 3 and isinstance(c.args[2], ast.Lambda), (name, "facts must be a lambda")
    node, guarded = c, False
    while node in par:
        p = par[node]
        if isinstance(p, ast.BoolOp):
            idx = [i for i, v in enumerate(p.values) if any(x is node for x in ast.walk(v))][0]
            if any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr == "collect_active" for v in p.values[:idx] for x in ast.walk(v)):
                guarded = True
                break
        node = p
    assert guarded, (name, "try_collect is not behind collect_active()")


def main():
    for t in TOOLS:
        structure(t)
    tmp = tempfile.mkdtemp(prefix="xt_hooks_")
    cwd = os.getcwd()
    try:
        import gtr_family_refresh_splice as GF
        os.chdir(tmp)
        os.makedirs("analyses")
        row = lambda a, f: {"axis": a, "gen100": 1.0, "trac100": 2.0, "fgen": f, "etaBus": 0.9}
        O = {"sensitivity": {"rows": [row("A1", 0.6), row("A2", 0.4)]}, "simultaneity": {"rows": [{"type": "urban"}]}}
        json.dump(O, open("analyses/M377_O_blocks.json", "w", encoding="utf-8"))
        json.dump({}, open("summary_arrays.json", "w", encoding="utf-8"))
        open("drive_master.csv", "w", encoding="utf-8").write("x\n")
        GF.M377_PIN.spec_sha = lambda p: "spec"
        GF.md5 = lambda p: "MASTERMD5"
        saved_argv = sys.argv[:]

        def run(stops, env):
            GF.plan = lambda *a, **k: (None, {"changedPaths": 5}, list(stops))
            sys.argv = ["x"]
            err = io.StringIO()
            old = {k: os.environ.get(k) for k in (SP.TOKEN_ENV, SP.DIR_ENV)}
            for k in old:
                os.environ.pop(k, None)
            os.environ.update(env)
            code = "returned"
            try:
                with contextlib.redirect_stderr(err):
                    GF.main()
            except SystemExit as e:
                code = e.code
            finally:
                for k, v in old.items():
                    os.environ.pop(k, None)
                    if v is not None:
                        os.environ[k] = v
                sys.argv = saved_argv
            return code, err.getvalue()
        msg = lambda s: "STOP (Director): " + "; ".join(s) + "\n"
        # 2a. no token: byte-identical message, exit 3, facts never built (record_stop would raise if reached with a callable that raises)
        code, err = run([GF.FLIP_STOP], {})
        assert code == 3 and err == msg([GF.FLIP_STOP]), (code, err)
        # a stale variable without a token file is inactive too
        rd = os.path.join(tmp, "runs", "r1")
        os.makedirs(rd)
        code, err = run([GF.FLIP_STOP], {SP.TOKEN_ENV: "stale", SP.DIR_ENV: rd})
        assert code == 3 and err == msg([GF.FLIP_STOP]) and not os.path.exists(os.path.join(rd, "stops"))
        # 2b. valid pass: recorded, nothing spliced, main returns
        tok = SP.issue_token(rd)
        code, err = run([GF.FLIP_STOP], {SP.TOKEN_ENV: tok, SP.DIR_ENV: rd})
        assert code == "returned" and "COLLECT (M610b)" in err, (code, err)
        recs = SP.load_records(rd)
        assert len(recs) == 1 and recs[0]["stage"] == "gtr_family_refresh" and recs[0]["facts"]["driveMasterMd5"] == "MASTERMD5" and recs[0]["facts"]["flipped"] == [{"axis": "A1", "fgen": 0.6}], recs
        assert set(recs[0]["facts"]) >= {"stops", "sensitivityAxesSha256", "simultaneityRowsSha256", "flipped", "changedPaths"} and len(json.dumps(recs[0]["facts"])) < SP.MAX_FACTS_BYTES
        assert not os.path.exists("analyses/summary_spliced") and open("summary_arrays.json", encoding="utf-8").read() == "{}", "nothing spliced"
        # 2c. a hard stop stays a hard stop in a valid pass: same message, exit 3, no new record
        hard = [GF.FLIP_STOP, "O file was produced on a different drive_master.csv"]
        code, err = run(hard, {SP.TOKEN_ENV: tok, SP.DIR_ENV: rd})
        assert code == 3 and err == msg(hard) and len(SP.load_records(rd)) == 1, (code, err)
        # 2d. gtr_closure_refresh (blind audit finding 1): only a pure escalation list is collectable; a stop or a REFUSED acknowledgement keeps it a hard stop
        import gtr_closure_refresh as CL
        esc = [{"rule": "r", "path": "p"}]
        assert CL.closure_collectable({"stops": [], "escalations": esc}) is True
        assert CL.closure_collectable({"stops": [], "escalations": []}) is False
        assert CL.closure_collectable({"stops": [{"rule": "s", "path": "p"}], "escalations": esc}) is False
        assert CL.closure_collectable({"stops": [], "escalations": esc, "acknowledgementRefused": "bound to a different drive_master.csv MD5"}) is False
        # 3. changed fact: an ack bound to the first record is refused for the changed record
        ack = {"ruling": "R", "recordSha256": recs[0]["recordSha256"]}
        changed = SP.build_record("gtr_family_refresh", "reading_flip_or_band", dict(recs[0]["facts"], flipped=[{"axis": "A1", "fgen": 0.7}]), recs[0]["ackEnv"], recs[0]["ackSchema"], recs[0]["withheld"], recs[0]["artifacts"], recs[0]["upstream"])
        assert changed["recordSha256"] != recs[0]["recordSha256"] and SP.check_ack_binding(recs[0]["recordSha256"], ack) and not SP.check_ack_binding(changed["recordSha256"], ack)
        SP.close_token(rd)
        print("test_collect_hooks OK")
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
