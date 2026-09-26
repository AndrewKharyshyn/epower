#!/usr/bin/env python3
"""records_disclosure.py (M291, external audit Section 10 "record-object contract" / B8).

Attaches a machine-readable `disclosure` object to every entry in summary_arrays.json -> records,
ending the `sane_max` silent-drop: an extremum computed under a sanity/eligibility rule now carries
the rule, the number of drives that rule excluded (`excludedByCap`), and — when any were excluded —
the raw pre-cap extremum. On this corpus the only record with real exclusions is the OBD engine-load
peak, which reported 211.0 % while silently dropping 10 drives up to 1712.5 % (OBD Absolute Load PID
artefacts). Idempotent (re-attaches from the live drive_master.csv on every run); reads drive_master.csv
READ-ONLY and never changes any record's value or attribution.

Run AFTER _records() has populated summary_arrays.json (e.g. after compute_summary_arrays.py), like the
other records_*.py post-passes. The caps below mirror the sane_max/sane_min/abs_min caps in
compute_summary_arrays._records exactly; keep them in sync if a cap changes there.
"""
import json, os
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("XT_WORK") or (_HERE if os.path.exists(os.path.join(_HERE, "drive_master.csv")) else os.path.dirname(_HERE))

# metric-prefix -> (column, cap, direction, unit, note-on-the-channel)
CAPPED = [
    ("Peak engine load", "eng_load_abs_max", 300, "max", "%",
     "OBD Absolute Engine Load PID; values above the cap are sensor/PID artefacts"),
    ("Peak motor torque", "target_torque_max", 400, "max", "Nm", "target-torque channel"),
    ("Max speed", "speed_max", 200, "max", "km/h", "vehicle speed"),
    ("Battery temp (pack mean)", "T_pack_mean_max", 80, "max", "C", "pack-mean temperature"),
    ("Engine coolant peak", "T_eng_coolant_max", 120, "max", "C", "engine coolant"),
    ("HV coolant peak", "T_coolant_max", 120, "max", "C", "VCM/HV coolant loop"),
    ("Traction motor temperature", "T_motor_max", 130, "max", "C", "motor temperature"),
    ("Oil temperature peak", "T_oil_max", 150, "max", "C", "oil temperature"),
    ("Peak discharge current", "peak_I_discharge", 300, "max", "A", "discharge current"),
    ("Peak discharge power", "peak_discharge_kw", 150, "max", "kW", "discharge power"),
    ("Max engine speed", "eng_rpm_max", 7000, "max", "rpm", "engine rpm"),
    ("Peak boost", "boost_max", 3.0, "max", "bar", "boost pressure"),
    ("Peak intake manifold pressure", "map_kpa_max", 400, "max", "kPa", "manifold absolute pressure"),
    ("Battery intake air temperature max", "T_intake", 80, "max", "C", "intake-air temperature"),
    ("Largest single-drive throughput", "gross_throughput_kwh", 100, "max", "kWh", "per-drive gross throughput"),
    ("Maximum SoC", "soc_max", 100, "max", "%", "state of charge"),
    ("Deepest 80-120", "soc_band", 100, "max", "%", "engine-on discharge band share"),
    ("Highest moving-average speed", "speed_mean_moving", 200, "max", "km/h", "moving-average speed"),
]
# additional minimum-support / eligibility notes for pooled or gated records
SUPPORT = {
    "Most stationary": "eligible drives require distance_km > 0.5 km (excludes standstill-only logs)",
    "Lowest net battery draw": "SoC-neutral pool: |soc_delta_kwh| < 0.05 and net_draw > 0",
    "Longest 130+": "longest contiguous engine-on discharge run above 130 km/h; 0 s reported as unavailable",
    "Deepest 80-120": "requires >= 120 s of in-band time (M14 validity gate)",
}


def _cap_disclosure(dm, col, cap, direction, unit, chan_note):
    s = dm[col].dropna()
    if direction == "max":
        n_ex = int((s > cap).sum())
        kept = s[s <= cap]
        raw = float(s.max()) if len(s) else None
        keptx = float(kept.max()) if len(kept) else None
    else:  # min with a low cap
        n_ex = int((s < cap).sum())
        kept = s[s >= cap]
        raw = float(s.min()) if len(s) else None
        keptx = float(kept.min()) if len(kept) else None
    d = {
        "eligibilityRule": f"sanity cap: {col} {'<=' if direction=='max' else '>='} {cap} {unit} "
                           f"(physical-plausibility bound on {chan_note})",
        "column": col, "cap": cap, "nNonNull": int(len(s)),
        "excludedByCap": n_ex,
        "keptExtremum": round(keptx, 3) if keptx is not None else None,
    }
    if n_ex > 0:
        d["rawExtremum"] = round(raw, 3)
        d["excludedNote"] = (f"{n_ex} drive(s) with {col} "
                             f"{'up to' if direction=='max' else 'down to'} {round(raw,3)} {unit} "
                             f"excluded as out-of-range artefacts ({'>' if direction=='max' else '<'} {cap} {unit} cap); "
                             f"the reported record is the {direction} of the in-range values.")
    return d


AUDIT_ONLY = {
    "Lowest net battery draw": ("net draw on a SoC-neutral drive is a near-zero balance by construction and was retired "
                                "as an efficiency metric (M35); kept for audit only, not a battery-work or efficiency floor "
                                "(audit 2026-09-24 §7b)"),
}


def _winner_validity(dm, drive_label):
    """M295: resolve a record's winning drive label(s) to master rows and report canonical validity."""
    import records_resistance as RR
    files = list(dm.file)
    lab = {}
    for f in files:
        try:
            lab.setdefault(RR.drive_label(f, files), []).append(f)
        except Exception:
            pass
    parts = [p.strip() for p in str(drive_label or "").split("/") if p.strip()]
    hits = [f for p in parts for f in lab.get(p, [])]
    if not hits:
        return {"winnerValidity": "unresolved", "winnerFiles": []}
    bad = dm[dm.file.isin(hits)]
    inv = bad[(bad.ens_invalid.astype(str).str.lower() == "true") | (bad.ens_outlier_v2.astype(str).str.lower() == "true")]
    return {"winnerValidity": "canonically_invalid" if len(inv) else "canonical_clean",
            "winnerFiles": sorted(hits)}


def apply(arr, dm):
    recs = arr.get("records", [])
    for r in recs:
        metric = r.get("metric", "")
        disc = None
        for prefix, col, cap, direction, unit, chan_note in CAPPED:
            if metric.startswith(prefix) and col in dm.columns:
                disc = _cap_disclosure(dm, col, cap, direction, unit, chan_note)
                break
        if disc is None:
            disc = {"eligibilityRule": "corpus argmax/argmin over non-null drives; no plausibility cap "
                                       "applied (or cap not exceeded)", "excludedByCap": 0}
        for prefix, txt in SUPPORT.items():
            if metric.startswith(prefix):
                disc["minSupport"] = txt
        disc.update(_winner_validity(dm, r.get("drive")))
        for prefix, why in AUDIT_ONLY.items():
            if metric.startswith(prefix):
                r["auditOnly"] = True; disc["auditOnlyReason"] = why
        r["disclosure"] = disc
    arr["recordsContract"] = ("Every record carries a `disclosure` object: the eligibility/sanity rule, the count "
        "excluded by that rule (excludedByCap), and — when any were excluded — the raw pre-cap extremum "
        "(records_disclosure.py, audit B8). No extremum is reported without disclosing what its rule removed. "
        "M295: every record also states whether its winning drive is canonically clean (winnerValidity); a canonically "
        "invalid drive cannot win (builder eligibility), and conceptually weak extrema are flagged auditOnly.")
    # M235 artifact-stamp gate: every top-level key must be stamped. recordsContract is a derived,
    # corpus-invariant note; stamp it from the `records` stamp (same corpus identity) so build_html.js
    # accepts it without changing any corpus hash.
    import copy as _copy
    stamps = arr.get("_artifactStamps")
    if isinstance(stamps, dict) and "records" in stamps:
        st = _copy.deepcopy(stamps["records"])
        if isinstance(st, dict):
            st["computationStatus"] = "computed"
            st["computationStatusNote"] = "M291: records disclosure contract (records_disclosure.py, audit B8)."
        stamps["recordsContract"] = st
    return arr


if __name__ == "__main__":
    dm = pd.read_csv(os.path.join(WORK, "drive_master.csv"), low_memory=False)
    p = os.path.join(WORK, "summary_arrays.json")
    arr = json.load(open(p, encoding="utf-8"))
    arr = apply(arr, dm)
    json.dump(arr, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    flagged = [(r["metric"], r["disclosure"]["excludedByCap"], r["disclosure"].get("rawExtremum"))
               for r in arr["records"] if r.get("disclosure", {}).get("excludedByCap", 0) > 0]
    print("records:", len(arr["records"]), "| with disclosure:", sum("disclosure" in r for r in arr["records"]))
    print("records disclosing exclusions:", flagged)
