"""M650 (P-04): declared payload-key reads/writes and the stamping-final rule of tools/stage_order.py. Required swaps are rejected (comparison_cube / urban_week_block, build_html / jsdom, and the
dashboard readers), a payload write after the stamping stages is rejected, the shipped list passes. Run: python tests/synthetic/test_m650_stage_declarations.py"""
import copy, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
import stage_order as SO


def swap(stages, a, b):
    s = copy.deepcopy(stages); ids = [x["id"] for x in s]
    i, j = ids.index(a), ids.index(b)
    s[i], s[j] = s[j], s[i]
    return s


def kinds(r):
    return sorted(v["kind"] for v in r["violations"])


stages = SO.load_stages(os.path.join(REPO, "tools", "ingest_stages.json"))
ids = [s["id"] for s in stages]
t0 = time.time()
base = SO.lint(stages, REPO)
secs = time.time() - t0
assert base["ok"], base["violations"]
# the required swaps (both were accepted before M650)
for a, b, kind in (("comparison_cube", "urban_week_block", "declared_read_before_write"), ("build_html", "jsdom", "declared_read_before_write"),
                   ("comparison_cube", "urban_contrast_balance", "declared_read_before_write"), ("build_html", "dump_tabs", "declared_read_before_write")):
    r = SO.lint(swap(stages, a, b), REPO, file_level=False)
    assert not r["ok"] and kind in kinds(r), (a, b, r["violations"])
# the two content stages must stay before the stamping stages
for k in ("m483_wording_splice", "m432_refresh"):
    assert ids.index(k) < ids.index("stamp_basis"), k
    moved = copy.deepcopy(stages); x = moved.pop(ids.index(k)); moved.insert([s["id"] for s in moved].index("stamp_dependencies") + 1, x)
    r = SO.lint(moved, REPO, file_level=False)
    assert "payload_write_after_stamp" in kinds(r) and r["violations"][0]["stage"] == k, r["violations"]
# a waiver is honoured, and an undeclared swap stays undetected (declarations are the contract)
w = copy.deepcopy(swap(stages, "build_html", "jsdom")); next(s for s in w if s["id"] == "jsdom")["reads_prior_state"] = ["xtrail_dashboard.html"]
assert "jsdom" not in [v["stage"] for v in SO.lint(w, REPO, file_level=False)["violations"]]       # jsdom waived; the other readers of the dashboard still fire
print("PASS test_m650_stage_declarations (full lint %.0f s)" % secs)
