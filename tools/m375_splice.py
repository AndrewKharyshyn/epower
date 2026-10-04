#!/usr/bin/env python3
"""M375 splice (analyses/M375_spec.md Rev 2): align the GTR family to canonical-clean eligibility in ONE deep-diff-allow-listed pass.
 1. Headline: the REAL ingestion stage refresh_gtr_headline.py is run in a scratch directory on copies of the inputs (so the repo payload is never written by a producer); only the allow-listed
    headline paths of its output are copied back (generatorTractionRecon.{nProduction, nDrives, kmProduction, corpus, flows, driveTypeSplit, productionCheck, basis, glossary} and the seasonal
    entry seasonalCharts.charts.GeneratorTractionRecon); anything else that the stage changes is a STOP.
 2. sensitivity / simultaneity / speedSplit: values replaced from analyses/M375_O_blocks.json (row key sets equal); refreshedBlocks entries rebuilt (previousBlock carried forward).
 3. gtrClosure.scope.excludedNote regenerated from the files (tools/gtr_closure_block.py, M372 mode); every other key of the block must be unchanged.
 4. additive generatorTractionRecon.eligibilityAlignment: previous / current counts, the excluded drives with reasons, the changed fields per view and the disclosure note (all script-written).
Refuses unless: both points passed their gates, analyses/M375_delta.json has no breach / flip / expected-value mismatch, and summary_arrays.json sha256 equals the value recorded at the start of the runs.
Usage: M375_ARRAYS_SHA16=<sha16> python tools/m375_splice.py [--dry-run]"""
import copy, hashlib, json, os, shutil, subprocess, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
DRY = "--dry-run" in sys.argv
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
O = json.load(open("analyses/M375_O_blocks.json", encoding="utf-8"))
delta = json.load(open("analyses/M375_delta.json", encoding="utf-8"))
if not delta["summary"]["gatesPassed"] or not delta["specShaEqualBothPoints"] or delta["summary"]["nBreaches"] or delta["summary"]["nFlips"] or delta.get("expectedMismatches"):
    raise SystemExit("gates / breaches / flips / expected-value mismatches present: %s" % json.dumps(delta["summary"]))
raw = open("summary_arrays.json", "rb").read()
exp = os.environ.get("M375_ARRAYS_SHA16")
if not exp or hashlib.sha256(raw).hexdigest()[:16] != exp:
    raise SystemExit("summary_arrays.json changed since the runs started (or M375_ARRAYS_SHA16 not set)")
A = json.loads(raw.decode("utf-8"))
G = A["generatorTractionRecon"]
new = copy.deepcopy(A)
N = new["generatorTractionRecon"]

# ---- 1. headline via the real ingestion stage in a scratch directory ----
td = tempfile.mkdtemp(prefix="m375_refresh_")
try:
    for f in ("fuel_recon_master.csv", "seasonal_drive_master.csv", "drive_master.csv", "summary_arrays.json", "eligibility.py", "wire_gtr_seasonal.py", "refresh_gtr_headline.py"):
        shutil.copyfile(f, os.path.join(td, f))
    r = subprocess.run([sys.executable, "refresh_gtr_headline.py"], cwd=td, capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, PYTHONUTF8="1"))
    if r.returncode != 0:
        raise SystemExit("refresh_gtr_headline.py failed: " + r.stderr[-600:])
    B = json.load(open(os.path.join(td, "summary_arrays.json"), encoding="utf-8"))
finally:
    shutil.rmtree(td, ignore_errors=True)
HEAD_KEYS = ["nProduction", "nDrives", "kmProduction", "corpus", "flows", "driveTypeSplit", "productionCheck", "basis", "glossary"]
SEAS = ("seasonalCharts", "charts", "GeneratorTractionRecon")
allowed_stage = ["/generatorTractionRecon/" + k for k in HEAD_KEYS] + ["/seasonalCharts/charts/GeneratorTractionRecon"]


def walk(a, b, ok, path="", out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            walk(a.get(k), b.get(k), ok, f"{path}/{k}", out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, ok, f"{path}[{i}]", out)
    elif a != b:
        if not any(path.startswith(p) for p in ok):
            raise SystemExit("unexpected change %s" % path)
        out.append(path)
    return out


walk(A, B, allowed_stage)                      # the stage may change ONLY the allow-listed paths
for k in HEAD_KEYS:
    N[k] = B["generatorTractionRecon"][k]
new["seasonalCharts"]["charts"]["GeneratorTractionRecon"] = B["seasonalCharts"]["charts"]["GeneratorTractionRecon"]

# ---- 2. the three blocks and refreshedBlocks ----
D = delta["blocks"]
strip = lambda rows, keys: [{k: r[k] for k in keys} for r in rows]
vals = {"sensitivity": strip(O["sensitivity"]["axes"], ["axis", "gen100", "trac100", "fgen", "etaBus"]), "simultaneity": O["simultaneity"]["rows"], "speedSplit": O["speedSplit"]["bins"]}
nn = {"sensitivity": (O["sensitivity"]["nDrives"], O["sensitivity"]["nDays"]), "simultaneity": (O["simultaneity"]["nDrives"], O["simultaneity"]["nDays"]), "speedSplit": (O["speedSplit"]["nDrives"], O["speedSplit"]["nDays"])}
old_rb = {p["block"]: p for p in G["refreshedBlocks"]}
import pandas as pd
n_fuel = int(len(pd.read_csv("fuel_recon_master.csv")))
n_can = O["meta"]["driveIds"]["nAll"]            # canonical-clean fuel-instrumented drives in the producers' cache
extra = {
    "sensitivity": {"baseGate": {"passed": O["meta"]["sensitivityBaseGate"]["passed"], "equalsLiveHeadline": O["meta"]["sensitivityBaseGate"]["base"], "nClean": O["meta"]["sensitivityBaseGate"]["nClean"]},
                    "provenanceMaxAbsDelta_O_minus_R": {k: max(abs(r[k]) for r in D["sensitivity"]["O_minus_R_provenance"]) for k in ("gen100", "trac100", "fgen", "etaBus")},
                    "provenanceMaxAbsDeltaUnrounded_O_minus_R": D["sensitivity"].get("unroundedMaxAbsDelta_O_minus_R"), "previousBlock": old_rb["sensitivity"]["previousBlock"]},
    "simultaneity": {"deadbandMaxAbsDeltaPP_O_minus_R": {"primary_0.5kW": D["simultaneity"]["deadbandGrid"]["0.5_0.5"]["maxAbsDeltaPP_O_minus_R"], "grid_0.25_to_1.0kW": max(v["maxAbsDeltaPP_O_minus_R"] for v in D["simultaneity"]["deadbandGrid"].values())},
                     "epsilonKw": O["simultaneity"]["params"]},
    "speedSplit": {"validation": {**O["meta"]["speedSplitValidation"], "toleranceKwhPer100km": 0.01},
                   "provenanceMaxAbsDelta_O_minus_R": {"fGen": max(abs(r["fGen"]) for r in D["speedSplit"]["O_minus_R_provenance"] if r["fGen"] is not None)}}}
rb = []
for b in ("sensitivity", "simultaneity", "speedSplit"):
    old = G[b]
    assert len(old) == len(vals[b]) and all(set(x) == set(y) for x, y in zip(old, vals[b])), (b, "row key sets differ")
    if b == "sensitivity":
        assert [x["axis"] for x in old] == [y["axis"] for y in vals[b]], "axis labels differ"
    N[b] = vals[b]
    n_set = O["meta"]["driveIds"]["nClean"] if b != "speedSplit" else n_can
    rb.append({"block": b, "basisMilestone": old_rb[b]["basisMilestone"], "rerunMilestone": "M375", "nDrives": nn[b][0], "nDays": nn[b][1], "rawBasis": "raw/ = sha256-verified originals (M366)",
               "status": "descriptive point values, no interval; drive set = canonical-clean (ens_outlier_v2), %d of %d fuel-instrumented drives; re-run at M375 after the eligibility alignment" % (n_set, n_fuel),
               "provenanceDelta": "O minus R (former per-sample raw, current master): provenance; R minus published: combined drive-set + code + basis drift, unattributed (analyses/M375_delta.json)",
               "source": {"O": "analyses/M375_O_blocks.json sha256 " + sha("analyses/M375_O_blocks.json")[:16], "R": "analyses/M375_R_blocks.json sha256 " + sha("analyses/M375_R_blocks.json")[:16],
                          "spec": "analyses/M375_spec.md sha256 " + O["meta"]["specSha256"][:16], "expected": "analyses/M375_expected.json sha256 " + sha("analyses/M375_expected.json")[:16], "scripts": O["meta"]["scriptSha256"]}, **extra[b]})
N["refreshedBlocks"] = rb

# ---- 3. closure set note regenerated from the files; every other key of the block unchanged ----
if "--m372" not in sys.argv:
    sys.argv.append("--m372")
import gtr_closure_block as GB
cb = GB.build()
oldc = copy.deepcopy(G["gtrClosure"])
newc = copy.deepcopy(cb)
assert oldc["scope"]["excludedNote"] != newc["scope"]["excludedNote"]
oldc["scope"]["excludedNote"] = newc["scope"]["excludedNote"]
assert oldc == newc, "the regenerated closure block differs from the published one beyond scope.excludedNote"
N["gtrClosure"] = cb

# ---- 4. eligibilityAlignment (script-written record + disclosure note) ----
import wire_gtr_seasonal as W
merged = W.load_merged()
exc = merged[merged["ens_excluded"]]
excluded = [{"file": r.file, "drive_type": r.drive_type, "date": str(r.date), "km": float(r.distance_km), "fGenIsNaN": bool(pd.isna(r.f_gen)), "regime": r.thermal_regime, "reason": "ens_outlier_v2 / ens_invalid flagged in drive_master.csv"} for r in exc.itertuples()]
prev = {k: G[k] for k in ("nProduction", "nDrives", "kmProduction")}
cur = {k: N[k] for k in ("nProduction", "nDrives", "kmProduction")}


def flat(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flat(v, p + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from flat(v, f"{p}[{i}]")
    else:
        yield p, o


oldE, newE = A["seasonalCharts"]["charts"]["GeneratorTractionRecon"]["data"], new["seasonalCharts"]["charts"]["GeneratorTractionRecon"]["data"]
changed = {}
for view in ("all", "warm", "shoulder"):
    fo, fn = dict(flat(oldE[view])), dict(flat(newE[view]))
    changed[view] = {k: [fo.get(k), fn.get(k)] for k in sorted(set(fo) | set(fn)) if fo.get(k) != fn.get(k) and not k.startswith("/basis")}
corpus_same = {v: all(not k.startswith("/corpus") for k in changed[v]) for v in changed}
clause = []
clause.append("All-view corpus values are unchanged at published precision" if corpus_same["all"] else "All-view corpus fields changed: " + ", ".join(f"{k} {a} to {b}" for k, (a, b) in changed["all"].items() if k.startswith("/corpus")))
for v in ("warm", "shoulder"):
    cf = {k: ab for k, ab in changed[v].items()}
    clause.append(f"{v.title()}: " + ("; ".join(f"{k[1:].replace('/', ' ')} {a} to {b}" for k, (a, b) in cf.items()) if cf else "no field changed"))
note = ("Eligibility aligned to canonical-clean (ens_outlier_v2) in M375 (a definition change, not a correction; the key nProduction now counts canonical-clean fuel-instrumented drives). "
        f"Previous counts {prev['nProduction']} / {prev['nDrives']} / {prev['kmProduction']} km (nProduction / nDrives / km), now {cur['nProduction']} / {cur['nDrives']} / {cur['kmProduction']} km. "
        "Excluded fuel-instrumented drives: " + "; ".join(f"{e['file'].replace('.csv', '')} ({e['drive_type']}, {e['km']} km, {'f_gen NaN' if e['fGenIsNaN'] else 'f_gen present'})" for e in excluded) + ". " + "; ".join(clause) + ".")
# the P_aux-low row: the published M373 row was computed on a different drive set from the other rows (counts read from the committed M373 O run); sentence written from data, no typed numbers
old_ax = {r["axis"]: r["nClean"] for r in json.load(open("analyses/M373_O_blocks.json", encoding="utf-8"))["sensitivity"]["axes"]}
pa = next(a for a in old_ax if a.startswith("P_aux low"))
n_old_other = sorted({v for a, v in old_ax.items() if a != pa})
new_ax = {r["axis"]: r["nClean"] for r in O["sensitivity"]["axes"]}
assert len(set(new_ax.values())) == 1 and set(new_ax.values()) == {O["meta"]["driveIds"]["nClean"]}, "after alignment every sensitivity axis must use the same drive set"
assert len(n_old_other) == 1, "the other published axes used different sets"
n_new = O["meta"]["driveIds"]["nClean"]
k_other = sum(1 for e in excluded if not e["fGenIsNaN"])
k_pa = len(excluded) if old_ax[pa] == n_fuel else None
old_pa = next(r for r in G["sensitivity"] if r["axis"] == pa)
new_pa = next(r for r in N["sensitivity"] if r["axis"] == pa)
plural = lambda k: f"{k} canonical outlier" + ("" if k == 1 else "s")
sens_note = (f"Set alignment, not a method change: the previous {pa.split(' (')[0]} row was computed on {old_ax[pa]} drives and all other rows on {n_old_other[0]} (the previous rows included {plural(k_other)}"
             + (f", the {pa.split(' (')[0]} row {k_pa}" if k_pa is not None else "") + f"); all rows now use the same {n_new} canonical-clean drives; the {pa.split(' (')[0]} row moves by {new_pa['gen100'] - old_pa['gen100']:+.2f} / {new_pa['trac100'] - old_pa['trac100']:+.2f} kWh/100 km (generator / traction).")
N["eligibilityAlignment"] = {"milestone": "M375", "rule": "canonical-clean: ens_outlier_v2 or ens_invalid explicitly True excludes a drive (single source drive_master.csv; eligibility.py)", "previous": prev, "current": cur, "nFuelInstrumentedRows": n_fuel,
                             "excluded": excluded, "sensitivityNote": sens_note, "changedFields": changed, "corpusUnchangedAtPublishedPrecision": corpus_same, "note": note,
                             "source": {"effect": "analyses/M375_eligibility_effect.json sha256 " + sha("analyses/M375_eligibility_effect.json")[:16], "spec": "analyses/M375_spec.md sha256 " + O["meta"]["specSha256"][:16]}}

# ---- deep diff: only the allow-listed paths changed ----
ALLOW = allowed_stage + ["/generatorTractionRecon/" + b for b in ("sensitivity", "simultaneity", "speedSplit", "refreshedBlocks", "eligibilityAlignment")] + ["/generatorTractionRecon/gtrClosure/scope/excludedNote"]
changed_paths = walk(A, new, ALLOW)
if DRY:
    print("dry run ok;", len(changed_paths), "changed leaves;", note[:200])
else:
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    print("spliced;", len(changed_paths), "changed leaves")
