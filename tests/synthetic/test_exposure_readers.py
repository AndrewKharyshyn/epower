"""M414 grep gate (spec analyses/M413_spec.md Rev 1): every Python file that reads the exposure columns (gtc, fce, cap_ah_est, *_Crate, efc_per100km) is either ROUTED through tools/exposure_frame.py
or declared LEGACY_BY_DESIGN with a reason. A new direct reader that is in neither list fails this test, so a silent legacy leftover cannot appear at the flip (M415)."""
import os, re, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)

PAT = re.compile(r"""['"](gtc|fce|cap_ah_est|dual_peak_Crate|regen_peak_Crate|eng_charge_peak_Crate|efc_per100km)['"]|\.(gtc|fce)\b""")
# M415: files that call the arrays producers on a master frame read the exposure columns indirectly
CALLERS = re.compile(r"\b(category_A|category_B)\(")
ROUTED = {"compute_summary_arrays.py": "build_summary_arrays: exposure_frame() at the single substitution point", "cohort_arrays.py": "row_overrides() for the C-rate extras",
          "compute_seasonal.py": "row_overrides() for the seasonal-master gtc", "tools/regime_stratified.py": "exposure_frame()", "tools/extend_session_ledgers.py": "exposure_frame()",
          "tools/m368_ledger_round.py": "exposure_frame(), pinned legacy (ledger prose stays legacy)", "tools/exposure_frame.py": "the shared function itself",
          "records_rainflow.py": "exposure_frame() in its main path (coulometric FCE in the record note)", "m296_refresh_master_seasonal.py": "exposure_frame() before category_A on the cohort subsets",
          "tools/regen_seasonal_raw.py": "exposure_frame() and the basis in every cache key",
          "tools/highway_session_gtc.py": "exposure_frame(dm, RATED) gross_throughput_ah, unrounded Ah per date (M488)",
          "tools/exposure_basis_refresh.py": "exposure_frame(dm, 'legacy2p1kWh') for the legacy disclosure values of the exposureBasis block (M423)"}
LEGACY_BY_DESIGN = {
    "compute_drive_summary_v6.py": "producer of the legacy master columns (the master is never rewritten)",
    "energy_uncertainty_mc.py": "Q2: the energy Monte Carlo draws are kWh / 2.1 and stay legacy, labelled",
    "ingest_e4orce.py": "e4orce leg of the cross-vehicle comparison stays legacy until an e4orce Ah sidecar exists",
    "crosscheck_vehicles.py": "cross-vehicle comparison, both legs legacy",
    "sustained_current_peaks.py": "standalone probe, not in the summary payload",
    "classify_all_columns.py": "column documentation / classification only",
    "tools/m358_splice.py": "retired one-off splice (asserts C == A / cap_ah_est on the legacy basis)",
    "tools/cadence_sensitivity.py": "cadence monitors compare same-basis emulated frames; key names only",
    "tools/cadence_regime.py": "cadence monitors compare same-basis emulated frames; key names only",
    "tools/cadence_emulate.py": "cadence monitors compare same-basis emulated frames; key names only",
    "test_seasonal.py": "test",
    "semantic_gate.py": "release gate: independent recomputation from the master and the Ah sidecar (never routed through the function it checks)",
    "tools/exposure_splice.py": "splice tool: operates on control-build outputs; exposure column names appear only in comments/labels",
    "tools/m384_parity_diag.py": "read-only diagnostic of non-exposure blocks (CrawlStopGo, EngineStartsByType)",
}
sys.path.insert(0, os.path.join(os.getcwd(), "tools"))
from source_inventory import tracked_py       # M427 (audit F30): git ls-files in a checkout, a directory scan in a zip export
files = tracked_py(os.getcwd())
skip = ("analyses/", "runs/", "tests/", "tabtext/")
readers = []
for f in files:
    if f.startswith(skip) or not os.path.exists(f):
        continue
    src_ = open(f, encoding="utf-8", errors="replace").read()
    if PAT.search(src_) or (f != "compute_summary_arrays.py" and CALLERS.search(src_)):
        readers.append(f)
unlisted = sorted(set(readers) - set(ROUTED) - set(LEGACY_BY_DESIGN))
assert not unlisted, "new direct reader(s) of the exposure columns: %r (route through tools/exposure_frame.py or add to LEGACY_BY_DESIGN with a reason)" % unlisted
for f in ROUTED:
    src = open(f, encoding="utf-8", errors="replace").read()
    assert ("exposure_frame" in src), f + ": declared routed but does not use exposure_frame"
stale = sorted((set(ROUTED) | set(LEGACY_BY_DESIGN)) - set(readers) - {"tools/exposure_frame.py"})
assert not stale, "listed but no longer a reader (remove from the lists): %r" % stale
print("OK test_exposure_readers (%d routed, %d legacy-by-design)" % (len(ROUTED), len(LEGACY_BY_DESIGN)))
