"""M610a (spec R2): when a rerun cannot restore, the run record says what differed from the stored chain (data file, raw listing, XT_* variable). Toy chain of test_ingest_checkpoint.py."""
import os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_ingest_checkpoint as T


def main():
    tmp = tempfile.mkdtemp(prefix="xt_miss_")
    try:
        root, logd = os.path.join(tmp, "root"), os.path.join(tmp, "log")
        os.makedirs(logd)
        T.setup(root)
        L = lambda n: os.path.join(logd, n + ".log")
        rc, st, _ = T.run(root, L("1"))
        assert rc == 1 and T.executed(L("1")) == ["a", "b", "c"]
        assert os.path.isfile(os.path.join(root, "runs", ".checkpoints", os.listdir(os.path.join(root, "runs", ".checkpoints"))[0], "base.json")), "base.json is stored with the chain"
        # 1. a data file edited between the runs
        T.write(os.path.join(root, "data", "in.txt"), "in edited")
        rc, st, _ = T.run(root, L("2"))
        ck = st["checkpoint"]
        assert not ck["resumed"] and ck["reason"].startswith("no valid checkpoint chain"), ck
        assert ck["missReason"] == "data file changed: data/in.txt", ck
        # 2. a new data file
        T.write(os.path.join(root, "data", "extra.txt"), "x")
        rc, st, _ = T.run(root, L("3"))
        assert "data file added: data/extra.txt" in st["checkpoint"]["missReason"], st["checkpoint"]
        # 3. an XT_* variable (a data-state input of the base key)
        os.environ["XT_TOY_SETTING"] = "1"
        try:
            rc, st, _ = T.run(root, L("4"))
        finally:
            del os.environ["XT_TOY_SETTING"]
        assert "environment differs: XT_* variables" in st["checkpoint"]["missReason"], st["checkpoint"]
        # 4. an identical rerun restores and carries no missReason
        rc, st, _ = T.run(root, L("5"))
        T.write(os.path.join(root, "tools", "c_flag.txt"), "FAIL")
        rc, st, _ = T.run(root, L("6"))
        assert st["checkpoint"]["resumed"] and "missReason" not in st["checkpoint"], st["checkpoint"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_resume_miss_reason OK")


if __name__ == "__main__":
    main()
