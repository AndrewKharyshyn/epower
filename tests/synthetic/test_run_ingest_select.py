"""F10 (audit 2026-10-05): run_ingest stage selection validates IDs and refuses an empty selection."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from run_ingest import select_stages

S = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
ids = lambda x: [s["id"] for s in x]


def raises(**kw):
    try:
        select_stages(S, **kw)
    except ValueError:
        return True
    return False


assert ids(select_stages(S)) == ["a", "b", "c"]
assert ids(select_stages(S, only="b")) == ["b"]
assert ids(select_stages(S, frm="b")) == ["b", "c"]
assert ids(select_stages(S, skip=["b"])) == ["a", "c"]
assert raises(only="typo"), "unknown --only must be rejected"
assert raises(frm="typo"), "unknown --from must be rejected"
assert raises(skip=["typo"]), "unknown --skip must be rejected"
assert raises(only="a", skip=["a"]), "empty selection must be rejected"
print("OK test_run_ingest_select")
