#!/usr/bin/env python3
"""M373 splice (analyses/M373_spec.md Rev 2): replace generatorTractionRecon.{sensitivity, simultaneity, speedSplit} by the O-point values (current set on the sha256-verified originals), add the
additive key generatorTractionRecon.refreshedBlocks, and remove the spliced blocks from staleBlocks (blocks + perBlock). Values only: row key sets must equal the published ones.
Refuses unless: both points passed their gates; analyses/M373_delta.json has no tolerance breach (a breach goes to the Director: --accept-breaches only after a ruling) and no reading flip
FOR THAT BLOCK (a flipped block is skipped, the others proceed); summary_arrays.json sha256 equals the value recorded at the start of the runs. Every number is read from the script-written
M373 JSON; nothing is typed. Deep diff: only the spliced blocks, refreshedBlocks, staleBlocks and the three reworded limitation paragraphs (limitations[4], [5], [6]) change.
Usage: python tools/m373_p2_splice.py [--dry-run] [--accept-breaches] [--only sensitivity,simultaneity,speedSplit]"""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
DRY, ACC = "--dry-run" in sys.argv, "--accept-breaches" in sys.argv
only = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")), None)
ALL = ["sensitivity", "simultaneity", "speedSplit"]
want = only.split(",") if only else ALL
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
O = json.load(open("analyses/M373_O_blocks.json", encoding="utf-8"))
delta = json.load(open("analyses/M373_delta.json", encoding="utf-8"))
if not delta["summary"]["gatesPassed"] or not delta["specShaEqualBothPoints"]:
    raise SystemExit("gates failed or spec hash differs between points")
if delta["summary"]["nBreaches"] and not ACC:
    raise SystemExit("tolerance breaches present (Director ruling required): %s" % delta["breaches"][:3])
flipped = set(delta["summary"]["blocksWithFlip"])
todo = [b for b in want if b not in flipped]
if flipped & set(want):
    print("SKIPPED (reading flip, Director): %s" % sorted(flipped & set(want)))
raw = open("summary_arrays.json", "rb").read()
exp = os.environ.get("M373_ARRAYS_SHA16")          # summary_arrays.json sha256[:16] recorded at the start of the runs (log line 1): mandatory
if not exp or hashlib.sha256(raw).hexdigest()[:16] != exp:
    raise SystemExit("summary_arrays.json changed since the runs started (or M373_ARRAYS_SHA16 not set)")
A = json.loads(raw.decode("utf-8"))
G = A["generatorTractionRecon"]
new = json.loads(json.dumps(A))
N = new["generatorTractionRecon"]
strip = lambda rows, keys: [{k: r[k] for k in keys} for r in rows]
vals = {"sensitivity": strip(O["sensitivity"]["axes"], ["axis", "gen100", "trac100", "fgen", "etaBus"]), "simultaneity": O["simultaneity"]["rows"], "speedSplit": O["speedSplit"]["bins"]}
nn = {"sensitivity": (O["sensitivity"]["nDrives"], O["sensitivity"]["nDays"]), "simultaneity": (O["simultaneity"]["nDrives"], O["simultaneity"]["nDays"]), "speedSplit": (O["speedSplit"]["nDrives"], O["speedSplit"]["nDays"])}
refreshed = []
D = delta["blocks"]
old_sens = G["sensitivity"]          # the PREVIOUS published table (M279 basis), read before replacement
prevBlock = {"basis": "published table before M373 (M279 basis)", "nAxes": len(old_sens), "nAxesFgenAtOrAbove0p5": sum(1 for r in old_sens if r["fgen"] >= 0.5), "baseFgen": old_sens[0]["fgen"],
             "combinedDriftMaxAbsFgen_R_minus_published": max(abs(r["fgen"]) for r in D["sensitivity"]["R_minus_P_combined_unattributed"]),
             "note": "the difference between the previous table and the refreshed one is combined drive-set + code + basis drift, unattributed"}
extra = {   # script-written from M373_delta.json / the O meta; bound by the dashboard text (no typed numbers)
    "sensitivity": {"baseGate": {"passed": O["meta"]["sensitivityBaseGate"]["passed"], "equalsLiveHeadline": O["meta"]["sensitivityBaseGate"]["base"], "nClean": O["meta"]["sensitivityBaseGate"]["nClean"]},
                    "provenanceMaxAbsDelta_O_minus_R": {k: max(abs(r[k]) for r in D["sensitivity"]["O_minus_R_provenance"]) for k in ("gen100", "trac100", "fgen", "etaBus")},
                    "provenanceMaxAbsDeltaUnrounded_O_minus_R": D["sensitivity"].get("unroundedMaxAbsDelta_O_minus_R"), "previousBlock": prevBlock},
    "simultaneity": {"deadbandMaxAbsDeltaPP_O_minus_R": {"primary_0.5kW": D["simultaneity"]["deadbandGrid"]["0.5_0.5"]["maxAbsDeltaPP_O_minus_R"], "grid_0.25_to_1.0kW": max(v["maxAbsDeltaPP_O_minus_R"] for v in D["simultaneity"]["deadbandGrid"].values())},
                     "epsilonKw": O["simultaneity"]["params"]},
    "speedSplit": {"validation": {**O["meta"]["speedSplitValidation"], "toleranceKwhPer100km": 0.01},
                   "provenanceMaxAbsDelta_O_minus_R": {"fGen": max(abs(r["fGen"]) for r in D["speedSplit"]["O_minus_R_provenance"] if r["fGen"] is not None)}}}
for b in todo:
    old = G[b]
    assert len(old) == len(vals[b]) and all(set(x) == set(y) for x, y in zip(old, vals[b])), (b, "row key sets differ")
    if b == "sensitivity":
        assert [x["axis"] for x in old] == [y["axis"] for y in vals[b]], "axis labels differ"
    N[b] = vals[b]
    refreshed.append({"block": b, "basisMilestone": "M373", "nDrives": nn[b][0], "nDays": nn[b][1], "rawBasis": "raw/ = sha256-verified originals (M366)",
                      "status": ("descriptive point values, no interval; drive set = all %d fuel-instrumented drives of fuel_recon_master.csv (includes drives with NaN f_gen and canonical outliers), not canonical-clean" % O["meta"]["driveIds"]["nAll"] if b == "speedSplit" else
                           "descriptive point values, no interval; drive set = headline definition (f_gen not NaN: %d of %d fuel-instrumented drives), not canonical-clean" % (O["meta"]["driveIds"]["nClean"], O["meta"]["driveIds"]["nAll"])),
                      "provenanceDelta": "O minus R (former per-sample raw, current master): provenance; R minus published: combined drive-set + code + basis drift, unattributed (analyses/M373_delta.json)",
                      "source": {"O": "analyses/M373_O_blocks.json sha256 " + sha("analyses/M373_O_blocks.json")[:16], "R": "analyses/M373_R_blocks.json sha256 " + sha("analyses/M373_R_blocks.json")[:16],
                                 "spec": "analyses/M373_spec.md sha256 " + O["meta"]["specSha256"][:16], "scripts": O["meta"]["scriptSha256"]}, **extra[b]})
N["refreshedBlocks"] = refreshed
# wording fixes in two rendered limitation paragraphs (Director string review; asserted verbatim; values only, no key renamed)
L4 = N["limitations"][4]
for old_txt, new_txt in [
    ("so its figures are current, not stale.", "so the M265 fix did not change them (the figures are on the 82-drive recovered file, pre-M366 basis; see the crossval label)."),
    ("The sensitivity table was recomputed to the current corpus at the corrected sign (M279). The headline corpus figures, drive-type split, RPM empirical-grounding sample (410 drives, refreshed M281), and the speed-binned traction split (M255) are current.",
     "The sensitivity table, the simultaneity table and the speed-binned traction split were refreshed at M373 on raw/ = sha256-verified originals (M366) as descriptive point values with no interval (see the refreshed-blocks line). The headline corpus figures, drive-type split and RPM empirical-grounding sample (410 drives, refreshed M281) are current."),
]:
    assert L4.count(old_txt) == 1, old_txt[:60]
    L4 = L4.replace(old_txt, new_txt)
N["limitations"][4] = L4
L5 = N["limitations"][5]
for old_txt, new_txt in [
    ("at the corrected M265 sign; its lost classification code was reconstructed and validated by the per-drive persample\u2192aggregate energy identity (exact) and by threshold-robustness of the four-state split. The corrected sign inverted the earlier (sign-flipped) reading: urban engine-on time is predominantly battery-CHARGING, not battery-assisting.",
     "at the M265 battery-current sign convention and refreshed at M373 on raw/ = sha256-verified originals; its lost classification code was reconstructed and checked by the per-drive persample\u2192aggregate energy identity (exact). The sign convention inverted the earlier (sign-flipped) reading: most urban engine-on time is classified as charge-and-drive or fully banked, not battery-assisting (point shares, no interval)."),
    ("and \u00a74a's M41/M42 decomposition applies to the high-speed gen+battery-discharge state \u2014 it is SoC-steering with generator headroom, not saturation.",
     "\u00a74a's M41/M42 decomposition of the high-speed gen+battery-discharge state reports SoC steering with generator headroom and no saturation (not tested here)."),
]:
    assert L5.count(old_txt) == 1, old_txt[:60]
    L5 = L5.replace(old_txt, new_txt)
N["limitations"][5] = L5
L6 = N["limitations"][6]
OLD6 = L6
assert "supply split by vehicle speed" in L6 and "all 145 fuel-instrumented drives" in L6, "limitations[6] changed"
N["limitations"][6] = ("The per-second \u2018supply split by vehicle speed\u2019 sub-analysis was rebuilt (M255) from recon_engine.py\u2019s per-drive reconstruction (central_estimate_v2_persample, a copy of the aggregate formula that additionally exposes per-second arrays) "
                       "and refreshed at M373 on raw/ = sha256-verified originals (M366). Before the speed-binned output was used, the per-drive sums were checked against fuel_recon_master.csv\u2019s figures to <0.01 kWh/100km; the number of drives checked and matched is stated in the speed-split text above "
                       "(script-written, from the M373 run). The 120+ bin is thin; read as indicative.")
sb = N["staleBlocks"]
sb["blocks"] = [b for b in sb["blocks"] if b not in todo]
sb["perBlock"] = [p for p in sb["perBlock"] if p["block"] not in todo]
assert [p["block"] for p in sb["perBlock"]] == sb["blocks"]


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            walk(a.get(k), b.get(k), f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{i}]")
    elif a != b:
        assert any(path.startswith("/generatorTractionRecon/" + k) for k in todo + ["refreshedBlocks", "staleBlocks", "limitations[4]", "limitations[5]", "limitations[6]"]), (path, a, b)


walk(A, new)
if DRY:
    print("dry run ok; would splice", todo, "; staleBlocks.blocks ->", sb["blocks"])
else:
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    print("spliced", todo, "; staleBlocks.blocks =", sb["blocks"])
