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
    # M766 note X1 under the revised rule P: registered M766 fields copied (tolerance 0 before the frozen display rounding), the Director sentence verbatim, no B number, no absolute cloud value
    x1, res, dec = blk["x1LoggedDistance"], src["M766_odometer_agreement_P.json"], src["M765_director_decision.json"]
    pr = res["P1_agreement"]["E_int"]["primary_identity_ge2km"]
    assert (x1["nDrives"], x1["nDays"], x1["available"]) == (pr["nDrives"], pr["nDays"], res["P0_coverage"]["E_int"]["available"]) and "x1HeldBack" not in blk
    assert "revised rule P" in x1["ruleLabel"] and "M752 window rule" in x1["ruleLabel"]
    assert cp.pct2(0.01195) == 1.2 and cp.pct2(0.01129) == 1.13 and cp.pct2(0.00925) == 0.93 and cp.pct2(0.01387) == 1.39
    assert x1["relativeDifferencePercent"]["est"] == cp.pct2(pr["relative"]["est"]) and x1["relativeDifferencePercent"]["ci95"] == [cp.pct2(pr["relative"]["ci95"][0]), cp.pct2(pr["relative"]["ci95"][1])]
    assert x1["relativeDifferencePercent"]["rawFraction"] == {"est": pr["relative"]["est"], "ci95": pr["relative"]["ci95"]} and x1["medianDifferenceKm"]["raw"]["est"] == pr["median"]["est"]
    assert (x1["medianDifferenceKm"]["est"], x1["medianDifferenceKm"]["ci95"]) == (cp.km2(pr["median"]["est"]), [cp.km2(pr["median"]["ci95"][0]), cp.km2(pr["median"]["ci95"][1])])
    # the verdict phrases come from the interval (the M765 verdict_three words), without the repeated numbers; the interval straddles 1 % under P
    assert x1["verdict"]["within1pct"] == cp.short_word(res["P1_verdict_wording"]["primary_E_int_identity_ge2km"]["within1pct"]) == "the interval includes 1 %"
    assert x1["verdict"]["within3pct"] == "consistent within +-3 %" and x1["verdict"]["size"] == "small difference, cloud larger"
    assert cp.short_word("aggregate relative difference 1.20 % [1.04, 1.41]: the interval lies above 1 %") == "the interval lies above 1 %" and cp.short_word("consistent within +-1 %") == "consistent within +-1 %"
    lo_, hi_ = pr["relative"]["ci95"]
    assert (lo_ <= 0.01 <= hi_) == (x1["verdict"]["within1pct"] == "the interval includes 1 %") and not ("above" in x1["verdict"]["within1pct"] and lo_ <= 0.01)
    assert x1["strata"]["2to10km"]["est"] == cp.pct2(res["P1_agreement"]["E_int"]["strata"]["2to10km"]["relative"]["est"]) and x1["strata"]["10kmplus"]["nDrives"] == res["P1_agreement"]["E_int"]["strata"]["10kmplus"]["nDrives"]
    assert x1["sensitivity"]["shift16s"]["nDrives"] == res["P1_agreement"]["E_int_shift16"]["primary_identity_ge2km"]["nDrives"] and x1["sensitivity"]["bracketedEndpoints"]["est"] == cp.pct2(res["P1_agreement"]["E_br"]["primary_identity_ge2km"]["relative"]["est"])
    for k in ("S1_strict", "S2_wide"):
        assert x1["excursionSensitivity"][k]["drivesDropped"] == res["excursionSensitivity"][k]["drives_with_an_endpoint_inside_an_excursion"] and x1["excursionSensitivity"][k]["nDrives"] == res["excursionSensitivity"][k]["primary_identity_ge2km"]["nDrives"]
    assert (x1["excursionSensitivity"]["S1_strict"]["drivesDropped"], x1["excursionSensitivity"]["S2_wide"]["drivesDropped"]) == (22, 31) and "strict = " in x1["excursionSensitivity"]["note"]
    assert x1["integrity"]["jumpExcluded"] == res["P0_coverage"]["E_int"]["unavailableByReason"]["odometer_jump"] == 13
    assert set(x1["anchor"]) == {"differenceKm", "rawDifferenceKm", "n"} and x1["anchor"]["differenceKm"] == cp.km2(res["P3_anchor"]["differenceKm"]) and x1["anchor"]["rawDifferenceKm"] == res["P3_anchor"]["differenceKm"]
    # the Director sentence is copied verbatim; no B number, no auditor count and no absolute cloud value in the block
    assert dec["disclosure_sentence"] in x1["disclosures"]
    fx1 = json.dumps(x1)
    for bad in ("cloudLastOdoKm", "cloudPlusLogged", "dashOdoKm", "48104", "48110", "jumpExcludedAuditor", "nAuditor", "auditorAvailable", "jumpExcludedTool", "586", "418", "584", "1.20 %", "[1.04", "lower and E_br an upper bracket", "reading", "accurate distance"):
        assert bad not in fx1, bad
    # Director (M766): no verdict_words or allowed_wording number string reaches the page or the payload (only the frozen formatter output and the verbatim disclosure sentence)
    for w in (res["P1_verdict_wording"]["primary_E_int_identity_ge2km"]["within1pct"], res["excursionSensitivity"]["S1_strict"]["verdict_words"]["within1pct"], res["excursionSensitivity"]["S2_wide"]["verdict_words"]["within1pct"]):
        assert w not in fx1 and ": the interval" not in fx1, w
    assert "[0.92, 1.39]" not in fx1
    for need in ("same wheel-speed scale", "not a known answer", "logger edge losses (a hypothesis)", "revised rule P", "M752 window rule", "selected by month and by drive length", "parked-edge model of the design is not confirmed", "km-weighted", "strict = "):
        assert need in fx1, need
    r760 = [r for r in LG.RULES if r.rid == "M760-logged-distance-wording"][0]
    r766 = [r for r in LG.RULES if r.rid == "M766-x1-revised-wording"][0]
    def _strings(o):
        if isinstance(o, str):
            yield o
        elif isinstance(o, dict):
            for v in o.values():
                yield from _strings(v)
        elif isinstance(o, list):
            for v in o:
                yield from _strings(v)
    for t in _strings(x1):
        assert not r760.hits(t) and not r766.hits(t), t
    low = " ".join(t.lower() for t in _strings(x1))
    for bad in ("bias", "error", "agrees", "agree ", "verified", "calibrated", "under-report", "underreport", "missing km", "lost km", "lower bracket", "upper bracket", "consistent with the cloud odometer", "overestimate", "inflated", "true distance", "reference distance", "accurate distance", "tost", "equivalent to", "not different from", "reaches beyond", "exceeds 1", "above 1 %"):
        assert bad not in low, bad
    for bad in ("the cloud odometer is a lower bracket", "the logged distance is too low", "cloud odometer verified", "bias of the cloud odometer", "the logger under-reports", "distance accuracy is shown", "true odometer"):
        assert r760.hits(bad), bad
    for bad in ("the difference is equivalent to 1 %", "not different from 1 %", "a TOST on the cloud odometer shows it", "equivalent to one percent"):
        assert r766.hits(bad), bad
    for ok in ("this checks logging completeness, not distance accuracy", "the interval includes 1 %", "consistent within +-3 %", "the parked-edge model of the design is not confirmed"):
        assert not r760.hits(ok) and not r766.hits(ok), ok
    # fail closed: a wrong master, a rule other than P, a control that did not pass, a missing disclosure sentence, a missing n_days
    for mut, what in ((lambda r, d: r.update(masterMd5="0" * 32), "wrong master"), (lambda r, d: r.update(rule="B"), "wrong rule"),
                      (lambda r, d: r["control_R0"].update(reproduced_leaf_by_leaf=False), "control not reproduced"), (lambda r, d: r["consistency_R2"].update(equals_M765_P=False), "M765 inconsistency"),
                      (lambda r, d: d.pop("disclosure_sentence"), "missing sentence"), (lambda r, d: r["P1_agreement"]["E_int"]["primary_identity_ge2km"].update(nDays=0), "no n_days")):
        bad_src = copy.deepcopy(src)
        mut(bad_src["M766_odometer_agreement_P.json"], bad_src["M765_director_decision.json"])
        try:
            cp.build(bad_src)
            raise SystemExit("must stop: %s" % what)
        except cp.Stop:
            pass
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
