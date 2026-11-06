"""M585 (analyses/M585_spec.md Rev 1; M582b): regime_reader boundaries and missing-value behaviour, agreement with the sidecar on the pinned master, the migrated consumers' regime functions,
and the tripwire: no float in [1.0, 1.2] is compared with a period expression outside tools/regime_reader.py (AST), no literal assigned to a FAST* constant, exactly one documented allowlist entry."""
import ast, hashlib, os, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import regime_reader as RR

# ---- boundaries (strict '<' for fast, guard zone STOP, missing -> None)
assert RR.THRESHOLD_S == 1.10 and RR.GUARD_ZONE == (1.06, 1.135)
assert RR.regime_of(0.8) == "fast" and RR.regime_of(1.059) == "fast" and RR.regime_of(1.135) == "slow" and RR.regime_of(1.2) == "slow"
for bad in (1.06, 1.0999, 1.10, 1.134):
    try:
        RR.regime_of(bad)
    except SystemExit as e:
        assert "guard zone" in str(e)
    else:
        raise AssertionError("inside the guard zone must STOP: %r" % bad)
assert RR.regime_of(None) is None and RR.regime_of(float("nan")) is None
assert RR.slow_flag(1.2) == 1.0 and RR.slow_flag(0.9) == 0.0 and RR.slow_flag(float("nan")) != RR.slow_flag(float("nan")) and RR.slow_flag(None, missing=0.0) == 0.0

# ---- cadence_regime delegates to the reader; the migrated consumers expose the same constants
import cadence_regime as CR
assert CR.THRESHOLD_S == RR.THRESHOLD_S and CR.GAP == RR.GUARD_ZONE and all(CR.classify(p) == RR.regime_of(p) for p in (0.7, 0.99, 1.05, 1.059, 1.135, 1.5, None))
import timing_support as TS, dependence_sensitivity as DS
assert TS.FAST_SLOW_S == RR.THRESHOLD_S and DS.FAST_S == RR.THRESHOLD_S

# ---- tie-out to the sidecar on the pinned master (fixture), not live counts
if hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest() == "1574a8156a36c6ea4ea1dfdaafc7cc72":
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    side = pd.read_csv("cadence_regime.csv").set_index("file")["regime"]
    got = dm.set_index("file")["I_sample_period_s"].map(RR.regime_of)
    assert all((got[f] if isinstance(got[f], str) else None) == (side[f] if isinstance(side[f], str) else None) for f in got.index)
    assert got.value_counts().to_dict() == {"slow": 424, "fast": 196} and int(got.isna().sum()) == 12
    assert [f for f in dm["file"] if RR.regime_of(dm.set_index("file")["I_sample_period_s"][f]) == "fast" and dm.set_index("file")["I_sample_period_s"][f] >= 1.05] == ["2026-11-04_08-01-15.csv"]

# ---- tripwire (AST): a float constant in [1.0, 1.2] compared with an expression that mentions the sampling period, outside the reader
ALLOWED_FILES = {"regime_reader.py", "m585_difference_sets.py", "m585_controls.py"}
hits, lits = [], []
for fn in sorted(os.listdir("tools")):
    if not fn.endswith(".py") or fn in ALLOWED_FILES:
        continue
    src = open(os.path.join("tools", fn), encoding="utf-8").read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            parts = [node.left] + list(node.comparators)
            consts = [p for p in parts if isinstance(p, ast.Constant) and isinstance(p.value, float) and 1.0 <= p.value <= 1.2]
            others = [p for p in parts if not (isinstance(p, ast.Constant))]
            if consts and any(("i_sample_period" in ast.unparse(o).lower()) for o in others):
                hits.append("%s:%d %s" % (fn, node.lineno, ast.unparse(node)[:80]))
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, float) and 1.0 <= node.value.value <= 1.2:
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and __import__("re").search(r"(FAST|SLOW|REGIME|THRESHOLD).*_S$", tgt.id.upper()):
                    lits.append("%s:%d %s = %s" % (fn, node.lineno, tgt.id, node.value.value))
assert not hits, hits
assert not lits, lits
# M593: no allowlisted exception remains; the builder constant equals the single source (read from the source text, the module is not imported)
assert CR.ALLOWLIST == [] and CR.v6_cut() == RR.THRESHOLD_S
print("test_regime_reader: OK")
