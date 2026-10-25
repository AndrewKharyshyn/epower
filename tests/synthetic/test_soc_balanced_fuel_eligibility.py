"""M511 known-answer tests (analyses/M511_spec.md Rev 2): canonical-clean primary population of the SoC-balanced fuel producer, matched sensitivity, STOP on a missing flag."""
import io, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import compute_summary_arrays as cs
import eligibility as EL

def trip(fuel_l, dsoc, kmh=60.0, n=1200):
    t = pd.to_datetime("2026-08-01 10:00:00") + pd.to_timedelta(np.arange(n), unit="s")
    df = pd.DataFrame({"time": t.strftime("%H:%M:%S.000"), cs._HF_FUEL: np.linspace(100.0, 100.0 + fuel_l, n),
                       cs._HF_SOC: np.linspace(60.0, 60.0 + dsoc, n), cs._HF_SPD_VCM: kmh})
    return df.to_csv(index=False).encode()

specs = {f"d{i}.csv": (1.0 + 0.1 * i, (-1.0) ** i * 0.5 * i) for i in range(8)}
raws = {k: trip(*v) for k, v in specs.items()}
loader = lambda fn: raws.get(fn)
dm = pd.DataFrame({"file": list(specs), "date": ["2026-08-0%d" % (1 + i // 2) for i in range(8)],
                   "ens_outlier_v2": [False] * 8, "ens_invalid": [False] * 8})
dm.loc[3, ["ens_outlier_v2", "ens_invalid"]] = True

out = cs._soc_balanced_fuel(dm, loader, None)
assert out["nDrives"] == 7 and out["eligibility"]["nExcludedByRule"] == 1 and out["eligibility"]["excludedFiles"][0]["file"] == "d3.csv"
sens = out["allAccumulatorSensitivity"]
assert sens["nDrives"] == 8 and sens["extraFiles"] == out["eligibility"]["excludedFiles"]
# sensitivity equals the unfiltered control run
ctrl = cs._soc_balanced_fuel(dm, loader, None, _apply_eligibility=False)
assert ctrl["nDrives"] == 8 and sens["socBalancedFleetL100"] == ctrl["socBalancedFleetL100"] and sens["rawFleetL100"] == ctrl["rawFleetL100"]
assert sens["socBalancedFleetBoot"] == ctrl["socBalancedFleetBoot"] and "eligibility" not in ctrl
# hand-computed ratio of sums on the primary population
keep = [f for f in specs if f != "d3.csv"]
rows = [cs._hf_perdrive(f, loader, None) for f in keep]
assert abs(out["rawFleetL100"] - round(sum(r["fuelL"] for r in rows) / sum(r["distKm"] for r in rows) * 100, 3)) < 1e-9
# nothing excluded: no sensitivity block, same headline as the control
clean = dm.copy(); clean[["ens_outlier_v2", "ens_invalid"]] = False
o2 = cs._soc_balanced_fuel(clean, loader, None)
assert o2["eligibility"]["nExcludedByRule"] == 0 and "allAccumulatorSensitivity" not in o2 and o2["socBalancedFleetL100"] == ctrl["socBalancedFleetL100"]
# a missing flag for an accepted accumulator trip is a STOP, never treated as clean
bad = dm.copy(); bad["ens_outlier_v2"] = bad["ens_outlier_v2"].astype(object); bad.loc[5, "ens_outlier_v2"] = np.nan
try:
    cs._soc_balanced_fuel(bad, loader, None)
    raise SystemExit("expected EligibilityError")
except EL.EligibilityError:
    pass
print("test_soc_balanced_fuel_eligibility: OK")
