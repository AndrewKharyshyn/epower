"""M609: an ingestion must not restart from stage 1 after a plain gate stop (analyses of the Nov 2026 ingestion: every rerun re-executed all stages).
Known answers on the toy chain of test_ingest_checkpoint.py:
 1. a plain `run_ingest.py` (no flag) after a failed run restores the passed stages (resume is the default);
 2. a top-level run-output log (shell redirect of the run's own stdout) that changes between runs does not change the base key;
 3. `--fresh` executes every stage;
 4. a root-level .log written while a run is rolling back does not make the rollback fail;
 5. an acknowledgement / ruling file written after the journal snapshot survives a rollback and recovery (human input, not run output);
 6. an ordinary new data file created after the snapshot is still removed by a rollback (the protection is narrow)."""
import json, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import test_ingest_checkpoint as T
import release_journal as RJ


def main():
    tmp = tempfile.mkdtemp(prefix="xt_resume_")
    try:
        root, logd = os.path.join(tmp, "root"), os.path.join(tmp, "log")
        os.makedirs(logd)
        T.setup(root)
        L = lambda n: os.path.join(logd, n + ".log")
        rc, st, _ = T.run(root, L("1"))
        assert rc == 1 and T.executed(L("1")) == ["a", "b", "c"]
        # 2. a root-level run log appears and differs between the runs; the code fix of c keeps a and b restorable
        T.write(os.path.join(root, "ingest_run_1.log"), "output of the first run\n")
        T.write(os.path.join(root, "ingest_run_2.out"), "more output\n")
        T.write(os.path.join(root, "tools", "c.py"), "import toylib\ntoylib.run('c', 'data/b.txt', 'data/c.txt', False)\n")
        rc, st, _ = T.run(root, L("2"))                                     # NO --resume flag
        assert rc == 0, (rc, st)
        assert T.executed(L("2")) == ["c"], "plain rerun must resume: %s" % T.executed(L("2"))
        assert st["checkpoint"]["resumed"] and st["checkpoint"]["restoredStages"] == 2, st["checkpoint"]
        # 3. --fresh runs everything (chain is not consulted)
        shutil.rmtree(os.path.join(root, "data")); T.write(os.path.join(root, "data", "in.txt"), "in")
        T.write(os.path.join(root, "tools", "c_flag.txt"), "FAIL")
        T.write(os.path.join(root, "tools", "c.py"), "import toylib\nfail = open('tools/c_flag.txt').read().strip() == 'FAIL'\ntoylib.run('c', 'data/b.txt', 'data/c.txt', fail)\n")
        rc, st, _ = T.run(root, L("3"))
        assert rc == 1
        rc, st, _ = T.run(root, L("4"), "--fresh")
        assert T.executed(L("4")) == ["a", "b", "c"], T.executed(L("4"))
        # 4-6: journal level
        jroot = os.path.join(tmp, "jroot")
        T.write(os.path.join(jroot, "data", "keep.txt"), "x")
        T.write(os.path.join(jroot, "ingest_run.log"), "before")
        j = RJ.Journal(jroot, os.path.join(jroot, "runs", "r1"))
        j.begin({})
        T.write(os.path.join(jroot, "ingest_run.log"), "before and growing while the run executes")        # 4: top-level log changes after the snapshot
        T.write(os.path.join(jroot, "analyses", "M999_x_gtr_flip_ack.json"), "{}")                          # 5: human input written after the snapshot
        T.write(os.path.join(jroot, "analyses", "M999_x_director_ruling.json"), "{}")
        T.write(os.path.join(jroot, "data", "new.txt"), "run output")                                       # 6: ordinary output created after the snapshot
        T.write(os.path.join(jroot, "data", "keep.txt"), "changed")
        rep = j.rollback("test")
        assert rep["state"] == "rolled_back", rep
        assert os.path.exists(os.path.join(jroot, "analyses", "M999_x_gtr_flip_ack.json")) and os.path.exists(os.path.join(jroot, "analyses", "M999_x_director_ruling.json"))
        assert not os.path.exists(os.path.join(jroot, "data", "new.txt")), "ordinary created files are still removed"
        assert open(os.path.join(jroot, "data", "keep.txt")).read() == "x"
        assert sorted(rep["restored"]["keptAckInputs"]) == ["analyses/M999_x_director_ruling.json", "analyses/M999_x_gtr_flip_ack.json"], rep["restored"]
        assert RJ.skip_root_file(".", "a.log") and RJ.skip_root_file(".", "b.out") and not RJ.skip_root_file("analyses", "c.log") and not RJ.skip_root_file(".", "d.json")
        print("test_ingest_resume_robust OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
