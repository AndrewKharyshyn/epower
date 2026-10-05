"""M382 (audit 2026-10-05): the replaced statements are forbidden by the language gate (known-answer: the OLD wording hits, the NEW wording does not)
and the producers bind the facts the old text contradicted."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

OLD = {
    "M382-F01-nooriginals": "No original bytes are available (F02): the cause is inferred, not shown",
    "M382-F01-archivediffers": "the raw archive held in this repository differs from the originals for 333 of 489 canonical files",
    "M382-F02-identical": "reproduces the canonical exclusion sets (ens_invalid, ens_outlier_v2) with identical file identities",
    "M382-F02-purefunction": "so every group statistic that filters on ens_outlier_v2 is a pure function of current inputs",
    "M382-F03-zeroenergy": "they contribute literal 0.0 kWh gross throughput at the released tolerance",
    "M382-F08-rpm22": "RPM has ~22% missing samples (sensor polling rate)",
    "M382-F08-1hz": "OBD-II / ELM327 CSV logs, ~1 Hz, resampled to a uniform 1-second grid",
    "M382-F09-onepass": "totals were reprocessed from raw logs in one pass with the v6 pipeline",
    "M382-F09-everyfile": "charge-positive sign convention verified via torque co-check on every file carrying the HV-current PID",
}
NEW = ["The determinism check re-runs the ML16 exclusion stage twice on the current master; the canonical sets reproduce by file identity (seed-stability only).",
       "Historical block: when this rebuild ran no original bytes were available; raw/ now holds the originals.",
       "These are tolerance sensitivities of drives that carry non-zero released energy, not zero-energy files."]
rules = {r.rid: r for r in G.RULES}
for rid, text in OLD.items():
    assert rid in rules and rules[rid].hits(text), rid
for text in NEW:
    assert not any(r.hits(text) for rid, r in rules.items() if rid.startswith("M382-")), text

# producers: F03 finding is generated from nominal energy, never asserts zero
import energy_uncertainty_mc as MC
f = MC.data_quality_finding(0.077, [{"file": "a.csv", "nominalKwh_1500ms": 9.905, "deltaKwh_1500to2000ms": 0.0376, "cumulativePctOfTotalWidening": 49.0},
                                    {"file": "b.csv", "nominalKwh_1500ms": 2.9667, "deltaKwh_1500to2000ms": 0.0183, "cumulativePctOfTotalWidening": 72.8}])
assert "9.905" in f and "2.9667" in f and "0.38%" in f and "0.62%" in f and "72.8%" in f and not rules["M382-F03-zeroenergy"].hits(f)
assert "no drive" in MC.data_quality_finding(0.0, []).lower()

# stamp note: a refreshed closure is not described as carried; a carried one names its basis
sys.path.insert(0, os.path.join(ROOT, "tools"))
from stamp_notes import gtr_stamp_note
A = {"meta": {"totalDrives": 10}, "generatorTractionRecon": {"nDrives": 8, "refreshedBlocks": [], "staleBlocks": {"perBlock": []},
     "gtrClosure": {"scope": {"nDrives": 7, "nDays": 3, "nCanonical": 10}}}}
n = gtr_stamp_note(A, "MX")
assert "gtrClosure recomputed on the live corpus (7 drives, 3 days)" in n and "carried at the" not in n
A["generatorTractionRecon"]["gtrClosure"]["scope"]["carriedAtIngestion"] = {"milestone": "M372", "basisNDrives": 5}
n = gtr_stamp_note(A, "MX")
assert "gtrClosure numbers carried at the M372 set (5 drives" in n

# eligibility: EV census predicate = ev_valid AND canonical-clean; dataCoverage categories sum to the corpus
import pandas as pd, compute_summary_arrays as C
dm = pd.DataFrame({"file": list("abcd"), "date": ["d1", "d1", "d2", "d2"], "distance_km": [1.0, 2.0, 3.0, 4.0],
                   "ens_outlier_v2": [False, True, False, False], "ev_valid": [True, True, False, True],
                   "drive_type": ["urban"] * 4, "deficit_80_120_valid": [False] * 4, "vreg_R_pack_mohm": [1.0] * 4,
                   "vsag_R_pack_mohm": [1.0] * 4, "cell_spread_loaded_p95_adj_mv": [1.0] * 4, "gross_throughput_kwh": [1.0] * 4,
                   "n_I_samples": [5] * 4, "sign_check": ["ok", "not_testable", None, "ok"], "ev_cov_rpm": [1.0, 0.5, 1.0, 0.95],
                   "ev_rpm_dt_med_s": [1.0, 1.5, 1.2, 1.0], "I_sample_period_s": [1.0, 1.0, None, 2.0]})
e = C._audit_eligibility(dm)
ev = next(x for x in e["families"] if x["family"].startswith("EV traction census"))
assert ev["n"] == 2 and ev["km"] == 5.0, ev            # rows a and d: ev_valid and clean (b is an outlier, c is not ev_valid)
sc = e["dataCoverage"]["signCheck"]
assert (sc["ok"], sc["notTestable"], sc["missing"], sc["anomaly"], sc["total"]) == (2, 1, 1, 0, 4)
assert e["dataCoverage"]["rpm"]["gridCoverage"]["nBelow90pct"] == 1 and e["dataCoverage"]["currentPid"]["updateIntervalS"]["n"] == 3
print("OK test_m382_wording")
