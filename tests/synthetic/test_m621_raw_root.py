"""M621 (P-02b): run_ingest resolves the effective raw root before RF.plan, and the fingerprint raw root follows XT_RAW_DIR (so a new file in raw/ is seen when raw_only was inherited)."""
import os, re, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
src = open(os.path.join(REPO, "tools", "run_ingest.py"), encoding="utf-8").read()
i_set = src.index('os.environ["XT_RAW_DIR"] = os.path.join(ROOT, "raw")'); i_plan = src.index("RF.plan(ROOT")
assert i_set < i_plan, "XT_RAW_DIR must be forced before RF.plan"
sys.path.insert(0, os.path.join(REPO, "tools")); import run_fingerprint as RF
os.environ["XT_RAW_DIR"] = os.path.join(REPO, "raw_only_nonexistent")
a = RF.raw_dir(REPO); os.environ["XT_RAW_DIR"] = os.path.join(REPO, "raw"); b = RF.raw_dir(REPO)
assert a != b and b == os.path.realpath(os.path.join(REPO, "raw"))
print("PASS test_m621_raw_root")
