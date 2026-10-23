"""M489 known-answer tests (audit Update 7 A05, A07, A09): (A05) the dependency-closure hash changes when a shared helper, a constant or an imported repository module changes, and the real pair-cache / regen-cache
closures reach the helpers the audit named; (A07) the replay identities flag an isolated corruption in a LATE row (beyond the first 12 differing files) and a rebuilt value that does not follow the frozen offset or the
distance repair, and the committed full report passes; (A09) a missing regen-cache entry or raw directory is a named failure."""
import copy, importlib, json, os, sys, tempfile, textwrap
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import dep_hash

# ---- A05: closure hash semantics on a throw-away package inside the repository root (so _in_repo holds)
tmpd = tempfile.mkdtemp(dir=ROOT, prefix="_m489_tmp_")
sys.path.insert(0, tmpd)
base = os.path.basename(tmpd)
def write(name, src):
    open(os.path.join(tmpd, name), "w", encoding="utf-8").write(textwrap.dedent(src))
def load(modname):
    for m in [m for m in sys.modules if m in (modname, "helper_m489")]:
        del sys.modules[m]
    importlib.invalidate_caches()
    return importlib.import_module(modname)
write("helper_m489.py", "K = 3\ndef shared(x):\n    return x + K\n")
write("root_m489.py", "import helper_m489 as H\nLIMIT = 5\ndef extract(x):\n    return H.shared(x) * LIMIT\n")
def hash_now():
    m = load("root_m489"); h = load("helper_m489")
    return dep_hash.closure_hash([m.extract], modules=(h,))
try:
    h0 = hash_now()
    assert h0 == hash_now(), "hash must be deterministic"
    write("helper_m489.py", "K = 3\ndef shared(x):\n    return x + K + 0\n")           # helper body changes
    h1 = hash_now(); assert h1 != h0, "a changed shared helper must change the hash"
    write("helper_m489.py", "K = 4\ndef shared(x):\n    return x + K + 0\n")             # constant changes
    h2 = hash_now(); assert h2 != h1, "a changed helper constant must change the hash"
    write("root_m489.py", "import helper_m489 as H\nLIMIT = 6\ndef extract(x):\n    return H.shared(x) * LIMIT\n")   # root constant changes
    h3 = hash_now(); assert h3 != h2, "a changed root constant must change the hash"
    assert dep_hash.closure_hash([load("root_m489").extract], modules=(load("helper_m489"),), extra={"v": 1}) != dep_hash.closure_hash([load("root_m489").extract], modules=(load("helper_m489"),), extra={"v": 2}), "schema/extra must be keyed"
finally:
    sys.path.remove(tmpd)
    for f in os.listdir(tmpd):
        os.remove(os.path.join(tmpd, f))
    os.rmdir(tmpd)

# the real closures reach what the audit named
import compute_drive_summary_v6 as D
import pair_cache as P
funcs, consts, files = dep_hash.closure([P.pairs_from_bytes], modules=(D,))
names = {k.split(".")[-1] for k in funcs}
assert {"_prep_bytes", "_series", "_asof", "pairs_from_bytes"} <= names, names
h_a = P.extractor_hash(); assert h_a == P.extractor_hash()
import regen_v2_cache as K
import compute_summary_arrays as C, drive_raw_cache as drc
f2, c2, _ = dep_hash.closure([K.R.extract_drive, drc.make_frame_loader], modules=(C, drc))
n2 = {k.split(".")[-1] for k in f2}
assert {"extract_drive", "_apply_speed_priority", "fast_time", "make_frame_loader"} <= n2, n2
assert any(k.endswith(".RAW_MAP") for k in c2) or any(k.endswith("RAW_MAP") for k in map(str, c2)) or "RAW_MAP" in " ".join(f2.values()), "RAW_MAP must be inside the regen closure"
assert "closureSrc" in K.code_hashes()

# ---- A07: identities on synthetic frames
import replay_master as R
def frames(n=20, corrupt=None, dI=-0.0002):
    idx = ["f%02d.csv" % i for i in range(n)]
    V = np.full(n, 330.0); h = np.full(n, 0.5); dist = np.full(n, 10.0)
    off_pub = np.round(-0.387 * V * h / 1000, 4)
    ref = pd.DataFrame({"file": idx, "I_offset_2p_A_applied": -0.387, "V_pack_median": V, "integr_time_h": h, "duration_s": h * 3600, "distance_km": dist,
                        "distance_reset_repaired": ["True"] + ["False"] * (n - 1), "distance_endpoint_raw_km": [13.0] + [np.nan] * (n - 1),
                        "offset_2p_kwh_removed": off_pub, "net_draw_kwh_corr2p": 5.0 - off_pub, "energy_residual_kwh_corr2p": 1.0 - off_pub,
                        "net_draw_per100km_corr2p": np.round((5.0 - off_pub) / dist * 100, 2)}).set_index("file", drop=False).astype(str)
    chk = ref.copy()
    new_off = np.round((-0.387 + dI) * V * h / 1000, 4)
    chk["I_offset_2p_A_applied"] = str(-0.387 + dI)
    chk["offset_2p_kwh_removed"] = new_off.astype(str)
    chk["net_draw_kwh_corr2p"] = (5.0 - new_off).astype(str)
    chk["energy_residual_kwh_corr2p"] = (1.0 - new_off).astype(str)
    chk["net_draw_per100km_corr2p"] = np.round((5.0 - new_off) / dist * 100, 2).astype(str)
    chk.loc["f00.csv", "distance_km"] = "13.0"
    if corrupt:
        chk.loc[corrupt[0], corrupt[1]] = str(float(chk.loc[corrupt[0], corrupt[1]]) + corrupt[2])
    return ref, chk
ref, chk = frames()
ok = R.identities(ref, chk, {"distance_km": {"filesAll": ["f00.csv"]}})
assert not any(ok["offsetIdentityFailures"].values()) and ok["distanceIdentityFailures"] == [] and ok["distanceDerivedOutsideRepaired"] == [], ok
# an isolated corruption in the LAST row, far beyond a 12-example list, is found
ref, chk = frames(n=40, corrupt=("f39.csv", "net_draw_kwh_corr2p", 0.01))
bad = R.identities(ref, chk, {})
assert bad["offsetIdentityFailures"]["net_draw_kwh_corr2p"] == ["f39.csv"], bad["offsetIdentityFailures"]
ref, chk = frames(n=40, corrupt=("f37.csv", "offset_2p_kwh_removed", -0.02))
assert R.identities(ref, chk, {})["offsetIdentityFailures"]["offset_2p_kwh_removed"] == ["f37.csv"]
ref, chk = frames(n=40, corrupt=("f38.csv", "net_draw_per100km_corr2p", 0.5))
assert R.identities(ref, chk, {})["offsetIdentityFailures"]["net_draw_per100km_corr2p"] == ["f38.csv"]
# the distance repair identity: the rebuilt distance must equal the published endpoint value
ref, chk = frames(); chk.loc["f00.csv", "distance_km"] = "14.0"
assert R.identities(ref, chk, {"distance_km": {"filesAll": ["f00.csv"]}})["distanceIdentityFailures"] == ["f00.csv"]
# a distance-derived column that differs on a non-repaired row is reported
ref, chk = frames()
assert R.identities(ref, chk, {"distance_km": {"filesAll": ["f00.csv", "f07.csv"]}})["distanceDerivedOutsideRepaired"] == ["f07.csv"]

# ---- A07: the committed full report passes its own check and the check fails on a late hidden row / failed identity / old report
good = json.load(open(os.path.join(R.D, "replay_report_full.json"), encoding="utf-8"))
assert R.check_expected(good) == [], R.check_expected(good)
def mutate(f):
    x = copy.deepcopy(good); f(x); return R.check_expected(x)
elig_free = "z_not_eligible_late_row.csv"
assert mutate(lambda x: x["columnsDiffering"]["offset_2p_kwh_removed"].update(filesAll=x["columnsDiffering"]["offset_2p_kwh_removed"]["filesAll"] + [elig_free])), "a late row outside the eligible set must fail"
assert mutate(lambda x: x["identities"]["offsetIdentityFailures"].update({"net_draw_kwh_corr2p": ["a.csv"]})), "a failed offset identity must fail"
assert mutate(lambda x: x["identities"].update(distanceIdentityFailures=["20260906_122920.csv"])), "a failed distance identity must fail"
assert mutate(lambda x: x.pop("identities")), "a report without identities must fail"
assert mutate(lambda x: [d.pop("filesAll") for d in x["columnsDiffering"].values()]), "a report without the full row list must fail"

# ---- A09: a missing cache entry or raw directory is a named failure
with tempfile.TemporaryDirectory() as td:
    old_dir, old_raw = K.CACHE_DIR, K.raw_dir
    K.CACHE_DIR = td
    try:
        try:
            K.load(["x.csv"], "base"); raise SystemExit("missing cache entry accepted")
        except K.CacheAbsentError as e:
            assert "regen cache entry missing" in str(e) and "regen_v2" in str(e)
        K.raw_dir = lambda: os.path.join(td, "no_such_raw")
        try:
            K.ensure(["x.csv"], -0.38); raise SystemExit("missing raw directory accepted")
        except K.CacheAbsentError as e:
            assert "raw directory not found" in str(e)
    finally:
        K.CACHE_DIR, K.raw_dir = old_dir, old_raw
print("test_m489_hardening OK")
