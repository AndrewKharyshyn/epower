"""M758 known-answer tests (analyses/M758_spec.md Rev 2): tools/heatsoak_gap_payload.py copies the registered M756 rerun result into the carried block
heatSoakGapSensitivity leaf by leaf (tolerance 0), fails closed on a pin mismatch or wrong basis, stops on an R1 mismatch, touches only its own key, is idempotent and its wording passes the M758 rule.
The planted-result tests always run; the real-result tests are skipped when the registered file is absent or changed."""
import copy, json, os, shutil, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import heatsoak_gap_payload as hp
import language_gate as LG

M = hp.REGISTERED_MASTER


def cell(med, nAmb, days, shift=None, ci=None, verdict="not distinguishable", supported=True):
    c = {"nAmb": nAmb, "days": days, "supported": supported, "med": med, "verdict": verdict}
    if supported:
        c.update(shiftPp=shift, ci95Pp=ci, relativeShift=0.1, mdePp=5.0)
    return c


def planted():
    def tau(k, shift=None):
        t = {"nAmbBeforeFilter": 100, "nFit": 80, "slope": -k, "decayRateK": k, "decayRateKCI": [k - 0.01, k + 0.01], "tauH": round(1 / k, 2), "tauCI": [8.0, 12.0], "clusteringTable": []}
        if shift is not None:
            t.update(kShiftVsA=shift, kShiftCI95=[0.001, 0.02], kRatioAOverSet=0.9, verdictK="small")
        return t
    bins = [
        {"gapLoH": 0, "gapHiH": 1, "nAmbA": 50, "medA": 1.0, "B": cell(1.0, 40, 20, 0.0, [0.0, 0.0]), "C": cell(1.0, 45, 21, 0.0, [0.0, 0.0])},
        {"gapLoH": 6, "gapHiH": 12, "nAmbA": 66, "medA": 0.35, "B": cell(0.27, 32, 29, 8.1, [2.85, 17.97], "material"), "C": cell(0.28, 46, 42, 7.2, [2.45, 12.98], "material")},
        {"gapLoH": 12, "gapHiH": 24, "nAmbA": 73, "medA": 0.0625, "B": cell(0.0, 41, 41, 6.25, [0.0, 14.31]), "C": cell(0.0, 53, 53, 6.25, [0.0, 15.95])},
        {"gapLoH": 24, "gapHiH": None, "nAmbA": 24, "medA": -0.01, "B": cell(-0.14, 10, 10, supported=False, verdict="not estimable at this support"), "C": cell(-0.1, 14, 14, supported=False, verdict="not estimable at this support")},
    ]
    comp = {"0-1": {"n": 60, "S": 50}, "6-12": {"n": 73, "S": 37}, "12-24": {"n": 76, "S": 40}, "24-": {"n": 25, "S": 12}}
    return {"masterMd5": M, "registeredMasterMd5": M, "m729GapsSha256": hp.GAP_TABLE_SHA, "seed": 42, "nBoot": 4000, "toolSha256": "t" * 64,
            "control_V0": {"status": "reproduced"}, "reconciliation": {"pairs": 706}, "unlogged_shares": {"S": 5, "D": 2, "U": 1, "X": 0},
            "E1_composition_by_gap_bin": comp, "E2_retained_fraction_shift": {"primaryArrivalDay": bins},
            "E3_tau": {"A": tau(0.09), "B": tau(0.105, 0.015), "C": tau(0.107, 0.017), "C1": tau(0.108, 0.018)},
            "overall": "sensitive to unlogged driving (lower bound): a supported bin or tau is material under B and under C"}


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)


res = planted()
blk = hp.build(res)
rows = {(r["gapLoH"], r["gapHiH"]): r for r in blk["bins"]}
# leaf equality with the planted result (tolerance 0), C first, C1 absent
for b in res["E2_retained_fraction_shift"]["primaryArrivalDay"]:
    r = rows[(b["gapLoH"], b["gapHiH"])]
    assert r["allPairs"] == {"nAmb": b["nAmbA"], "med": b["medA"]}
    for s in ("B", "C"):
        c = b[s]
        assert (r[s]["nAmb"], r[s]["days"], r[s]["med"], r[s]["supported"]) == (c["nAmb"], c["days"], c["med"], c["supported"])
        if c["supported"]:
            assert (r[s]["shiftPp"], r[s]["ci95Pp"], r[s]["mdePp"]) == (c["shiftPp"], c["ci95Pp"], c["mdePp"])
        else:
            assert "shiftPp" not in r[s] and r[s]["verdict"] == "not estimable at this support"
    assert "C1" not in r
assert list(blk["setLabels"]) == ["A", "C", "B"] and hp.SETS == ("C", "B")
assert rows[(6, 12)]["C"]["verdict"] == "material" and rows[(6, 12)]["B"]["verdict"] == "material"
# boundary wording only for a not-distinguishable cell with interval lower bound exactly 0.0 and a positive shift; 0-1 h (shift 0) keeps the plain word
assert rows[(12, 24)]["C"]["verdict"] == hp.BOUNDARY == "not distinguishable (interval lower bound at 0.0; boundary case, not evidence of no shift)"
assert rows[(0, 1)]["C"]["verdict"] == "not distinguishable"
assert rows[(6, 12)]["pairsWithMovementOrUnknown"] == 73 - 37
for s in ("A", "B", "C"):
    t, src = blk["tau"][s], res["E3_tau"][s]
    assert (t["tauH"], t["tauCI"], t["decayRateK"], t["decayRateKCI"], t["nFit"]) == (src["tauH"], src["tauCI"], src["decayRateK"], src["decayRateKCI"], src["nFit"])
assert "kShiftVsA" not in blk["tau"]["A"] and blk["tau"]["B"]["kShiftVsA"] == 0.015 and blk["tau"]["C"]["verdictK"] == "small"
assert blk["overall"] == res["overall"]
# labels and staleness
assert blk["staleness"] == {"carried": True, "corpusDrives": 717, "refreshedAt": None}
assert "registered corpus of 717 drives" in blk["basis"] and "later drives are not included" in blk["basis"] and M[:8] in blk["basis"]
assert blk["setLabels"]["A"] == "all pairs, registered corpus" and "published" not in blk["setLabels"]["A"]
assert "not an article figure" in blk["status"] and "not refreshed by ingestion" in blk["status"]
for k in ("estimated", "lower bound", "sensitivity", "no OBD record"):
    assert k in json.dumps(blk), k
assert "cloud coverage" in blk["notes"]["setB"] and "not leaf-exactly" in blk["notes"]["audit"]

rule = [r for r in LG.RULES if r.rid == "M758-heatsoak-gap-wording"][0]
for t in strings(blk):
    assert not rule.hits(t), t
for bad in ("the published heat soak median is inflated", "the true retained heat is", "unlogged drives were removed", "the soak value is bias-corrected", "contaminated pairs removed"):
    assert rule.hits(bad), bad
for ok in ("estimated unlogged driving, never a correction", "a sensitivity of the registered-corpus median", "estimated unlogged drives"):
    assert not rule.hits(ok), ok

# fail closed: wrong master, wrong gap table, control not reproduced
for mut in (lambda r: r.update(masterMd5="0" * 32), lambda r: r.update(m729GapsSha256="0" * 64), lambda r: r["control_V0"].update(status="mismatch")):
    r2 = copy.deepcopy(res)
    mut(r2)
    try:
        hp.build(r2)
        raise SystemExit("a wrong basis must stop")
    except hp.Stop:
        pass

# load pin: an unchanged file passes, a changed or missing one stops
tmp = tempfile.mkdtemp()
rel = "r.json"
with open(os.path.join(tmp, rel), "w", encoding="utf-8") as f:
    json.dump(res, f)
pin = hp.sha256(os.path.join(tmp, rel))
assert hp.load(tmp, rel, pin)["seed"] == 42
with open(os.path.join(tmp, rel), "ab") as f:
    f.write(b" ")
for args in ((tmp, rel, pin), (tmp, "absent.json", pin)):
    try:
        hp.load(*args)
        raise SystemExit("a changed or missing source must stop")
    except hp.Stop:
        pass

# splice: only the block and its stamp change; idempotent; R1 stops on a live-median mismatch
arr = {"meta": {"a": 1}, "other": [1, 2], "_artifactStamps": {"powerFadeTemperatureSpecs": {"corpusHash": "x", "computedAt": "t", "generatedAt": "t", "includedInReleaseAt": "t"}}}
p = os.path.join(tmp, "arr.json")
with open(p, "w", encoding="utf-8") as f:
    json.dump(arr, f, indent=1)
assert hp.splice(blk, path=p) is True
with open(p, encoding="utf-8") as f:
    got = json.load(f)
assert got[hp.KEY] == blk and got["meta"] == arr["meta"] and got["other"] == arr["other"] and hp.KEY in got["_artifactStamps"]
with open(p, "rb") as f:
    before = f.read()
assert hp.splice(blk, path=p) is False
with open(p, "rb") as f:
    assert f.read() == before
live = copy.deepcopy(arr)
live["_artifactStamps"]["heatSoakCarryover"] = {"corpusHash": M}
live["heatSoakCarryover"] = {"gapBins": [{"gapLoH": 6, "gapHiH": 12, "medRetainedFrac": 0.35}]}
assert hp.r1_check(live, blk)[0] is True
live["heatSoakCarryover"]["gapBins"][0]["medRetainedFrac"] = 0.36
assert hp.r1_check(live, blk)[0] is False
p2 = os.path.join(tmp, "arr2.json")
with open(p2, "w", encoding="utf-8") as f:
    json.dump(live, f, indent=1)
try:
    hp.splice(blk, path=p2)
    raise SystemExit("R1 mismatch must stop")
except hp.Stop:
    pass
# a live master that differs from the registered one: R1 not applicable (the carried block is disclosed instead)
live["_artifactStamps"]["heatSoakCarryover"]["corpusHash"] = "f" * 32
assert hp.r1_check(live, blk)[0] is True
shutil.rmtree(tmp, ignore_errors=True)

# real registered result
try:
    real = hp.load()
except hp.Stop as e:
    print("test_heatsoak_gap_payload: registered result absent or changed, real-result tests skipped (%s)" % e)
    real = None
if real is not None:
    rb = hp.build(real)
    r612 = {(r["gapLoH"], r["gapHiH"]): r for r in rb["bins"]}[(6, 12)]
    sh = {(b["gapLoH"], b["gapHiH"]): b for b in real["E2_retained_fraction_shift"]["primaryArrivalDay"]}[(6, 12)]
    assert r612["C"]["shiftPp"] == sh["C"]["shiftPp"] and r612["B"]["ci95Pp"] == sh["B"]["ci95Pp"] and r612["allPairs"]["med"] == sh["medA"]
    assert rb["tau"]["A"]["tauH"] == real["E3_tau"]["A"]["tauH"]
    for t in strings(rb):
        assert not rule.hits(t), t
print("test_heatsoak_gap_payload: OK")
