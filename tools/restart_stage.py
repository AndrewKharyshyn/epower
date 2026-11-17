#!/usr/bin/env python3
"""M711 (spec analyses/M708_spec.md Rev 2, sections 7 and 9): ingestion stage `restart_census`. Recomputes the restart / post-drive pack-temperature census (tools/restart_census.py), the one-state park model
(tools/park_model.py) and the winter-protocol tables on the live corpus and splices ONE additive top-level key, `restartTemperature`, into summary_arrays.json together with its artifact stamp.

At every ingestion: E1 restart change by gap class (flagged unlogged-use pairs kept; the without-flags table beside it; previous-day-cluster sensitivity), the winter-only and the 4-12 h-only tables (condition by the
reconstructed day-mean ambient of the restart day below 10 C, or the vehicle-sensor reading at the restart after a gap of 4 h or more below 10 C; uncalibrated, model-derived; floor 10 pairs on 5 days, else
"not evaluable"; never pooled across thermal classes), E5 (ledger start composite vs the native start by logger regime), the park model with and without the flagged legs, and the cold / warm threshold counts.
Reproduction gates P-R0 / P-R1 / P-R5 of M708 are evaluated ONLY on the frozen 665-drive basis (analyses/M708_targets.json); on a grown corpus the new data fall under the standing rule: an estimate outside its previous
interval is a FLAG (printed and recorded in the block, never a stop) for the Director. P-R3b and the contamination direction of P-R4 are re-evaluated at every refresh; the two-state gate P-R2 is not evaluated
(open item). Logged BMS readings are "logged"; quantities from the park model are "estimated / model-derived", never "measured".
Usage: python tools/restart_stage.py [--dry-run] [--check] [--raw-dir DIR] [--workers N]     (--check: the spliced block equals nothing stale: masters and source hashes match)"""
import argparse, copy, datetime, hashlib, json, os, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import restart_census as RC
import park_model as PM
import restart_gates as RG

KEY = "restartTemperature"
TARGETS = "analyses/M708_targets.json"
BASIS_DRIVES = 665


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def conditions(D):
    """Pair masks of the winter protocol (spec M708 section 9). D = model_frame (pair table + ambient reconstruction)."""
    recon = D["n_Abar_s"] < 10                                            # reconstructed day-mean ambient (diurnal term removed) at the restart drive
    reading = (D["gap_h"] >= 4) & (D["n_A0"] < 10)                       # recorded vehicle-sensor ambient at the restart after a gap of 4 h or more
    winter = (recon | reading).fillna(False)
    return {"winterOnly": (winter, "restart ambient below 10 C: reconstructed day-mean ambient of the restart day, or the recorded vehicle-sensor reading at the restart after a gap of 4 h or more (uncalibrated)"),
            "gap4to12h": ((D["gc"] == "4-12 h"), "gap class 4-12 h (the class with the largest share of pairs carrying evidence of unlogged use)")}


def build_block(E, P, previous=None):
    res, E5 = RC.build_result(E, P)
    D, par = PM.model_frame(E, P)
    park = PM.evaluate(E, P, None)
    conds = {k: RC.condition_table(D, m, lab) for k, (m, lab) in conditions(D).items()}
    ex = res["exclusions"]
    # reproduction gates on the frozen basis only
    repro = {"basis": "analyses/M708_targets.json (665-drive basis, exploratory targets, unaudited)", "evaluated": False}
    if res["nDrives"] == BASIS_DRIVES:
        with tempfile.TemporaryDirectory() as td:
            RC.write_outputs(td, E, P, res, E5)
            g = RG.evaluate(td)
        repro = {"basis": repro["basis"], "evaluated": True, "gates": {k: {"pass": v["pass"]} for k, v in g.items()}, "detail": g}
    cls = ["<10 min", "10-60 min", "1-4 h", "4-12 h", ">=12 h", "<1 h", "all gaps"]
    flags = []
    if previous:
        for c in cls:
            new, old = res["E1_primary_flaggedKept"][c]["meanChange"], previous["E1_primary_flaggedKept"][c]["meanChange"]
            if new["est"] is not None and old["lo"] is not None and not (old["lo"] <= new["est"] <= old["hi"]):
                flags.append("E1 %s: mean change %.3f C outside its previous interval [%.3f, %.3f]" % (c, new["est"], old["lo"], old["hi"]))
        if res["E1_primary_flaggedKept"]["<1 h"]["nGe2Pairs"] > 0:
            flags.append("E1 <1 h: %d pair(s) with a 4-probe-mean rise of 2 C or more (falsifier of the spec: check the raw probe rows)" % res["E1_primary_flaggedKept"]["<1 h"]["nGe2Pairs"])
        pm_old = previous.get("parkModel", {}).get("M2_fullSample_nonFlagged")
        if pm_old and not (pm_old["tauCi"][0] <= park["M2_fullSample_nonFlagged"]["tau_h"] <= pm_old["tauCi"][1]):
            flags.append("park model tau %.3f h outside its previous interval %s" % (park["M2_fullSample_nonFlagged"]["tau_h"], pm_old["tauCi"]))
    g = park["gates"]
    if g["P-R4"]["contaminationDirection"]["pass"] is False:
        flags.append("P-R4: the flagged-kept refit no longer shows the contamination direction (lower tau, higher offset)")
    if g["P-R3b"]["pass"] is False:
        flags.append("P-R3b: the park model no longer beats persistence by the pre-registered margins")
    blk = {
        "milestone": "M711", "spec": "analyses/M708_spec.md", "specSha256": sha("analyses/M708_spec.md"), "targetsSha256": sha(TARGETS), "masterMd5": res["masterMd5"], "nDrives": res["nDrives"],
        "scriptSha256": {"restart_stage": sha(os.path.abspath(__file__)), "restart_census": sha("tools/restart_census.py"), "park_model": sha("tools/park_model.py")},
        "bootstrap": res["bootstrap"], "label": res["label"],
        "endpointRule": "start reading of a probe = earliest native reading at or before first movement (speed > 0.5 km/h) and within 60 s of log start, else the first reading within 30 s; end reading = last native reading within 60 s of log end; no forward fill, no averaging in time",
        "exclusions": ex, "E1_primary_flaggedKept": res["E1_primary_flaggedKept"], "E1_secondary_flaggedDropped": res["E1_secondary_flaggedDropped"], "E1_sensitivity_previousDayCluster": res["E1_sensitivity_previousDayCluster"],
        "conditionTables": conds, "E5_startColumn": res["E5"],
        "parkModel": {k: park[k] for k in ("ambientReconstruction", "support", "M2_fullSample_nonFlagged", "M2_flaggedKept", "validation_fitMayAug_testSepNov", "E4_coldStartCounts")},
        "parkGates": {"P-R3b": g["P-R3b"], "P-R4": g["P-R4"], "P-R2": g["P-R2"], "note": "P-R3a and the tau band are binding only when the production ambient reconstruction matches the exploratory file; not evaluated in the stage"},
        "reproductionGates": repro,
        "deltaFlags": flags,
        "reading": "Restart change = next start minus previous end of the logged pack-probe readings (whole degrees), by gap class. A one-step rise of a single probe is a resolution artefact of whole-degree readings, not an event rate. Pairs with evidence of use inside the gap (state of charge up, engine coolant warm) are flagged and kept in the primary table; the park model fits drop them.",
        "limits": ["whole-degree probe readings; no sub-zero pack data yet", "the hold-out is not clean (ambient amplitude and peak hour fitted on the whole corpus; split confounded with slow polling and the battery software update)",
                   "ambient is the vehicle sensor read only while driving (uncalibrated, heat-soaked after parking)", "the unlogged-use flags miss short unlogged legs", "the two-state model is not evaluated (open item)"],
        "refresh": "recomputed at every ingestion by the stage restart_census; reproduction gates only on the 665-drive basis, new data fall under the outside-previous-interval flag",
    }
    return blk


def splice(A, blk, md5, now=None):
    import stamp_common as _sc
    new = copy.deepcopy(A)
    new[KEY] = blk
    ts = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    old = (A.get("_artifactStamps") or {}).get(KEY)
    st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=md5, generatedAt=ts, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M711: derived by tools/restart_stage.py (tools/restart_census.py, tools/park_model.py) from raw drive CSVs, drive_master.csv and summary_config.json ambientByDrive (spec analyses/M708_spec.md Rev 2); logged probe readings, model-derived park model")
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    new["_artifactStamps"][KEY] = _sc.carry_declared(old, st)
    bad = [k for k in set(A) | set(new) if k not in (KEY, "_artifactStamps") and A.get(k) != new.get(k)]
    bad += [k for k in set(A["_artifactStamps"]) | set(new["_artifactStamps"]) if k != KEY and A["_artifactStamps"].get(k) != new["_artifactStamps"].get(k)]
    return new, bad


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--drives-cache", default=None)
    a = ap.parse_args(argv)
    E = RC.load_endpoints(a.raw_dir, a.workers, a.drives_cache)
    P = RC.build_pairs(E, RC.ambient_start_map())
    raw = open("summary_arrays.json", encoding="utf-8", newline="").read()
    A = json.loads(raw)
    blk = build_block(E, P, A.get(KEY))
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    for f in blk["deltaFlags"]:
        print("FLAG restart_census:", f)
    new, bad = splice(A, blk, md5)
    print(json.dumps({"outsideKeys": bad, "sizeBytes": len(json.dumps(blk)), "nDrives": blk["nDrives"], "eligiblePairs": blk["exclusions"]["eligible"], "flags": len(blk["deltaFlags"]),
                      "reproduction": blk["reproductionGates"].get("evaluated") and {k: v["pass"] for k, v in blk["reproductionGates"]["gates"].items()}}))
    if bad:
        return 1
    if not a.dry_run:
        open("summary_arrays.json", "w", encoding="utf-8", newline="").write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
