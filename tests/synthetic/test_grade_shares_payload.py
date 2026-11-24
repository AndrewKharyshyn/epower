"""M767 known-answer tests (analyses/M767_spec.md Rev 2): tools/grade_shares_payload.py copies the registered grade-class share result into the carried block gradeClassShares leaf by leaf (raw values kept, the frozen display rounding),
fails closed on a pin mismatch or a failed control, writes the Director wording (coverage, product dependence, limits) from the registered numbers, keeps the cohort block out, touches only its own key and its stamp, is idempotent, and its wording passes
the M767 rule. The real-result tests are skipped when the registered file is absent or changed."""
import copy, json, os, shutil, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import grade_shares_payload as P
import language_gate as LG
import odometer_jump_audit as J

assert P.r2(0.925) == 0.93 and P.r2(70.675) == 70.68 and P.r2(3.365) == 3.37 and P.r1(57.605) == 57.6 and P.r1(0.05) == 0.1


def planted():
    def row(cls, est, lo, hi, steps, days, km, shown=True):
        return {"class": cls, "support": {"steps": steps, "days": days, "drives": 100, "km": km, "interval_shown": shown},
                "step_share_pct": {"est": est, "ci95": [lo, hi] if shown else [None, None]}, "km_share_pct": {"est": est * 0.99, "ci95": [lo * 0.99, hi * 0.99] if shown else [None, None]}}
    names = ["below -3 pp", "-3 to -1 pp", "-1 to 1 pp", "1 to 3 pp", "above 3 pp"]
    ests = [3.365, 11.475, 70.675, 11.125, 3.36]
    e1 = {"n_steps": 11088, "n_days": 134, "km": 6373.18, "rows": [row(n, e, e - 1.0, e + 1.0, 400 + i, 50 + i, 200.0 + i) for i, (n, e) in enumerate(zip(names, ests))]}
    e3 = [{"class": n, "by_product_step_share_pct": {"F": e, "N": e + 0.5, "A": e + 0.4, "G": e + 0.2}, "bracket_min": e, "bracket_max": e + 0.5, "source_dependent": bool(i in (1, 2, 3))} for i, (n, e) in enumerate(zip(names, ests))]
    e4 = {"logged_km": 11062.24, "covered_km": 6373.18, "covered_share_of_logged_km_pct": 57.61, "drives": 717, "drives_with_a_covered_step": 474,
          "by_stratum": {"below 2 km": {"drives": 184, "logged_km": 222.3, "covered_km": 24.0, "covered_share_pct": 10.8}, "2 to 10 km": {"drives": 344, "logged_km": 1261.5, "covered_km": 365.3, "covered_share_pct": 29.0}},
          "by_month": {"2026-05": {"drives": 38, "logged_km": 500.0, "covered_km": 287.0, "covered_share_pct": 57.4}, "2026-06": "suppressed (fewer than 3 drives)"},
          "by_cohort": {"cold": {"drives": 77, "logged_km": 800.0, "covered_km": 452.0, "covered_share_pct": 56.5}},
          "drive_level_speed_class_mix_km_weighted": {"all_logged": {"urban_pct": 46.3, "highway_pct": 23.8, "mixed_pct": 29.9}, "covered": {"urban_pct": 40.8, "highway_pct": 25.3, "mixed_pct": 33.9}, "uncovered_remainder": {"urban_pct": 53.8, "highway_pct": 21.8, "mixed_pct": 24.4}},
          "steps_excluded_above_8pp": {"n_steps": 27, "share_of_steps_after_masks_pct": 0.2429, "below_minus_8": 15, "above_8": 12},
          "fabdem_sensitivities_step_share_pct": {"pre_mask_set_11682_steps": ests, "primary_set_11088_steps": ests}}
    return {"masterMd5": P.REGISTERED_MASTER, "m762ManifestSha256": "c" * 64, "toolSha256": "t" * 64, "seed": 42, "nBoot": 4000, "control_R1": {"stages_equal_M762": True, "fabdem_step_shares_equal_M762_C6": True, "misclassification_equal_M762": True},
            "E1_shares_primary_steps_secondary_km": e1, "E2_cohorts_result_only": {"cold": {"secret": 1}}, "E3_products": e3, "E4_coverage_and_selection": e4,
            "three_class_and_five_class_misclassification_vs_fabdem_pct": {"five_class": {"N": 15.6746, "A": 14.6374, "G": 9.3705}},
            "limits": ["inter-product DEM error only, assumption-conditional; common-mode error is not identified", "shares describe the COVERED driving, not all driving"]}


res = planted()
blk = P.build(res)
assert [c["label"] for c in blk["classes"]] == ["below -3 pp", "-3 to -1 pp", "-1 to 1 pp", "1 to 3 pp", "above 3 pp"]
c2 = blk["classes"][2]
assert c2["stepSharePct"]["est"] == 70.68 and c2["stepSharePct"]["raw"]["est"] == 70.675 and c2["stepSharePct"]["ci95"] == [69.68, 71.68] and c2["sourceDependent"] is True and blk["classes"][0]["sourceDependent"] is False
assert c2["products"] == {"FABDEM": 70.68, "NASADEM": 71.18, "AW3D30": 71.08, "GLO-30": 70.88} and c2["bracketMinPct"] == 70.68 and c2["bracketMaxPct"] == 71.18
assert blk["misclassificationPct"] == {"NASADEM": 15.7, "AW3D30": 14.6, "GLO-30": 9.4}
assert blk["coverage"]["coveredSharePct"] == 57.6 and blk["coverage"]["byMonth"]["2026-06"] == "suppressed (fewer than 3 drives)" and blk["coverage"]["byLength"]["2 to 10 km"]["coveredSharePct"] == 29.0
assert blk["excludedAbove8pp"] == {"steps": 27, "belowMinus8": 15, "above8": 12, "sharePct": 0.24}
assert "E2_cohorts_result_only" not in blk and "secret" not in json.dumps(blk)                         # the cohort block stays in the result only
assert blk["staleness"] == {"carried": True, "corpusDrives": 717, "refreshedAt": None} and "later drives are not included" in blk["basis"] and "not an article figure" in blk["status"]
assert "not all driving" in blk["notes"]["coverage"]
assert "-3 to -1 pp, -1 to 1 pp, 1 to 3 pp" in blk["notes"]["products"] and "below -3 pp, above 3 pp" in blk["notes"]["products"] and "not an interval" in blk["notes"]["products"]
assert "15.7 %" in blk["notes"]["labels"] and "14.6 %" in blk["notes"]["labels"] and "11,088" in blk["notes"]["lead"]


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)


rule = [r for r in LG.RULES if r.rid == "M767-grade-class-share-wording"][0]
for t in strings(blk):
    assert not rule.hits(t), t
for bad in ("this is all driving", "representative of the whole corpus", "error bars on the shares", "a hilly route", "the terrain profile", "measured grade", "true grade"):
    assert rule.hits(bad), bad
for ok in ("the shares describe where the covered driving takes place, not all driving", "not the error against the road grade", "estimated DEM step grade"):
    assert not rule.hits(ok), ok
low = json.dumps({k: v for k, v in blk.items() if k not in ("limits", "notes")}).lower()
for w in ("regenerat", "traction", "fuel", "kwh", "validated", "measured", "proven"):
    assert w not in low, w
# the energy words appear only in the 'locked' note and the limits, as negations
assert "not shown here" in blk["notes"]["locked"]
assert J.scan_privacy(blk) == [] or all(k != "str" for k, _ in J.scan_privacy(blk))

# fail closed
for mut, what in ((lambda r: r.update(masterMd5="0" * 32), "wrong master"), (lambda r: r["control_R1"].update(stages_equal_M762=False), "control failed"),
                  (lambda r: r["E3_products"][0].update({"class": "x"}), "class rows disagree"), (lambda r: r["E1_shares_primary_steps_secondary_km"]["rows"].pop(), "wrong class count")):
    r2_ = copy.deepcopy(res)
    mut(r2_)
    try:
        P.build(r2_)
        raise SystemExit("must stop: %s" % what)
    except P.Stop:
        pass
tmp = tempfile.mkdtemp()
try:
    with open(os.path.join(tmp, "r.json"), "w", encoding="utf-8") as f:
        json.dump(res, f)
    pin = P.sha256(os.path.join(tmp, "r.json"))
    assert P.load(tmp, "r.json", pin)["seed"] == 42
    with open(os.path.join(tmp, "r.json"), "ab") as f:
        f.write(b" ")
    for args in ((tmp, "r.json", pin), (tmp, "absent.json", pin)):
        try:
            P.load(*args)
            raise SystemExit("a changed or missing source must stop")
        except P.Stop:
            pass
    arr = {"meta": {"a": 1}, "other": [1, 2], "_artifactStamps": {"powerFadeTemperatureSpecs": {"corpusHash": "x", "computedAt": "t", "generatedAt": "t", "includedInReleaseAt": "t"}}}
    p = os.path.join(tmp, "arr.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(arr, f, indent=1)
    assert P.splice(blk, path=p) is True
    with open(p, encoding="utf-8") as f:
        got = json.load(f)
    assert got[P.KEY] == blk and got["meta"] == arr["meta"] and got["other"] == arr["other"] and P.KEY in got["_artifactStamps"]
    with open(p, "rb") as f:
        before = f.read()
    assert P.splice(blk, path=p) is False
    with open(p, "rb") as f:
        assert f.read() == before
finally:
    shutil.rmtree(tmp, ignore_errors=True)

try:
    real = P.load()
except P.Stop as e:
    print("test_grade_shares_payload: registered result absent or changed, real-result tests skipped (%s)" % e)
    real = None
if real is not None:
    rb = P.build(real)
    assert rb["classes"][2]["stepSharePct"]["raw"]["est"] == real["E1_shares_primary_steps_secondary_km"]["rows"][2]["step_share_pct"]["est"]
    for t in strings(rb):
        assert not rule.hits(t), t
print("test_grade_shares_payload: OK")
