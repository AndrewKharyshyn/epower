"""M464: tools/ingest_preflight.py (spec analyses/M464_spec.md, component B) on a toy root: the sandbox never writes the real tree, a shared cache link is not followed
on removal, the seasonal prerequisite is run only when needed, and a failing check makes the report not ok."""
import os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import ingest_preflight as P


def w(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8", newline="\n").write(s)


def main():
    tmp = tempfile.mkdtemp(prefix="xt_pf_")
    try:
        root = os.path.join(tmp, "root")
        w(os.path.join(root, "drive_master.csv"), "file,x\na.csv,1\nb.csv,2\n")
        w(os.path.join(root, "seasonal_drive_master.csv"), "file,thermal_regime\na.csv,warm\n")
        w(os.path.join(root, "tools", "eol_shim", "sitecustomize.py"), "")
        w(os.path.join(root, "raw", "a.csv"), "raw")
        w(os.path.join(root, "regen_cache", "k.json"), "{}")
        w(os.path.join(root, "analyses", "x.json"), "{}")
        sb, linked = P.make_sandbox(root)
        try:
            assert os.path.isfile(os.path.join(sb, "drive_master.csv")) and not os.path.exists(os.path.join(sb, "raw")), "raw is never copied"
            assert not P.seasonal_covers_master(sb)
            if linked:                                           # the cache is shared, not copied
                assert os.path.isfile(os.path.join(sb, "regen_cache", "k.json"))
        finally:
            P.remove_sandbox(sb)
        assert not os.path.exists(sb)
        assert os.path.isfile(os.path.join(root, "regen_cache", "k.json")), "removing the sandbox must not touch the shared cache"
        # run() with a stubbed command runner
        calls = []
        outcome = {"m296_refresh_master_seasonal.py": 0, "tools/regen_v2_stage.py": 0}

        def fake(sb_, cmd, env, timeout):
            calls.append(cmd[0])
            if cmd[0] == "compute_seasonal.py":
                w(os.path.join(sb_, "seasonal_drive_master.csv"), "file,thermal_regime\na.csv,warm\nb.csv,cold\n")
            return outcome.get(cmd[0], 0), "out", 0.1
        P.sh = fake
        before = P.tree_hash(root)
        rep = P.run(root, ["m296_parity", "regen_v2"])
        assert rep["ok"] and not rep["wroteReal"], rep
        assert calls == ["tools/stage_raw.py", "compute_seasonal.py", "m296_refresh_master_seasonal.py", "tools/regen_v2_stage.py"], calls
        assert P.tree_hash(root) == before
        calls.clear(); outcome["tools/regen_v2_stage.py"] = 1
        rep = P.run(root, ["regen_v2"])
        assert not rep["ok"] and [c["status"] for c in rep["checks"]][-1] == "failed", rep
        calls.clear(); outcome["m296_refresh_master_seasonal.py"] = 1
        w(os.path.join(root, "seasonal_drive_master.csv"), "file,thermal_regime\na.csv,warm\nb.csv,cold\n")
        rep = P.run(root, ["m296_parity"])
        assert "compute_seasonal.py" not in calls and not rep["ok"], (calls, rep)
        print("OK test_ingest_preflight")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
