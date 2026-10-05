"""M377c known-answer tests (analyses/M377c_spec.md Rev 2): the ingestion-mode set rules of tools/m372_closure_common.py and the diff / splice rules of
tools/gtr_closure_refresh.py on synthetic data. Nothing is read from or written to the repository payload."""
import copy, hashlib, json, os, sys, tempfile
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import m372_closure_common as CM
import gtr_closure_refresh as R


def stops(fn):
    try:
        fn()
    except SystemExit as e:
        return str(e)
    return None


# ---- set rules ----
dm = pd.DataFrame({"file": ["a", "b", "c", "d"], "date": ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-03"], "distance_km": [1.0, 2.0, 3.0, 4.0],
                   "drive_type": ["urban"] * 4, "ens_outlier_v2": [False, False, False, False], "ens_invalid": [False, False, False, False]})
with tempfile.TemporaryDirectory() as td:
    prev = os.path.join(td, "prev.csv"); pd.DataFrame({"file": ["a", "b"], "x": [1.0, 2.0]}).to_csv(prev, index=False)
    rec = os.path.join(td, "rec.json")
    CM.RECORD = rec
    json.dump({"previousPerDrive": {"path": prev, "sha256": CM.sha256(prev)}}, open(rec, "w"))
    ok = CM.assert_expected_set(["a", "b", "c"], dm)
    assert ok["nNew"] == 1 and ok["newIds"][0]["file"] == "c" and ok["nPrevious"] == 2 and ok["nDays"] == 2
    assert "no longer eligible" in stops(lambda: CM.assert_expected_set(["a", "c"], dm)), "a missing previous ID must STOP"
    dm_bad = dm.copy(); dm_bad.loc[dm_bad.file == "c", "ens_outlier_v2"] = True
    assert "ineligible" in stops(lambda: CM.assert_expected_set(["a", "b", "c"], dm_bad)), "a canonical-flagged new ID must STOP"
    open(prev, "a").write("a,9.0\n")                                          # the pinned previous file changes -> sha256 mismatch
    assert "sha256 differs" in stops(lambda: CM.assert_expected_set(["a", "b"], dm))
    json.dump({"previousPerDrive": {"path": os.path.join(td, "gone.csv"), "sha256": "0"}}, open(rec, "w"))
    assert "missing" in stops(lambda: CM.assert_expected_set(["a", "b"], dm))
    # previous-ID identity
    old = pd.DataFrame({"file": ["a", "b"], "x": [1.0, 2.0], "t": ["u", "u"]})
    cur = pd.DataFrame({"file": ["a", "b", "c"], "x": [1.0, 2.0, 5.0], "t": ["u", "u", "u"]})
    assert CM.assert_previous_identity(cur, old)["nIdentical"] == 2
    cur2 = cur.copy(); cur2.loc[0, "x"] = 1.5
    assert "differ" in stops(lambda: CM.assert_previous_identity(cur2, old))
# flags
assert CM.assert_flags_equal(dm)["nDiverging"] == 0
dm_div = dm.copy(); dm_div.loc[0, "ens_invalid"] = True
assert "diverge" in stops(lambda: CM.assert_flags_equal(dm_div))

# ---- diff rules ----
OLD = {"scope": {"nDrives": 257, "nDays": 50, "excludedNoBatteryInputs": ["x"]}, "fGen": {"est": 0.45, "ci95": [0.40, 0.50], "ciContains0p5": True},
       "per100km": {"generator": 15.0, "tiny": 0.05}, "strata": {"urban": {"excess_rel": {"est": 0.01, "ci95": [-0.02, 0.04], "closed": True}}, "mixed": {"excess_rel": "n<10: not evaluated"}}}
def new(f):
    n = copy.deepcopy(OLD); f(n); return n
def rules(n):
    d = R.diff_blocks(OLD, n); return {s["rule"] for s in d["stops"]}, {e["rule"] for e in d["escalations"]}, d

st, es, d = rules(copy.deepcopy(OLD)); assert not st and not es and d["summary"]["nCiChecked"] == 2
st, _, _ = rules(new(lambda n: n["fGen"].update(est=0.55))); assert "estimate outside previous 95% CI" in st
st, _, _ = rules(new(lambda n: n["fGen"].update(ciContains0p5=False))); assert "flag/verdict flip" in st
st, _, _ = rules(new(lambda n: n["fGen"].pop("ciContains0p5"))); assert "key-set difference" in st
st, _, _ = rules(new(lambda n: n["strata"]["mixed"].update(excess_rel={"est": 0.0, "ci95": [-0.1, 0.1]}))); assert any("type change" in s for s in st)
st, _, _ = rules(new(lambda n: n["scope"].update(excludedNoBatteryInputs=["x", "y"]))); assert not st, "documentation lists may change length"
def lst(n): n["per100km"]["l"] = [1]; 
st, _, _ = rules(new(lambda n: n["scope"].update(nDrives=294, nDays=54))); assert not st
_, es, _ = rules(new(lambda n: n["scope"].update(nDays=70))); assert "n_days changed by more than 20%" in es
_, es, d = rules(new(lambda n: n["per100km"].update(generator=15.5))); assert not es and d["pointOnly"][0]["withinBand"]              # 3.3 % move: reported only
_, es, _ = rules(new(lambda n: n["per100km"].update(generator=17.0))); assert any("escalation band" in e for e in es)               # 13 % move
_, es, _ = rules(new(lambda n: n["per100km"].update(tiny=0.07))); assert any("escalation band" in e for e in es)                    # |prev| < 0.1: absolute 0.01 band, move 0.02


# ---- Rev 3: count-of-drives leaves compared as shares of the set size ----
OLDC = {"scope": {"nDrives": 257, "nDays": 50}, "alphaStar": {"nInfeasibleDrivesBaseline": 15, "nVariants": 23}}
def newc(nd, ninf, nvar=23): return {"scope": {"nDrives": nd, "nDays": 54}, "alphaStar": {"nInfeasibleDrivesBaseline": ninf, "nVariants": nvar}}
d3 = R.diff_blocks(OLDC, newc(292, 18)); assert not d3["escalations"], "15/257 -> 18/292 is a share move inside the band"
assert any(p.get("comparedAs") == "share of set size" for p in d3["pointOnly"])
d3 = R.diff_blocks(OLDC, newc(292, 40)); assert any("count leaf" in e["rule"] for e in d3["escalations"]), "a share jump must escalate"
d3 = R.diff_blocks(OLDC, newc(292, 15, nvar=40)); assert any(e["path"].endswith("nVariants") for e in d3["escalations"]), "non-drive counts keep the plain rule"

# ---- splice allow-list ----
A = {"generatorTractionRecon": {"gtrClosure": {"x": 1}, "staleBlocks": {"blocks": ["crossval", "gtrClosure"], "perBlock": [{"block": "crossval"}, {"block": "gtrClosure"}]}, "other": 1}, "meta": {"n": 1}}
nw = R.splice_plan(A, {"x": 2})
assert nw["generatorTractionRecon"]["staleBlocks"]["blocks"] == ["crossval"] and nw["generatorTractionRecon"]["gtrClosure"] == {"x": 2}
assert R.allow_check(A, nw) == []
nw["meta"]["n"] = 2
assert R.allow_check(A, nw) == ["/meta/n"]

# ---- one-time re-pin (Director ruling; stated deviation from spec Rev 2 item 1) ----
with tempfile.TemporaryDirectory() as td:
    old_root, old_rec = CM.ROOT, CM.RECORD
    CM.ROOT, CM.RECORD = td, os.path.join(td, "rec.json")
    prev = pd.DataFrame({"file": ["a", "b"], "x": [1.0, 2.0]})
    cur = pd.DataFrame({"file": ["a", "b", "c"], "x": [1.00001, 2.0, 7.0]})
    rec = {"path": "analyses/old.csv", "sha256": "0"}
    new_rec = CM.repin_previous(cur, prev, rec, "test reason")
    CM.ROOT, CM.RECORD = old_root, old_rec
    pinned = pd.read_csv(os.path.join(td, new_rec["previousPerDrive"]["path"]))
    assert list(pinned["file"]) == ["a", "b"] and abs(pinned["x"][0] - 1.00001) < 1e-9, "the pin holds the previous IDs only, on the new values"
    assert new_rec["repinnedFrom"] == rec and new_rec["repinReason"] == "test reason"
    assert new_rec["previousPerDrive"]["sha256"] == hashlib.sha256(open(os.path.join(td, new_rec["previousPerDrive"]["path"]), "rb").read()).hexdigest()
print("test_gtr_closure_refresh: OK")
