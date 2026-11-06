"""M596 (audit D1): a renamed copy of a registered B/D control capture is comparison_only (not an orphan) in a manifest rebuild;
an unregistered stray file is still an orphan; a master drive is still canonical."""
import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
import pandas as pd, corpus_manifest as cm
d = tempfile.mkdtemp()
hdr = "time,x\n"
for name in ("2026-05-11 18-57-09.csv", "2026-07-30 22-06-51.csv", "2026-08-01 20-53-20.csv", "2026-09-30 10-00-00.csv"):
    open(os.path.join(d, name), "w").write(hdr + "0,1\n1,2\n")
m = cm.build(d, master_df=pd.DataFrame({"file": ["2026-05-11 18-57-09.csv"]}), out_path=None)
roles = {r["raw_name"]: r["role"] for r in m["files"]}
assert roles["2026-05-11 18-57-09.csv"] == "canonical", roles
assert roles["2026-07-30 22-06-51.csv"] == "comparison_only" and roles["2026-08-01 20-53-20.csv"] == "comparison_only", roles
assert roles["2026-09-30 10-00-00.csv"] == "orphan", roles
assert m["roles"].get("comparison_only") == 2 and m["roles"].get("orphan") == 1, m["roles"]
print("ok test_control_registry")
