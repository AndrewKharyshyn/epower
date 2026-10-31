#!/usr/bin/env python3
"""M546 G0 (analyses/M546_spec.md Rev 2 A0 / KA1): the default call of compute_summary_arrays._engine_state_machine (strict_off=False) reproduces the stored engineStateMachine block and the three cohort variants of the stored chart
EngineStateMachine byte for byte (canonical JSON), over the canonical drive set (pipeline frame loader). Read-only; writes analyses/M546_g0.json. Usage: python tools/engine_state_machine_g0.py"""
import hashlib, json, os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd

OUT = os.path.join(ROOT, "analyses", "M546_g0.json")


def canon(o):
    return json.dumps(json.loads(json.dumps(o, default=float)), sort_keys=True)


def main():
    os.chdir(ROOT)
    import drive_raw_cache as drc
    import ah_throughput as AH
    import compute_summary_arrays as C
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False, usecols=["file", "thermal_regime"]).set_index("file")["thermal_regime"]
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    fl = drc.make_frame_loader(raw_dir=os.path.abspath("raw_only")); rl = AH.raw_loader()
    t0 = time.time()
    g = {"primary": canon(C._engine_state_machine(dm, rl, frame_loader=fl)) == canon(A["engineStateMachine"])}
    ch = A["seasonalCharts"]["charts"]["EngineStateMachine"]["data"]
    g["cohortCharts"] = {}
    for c in ("warm", "shoulder", "cold"):
        sub = dm[dm["file"].map(sdm) == c]
        g["cohortCharts"][c] = canon(C._engine_state_machine(sub, rl, frame_loader=fl)) == canon(ch.get(c))
    g["passed"] = bool(g["primary"] and all(g["cohortCharts"].values()))
    res = {"spec": "analyses/M546_spec.md Rev 2 (A0 / KA1)", "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "runSeconds": round(time.time() - t0, 1), "gates": g}
    json.dump(res, open(OUT, "w", encoding="utf-8", newline=chr(10)), indent=1)
    print(json.dumps(res))
    return 0 if g["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
