"""M375 known-answer tests for eligibility.py (single canonical-clean rule, analyses/M375_spec.md Rev 2): stop conditions on synthetic frames, the repo's known answers against the
script-written measurement (analyses/M375_eligibility_effect.json; nothing typed), and persistence of the 259-set definition through the real ingestion stage refresh_gtr_headline.py."""
import json, os, shutil, subprocess, sys, tempfile
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)
import eligibility as EL


def flags(rows):
    return pd.DataFrame(rows, columns=["file", "ens_outlier_v2", "ens_invalid"])


def raises(fn):
    try:
        fn()
    except EL.EligibilityError:
        return True
    return False


# ---- stop conditions (never treated as clean) ----
F = flags([("a", False, False), ("b", True, True), ("c", False, None), ("d", None, None), ("e", "True", "True"), ("f", False, True)])
assert raises(lambda: EL.excluded_files(F, ["a", "d"])), "a missing ens_outlier_v2 flag must stop"
assert raises(lambda: EL.excluded_files(F, ["a", "zzz"])), "a fuel drive without a drive_master row must stop"
assert raises(lambda: EL.excluded_files(F, ["a", "a"])), "duplicated fuel rows must stop"
assert raises(lambda: EL.excluded_files(F, ["a", "f"])), "ens_invalid / ens_outlier_v2 disagreement must stop"
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "dm.csv")
    pd.DataFrame({"file": ["x", "x"], "ens_outlier_v2": [False, False], "ens_invalid": [False, False]}).to_csv(p, index=False)
    assert raises(lambda: EL.load_flags(p)), "duplicated drive_master rows must stop"
# ---- the rule itself ----
assert EL.excluded_files(F, ["a", "b", "c", "e"]) == {"b", "e"}                  # explicit True of either flag excludes; NaN ens_invalid with a False outlier flag does not
assert EL.canonical_clean(["c", "a", "e", "b"], flags=F) == ["c", "a"]           # order kept

# ---- repo known answers from the script-written measurement ----
eff = json.load(open(os.path.join(ROOT, "analyses", "M375_eligibility_effect.json"), encoding="utf-8"))
fr = pd.read_csv(os.path.join(ROOT, "fuel_recon_master.csv"))
ex = EL.excluded_files(EL.load_flags(os.path.join(ROOT, "drive_master.csv")), fr["file"])
assert sorted(ex) == sorted(e["file"] for e in eff["sets"]["excludedByCanonical"]), "excluded set differs from the measurement"
assert len(fr) - len(ex) == eff["sets"]["canonicalCleanRows"]
import wire_gtr_seasonal as W
os.chdir(ROOT)
m = W.load_merged()
a = W.aggregate(m, "All", 489)
assert (a["nProduction"], a["nDrives"], a["kmProduction"]) == (eff["cohorts"]["all"]["canonical"]["nProduction"], eff["cohorts"]["all"]["canonical"]["nDrives"], eff["cohorts"]["all"]["canonical"]["kmProduction"])
a0 = W.aggregate(m, "All", 489, canonical=False)                                   # the pre-M375 definition stays reproducible (known answer of the measurement)
assert (a0["nProduction"], a0["nDrives"], a0["kmProduction"]) == (eff["cohorts"]["all"]["current"]["nProduction"], eff["cohorts"]["all"]["current"]["nDrives"], eff["cohorts"]["all"]["current"]["kmProduction"])
try:
    W.aggregate(m.drop(columns=["ens_excluded"]), "All", 489)
    raise SystemExit("aggregate() accepted a frame without the canonical flag")
except AssertionError:
    pass

# ---- persistence through the real ingestion stage ----
with tempfile.TemporaryDirectory() as td:
    for f in ("fuel_recon_master.csv", "seasonal_drive_master.csv", "drive_master.csv", "summary_arrays.json", "eligibility.py", "wire_gtr_seasonal.py", "refresh_gtr_headline.py"):
        shutil.copyfile(os.path.join(ROOT, f), os.path.join(td, f))
    r = subprocess.run([sys.executable, "refresh_gtr_headline.py"], cwd=td, capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, PYTHONUTF8="1"))
    assert r.returncode == 0, r.stderr[-500:]
    G = json.load(open(os.path.join(td, "summary_arrays.json"), encoding="utf-8"))["generatorTractionRecon"]
    assert (G["nProduction"], G["nDrives"], G["kmProduction"]) == (a["nProduction"], a["nDrives"], a["kmProduction"]), "the ingestion stage lost the canonical-clean definition"
    E = json.load(open(os.path.join(td, "summary_arrays.json"), encoding="utf-8"))["seasonalCharts"]["charts"]["GeneratorTractionRecon"]
    assert {k: E[k] for k in W.ENTRY_META} == W.ENTRY_META
print("test_eligibility: ok")
