#!/usr/bin/env python3
"""M334 fuel contract (spec analyses/M334_spec.md rev 2): script-written disclosure block for the Fuel tab -> fuel_contract.json (repo root).
Every number is computed here from files (never typed): per-file fuel column presence and USABILITY in the canonical raw files, fuel_recon_master.csv,
the two fuel-energy constants in use, and the existing accumulator-subset spans in summary_arrays.json. The pipeline's own column names are IMPORTED
(recon_engine.CH); the lifetime app counter, the cost columns (O3: never surfaced) and the native OBD fuel-rate PID (g/s) are counted separately.
'Fuel present' per file = column present AND (counter: >= 2 non-null numeric values with max > min; rate: any value > 0). Fuel-like headers outside the known set
(schema drift) are listed in driftHeaders and the script exits 1 (fail loud) unless --allow-drift.
Usage: XT_RAW_DIR=<raw dir by master keys or raw/> python tools/fuel_contract.py [--out fuel_contract.json] [--allow-drift]"""
import csv, hashlib, json, os, re, sys
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from recon_engine import CH            # the pipeline's own column names (flow = L/h, used = counter in L)
import model_constants as MC

RAW = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
OUT = os.path.join(ROOT, "fuel_contract.json")
for i, a in enumerate(sys.argv):
    if a == "--out":
        OUT = sys.argv[i + 1]
ALLOW_DRIFT = "--allow-drift" in sys.argv

COUNTER, RATE = CH["used"], CH["flow"]
LIFETIME_COUNTER = "Використане паливо(загальний) (L)"
NATIVE_PID = ["Витрата палива в автомобілі (g/sec)", "Витрата палива у двигуні (g/sec)"]    # standard OBD fuel-rate PID (g/s)
COST_PREFIX = "Вартість палива"                                                         # O3: counted for drift detection only, never surfaced
KNOWN_OTHER = {   # fuel-like headers seen in the corpus (one-time scan 2026-10-02) that are NOT used by the pipeline
    "Використане паливо (Сьогодні) (L)", "Використане паливо (Тиждень) (L)", LIFETIME_COUNTER,
    "Миттєва витрата палива (л/год) (L/h)", "Середня витрата палива (л/100 км)(загальний) (L/100km)",
    "Середня витрата палива (л/100 км) (Тиждень) (L/100km)", "Середня витрата палива (л/100 км) (Сьогодні) (L/100km)",
    "Миттєва витрата палива (л/100 км) (L/100km)", "Середня витрата палива (л/100 км) (L/100km)",
    "Середня витрата палива (л/100 км) 10 sec (L/100km)", "Тиск у паливній рампі (kPa)", "Commanded Fuel Rail Pressure (kPa)",
    "Співвідношення паливо/повітря ()", "G03 Engine air/fuel ()", "Економайзер палива (на основі стану паливної системи та положення дросельної заслінки) ()",
    "Датчик кисню 1 (широкополосний) Корекція співвідношення паливно-повітряної суміші ()", "Fuel_Group_1 ()", "Fuel Group ()",
} | set(NATIVE_PID)
FUEL_LIKE = re.compile(r"(?i)паливо|палив|fuel|л/год|л/100|l/h|l/100")
digits = lambda s: re.sub(r"\D", "", str(s).rsplit(".", 1)[0])[:14]
md5 = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()

dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file", "date"])
idx = {digits(f): f for f in os.listdir(RAW) if f.lower().endswith(".csv") and not f.startswith("e4ORCE")}
recon = pd.read_csv(os.path.join(ROOT, "fuel_recon_master.csv"))
recon_keys = {digits(f) for f in recon["file"]}
rows, drift, header_set = [], {}, set()
for f, date in zip(dm["file"], dm["date"]):
    k = digits(f)
    p = os.path.join(RAW, idx[k])
    with open(p, encoding="utf-8-sig", newline="") as fh:
        hdr = next(csv.reader(fh))
    header_set.update(c for c in hdr if FUEL_LIKE.search(c))
    for c in hdr:
        if FUEL_LIKE.search(c) and c not in KNOWN_OTHER and c not in (COUNTER, RATE) and not c.startswith(COST_PREFIX):
            drift.setdefault(c, []).append(k)
    r = {"key": k, "date": str(date), "counterCol": COUNTER in hdr, "rateCol": RATE in hdr, "lifetimeCol": LIFETIME_COUNTER in hdr,
         "nativePid": any(c in hdr for c in NATIVE_PID), "counterOk": False, "rateOk": False, "rateN": 0}
    use = [c for c in (COUNTER, RATE) if c in hdr]
    if use:
        d = pd.read_csv(p, usecols=use, low_memory=False)
        if COUNTER in d:
            v = pd.to_numeric(d[COUNTER], errors="coerce").dropna()
            r["counterOk"] = bool(len(v) >= 2 and v.max() > v.min())
        if RATE in d:
            v = pd.to_numeric(d[RATE], errors="coerce").dropna()
            r["rateN"] = int(len(v)); r["rateOk"] = bool((v > 0).any())
    rows.append(r)
df = pd.DataFrame(rows)
n = len(df)
df["month"] = df["date"].str[:7]
usable = df[df.counterOk & df.rateOk]
first = df.loc[df.counterCol | df.rateCol, "date"].min()
by_month = {m: {"files": int(len(g)), "withFuelColumns": int((g.counterCol & g.rateCol).sum()), "usableBoth": int((g.counterOk & g.rateOk).sum())}
            for m, g in df.groupby("month")}
# gap between usable files and recon rows (reasons by script)
not_in_recon = df[(df.counterOk & df.rateOk) & ~df.key.isin(recon_keys)]
gap = {"usableBothNotInRecon": int(len(not_in_recon)), "ofWhich_rateSamplesLt10": int((not_in_recon.rateN < 10).sum()),
       "otherReasonNotClassified": int((not_in_recon.rateN >= 10).sum()),
       "reconRowsWithoutUsableBoth": int(sum(1 for k in recon_keys if k not in set(usable.key))),
       "reconRowsWithRateSamplesGe10ButNoFuelUse": int(sum(1 for k in recon_keys if k not in set(usable.key) and int(df.loc[df.key == k, "rateN"].iloc[0]) >= 10)),
       "note": "recon requires >= 10 numeric rate samples (fuel_recon.load_drive), not fuel use; trips with a logged but flat counter / zero rate (engine off) are in the recon rows but not 'usable' here"}
# fuel-energy constants in use
arr = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
e10 = round(MC.RHO_G_PER_L[0] * MC.LHV_MJ_PER_KG[0] / 1000.0 / 3.6, 4)       # g/L * MJ/kg / 1000 = MJ/L; / 3.6 = kWh/L
sb, tf, g = arr.get("socBalancedFuel") or {}, arr.get("thermalFuelPenalty") or {}, arr.get("generatorTractionRecon") or {}
lhv_sb = sb.get("lhvKwhPerL")
out = {
    "_provenance": "GENERATED by tools/fuel_contract.py (M334) from raw headers/values, fuel_recon_master.csv, model_constants and the arrays' accumulator-subset keys. Do not hand-edit.",
    "schemaVersion": 1,
    "inputs": {"driveMasterMd5": md5(os.path.join(ROOT, "drive_master.csv")), "fuelReconMasterMd5": md5(os.path.join(ROOT, "fuel_recon_master.csv")),
              "fuelLikeHeaderSetHash": hashlib.sha256("\n".join(sorted(header_set)).encode("utf-8")).hexdigest()},
    "definition": "fuel present per file = column present AND (counter: >= 2 numeric values with max > min; rate: any value > 0); counter = the pipeline's 'used' column, rate = its 'flow' column (recon_engine.CH)",
    "coverage": {
        "nCanonical": n,
        "counter": {"column": COUNTER, "columnPresent": int(df.counterCol.sum()), "usable": int(df.counterOk.sum())},
        "rate": {"column": RATE, "columnPresent": int(df.rateCol.sum()), "usable": int(df.rateOk.sum()), "withAtLeast10Samples": int((df.rateN >= 10).sum())},
        "bothUsable": int(len(usable)),
        "lifetimeAppCounter": {"column": LIFETIME_COUNTER, "columnPresent": int(df.lifetimeCol.sum()), "usedByPipeline": False},
        "nativeObdFuelRatePid_gPerS": {"columns": NATIVE_PID, "filesWithColumn": int(df.nativePid.sum()),
                                       "note": "standard OBD fuel-rate PID (rawManifest.pidCoverage.fuelRate counts this one); distinct from the logger app's calculated L/h and counter"},
        "firstDateWithFuelColumns": first, "byMonth": by_month,
        "gapUsableToReconRows": gap,
    },
    "recon": {"nRows": int(len(recon)), "method": sorted(set(recon["method"].astype(str))), "nChargeSustaining": int((recon["charge_sustaining"].astype(str) == "True").sum()),
              "dateFrom": str(recon["date"].min()), "dateTo": str(recon["date"].max()), "fuelBasis": g.get("fuelBasis"),
              "nProduction": g.get("nProduction"), "nCleanDrives": g.get("nDrives"), "kmProduction": g.get("kmProduction")},
    "lhvBases": [
        {"name": "SoC-balanced fuel (accumulator-subset scenario)", "kWhPerL": lhv_sb, "where": "summary_arrays.socBalancedFuel.lhvKwhPerL"},
        {"name": "Generator-traction reconstruction (E10)", "kWhPerL": e10, "where": f"model_constants: {MC.RHO_G_PER_L[0]:g} g/L x {MC.LHV_MJ_PER_KG[0]:g} MJ/kg"},
        {"name": "Cold-start thermal fuel view", "kWhPerL": None, "where": "L/h from the logged rate; no energy conversion"}],
    "lhvRatio": round(lhv_sb / e10, 4) if lhv_sb else None,
    "lhvRatioDefinition": "SoC-balanced constant / E10 constant",
    "lhvStatus": ("harmonised (M338): one assumed E10 basis (composition not measured)" if (lhv_sb and abs(lhv_sb - e10) < 5e-5)
                  else "unharmonised (audit C05): the two energy constants coexist; a single E10 basis changes a stored correction and has its own audit"),
    "subsets": {"socBalanced": {"nDrives": sb.get("nDrives"), "nDays": sb.get("nDays"), "dateSpan": sb.get("dateSpan")},
                "thermalPenalty": {"nColdStartDrives": tf.get("nColdStartDrives"), "nDays": tf.get("nDays"), "dateSpan": tf.get("dateSpan")}},
    "viewBasis": [
        {"view": "GeneratorTractionRecon", "litresFrom": "logged fuel rate (L/h) integrated per second", "kmFrom": "master distance_km", "energyBasis": "E10 constants", "status": "model-derived"},
        {"view": "SocBalancedFuel", "litresFrom": "logged fuel counter (L), reset-checked", "kmFrom": "speed integral", "energyBasis": "socBalancedFuel.lhvKwhPerL", "status": "observed figure + scenario correction (CAP_KWH 2.1 verified:false)"},
        {"view": "ThermalFuelPenalty", "litresFrom": "logged fuel rate (L/h) at matched RPM x load", "kmFrom": "not used", "energyBasis": "none", "status": "adjusted association"}],
    "statusLabels": {"loggedAppCalculated": "fuel rate and counter are calculated by the logger app (Car Scanner), not an ECU measurement",
                     "modelDerived": "generator, traction, battery-to-traction and efficiency indices", "scenario": "corrected SoC-balanced value", "association": "cold-start fuel-rate contrast"},
    "driftHeaders": {c: len(v) for c, v in sorted(drift.items())},
}
tmp = OUT + ".tmp"
with open(tmp, "w", encoding="utf-8", newline="\n") as f:
    json.dump(out, f, indent=1, ensure_ascii=False, sort_keys=False)
    f.write("\n")
os.replace(tmp, OUT)
print(json.dumps({"coverage": {k: out["coverage"][k] for k in ("nCanonical", "counter", "rate", "bothUsable")}, "recon": out["recon"], "lhvRatio": out["lhvRatio"], "drift": out["driftHeaders"]}, ensure_ascii=False, indent=1))
if drift and not ALLOW_DRIFT:
    sys.exit("FAIL LOUD: fuel-like headers outside the known set (schema drift): %s" % sorted(drift))
