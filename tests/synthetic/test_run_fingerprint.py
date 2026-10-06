"""M385: run-level fingerprint skip logic (tools/run_fingerprint.py). A skip is allowed only when EVERY component equals the last fully green run;
any change to a source, the stage list, the lock, analyses/, a declared output, the master, the manifest, the raw listing or the environment
prevents it and is named in the reason; the rendered dashboard is excluded; the gate stages are never skipped."""
import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import run_fingerprint as RF

STAGES = [{"id": "preflight", "cmd": ["x"]}, {"id": "ingest_core", "cmd": ["x"], "outputs": ["summary_arrays.json", "drive_master.csv"]},
          {"id": "fuel_recon", "cmd": ["x"], "outputs": ["fuel_recon_master.csv"]}, {"id": "build_html", "cmd": ["x"], "outputs": ["xtrail_dashboard.html"]},
          {"id": "jsdom", "cmd": ["x"]}, {"id": "release_check", "cmd": ["x"]}, {"id": "state", "cmd": ["x"]}]


def w(root, rel, text):
    p = os.path.join(root, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w", encoding="utf-8").write(text)


with tempfile.TemporaryDirectory() as td:
    for rel, t in {"a.py": "1", "tools/b.py": "1", "drive_master.csv": "m", "raw_manifest.json": "{}", "raw/x.csv": "t", "requirements.pinned.txt": "numpy==1",
                   "analyses/s.md": "spec", "summary_arrays.json": "{}", "fuel_recon_master.csv": "f", "xtrail_dashboard.html": "h"}.items():
        w(td, rel, t)
    skip, why, comp = RF.plan(td, STAGES, True)
    assert skip == set() and "no valid ledger" in why
    RF.save_ledger(td, comp, "r1")
    skip, why, _ = RF.plan(td, STAGES, True)
    assert skip == {"ingest_core", "fuel_recon"}, skip                       # preflight/build_html/jsdom/release_check/state always run
    assert "equal" in why
    assert RF.plan(td, STAGES, False)[0] == set()                            # opt-in only
    w(td, "xtrail_dashboard.html", "rebuilt differently")                    # rebuilt every run: excluded
    assert RF.plan(td, STAGES, True)[0] == {"ingest_core", "fuel_recon"}

    def changed(rel, text, component, restore):
        old = open(os.path.join(td, rel), encoding="utf-8").read() if os.path.exists(os.path.join(td, rel)) else None
        w(td, rel, text)
        skip, why, _ = RF.plan(td, STAGES, True)
        assert skip == set() and component in why, (rel, why)
        if old is None:
            os.remove(os.path.join(td, rel))
        else:
            w(td, rel, old)
        assert RF.plan(td, STAGES, True)[0], "restoring the input must allow the skip again: " + rel

    changed("a.py", "2", "sources", None)
    changed("tools/b.py", "2", "sources", None)
    changed("analyses/s.md", "spec2", "analyses", None)
    changed("summary_arrays.json", "{1}", "outputs", None)
    changed("fuel_recon_master.csv", "g", "outputs", None)
    changed("drive_master.csv", "m2", "master", None)
    changed("raw_manifest.json", "{1}", "rawManifest", None)
    changed("raw/y.csv", "new drive", "rawListing", None)
    changed("requirements.pinned.txt", "numpy==2", "lock", None)
    os.environ["XT_TEST_FLAG"] = "1"
    skip, why, _ = RF.plan(td, STAGES, True)
    assert skip == set() and "env" in why
    del os.environ["XT_TEST_FLAG"]
    skip, why, _ = RF.plan(td, STAGES[:-1], True)
    assert skip == set() and "stageList" in why
print("OK test_run_fingerprint")
