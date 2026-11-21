"""M714 known-answer tests for tools/exposure_scenarios_block.py (spec analyses/M712_spec.md Rev 1.1, section 11): the support status mapping (Director ruling of M713, option A), the spliced block equals a fresh
assembly from the M713 files, the failed gates are shown as failed, the splice touches only its key and its stamp, and every string of the block passes the language gate."""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import exposure_scenarios_block as B
import language_gate as LG

# status mapping: cold outputs NOT SUPPORTED, hot outputs a bracket, dose indices indices, the rest supported
for k in ("coldChargeIndex_AhxC_lt10", "coldCharge_ah_lt0", "ahShare_T_lt10", "ah_T_<0", "ah_T_5-10", "warmups_Tstart_lt15", "starts_Tstart_lt0", "ah_in_warmup_lt15", "coldest_start_T", "chargeAh_aboveExtrapolatedLimit_lt10", "parked_hours_lt0"):
    assert B.metric_status(k) == "notSupported", k
for k in ("ahShare_T_ge35", "hotTail_ah_ge40", "ah_T_35-40", "ah_T_>=45", "parked_hours_ge30"):
    assert B.metric_status(k) == "bracket", k
for k in ("arrCycleAF_Ea50", "arrCalendarAF_year_Ea50", "parkedShareOfCalendarDose_Ea50", "parked_meanPackT"):
    assert B.metric_status(k) == "index", k
for k in ("annual_km", "drives", "ah_throughput", "gtc_5Ah_rated", "gtc_2p1kWh_legacy", "fce_5Ah_rated", "engine_starts", "ah_SoC_55-60", "ah_T_20-25", "episodes_chg_gt10C", "drive_hours"):
    assert B.metric_status(k) == "supported", k

A = json.load(open("summary_arrays.json", encoding="utf-8"))
blk = B.assemble(A[B.KEY]["masterMd5"])
assert A[B.KEY] == blk, "the spliced block equals a fresh assembly from analyses/M713"
assert B.do_check() == []
bym = blk["supportStatus"]["byMetric"]
assert all(v in ("supported", "notSupported", "bracket", "index") for v in bym.values()) and len(bym) == 77
assert blk["gates"]["G-S2 consistency check (in-sample)"] is False and blk["gates"]["G-S2b month-blocked hold-out"] is False, "the failed gates are shown as failed"
assert blk["gates"]["G-S0 replay identity"] is True and blk["gates"]["G-S1 distance anchoring"] is True and blk["gates"]["G-S3 reproduction of the prototype on identical inputs"] is True
assert set(blk["scenarios"]) >= {"S0_window_annualised_asLogged", "S2_balanced_owner_expected", "S3b_cold_winter", "S7_summer_like_year"}
s2 = blk["scenarios"]["S2_balanced_owner_expected"]
assert set(s2["E_exp"]) <= set(B.HEADLINE) and s2["E_real"]["annual_km"][1] < s2["E_real"]["annual_km"][0] < s2["E_real"]["annual_km"][2]
assert s2["E_exp"]["annual_km"][2] - s2["E_exp"]["annual_km"][1] < s2["E_real"]["annual_km"][2] - s2["E_real"]["annual_km"][1], "E-exp narrower than E-real"
assert blk["basisNDrives"] == blk["nDrives"] == 717 and "five" not in json.dumps(blk).lower()
assert all(k in blk["sources"] for k in ("scenario_gates.json", "state_params.json", "odometer_check.json"))

# every string of the block passes the language gate (estimated / model-derived wording, no forbidden phrases)
def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
assert [s for s in strings(blk) if LG.scan_text(s)] == []

# splice isolation on a synthetic payload: only the key and its stamp change; an existing stamp's declared basis fields are carried
stamp = {"corpusHash": "x", "generatedAt": "t", "computationStatus": "computed", "upstreamHashes": {}, "includedInReleaseAt": "t", "computedAt": "t"}
P = {"a": 1, "b": {"c": 2}, "_artifactStamps": {"fuelContract": copy.deepcopy(stamp), "a": {"corpusHash": "x"}}}
new, bad = B.splice(P, {"k": 1}, "md5new")
assert bad == [] and new[B.KEY] == {"k": 1} and new["a"] == 1 and new["_artifactStamps"]["a"] == {"corpusHash": "x"}
assert new["_artifactStamps"][B.KEY]["corpusHash"] == "md5new" and new["_artifactStamps"][B.KEY]["computedAt"] == new["_artifactStamps"][B.KEY]["generatedAt"] == new["_artifactStamps"][B.KEY]["includedInReleaseAt"]
assert P[B.KEY if B.KEY in P else "a"] == 1, "the input payload is not modified"
print("test_exposure_scenarios_block: ok")
