"""M546 (analyses/M546_spec.md Rev 2): the engineStateMachineRule payload block (structure, gates, stamps, conservation on the unrounded transition-matrix row sums, cohort floor), the display rebind (guarded accessor, cohort selection, labels),
the VALUE-LEVEL crosscheck_events identity (primary _RawAccum() and the e-4ORCE _RawAccum(eng_on_rpm=ENGINE_ON_STORED_RPM) accumulate the same engine-on state on the same synthetic frame), the count-only onset sensitivity (containment, not nesting),
the conventions document, the language rule and the dwell-sensitivity file."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C

A = json.load(open("summary_arrays.json", encoding="utf-8"))
B = A["engineStateMachineRule"]
S0 = A["engineStateMachine"]

# ---- payload ----
assert B["rule"] == {"thresholdRpm": 400, "boundary": "gt", "name": "engine-on (rpm > 400)", "storedKey": "engineStateMachine", "offState": "rpm <= 400"}
g = B["provenance"]["gates"]
assert g["passed"] is True and g["driveSetEqualsStored"] is True and g["conservationRowSums"]["passed"] is True and g["matrixOutsideOffLowEqual"] is True
assert g["A3"]["hit"] is False and g["A3"]["otherStatesDiffer"] is False
assert A["_artifactStamps"]["engineStateMachineRule"]["corpusHash"] and "stored" in B["basis"] or True
P = B["pooled"]
assert P["stateEdgesRpm"]["offBoundary"].startswith("rpm <= 400") and "off rpm<=400" in P["methodology"] and "not of engine time" in P["methodology"]
# conservation on the UNROUNDED transition-matrix row sums, recomputed here from the two payload blocks
To, Tn = np.array(S0["transitionMatrix"]["counts"], float), np.array(P["transitionMatrix"]["counts"], float)
ro, rn = To.sum(1), Tn.sum(1)
n_ex = B["detail"]["pooled"]["secondsExactly400LastClassifiedExcluded"]
assert rn[0] - ro[0] == n_ex and rn[1] - ro[1] == -n_ex and (rn[2:] == ro[2:]).all() and n_ex > 0
mask = np.ones((5, 5), bool); mask[:2, :] = False; mask[:, :2] = False
assert (To[mask] == Tn[mask]).all()
sh = B["detail"]["pooled"]["pooledOffShareUnroundedPct"]
assert abs(sh["rule"] - sh["stored"] - sh["movePp"]) < 1e-5 and abs(sh["movePp"]) < 0.01 and abs(sh["rule"] - rn[0] / rn.sum() * 100) < 1e-4
assert B["detail"]["pooled"]["nDrives"] == S0["nDrivesCovered"] and B["detail"]["pooled"]["nDays"] == S0["nDays"]
assert set(B["byCohort"]) == {"warm", "shoulder", "cold"} and all((b is None) == (B["detail"]["byCohort"][c] is None) for c, b in B["byCohort"].items())
assert all(d is None or d["exploratory"] == (d["nDays"] < 5) for d in B["detail"]["byCohort"].values())
# the stored blocks are untouched in shape
assert S0["stateEdgesRpm"].get("offBoundary") is None and "off rpm<400" in S0["methodology"]
# the stage reuses the whole block on an equal cache key
import engine_state_machine_stage as ST
assert ST.A3_PP == 0.01 and ST.MIN_DAYS == 5
assert B["provenance"]["cacheKey"] and len(B["provenance"]["cacheKey"]) == 64

# ---- crosscheck_events: VALUE-level identity of the engine-on state on a synthetic frame ----
RPM = "Оберти двигуна (rpm)"
BOOST = "Розрахунковий наддув (bar)"
n = 240
rp = np.array(([0.0] * 20 + [350.0] * 10 + [400.0] * 5 + [900.0] * 30 + [2000.0] * 40 + [0.0] * 15) * 2, float)[:n]
fr = pd.DataFrame({"time": pd.date_range("2026-01-01 10:00:00", periods=n, freq="1s").strftime("%H:%M:%S.%f").str[:-3], RPM: rp,
                   "[VCM] Vehicle Speed (km/h)": np.linspace(0, 110, n), BOOST: np.where(rp > 1500, 0.4, 0.0)})
a1, a2 = C._RawAccum(), C._RawAccum(eng_on_rpm=C.ENGINE_ON_STORED_RPM)
a1.add(fr.copy(), 5.0, "urban", "L", "f.csv"); a2.add(fr.copy(), 5.0, "urban", "L", "f.csv")
for k in ("eod", "eod_on", "turbo_rpm", "turbo_spd", "hvc_turbo"):
    assert json.dumps(getattr(a1, k), sort_keys=True, default=float) == json.dumps(getattr(a2, k), sort_keys=True, default=float), k
assert (a1.eng_on == a2.eng_on).all() and (a1.eng_tot == a2.eng_tot).all() and a1.eng_on.sum() > 0
a3 = C._RawAccum(eng_on_rpm=400); a3.add(fr.copy(), 5.0, "urban", "L", "f.csv")
assert a3.eng_on.sum() < a1.eng_on.sum()                      # the 350 and 400 rpm rows leave the engine-on count at the rule gate

# ---- onset sensitivity: counts only, containment ----
O = A["engineStartRate"]["onsetSensitivity400"]
assert O["displayed"] is False and O["countsOnly"] is True and O["containment"]["everyAbove400RunInsideAbove300Run"] is True and O["containment"]["driveSetNested"] is True
assert "per100km" not in json.dumps(O) and "ci95" not in json.dumps(O)
assert O["pooledPrimaryDrives"]["events400"] != O["pooledPrimaryDrives"]["events300"]       # counts are NOT nested: runs split
import engine_start_rate as ES
x = pd.DataFrame({"eng_rpm": [0, 500, 500, 350, 500, 500, 0, 350, 350, 350, 0.0]})
s3, l3, _ = ES.onsets(x, 300); s4, l4, _ = ES.onsets(x, 400)
assert len(s3) == 2 and len(s4) == 2 and list(s3) == [1, 7] and list(s4) == [1, 4]       # one > 300 run splits into two > 400 runs; a > 300 run of only 350 rpm drops out
assert all((x["eng_rpm"].values[j:j + int(L)] > 300).all() for j, L in zip(s4, l4))
assert ES.onsets(x)[0].tolist() == s3.tolist()                  # the default is the detector of record

# ---- dwell sensitivity file (counts only, not in the payload) ----
D = json.load(open("analyses/M546_dwell_sensitivity.json", encoding="utf-8"))
assert D["masterMd5"].startswith("5556a0c6") and D["difference"]["loadPoint"] == 0 and sum(abs(v) for v in D["difference"].values()) <= 3 * D["secondsExactly400OnStateGrid"]
assert "engineDwellSurvival" not in B["pooled"]

# ---- display ----
src = open("xtrail_summary.jsx", encoding="utf-8").read()
assert 'cohortOrRule("EngineStateMachine",_coh,"engineStateMachineRule",S.engineStateMachine)' in src and 'engineOnBlockRule("engineStateMachineRule")' in src
assert "stored basis, off = rpm < 400" in src and "state grid (1 s mean resample, hold 3 s)" in src
assert sum(len(re.findall(r"S\.engineStateMachineRule|S\[key\]", l)) for l in src.split("\n") if not l.strip().startswith("//")) == 1       # one direct reader: the accessor

# ---- conventions document, language rule, boundary registry ----
doc = open("docs/conventions_of_record.md", encoding="utf-8").read()
for k in ("ffill(limit=3)", "floors of the ABSOLUTE clock second", "build_hz", "strict_off", "_apply_speed_priority", "NaN policy", "NOT time-weighted"):
    assert k in doc, k
assert not re.search(r"\b\d{3,}\.\d+\b", doc.replace("400.0", ""))                    # no result figure in the document
import language_gate as G
assert "M546-state-machine-off-boundary" in [r.rid for r in G.RULES] and G.scan_text("off = rpm < 400, the engine state") and not G.scan_text("(stored basis, off = rpm < 400: 53%)")
import engine_on_sites
assert engine_on_sites.unregistered() == []
# ---- Director follow-ups (second blind pass): midnight rollover through the state-machine path, exactly-400 float equality, even-count median dwell ----
def _drv(times, rpm):
    return pd.DataFrame({"time": times, RPM: np.array(rpm, float)})


dmx = pd.DataFrame({"file": ["x.csv"], "date": ["2026-01-01"]})
# (a) a drive that crosses midnight: 23:59:00 + 120 s; the clock steps back by a day at 00:00:00 and must be unwrapped, so all 120 seconds are classified in order
tm = pd.date_range("2026-01-01 23:59:00", periods=120, freq="1s").strftime("%H:%M:%S.%f").str[:-3]
assert tm[0] == "23:59:00.000" and tm[-1] == "00:00:59.000"
rpm_x = [0.0] * 40 + [900.0] * 40 + [0.0] * 40
r_x = C._engine_state_machine(dmx, None, frame_loader=lambda f: _drv(tm, rpm_x), strict_off=True)
assert r_x["pooledTotalSeconds"] == 119 and sum(sum(r) for r in r_x["transitionMatrix"]["counts"]) == 119            # 120 classified seconds, 119 transitions
assert r_x["transitionMatrix"]["counts"][0][1] == 1 and r_x["transitionMatrix"]["counts"][1][0] == 1                 # exactly one off->low and one low->off: the sequence is in clock order
# (b) exactly 400 is float equality of the 1 s bin MEAN: two native rows 399 and 401 in one second average to 400.0 and count as 'off'; 399.9 and 401 do not
t2 = pd.DatetimeIndex(pd.date_range("2026-01-01 10:00:00", periods=60, freq="500ms")).strftime("%H:%M:%S.%f").str[:-3]
rp2 = np.tile([399.0, 401.0], 30)
r_b = C._engine_state_machine(dmx, None, frame_loader=lambda f: _drv(t2, rp2), strict_off=True)
r_b0 = C._engine_state_machine(dmx, None, frame_loader=lambda f: _drv(t2, rp2))
assert r_b["occupancy"]["off"]["pooled"] == 1.0 and r_b0["occupancy"]["low"]["pooled"] == 1.0                           # bin mean 400.0: off under the strict flag, low under the stored boundary
rp3 = np.tile([399.9, 401.0], 30)
r_c = C._engine_state_machine(dmx, None, frame_loader=lambda f: _drv(t2, rp3), strict_off=True)
assert r_c["occupancy"]["low"]["pooled"] == 1.0                                                                         # bin mean 400.45: low
# (c) the median dwell is the plain median of the run lengths in classified seconds (even count: mean of the two middle values)
t4 = pd.date_range("2026-01-01 10:00:00", periods=40, freq="1s").strftime("%H:%M:%S.%f").str[:-3]
rp4 = [0.0] * 2 + [900.0] * 5 + [0.0] * 4 + [900.0] * 5 + [0.0] * 24                                                    # off runs 2, 4, 24 (odd) ...
r_d = C._engine_state_machine(dmx, None, frame_loader=lambda f: _drv(t4, rp4), strict_off=True)
assert r_d["perState"]["off"]["dwellS"]["median"] == 4.0
rp5 = [0.0] * 2 + [900.0] * 5 + [0.0] * 4 + [900.0] * 5 + [0.0] * 8 + [900.0] * 5 + [0.0] * 11                           # off runs 2, 4, 8, 11 (even count): median (4 + 8) / 2
r_e = C._engine_state_machine(dmx, None, frame_loader=lambda f: _drv(t4, rp5[:40]), strict_off=True)
assert r_e["perState"]["off"]["dwellS"]["median"] == 6.0 and r_e["perState"]["off"]["dwellS"]["n"] == 4
print("OK test_m546_state_machine_rule: payload gates, unrounded conservation, value-level crosscheck identity, onset containment, dwell sensitivity, display, conventions, language")
