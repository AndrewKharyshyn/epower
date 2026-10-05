"""M377b known-answer tests for tools/gtr_family_refresh_splice.plan (analyses/M377_spec.md Rev 4). Uses the committed summary_arrays.json and the committed
analyses/M377_O_blocks.json (written by the point runner for the same master); mutated COPIES of the O file trigger each STOP. Nothing is written to the repo."""
import copy, hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import gtr_family_refresh_splice as S

A = json.load(open("summary_arrays.json", encoding="utf-8"))
O = json.load(open("analyses/M377_O_blocks.json", encoding="utf-8"))
SPEC = hashlib.sha256(open("analyses/M377_spec.md", "rb").read()).hexdigest()
MD5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()


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

# known answer: the committed pair reproduces the committed blocks (no new data) and only allow-listed paths change
new, delta, stops = stops_of(O)
assert not stops and new is not None, stops
G, N = A["generatorTractionRecon"], new["generatorTractionRecon"]
for b in S.BLOCKS:
    assert N[b] == G[b], b + ": values must be unchanged on the committed state"
assert N["eligibilityAlignment"]["current"] == G["eligibilityAlignment"]["current"] and N["eligibilityAlignment"]["excluded"] == G["eligibilityAlignment"]["excluded"]
assert N["eligibilityAlignment"]["note"] == G["eligibilityAlignment"]["note"]
assert N["gtrClosure"]["scope"]["carriedAtIngestion"]["basisNDrives"] == G["gtrClosure"]["scope"]["nDrives"]
assert "gtrClosure" in N["staleBlocks"]["blocks"] and "crossval" in N["staleBlocks"]["blocks"]
assert all("carriedBasis" in r for r in N["refreshedBlocks"] if "previousBlock" in r or "provenanceDelta" in r)
changed = list(S.walk(A, new))
assert all(any(p == a or p.startswith(a + "/") or p.startswith(a + "[") for a in S.ALLOW) for p in changed)
print("test_gtr_family_splice: OK (%d changed leaves, all allow-listed)" % len(changed))
