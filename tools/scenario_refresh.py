#!/usr/bin/env python3
"""M720: block-refresh stage of the additive payload block `exposureScenarios` (M714). Chains the M713 tools in their dependency order and splices the block, so that an ingestion refreshes the scenario block without a hand-run recipe.
Steps (all read the raw files / master read-only; every number is written by the tool named): frame (tools/scenario_frame.py, per-drive cache `scenario_cache/` keyed by the raw-file SHA-256 and the extractor source hash: only new or changed
drives are extracted) -> odometer (exposure_odometer.py --extend: the dash odometer of summary_config.json becomes a reading; the unlogged-day classifier is re-run) -> state (exposure_state.py: R(T), drive heating, limit map, diurnal ambient)
-> engine production (E-real intervals) -> engine project integration rule (S2) -> validation (consistency G-S2, hold-out G-S2b, leave-one-day-out, E-exp) -> sensitivity (Sobol and tornado on the frozen ranges) -> gates -> block splice -> block check.
Carried on purpose (they compare against the 2026-11-16 prototype inputs, which are fixed to the 665-drive basis and cannot be recomputed on new data): scenario_gs3_identical_S2.json, scenario_attribution.json,
scenario_validation_diagnostics.json. A gate that fails on new data is recorded as failed, never relaxed (spec analyses/M712_spec.md Rev 1.1); a changed support status or a headline outside its previous interval is printed in the
comparison with the previous block and left to the Director (flag only, never a stop).
Freshness: the inputs of the chain (master MD5, the dash odometer and its date, the SHA-256 of every tool script and of the frozen ranges file) are recorded in analyses/M713/refresh_state.json; when they equal the recorded state the stage
is a no-op apart from the block check, so an ingestion that adds no drive does not pay the multi-hour run.
Usage: python tools/scenario_refresh.py [--plan] [--force] [--only a,b] [--dry-run]   (--plan prints the steps and the freshness verdict; --force ignores the freshness record)"""
import argparse, hashlib, json, os, subprocess, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
DIR = "analyses/M713"
STATE = os.path.join(DIR, "refresh_state.json")
PY = sys.executable or "python"
TOOLS = ["scenario_frame.py", "exposure_odometer.py", "exposure_state.py", "scenario_engine.py", "scenario_validation.py", "scenario_sensitivity.py", "scenario_gates.py", "exposure_scenarios_block.py", "scenario_refresh.py"]
STEPS = [
    ("frame", ["tools/scenario_frame.py"]),
    ("odometer", ["tools/exposure_odometer.py", "--extend"]),
    ("state", ["tools/exposure_state.py"]),
    ("engine_production", ["tools/scenario_engine.py", "--mode", "production"]),
    ("engine_projectrule", ["tools/scenario_engine.py", "--integration", "project", "--scenarios", "S2_balanced_owner_expected", "--out", DIR + "/scenario_results_production_projectrule_S2.json"]),
    ("validation", ["tools/scenario_validation.py", "--what", "consistency,holdout,lodo,expected"]),
    ("sensitivity", ["tools/scenario_sensitivity.py"]),
    ("gates", ["tools/scenario_gates.py"]),
    ("splice", ["tools/exposure_scenarios_block.py", "--splice"]),
    ("check", ["tools/exposure_scenarios_block.py", "--check"]),
]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def inputs():
    """The inputs of the chain, as recorded in refresh_state.json."""
    cfg = json.load(open("summary_config.json", encoding="utf-8"))["vehicle"]
    return {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "odometerKm": cfg["odometerKm"], "odometerAsOf": cfg["odometerAsOf"],
            "toolSha256": {t: sha(os.path.join("tools", t)) for t in TOOLS if t != "scenario_refresh.py"}, "rangesSha256": sha("analyses/M712_ranges.json")}


def verdict(state, cur):
    """('fresh' | 'stale', reasons): the chain is fresh when every recorded input equals the current one."""
    if state is None:
        return "stale", ["no refresh_state.json"]
    why = [k for k in cur if k != "toolSha256" and state.get("inputs", {}).get(k) != cur[k]]
    why += ["tool " + t for t, h in cur["toolSha256"].items() if state.get("inputs", {}).get("toolSha256", {}).get(t) != h]
    return ("stale" if why else "fresh"), why


def block_summary(A):
    b = (A or {}).get("exposureScenarios") or {}
    return {"masterMd5": b.get("masterMd5"), "supportStatus": (b.get("supportStatus") or {}).get("byMetric")}


def compare(prev, new):
    """Flag-only comparison with the previous block: metrics whose support status changed."""
    ps, ns = prev.get("supportStatus") or {}, new.get("supportStatus") or {}
    return {"statusChanged": sorted(k for k in set(ps) | set(ns) if ps.get(k) != ns.get(k)), "previousMasterMd5": prev.get("masterMd5"), "newMasterMd5": new.get("masterMd5")}


def run(names, dry=False):
    for n, cmd in STEPS:
        if names and n not in names:
            continue
        t = time.time()
        print("[scenario_refresh] %s: %s" % (n, " ".join(cmd)), flush=True)
        if dry:
            continue
        r = subprocess.run([PY] + cmd, cwd=ROOT)
        print("[scenario_refresh] %s rc=%d in %.0f s" % (n, r.returncode, time.time() - t), flush=True)
        if r.returncode:
            return n
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    cur = inputs()
    state = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else None
    v, why = verdict(state, cur)
    names = [x for x in a.only.split(",") if x]
    if a.plan:
        print(json.dumps({"verdict": v, "reasons": why, "steps": [n for n, _ in STEPS]}, indent=1))
        return 0
    if v == "fresh" and not a.force and not names:
        print("[scenario_refresh] inputs unchanged since the recorded refresh: only the block check runs")
        return run(["check"], a.dry_run) and 1 or 0
    prev = block_summary(json.load(open("summary_arrays.json", encoding="utf-8")))
    failed = run(names, a.dry_run)
    if failed:
        print("[scenario_refresh] STOPPED at step %s" % failed)
        return 1
    if not a.dry_run and not names:
        json.dump({"milestone": "M720", "inputs": cur, "steps": [n for n, _ in STEPS]}, open(STATE, "w", encoding="utf-8"), indent=1)
        new = block_summary(json.load(open("summary_arrays.json", encoding="utf-8")))
        print(json.dumps({"comparisonWithPreviousBlock": compare(prev, new)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
