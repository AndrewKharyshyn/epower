"""M463 (Director ruling, option B): run-once regen study blocks are verified against the lock / recorded hashes, not against the current master."""
import json, os, sys, tempfile, hashlib
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import regen_v2_stage as S

OLD = "a641f34d7528d004b900c151cbde3d6d"


def w(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(json.dumps(o))


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def raises(f, *a):
    try:
        f(*a)
    except SystemExit:
        return True
    return False


def main():
    cwd = os.getcwd()
    d = tempfile.mkdtemp()
    os.chdir(d)
    try:
        R1 = {"_provenance": {"specSha256": "S1", "masterMd5": OLD}}
        w("analyses/M442_result.json", R1)
        w("analyses/M442_confirm.lock", {"specSha256": "S1", "startedAt": "x"})
        # first creation (no recorded block): passes
        S.check_locks_h(R1, R1, False, {})
        # carried block with its own (old) master, recorded hashes equal: passes (current master is irrelevant)
        rec = {"regenCaptureV2HStudy": {"firstOutputSha256": sha("analyses/M442_result.json"), "resultSha256": sha("analyses/M442_result.json"), "masterMd5": OLD}}
        S.check_locks_h(R1, R1, False, rec)
        # tampered result file: SystemExit
        w("analyses/M442_result.json", dict(R1, extra=1))
        assert raises(S.check_locks_h, R1, R1, False, rec)
        # missing/wrong lock spec: SystemExit
        w("analyses/M442_result.json", R1)
        w("analyses/M442_confirm.lock", {"specSha256": "OTHER"})
        assert raises(S.check_locks_h, R1, R1, False, rec)
        # M444 lock
        first = {"_provenance": {"specSha256": "S2", "masterMd5": OLD}}
        w("analyses/M444_result.json", first)
        w("analyses/M444_first.lock", {"specSha256": "S2", "resultSha256": sha("analyses/M444_result.json")})
        S.check_lock_std(first)
        w("analyses/M444_result.json", dict(first, x=1))
        assert raises(S.check_lock_std, first)
        # study basis keeps its own master and size
        b = S.study_basis(OLD)
        assert b["masterMd5"] == OLD and b["nDrives"] == 578
    finally:
        os.chdir(cwd)
    print("test_regen_v2_study_locks OK")


if __name__ == "__main__":
    main()
