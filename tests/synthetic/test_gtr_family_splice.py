"""M377b known-answer tests for tools/gtr_family_refresh_splice.plan (analyses/M377_spec.md Rev 4). Uses the committed summary_arrays.json and the committed
analyses/M377_O_blocks.json (written by the point runner for the same master); mutated COPIES of the O file trigger each STOP. Nothing is written to the repo."""
import copy, hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import gtr_family_refresh_splice as S

A = json.load(open("summary_arrays.json", encoding="utf-8"))
O = json.load(open("analyses/M377_O_blocks.json", encoding="utf-8"))
# M463: when the family blocks are CARRIED (generatorTractionRecon.carriedAtIngestion) the committed O file belongs to the carried basis, not to the newer live headline; the
# known-answer cases below therefore run against the arrays as they stood at the carried refresh (the headline target of the carried BASE row), a copy; nothing is written.
if A["generatorTractionRecon"].get("carriedAtIngestion"):
    A = copy.deepcopy(A)
    _b = O["sensitivity"]["axes"][0]
    _g = A["generatorTractionRecon"]
    _g["corpus"].update({"generator": _b["gen100"], "tractionGross": _b["trac100"], "fGen": _b["fgen"], "etaBus": _b["etaBus"]})
    _g["nProduction"] = _g["nDrives"] = O["sensitivity"]["nDrives"]
import m377_pin
SPEC = m377_pin.spec_sha("analyses/M377_spec.md")
MD5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
if A["generatorTractionRecon"].get("carriedAtIngestion"):
    MD5 = O["meta"]["driveMasterMd5After"]                    # M463: the carried O file is bound to the master of its own refresh


def stops_of(o):
    new, delta, stops = S.plan(A, o, "TEST", SPEC, MD5)
    return new, delta, stops


def mut(f):
    o = copy.deepcopy(O); f(o); return o


# binding
assert any("not bound" in s for s in stops_of(mut(lambda o: o["meta"].__setitem__("specSha256", "0" * 64)))[2])
assert any("different drive_master" in s for s in stops_of(mut(lambda o: o["meta"].__setitem__("driveMasterMd5After", "0" * 32)))[2])
assert any("gate failed" in s for s in stops_of(mut(lambda o: o["meta"]["speedSplitValidation"].__setitem__("passed", False)))[2])
# key sets / labels
assert any("key set" in s for s in stops_of(mut(lambda o: o["simultaneity"]["rows"][0].pop("fullyBanked")))[2])
assert any("axis labels" in s for s in stops_of(mut(lambda o: o["sensitivity"]["axes"][1].__setitem__("axis", "renamed")))[2])
# reading flips
assert any("sensitivity f_gen >= 0.5" in s for s in stops_of(mut(lambda o: o["sensitivity"]["axes"][1].__setitem__("fgen", 0.6)))[2])
def flip_speed(o):
    for r in o["speedSplit"]["bins"]:
        if r["bin"] == "90-120": r["fGen"] = 0.0
assert any("decreases" in s for s in stops_of(mut(flip_speed))[2])
def flip_sim(o):
    r = {x["type"]: x for x in o["simultaneity"]["rows"]}
    r["urban"]["chargesAndDrives"], r["highway"]["chargesAndDrives"] = r["highway"]["chargesAndDrives"], r["urban"]["chargesAndDrives"]
assert any("ordering" in s for s in stops_of(mut(flip_sim))[2])
# escalation bands
def band_share(o): o["simultaneity"]["rows"][3]["genAloneNeutral"] += 6.0
assert any("pp" in s for s in stops_of(mut(band_share))[2])
def band_f(o): o["speedSplit"]["bins"][0]["fGen"] += 0.06
assert any("f_gen moved" in s for s in stops_of(mut(band_f))[2])
assert any("n_days" in s for s in stops_of(mut(lambda o: o["speedSplit"].__setitem__("nDays", o["speedSplit"]["nDays"] * 2)))[2])

# M426: narrowly scoped acknowledgement of the simultaneity share-band stop (Director ruling); nothing else is acknowledgeable
def band_o(): return mut(band_share)
def mk_ack(o, **over):
    r = o["simultaneity"]["rows"][3]
    prev = [x for x in A["generatorTractionRecon"]["simultaneity"] if x["type"] == r["type"]][0]
    ack = {"ruling": "TEST", "driveMasterMd5": MD5, "simultaneityRowsSha256": S._rows_sha(o["simultaneity"]["rows"]),
           "acknowledged": [{"block": "simultaneity", "row": r["type"], "quantity": "genAloneNeutral", "deltaPP": round(r["genAloneNeutral"] - prev["genAloneNeutral"], 4)}]}
    ack.update(over); return ack
def with_ack(o, ack): return S.plan(A, o, "TEST", SPEC, MD5, ack)
o_ = band_o()
assert stops_of(o_)[2] == [S.BAND_STOP]                                                    # unacknowledged: still a stop
assert "rowMovePP" in stops_of(o_)[1]["blocks"]["simultaneity"]                            # row-level deltas are written
new_, delta_, st_ = with_ack(o_, mk_ack(o_))
assert st_ == [] and new_ is not None and delta_["bandAcknowledgement"]["acknowledged"] == mk_ack(o_)["acknowledged"] and delta_["bandAcknowledgement"]["band"] == S.BAND_SHARE_PP
for bad in ({"driveMasterMd5": "0" * 32}, {"simultaneityRowsSha256": "0" * 64}, {"ruling": ""}, {"acknowledged": []},
            {"acknowledged": mk_ack(o_)["acknowledged"] + [{"block": "simultaneity", "row": "urban", "quantity": "fullyBanked", "deltaPP": 6.0}]},
            {"acknowledged": [dict(mk_ack(o_)["acknowledged"][0], deltaPP=5.9)]}, {"acknowledged": [dict(mk_ack(o_)["acknowledged"][0], row="urban")]}):
    st = with_ack(o_, mk_ack(o_, **bad))[2]
    assert any("acknowledgement refused" in x for x in st) and S.BAND_STOP in st, bad          # any mismatch keeps the stop
# an acknowledgement for a run with no breach, or with any other stop present, is refused; other stops are never removed
assert any("refused" in x for x in with_ack(O, mk_ack(o_))[2])
def band_and_flip(o): band_share(o); flip_sim(o)
o2 = mut(band_and_flip); st2 = with_ack(o2, mk_ack(o2))[2]
assert any("ordering" in x for x in st2) and any("refused" in x for x in st2)
def band_and_days(o): band_share(o); o["speedSplit"]["nDays"] *= 2
o3 = mut(band_and_days); st3 = with_ack(o3, mk_ack(o3))[2]
assert any("n_days" in x for x in st3) and any("refused" in x for x in st3)
def band_and_key(o): band_share(o); o["simultaneity"]["rows"][0].pop("fullyBanked")
o4 = mut(band_and_key); st4 = with_ack(o4, mk_ack(o4))[2]
assert any("key set" in x for x in st4)
assert not any(("band acknowledgement" in x) for x in stops_of(O)[2])

if A["generatorTractionRecon"].get("carriedAtIngestion"):
    # M463: the committed-pair idempotence section recomputes eligibility from the live files (the newer drive set), which cannot equal blocks that are CARRIED at an older basis;
    # the stop cases above ran against the carried basis. The full section runs again as soon as the blocks are refreshed (M464).
    print("test_gtr_family_splice: OK (stop and acknowledgement cases only; the committed-pair section is skipped while the blocks are carried: carriedAtIngestion)")
    sys.exit(0)
# known answer: the committed pair reproduces the committed blocks (no new data) and only allow-listed paths change
new, delta, stops = stops_of(O)
assert not stops and new is not None, stops
G, N = A["generatorTractionRecon"], new["generatorTractionRecon"]
for b in S.BLOCKS:
    assert N[b] == G[b], b + ": values must be unchanged on the committed state"
assert N["eligibilityAlignment"]["current"] == G["eligibilityAlignment"]["current"] and N["eligibilityAlignment"]["excluded"] == G["eligibilityAlignment"]["excluded"]
assert N["eligibilityAlignment"]["note"] == G["eligibilityAlignment"]["note"]
carried = "carriedAtIngestion" in G["gtrClosure"]["scope"] or "gtrClosure" in G["staleBlocks"]["blocks"]
if carried:        # M377b state: the closure is carried and disclosed
    assert N["gtrClosure"]["scope"]["carriedAtIngestion"]["basisNDrives"] == G["gtrClosure"]["scope"]["nDrives"]
    assert "gtrClosure" in N["staleBlocks"]["blocks"] and "crossval" in N["staleBlocks"]["blocks"]
else:              # M377c state: the closure is refreshed by its own stage; this splice must leave it and staleBlocks untouched
    assert N["gtrClosure"] == G["gtrClosure"] and N["staleBlocks"] == G["staleBlocks"] and N["staleBlocks"]["blocks"] == ["crossval"]
assert all("carriedBasis" in r for r in N["refreshedBlocks"] if "previousBlock" in r or "provenanceDelta" in r)
changed = list(S.walk(A, new))
assert all(any(p == a or p.startswith(a + "/") or p.startswith(a + "[") for a in S.ALLOW) for p in changed)
print("test_gtr_family_splice: OK (%d changed leaves, all allow-listed)" % len(changed))
