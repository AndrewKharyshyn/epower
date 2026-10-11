"""M402 (analyses/M402_spec.md, audit F16b): Ah-throughput producer. Known answers on synthetic drives (sign crossing, gaps, artifacts, unpaired samples, too few pairs),
the identity with the kWh integration, the sidecar logic (incremental by raw sha256, rows for every master drive) and, when raw/ is present, matched support with the master."""
import io, json, os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import ah_throughput as AH

CI, CV = "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)"


def csv(i_samples, v_samples, volt=350.0):
    """i_samples: {second: BMS current (charge-positive)}; v_samples: iterable of seconds with a voltage reading (value volt)."""
    secs = sorted(set(i_samples) | set(v_samples))
    rows = [{"time": "%02d:%02d:%02d.000" % (s // 3600, (s // 60) % 60, s % 60), CI: i_samples.get(s, np.nan), CV: volt if s in v_samples else np.nan} for s in secs]
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def approx(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


# 1. constant 10 A discharge for 3600 s (BMS current -10 A): 10 Ah, 3.5 kWh at 350 V
secs = range(0, 3601)
r = AH.ah_from_bytes(csv({s: -10.0 for s in secs}, secs))
assert r["reason"] is None and approx(r["ah_discharge"], 10.0) and approx(r["ah_charge"], 0.0) and approx(r["kwh_discharge"], 3.5) and r["n_crossings"] == 0, r
assert approx(r["ah_throughput"], 10.0) and approx(r["ah_net"], 10.0) and r["n_pairs"] == 3601
# 2. constant charge
r = AH.ah_from_bytes(csv({s: 10.0 for s in range(0, 3601)}, range(0, 3601)))
assert approx(r["ah_charge"], 10.0) and approx(r["ah_discharge"], 0.0) and approx(r["ah_net"], -10.0) and approx(r["kwh_charge"], 3.5)
# 3. one +10 A -> -10 A crossing interval (M229 identity: gross = d(i0^2+i1^2)/(2(|i0|+|i1|)) = 5d, 2.5d to each side), then 1 s of -10 A
d = 1.0 / 3600.0
r = AH.ah_from_bytes(csv({0: -10.0, 1: 10.0, 2: 10.0}, range(3)))
assert r["n_crossings"] == 1 and approx(r["ah_discharge"], 2.5 * d) and approx(r["ah_charge"], 2.5 * d + 10 * d), r
assert approx(r["kwh_discharge"], r["ah_discharge"] * 350.0 / 1000.0) and approx(r["kwh_charge"], r["ah_charge"] * 350.0 / 1000.0)    # constant voltage: kWh = Ah x V
# 4. a 60 s logging gap is clipped to the 5 s integration cap (1 s + 5 s at 10 A)
r = AH.ah_from_bytes(csv({0: -10.0, 1: -10.0, 61: -10.0}, [0, 1, 61]))
assert approx(r["ah_discharge"], 10.0 * 6 / 3600.0), r
# 5. an |I| >= 900 artifact sample is dropped before pairing (remaining samples 0, 1, 3: 3 s at 10 A)
r = AH.ah_from_bytes(csv({0: -10.0, 1: -10.0, 2: -1600.0, 3: -10.0}, range(4)))
assert approx(r["ah_discharge"], 10.0 * 3 / 3600.0) and r["n_pairs"] == 3, r
# 6. a current sample with no voltage within 1.5 s is dropped (voltage only at 0, 1; currents at 0, 1, 2, 10, 11 -> pairs 0, 1, 2)
r = AH.ah_from_bytes(csv({0: -10.0, 1: -10.0, 2: -10.0, 10: -10.0, 11: -10.0}, [0, 1]))
assert r["n_pairs"] == 3 and approx(r["ah_discharge"], 10.0 * 2 / 3600.0), r
# 7. fewer than two integrable pairs -> empty values with a reason, never zero; no voltage / no current series -> reason as well
r = AH.ah_from_bytes(csv({0: -10.0, 10: -10.0, 20: -10.0}, [0]))                       # one pair only (the others are > 1.5 s from any voltage)
assert r["ah_discharge"] is None and r["ah_charge"] is None and r["reason"] == "no_integrable_iv_pairs", r
r = AH.ah_from_bytes(csv({0: -10.0, 1: -10.0, 2: -10.0, 3: -10.0}, []))
assert r["ah_discharge"] is None and r["reason"] == "no_iv_series", r
# 8. voltage outside the filter band 200-450 V is not a voltage sample
r = AH.ah_from_bytes(csv({s: -10.0 for s in range(5)}, range(5), volt=150.0))
assert r["ah_discharge"] is None and r["reason"] == "no_iv_series", r

# sidecar: one row per master drive, incremental by raw sha256, recomputed only when the hash changes
calls = []
real = AH.ah_from_bytes
AH.ah_from_bytes = lambda b: (calls.append(1), real(b))[1]
store = {"a.csv": csv({s: -10.0 for s in range(0, 61)}, range(0, 61)), "b.csv": csv({0: -10.0, 10: -10.0, 20: -10.0}, [0])}
master = pd.DataFrame({"file": ["a.csv", "b.csv", "c.csv"], "date": ["2026-07-01", "2026-07-01", "2026-07-02"]})
with tempfile.TemporaryDirectory() as td:
    sp = os.path.join(td, "ah.csv")
    out = AH.build_sidecar(master, lambda f: store.get(f), sp)
    assert list(out["file"]) == ["a.csv", "b.csv", "c.csv"] and len(calls) == 2
    assert approx(float(out.loc[0, "ah_discharge"]), 10.0 * 60 / 3600.0, 1e-6) and out.loc[1, "reason"] == "no_integrable_iv_pairs" and out.loc[2, "reason"] == "raw_file_missing"
    assert out.loc[0, "raw_sha256"] and not pd.isna(out.loc[0, "kwh_per_ah_throughput"]) and abs(out.loc[0, "kwh_per_ah_throughput"] - 0.35) < 1e-6
    n0 = len(calls)
    AH.build_sidecar(master, lambda f: store.get(f), sp)                          # unchanged bytes: nothing recomputed
    assert len(calls) == n0
    store["a.csv"] = csv({s: -20.0 for s in range(0, 61)}, range(0, 61))        # changed bytes: only that drive is recomputed
    out = AH.build_sidecar(master, lambda f: store.get(f), sp)
    assert len(calls) == n0 + 1 and approx(float(out.loc[0, "ah_discharge"]), 20.0 * 60 / 3600.0, 1e-6)
AH.ah_from_bytes = real

# matched support with the published master (the acceptance test of 'same intervals'), on a deterministic stratified sample when raw/ is present
dm = pd.read_csv("drive_master.csv", low_memory=False)
loader = AH.raw_loader()
have = [f for f in dm["file"] if loader(f) is not None]
if len(have) >= 20:
    sample = dm[dm["file"].isin(have)].sort_values("file").iloc[:: max(1, len(have) // 24)]
    worst = 0.0
    for _, row in sample.iterrows():
        r = AH.ah_from_bytes(loader(row["file"]))
        if pd.isna(row["gross_discharge_kwh"]):
            assert r["ah_discharge"] is None, row["file"]
            continue
        dd, dc = abs(r["kwh_discharge"] - row["gross_discharge_kwh"]), abs(r["kwh_charge"] - row["gross_charge_kwh"])
        assert dd <= AH.MASTER_ROUNDING_TOL and dc <= AH.MASTER_ROUNDING_TOL, (row["file"], dd, dc)
        worst = max(worst, dd, dc)
    print("matched support on %d sampled drives, worst |kWh - master| = %.2e" % (len(sample), worst))
print("OK test_ah_throughput")
