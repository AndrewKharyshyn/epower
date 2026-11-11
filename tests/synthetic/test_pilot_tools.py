"""M613 / M610b (Director ruling 2026-11-11, required changes 5 and 6): known answers for tools/state_hash.py and tools/collect_pass_compare.py.
 1. normalised_sha: two JSON files that differ only in pre-registered stamp leaves are equal; a difference in any other leaf is a difference; non-JSON files hash their bytes;
 2. state hash on a temp git repo: an identical state compares ok; a modified tracked file, a new untracked file, a changed index, a changed checkpoint inventory and a MODIFIED or DELETED pre-existing
    cache entry fail; an ADDED cache entry is allowed and listed;
 3. comparator: equal outputs before the first withheld stage pass; a difference before it fails and names the stage and file; a difference after it is provisional, never a failure; zero stop
    records compares every stage; a stage run without --record-normalised is a problem."""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import state_hash as SH
import collect_pass_compare as CC


def w(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8", newline="\n").write(s)


def git(root, *a):
    subprocess.run(["git", "-C", root] + list(a), check=True, capture_output=True)


def main():
    tmp = tempfile.mkdtemp(prefix="xt_pilot_")
    try:
        # 1. normalised_sha
        a, b, c, d = (os.path.join(tmp, n) for n in ("a.json", "b.json", "c.json", "d.csv"))
        w(a, json.dumps({"x": 1, "generatedAt": "2026-11-11T10:00:00", "n": {"computedAt": "t1", "v": [1, {"includedInReleaseAt": "t1", "k": 2}]}}))
        w(b, json.dumps({"n": {"v": [1, {"k": 2, "includedInReleaseAt": "t2"}], "computedAt": "t2"}, "generatedAt": "2026-11-12T11:11:11", "x": 1}))
        w(c, json.dumps({"x": 1, "generatedAt": "t", "n": {"v": [1, {"k": 3}]}}))
        w(d, "a,b\n1,2\n")
        assert SH.normalised_sha(a) == SH.normalised_sha(b) and SH.normalised_sha(a) != SH.normalised_sha(c) and SH.normalised_sha(d) == SH._sha_file(d)[:16]
        assert SH.normalised_sha(os.path.join(tmp, "missing")) is None
        # 2. state hash
        root = os.path.join(tmp, "repo")
        os.makedirs(root)
        git(root, "init", "-q")
        git(root, "config", "user.email", "t@example.com")
        git(root, "config", "user.name", "t")
        w(os.path.join(root, "t.txt"), "tracked")
        w(os.path.join(root, ".gitignore"), "*_cache/\nruns/\nraw_only/\n")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "init")
        w(os.path.join(root, "regen_cache", "e1.bin"), "cache1")
        w(os.path.join(root, "runs", ".checkpoints", "x", "entry.json"), "{}")
        pre = SH.snapshot(root)
        assert SH.compare(pre, SH.snapshot(root))["ok"]
        w(os.path.join(root, "regen_cache", "e2.bin"), "new entry")
        r = SH.compare(pre, SH.snapshot(root))
        assert r["ok"] and r["addedCacheEntries"] == ["regen_cache/e2.bin"], r
        os.remove(os.path.join(root, "regen_cache", "e2.bin"))
        for label, mutate in (("modified tracked", lambda: w(os.path.join(root, "t.txt"), "changed")),
                              ("untracked added", lambda: w(os.path.join(root, "u.txt"), "new")),
                              ("cache entry modified", lambda: w(os.path.join(root, "regen_cache", "e1.bin"), "tampered")),
                              ("cache entry deleted", lambda: os.remove(os.path.join(root, "regen_cache", "e1.bin"))),
                              ("checkpoint inventory", lambda: w(os.path.join(root, "runs", ".checkpoints", "y", "entry.json"), "{}")),
                              ("index changed", lambda: (w(os.path.join(root, "v.txt"), "v"), git(root, "add", "v.txt"))),
                              ("raw_only", lambda: w(os.path.join(root, "raw_only", "r.csv"), "r"))):
            mutate()
            r = SH.compare(pre, SH.snapshot(root))
            assert not r["ok"], label
            git(root, "reset", "-q", "--hard")
            for rel in ("u.txt", "v.txt", os.path.join("runs", ".checkpoints", "y"), "raw_only"):
                p = os.path.join(root, rel)
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else (os.path.exists(p) and os.remove(p))
            w(os.path.join(root, "regen_cache", "e1.bin"), "cache1")
        assert SH.compare(pre, SH.snapshot(root))["ok"], "restored"
        # 3. comparator
        def run_dir(name, stages, stops=None):
            d = os.path.join(tmp, name)
            os.makedirs(d)
            json.dump({"stages": [{"id": i, "rc": 0, **({"outputsNormalised": o} if o is not None else {})} for i, o in stages]}, open(os.path.join(d, "status.json"), "w", encoding="utf-8"))
            if stops is not None:
                json.dump({"records": stops}, open(os.path.join(d, "stops.json"), "w", encoding="utf-8"))
            return d
        S = lambda **kw: [("core", {"drive_master.csv": kw.get("dm", "h1")}), ("s2", {"summary_arrays.json": kw.get("s2", "h2")}), ("s3", {"x.json": kw.get("s3", "h3")}), ("s4", {"y.json": kw.get("s4", "h4")})]
        stops = [{"stage": "s3", "withheld": ["blk"]}]
        ok = CC.compare(run_dir("p1", S(), stops), run_dir("r1", S()))
        assert ok["ok"] and ok["firstWithheldStage"] == "s3" and ok["nCompared"] == 2 and ok["provisionalDifferences"] == [], ok
        late = CC.compare(run_dir("p2", S(s4="zz"), stops), run_dir("r2", S()))
        assert late["ok"] and any(x.startswith("s4") for x in late["provisionalDifferences"]), late
        at = CC.compare(run_dir("p3", S(s3="zz"), stops), run_dir("r3", S()))
        assert at["ok"] and at["nCompared"] == 2, "the withholding stage itself and later ones are provisional"
        early = CC.compare(run_dir("p4", S(dm="other"), stops), run_dir("r4", S()))
        assert not early["ok"] and "core" in early["problems"][0] and "drive_master.csv" in early["problems"][0], early
        early2 = CC.compare(run_dir("p5", S(s2="zz"), stops), run_dir("r5", S()))
        assert not early2["ok"] and early2["problems"][0].startswith("s2")
        nostops = CC.compare(run_dir("p6", S(s4="zz")), run_dir("r6", S()))
        assert not nostops["ok"] and nostops["nCompared"] == 4 and "non-interference only" in nostops["note"], nostops
        missing = CC.compare(run_dir("p7", [("core", None)], stops), run_dir("r7", [("core", None)]))
        assert not missing["ok"] and "--record-normalised" in missing["problems"][0]
        # withheld-free records (urban tools splice as if acknowledged) do not start the provisional region
        nowith = CC.compare(run_dir("p8", S(s4="zz"), [{"stage": "s2", "withheld": []}]), run_dir("r8", S()))
        assert not nowith["ok"] and nowith["firstWithheldStage"] is None
        # 4. urban_balance from/to record against the payload change (Director required change 7)
        pu = run_dir("p9", S(), [{"stage": "urban_balance", "withheld": [], "facts": {"from": "A", "to": "B"}}])
        mk = lambda v: {"urbanContrastBalance": {"overallVerdict": v}}
        assert CC.urban_balance_check(pu, mk("A"), mk("B"))[0] and not CC.urban_balance_check(pu, mk("A"), mk("C"))[0] and not CC.urban_balance_check(pu, mk("X"), mk("B"))[0]
        assert CC.urban_balance_check(run_dir("p10", S(), []), mk("A"), mk("B"))[0], "no record: nothing to check"
        print("test_pilot_tools OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
