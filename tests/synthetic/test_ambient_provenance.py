"""M352 known-answer test of ambientTable.{provenanceByCohort, meanKindByCohort, definitions, rows[].mk}: counts recomputed independently from
summary_config.json ambientByDrive + seasonal_drive_master.csv (kinds from the reading count, not from the stored kind)."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
import pandas as pd
a = json.load(open("summary_arrays.json", encoding="utf-8"))["ambientTable"]
cfg = json.load(open("summary_config.json", encoding="utf-8"))["ambientByDrive"]
sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False).set_index("file")
fails = 0
def ok(l, c, e=""):
    global fails
    print(("PASS " if c else "FAIL ") + l + ((" - " + str(e)) if (not c and e) else "")); fails += 0 if c else 1
def nread(v): return len(v) if isinstance(v, list) else 1
kind = lambda n: "singleValue" if n == 1 else ("endpointPair" if n == 2 else "trapezoidal")
reg = sdm["thermal_regime_raw"].astype(str)
for c in ("all", "warm", "shoulder", "cold"):
    files = list(sdm.index) if c == "all" else list(sdm.index[reg == c])
    exp = {"trapezoidal": 0, "endpointPair": 0, "singleValue": 0}
    for f in files: exp[kind(nread(cfg[f]))] += 1
    ok(f"{c}: mean-kind counts equal the counts recomputed from the number of readings ({exp})", a["meanKindByCohort"][c] == exp, a["meanKindByCohort"][c])
    p = a["provenanceByCohort"][c]
    ok(f"{c}: n = {len(files)}, recorded + substituted = n, mixed 0", p["n"] == len(files) and p["recorded"] + p["substituted"] == p["n"] and p["mixedSource"] == 0, p)
ok("cohorts sum to 489", sum(a["provenanceByCohort"][c]["n"] for c in ("warm", "shoulder", "cold")) == a["provenanceByCohort"]["all"]["n"] == 489)
ok("single readings == nSingleValueLegacy", a["meanKindByCohort"]["all"]["singleValue"] == a["nSingleValueLegacy"])
code = {"t": "trapezoidal", "e": "endpointPair", "s": "singleValue"}
ok("every row mk matches its reading count", all(code[r["mk"]] == kind(len(r["a"]) if not r.get("s") else 1) for r in a["rows"]))
ok("definitions present: thermal class, battery vs ambient, aux load (start reading only), scope", len(a["definitions"]) == 4 and "equal intervals" in a["definitions"][0]["definition"] and "END reading" in a["definitions"][1]["definition"])
arr = json.load(open("summary_arrays.json", encoding="utf-8"))
ok("keys named in the definitions exist: batteryVsAmbient, belowAmbient, auxLoadAmbient", all(k in arr for k in ("batteryVsAmbient", "belowAmbient", "auxLoadAmbient")))
print("AMBIENT_PROVENANCE FAILS =", fails); sys.exit(1 if fails else 0)
