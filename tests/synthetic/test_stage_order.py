"""M610a: static order lint of the ingestion stage list (tools/stage_order.py; spec analyses/M610_spec.md Rev 1, T1).
Known answers on a toy root plus the real list: the order BEFORE the M610a reorder (thermal_provenance ahead of thermal_support_ledger, the Nov 2026 defect) must fail on `needs`;
the current order passes."""
import copy, json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
import stage_order as SO


def write(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8", newline="\n").write(s)


def kinds(res):
    return sorted(v["kind"] for v in res["violations"])


def main():
    # ---- real list: negative control and current order (needs only: fast)
    stages = SO.load_stages(os.path.join(REPO, "tools", "ingest_stages.json"))
    ids = [s["id"] for s in stages]
    assert ids.index("thermal_provenance") > ids.index("thermal_support_ledger"), "M610a reorder missing"
    tp = next(s for s in stages if s["id"] == "thermal_provenance")
    assert tp.get("needs") == ["thermal_support_ledger"], tp.get("needs")
    assert SO.lint(stages, REPO, file_level=False)["ok"], SO.lint(stages, REPO, file_level=False)
    old = copy.deepcopy(stages)
    x = old.pop(ids.index("thermal_provenance"))
    old.insert([s["id"] for s in old].index("thermal_support_ledger"), x)               # the order before the reorder
    res = SO.lint(old, REPO, file_level=False)
    assert not res["ok"] and kinds(res) == ["needs_after"] and res["violations"][0]["stage"] == "thermal_provenance", res
    # ---- real list, file level (ratchet): no finding outside analyses/M610_stage_needs.json (slow: static closure of every stage)
    full = SO.lint(stages, REPO)
    assert full["ok"], "NEW file-level order finding(s): %s" % full["violations"]
    # ---- toy root: needs rules
    tmp = tempfile.mkdtemp(prefix="xt_order_")
    try:
        for n in "abc":
            write(os.path.join(tmp, "tools", n + ".py"), "pass\n")
        mk = lambda i, **kw: dict({"id": i, "title": i, "cmd": ["python3", "tools/%s.py" % i], "outputs": ["data/%s.txt" % i]}, **kw)
        assert SO.lint([mk("a"), mk("b", needs=["a"]), mk("c", needs=["a", "b"])], tmp, file_level=False)["ok"]
        r = SO.lint([mk("a", needs=["b"]), mk("b")], tmp, file_level=False)
        assert kinds(r) == ["needs_after"], r
        r = SO.lint([mk("a"), mk("b", needs=["zz"])], tmp, file_level=False)
        assert kinds(r) == ["needs_unknown"], r
        r = SO.lint([mk("a", needs=["a"])], tmp, file_level=False)
        assert kinds(r) == ["needs_after"], r                                          # a self-dependency is a cycle
        r = SO.lint([mk("a"), mk("a")], tmp, file_level=False)
        assert "duplicate_stage_id" in kinds(r), r
        # ---- toy root: file level. a names data/b.txt which the LATER stage b writes
        write(os.path.join(tmp, "tools", "a.py"), "X = 'data/b.txt'\n")
        S = [mk("a"), mk("b"), mk("c")]
        r = SO.lint(S, tmp, baseline=set())
        assert kinds(r) == ["reads_before_writer"] and (r["violations"][0]["stage"], r["violations"][0]["file"]) == ("a", "data/b.txt"), r
        r = SO.lint(S, tmp, baseline={("a", "data/b.txt")})                           # ratchet: a baselined finding passes, is reported
        assert r["ok"] and len(r["baselined"]) == 1, r
        r = SO.lint([mk("a", reads_prior_state=["data/b.txt"]), mk("b"), mk("c")], tmp, baseline=set())
        assert r["ok"], r                                                              # reasoned waiver
        assert SO.lint([mk("a", reads_prior_state=["*"]), mk("b"), mk("c")], tmp, baseline=set())["ok"]     # wildcard waiver
        r = SO.lint([mk("b"), mk("a"), mk("c")], tmp, baseline=set())
        assert r["ok"], r                                                              # writer first: fine
        T = [mk("a", outputs=["data/s.json"]), mk("b", outputs=["data/s.json"]), mk("c", outputs=["data/s.json"])]
        write(os.path.join(tmp, "tools", "a.py"), "X = 'data/s.json'\n")
        r = SO.lint(T, tmp, baseline=set())
        assert r["ok"] and r["shared"] == ["data/s.json"], r                           # 3 writers = shared accumulator, not checked at file level
        # a stage naming its own output is not a violation
        write(os.path.join(tmp, "tools", "a.py"), "X = 'data/a.txt'\n")
        assert SO.lint([mk("a"), mk("b")], tmp, baseline=set())["ok"]
        # the stored baseline is read from analyses/M610_stage_needs.json
        write(os.path.join(tmp, "tools", "a.py"), "X = 'data/b.txt'\n")
        write(os.path.join(tmp, "analyses", "M610_stage_needs.json"), json.dumps({"fileLevelBaseline": [{"stage": "a", "file": "data/b.txt", "status": "unreviewed"}]}))
        assert SO.lint(S, tmp)["ok"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_stage_order OK")


if __name__ == "__main__":
    main()
