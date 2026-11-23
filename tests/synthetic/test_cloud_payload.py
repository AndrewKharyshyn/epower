"""M749 known-answer tests (analyses/M749_spec.md Rev 4): tools/cloud_payload.py copies registered cloud-export values into the additive block
cloudCrossChecks, fails closed on a pin mismatch or a missing source, derives direction words from sign and day interval, touches only its own key, is idempotent,
and writes wording that passes the M749-cloud-wording rule. Skipped (exit 0) when the registered analyses files are absent."""
import copy, json, os, shutil, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import cloud_payload as cp
import language_gate as LG

# direction words: only an interval that excludes zero gives larger / smaller
assert cp.direction({"ci95_day": [0.07, 0.27]}) == "larger"
assert cp.direction({"ci95_day": [-0.29, -0.09]}) == "smaller"
assert cp.direction({"ci95_day": [-0.02, 0.09]}) == "not distinguishable"
assert cp.direction({"ci95_day": [0.0, 0.1]}) == "not distinguishable"

src = None
try:
    src = cp.load()
except cp.Stop as e:
    print("test_cloud_payload: registered sources absent or changed, value tests skipped (%s)" % e)

if src is not None:
    blk = cp.build(src)
    m30, m34, m39 = (src[k] for k in ("M730_clock_offset.json", "M734_thermal_forcing.json", "M739_unlogged_exposure.json"))
    # every displayed value equals the registered field it is copied from
    x2, x3, x4 = blk["x2BetweenDriveLogging"], blk["x3Ambient"], blk["x4Timestamps"]
    assert x2["strictUnits"] == m39["U1_unlogged"]["strict_units"] and x2["days"] == m39["U1_unlogged"]["days"]
    assert x2["exportReconstructionErrorTimeShares"]["validationDrives"] == m39["V1_n"]["validation_drives"]
    assert x2["exportReconstructionErrorTimeShares"]["medianTotalVariation"] == round(m39["V1_reconstruction_error"]["time_shares"]["median_tv"], 4)
    u2c = m39["U2_representativeness"]["km_weighted_primary"]
    assert x2["direction"] == {"timeBelow30": cp.direction(u2c["below30"]), "timeAbove80": cp.direction(u2c["above80"]), "longUnits": cp.direction(u2c["length_t3"])}
    assert set(x2["direction"].values()) <= {"larger", "smaller", "not distinguishable"}
    t1 = m34["T1_ambient"]["screened_minus_manual"]
    assert (x3["nDrives"], x3["nDays"]) == (t1["n_drives"], t1["n_days"]) and x3["medianAbs"] == round(t1["median_abs"], 2) and x3["p90Abs"] == round(t1["p90_abs"], 2)
    assert (x4["nDrives"], x4["nDays"], x4["pooledS"]) == (m30["n_drives"], m30["n_days"], m30["pooled_best_offset_s"]) and x4["adoptGlobalOffset"] is False
    assert x4["dayBootstrapCi95S"] == [float(v) for v in m30["median_best_offset_ci95_day_bootstrap"]]
    assert blk["x1LoggedDistance"] is None and "heldBack" not in blk["x1HeldBack"] and "431 drives" in blk["x1HeldBack"]
    # no cloud kilometres, hours or absolute odometer in the block
    flat = json.dumps(blk)
    for bad in ("48104", "48105", "total_km_cloud", "totalHours", "netCloudOdometerGainKm", "lowerBiasedCloudTotal"):
        assert bad not in flat, bad
    # wording: every string passes the M749 rule and the block states its basis and status
    rule = [r for r in LG.RULES if r.rid == "M749-cloud-wording"][0]
    def strings(o):
        if isinstance(o, str):
            yield o
        elif isinstance(o, dict):
            for v in o.values():
                yield from strings(v)
        elif isinstance(o, list):
            for v in o:
                yield from strings(v)
    for t in strings(blk):
        assert not rule.hits(t), t
    assert "not an article figure" in blk["status"] and "717 drives" in blk["basis"] and "not recomputed with later drives" in blk["basis"]
    assert "measurement error" not in flat

    # fail closed: a changed source, a missing source, a wrong registered master
    tmp = tempfile.mkdtemp()
    for fn in cp.PINS:
        shutil.copy(os.path.join(cp.A_DIR, fn), os.path.join(tmp, fn))
    cp.load(tmp)
    with open(os.path.join(tmp, "M730_clock_offset.json"), "ab") as f:
        f.write(b" ")
    try:
        cp.load(tmp)
        raise SystemExit("a changed source must stop")
    except cp.Stop:
        pass
    os.remove(os.path.join(tmp, "M734_thermal_forcing.json"))
    try:
        cp.load(tmp)
        raise SystemExit("a missing source must stop")
    except cp.Stop:
        pass
    bad_src = copy.deepcopy(src)
    bad_src["M739_unlogged_exposure.json"]["masterMd5"] = "0" * 32
    try:
        cp.build(bad_src)
        raise SystemExit("a wrong master must stop")
    except cp.Stop:
        pass
    bad_src = copy.deepcopy(src)
    bad_src["M730_clock_offset.json"].pop("n_days")
    try:
        cp.build(bad_src)
        raise SystemExit("a note without n_days must stop")
    except (cp.Stop, KeyError):
        pass

    # splice: only the block and its stamp change; a second splice changes nothing
    arr = {"meta": {"a": 1}, "other": [1, 2], "_artifactStamps": {"powerFadeTemperatureSpecs": {"corpusHash": "x", "computedAt": "t", "generatedAt": "t", "includedInReleaseAt": "t"}}}
    p = os.path.join(tmp, "arr.json")
    json.dump(arr, open(p, "w", encoding="utf-8"), indent=1)
    assert cp.splice(blk, path=p) is True
    got = json.load(open(p, encoding="utf-8"))
    assert got["cloudCrossChecks"] == blk and got["meta"] == arr["meta"] and got["other"] == arr["other"] and "cloudCrossChecks" in got["_artifactStamps"]
    before = open(p, "rb").read()
    assert cp.splice(blk, path=p) is False and open(p, "rb").read() == before
    arr2 = json.load(open(p, encoding="utf-8"))
    assert {k for k in arr2 if k not in arr} == {"cloudCrossChecks"}

# the payload key is the one declared for stamping
deps = json.load(open(os.path.join(ROOT, "tools", "stamp_dependencies.json"), encoding="utf-8"))["blocks"]
assert "cloudCrossChecks" in deps and "cloudAuxiliary" not in deps and deps["cloudCrossChecks"]["producer"] == "tools/cloud_payload.py"
print("test_cloud_payload: OK")
