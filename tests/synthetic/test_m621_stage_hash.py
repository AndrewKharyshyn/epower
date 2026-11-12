"""M621 (P-02a) known-answer test: the stage code hash ignores CHANGELOG/STATE leaves, and refresh_cohort_meta ignores jsx edits outside COHORT_MIN_SUPPORT_DRIVES."""
import os, shutil, sys, tempfile
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
import ingest_checkpoint as C
tmp = tempfile.mkdtemp(prefix="xt_sh_")
try:
    os.makedirs(os.path.join(tmp, "tools"))
    w = lambda n, t: open(os.path.join(tmp, n), "w", newline="", encoding="utf-8").write(t)
    w("tools/refresh_cohort_meta.py", "import re\nre.search('x', open('xtrail_summary.jsx').read())\nopen('CHANGELOG.md')\nopen('STATE.md')\n")
    w("tools/other.py", "open('xtrail_summary.jsx'); open('CHANGELOG.md')\n")
    w("xtrail_summary.jsx", "const COHORT_MIN_SUPPORT_DRIVES = 10;\nconst a = 1;\n"); w("CHANGELOG.md", "x"); w("STATE.md", "x")
    stages = [{"id": "refresh_cohort_meta", "cmd": ["python3", "tools/refresh_cohort_meta.py"]}, {"id": "other", "cmd": ["python3", "tools/other.py"]}]
    def hashes():
        cp = C.Checkpoints(tmp, stages); return [cp.code_hash(s) for s in stages]
    h0 = hashes()
    w("CHANGELOG.md", "changed"); w("STATE.md", "changed"); assert hashes() == h0, "CHANGELOG/STATE leaf changes the code hash"
    w("xtrail_summary.jsx", "const COHORT_MIN_SUPPORT_DRIVES = 10;\nconst a = 2;\n"); h1 = hashes()
    assert h1[0] == h0[0], "jsx wording edit restarts refresh_cohort_meta"; assert h1[1] != h0[1], "other stage must still see the jsx"
    w("xtrail_summary.jsx", "const COHORT_MIN_SUPPORT_DRIVES = 12;\nconst a = 2;\n"); assert hashes()[0] != h0[0], "constant change not detected"
    print("PASS test_m621_stage_hash")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
