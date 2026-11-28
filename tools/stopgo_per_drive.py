#!/usr/bin/env python3
"""M796 (analyses/M796_spec.md Rev 2): per-drive count of stop-and-go cycles (the M183 census, unchanged) as a tracked sidecar stopgo_per_drive.csv and the additive payload block S.stopGoPerDrive (histogram counts by drive type).
Display of values already computed: nothing is re-implemented, the sidecar calls compute_summary_arrays._csg_grid / _csg_events with the loaders of the released composition. The sidecar is keyed by the raw sha256 and a method hash of the whole chain.
STOP (exit 2) unless the sidecar reproduces the published S.crawlStopGo (rows == nDrivesCovered, sum n_cycles == nStopGoCycles, sum n_stops == nStops, per drive type n / median / p25 / p75 / p95).
Usage: python tools/stopgo_per_drive.py [--rebuild] [--check] [--dry-run]   (default: incremental update + additive splice)"""
import copy, datetime, hashlib, inspect, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

ARR = os.path.join(ROOT, "summary_arrays.json")
SIDECAR = os.path.join(ROOT, "stopgo_per_drive.csv")
MAX_BIN = 20
SMALL_N, TINY_N = 30, 10
SPEC_REV = "analyses/M796_spec.md Rev 2"
AUDIT_RECORD = {"specRev": "analyses/M796_spec.md Rev 2, section 9",
                "firstAudit": "independent implementation from the words of the definition: 712 covered, per-type n / median / quartiles identical, 4 of 712 drives differed (+5 cycles of 3257 against 3252) because the brief did not state the edge rules",
                "secondAudit": "the same auditor re-ran the four drives with the written edge rules only: 0 per-drive cycle differences; the rejected pairs are explained by the 30 km/h ceiling (peaks 33, 36, 50, 56, 65), the 1.5 km/h minimum (peak 0) and the grid rule; stop counts differed on 2 drives (3 against 4, 20 against 21) because the last stop reaches 3 s only through the forward fill after the last speed sample, which the census grid includes",
                "status": "cycle counts reproduced by an independent implementation given the stated edge rules; the rules are a reading of record, not independently validated against the M183 intent"}
COLS = ["file", "date", "drive_type", "raw_sha256", "method_hash", "n_cycles", "n_stops", "starts_low_speed", "low_speed_time_s", "duration_s"]


# ---------------------------------------------------------------- pure kernels (unit-tested)
def bin_counts(values, max_bin=MAX_BIN):
    """counts for the integer cycle counts 0..max_bin and the overflow ("max_bin + 1 or more")."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    counts = [int((v == k).sum()) for k in range(max_bin + 1)]
    return counts, int((v > max_bin).sum())


def med_iqr(values):
    """same arithmetic as compute_summary_arrays._csg_med_iqr (median rounded to 2, percentiles linear)."""
    x = np.asarray([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if not len(x):
        return None
    return {"median": round(float(np.median(x)), 2), "p25": round(float(np.percentile(x, 25)), 2), "p75": round(float(np.percentile(x, 75)), 2), "p95": round(float(np.percentile(x, 95)), 2), "n": int(len(x))}


def type_block(values):
    n = len(values)
    counts, over = bin_counts(values)
    q = med_iqr(values)
    s02 = sum(counts[:3]) / n if n else None
    s10 = (sum(counts[10:]) + over) / n if n else None
    return {"nDrives": n, "counts": counts, "overflow": over, "median": q["median"] if q else None, "p25": q["p25"] if q else None, "p75": q["p75"] if q else None, "p95": q["p95"] if q else None,
            "share0to2": None if s02 is None else round(s02, 4), "share10plus": None if s10 is None else round(s10, 4), "oneDrivePct": round(100.0 / n, 2) if n else None,
            "fewDrives": bool(n < SMALL_N), "countListOnly": bool(n < TINY_N)}


# ---------------------------------------------------------------- sidecar
def method_hash():
    import compute_summary_arrays as C
    parts = [inspect.getsource(f) for f in (C._csg_grid, C._csg_events, C._csg_pos, C._apply_speed_priority, C._ft)] + [repr(C._CSG_COLS)]
    parts.append(hashlib.sha256(open(os.path.join(ROOT, "drive_raw_cache.py"), "rb").read()).hexdigest())
    return hashlib.sha256("".join(parts).encode()).hexdigest()[:16]


def load_sidecar():
    if not os.path.exists(SIDECAR):
        return pd.DataFrame(columns=COLS)
    return pd.read_csv(SIDECAR, dtype={"raw_sha256": str, "method_hash": str}, keep_default_na=False, na_values=[""])


def build_rows(dm, rebuild=False):
    import compute_summary_arrays as C
    import drive_raw_cache as drc
    import regen_seasonal_raw as R
    fl = drc.make_frame_loader()
    mh = method_hash()
    old = {} if rebuild else {r["file"]: r for r in load_sidecar().to_dict("records")}
    rows, stats = [], {"reused": 0, "computed": 0, "noGrid": 0}
    for _, row in dm.iterrows():
        fn = row["file"]
        b = R.raw_loader(fn)
        digest = hashlib.sha256(b).hexdigest() if b else None
        o = old.get(fn)
        if o is not None and digest is not None and o["raw_sha256"] == digest and o["method_hash"] == mh:
            rows.append({k: o[k] for k in COLS}); stats["reused"] += 1; continue
        try:
            g = C._csg_grid(fn, R.raw_loader, fl)
        except Exception:
            g = None
        r = C._csg_events(g) if g is not None else None
        if r is None:
            stats["noGrid"] += 1; continue
        rows.append({"file": fn, "date": str(row.get("date"))[:10], "drive_type": row.get("drive_type"), "raw_sha256": digest, "method_hash": mh, "n_cycles": len(r["cycles"]), "n_stops": r["nStops"],
                     "starts_low_speed": r["startsLowSpeed"], "low_speed_time_s": r["lowSpeedTimeS"], "duration_s": float(row.get("duration_s") or 0.0)})
        stats["computed"] += 1
    return pd.DataFrame(rows, columns=COLS), stats


def write_sidecar(df):
    df.to_csv(SIDECAR, index=False, lineterminator="\n", encoding="utf-8", float_format="%.10g")


# ---------------------------------------------------------------- block and identity gates
def make_block(side, A, full=True):
    csg = A["crawlStopGo"]
    miss = []
    if len(side) != csg["nDrivesCovered"]:
        miss.append(("rows", len(side), csg["nDrivesCovered"]))
    if int(side["n_cycles"].sum()) != csg["nStopGoCycles"]:
        miss.append(("sumCycles", int(side["n_cycles"].sum()), csg["nStopGoCycles"]))
    if int(side["n_stops"].sum()) != csg["nStops"]:
        miss.append(("sumStops", int(side["n_stops"].sum()), csg["nStops"]))
    nan_type = int(side["drive_type"].isna().sum())
    types = {}
    for t, sub in side[side["drive_type"].notna()].groupby("drive_type"):
        types[str(t)] = type_block(sub["n_cycles"].astype(float).tolist())
    if sum(v["nDrives"] for v in types.values()) + nan_type != csg["nDrivesCovered"]:
        miss.append(("sumTypes", sum(v["nDrives"] for v in types.values()), csg["nDrivesCovered"]))
    for t, v in csg["byDriveType"].items():
        pub = v["cyclesPerDrive"]; mine = types.get(t)
        if mine is None or pub is None or (mine["nDrives"], mine["median"], mine["p25"], mine["p75"], mine["p95"]) != (pub["n"], pub["median"], pub["p25"], pub["p75"], pub["p95"]):
            miss.append(("type", t, None if mine is None else (mine["nDrives"], mine["median"], mine["p25"], mine["p75"], mine["p95"]), pub))
    if set(types) != set(csg["byDriveType"]):
        miss.append(("typeSet", sorted(types), sorted(csg["byDriveType"])))
    allv = side["n_cycles"].astype(float).tolist()
    block = {"_provenance": "GENERATED by tools/stopgo_per_drive.py (M796). Do not hand-edit.", "schemaVersion": 1, "specRev": SPEC_REV,
             "definition": "stop-and-go cycles per drive (count), M183 census (compute_summary_arrays._csg_events, default thresholds, unchanged). On the 1 s grid (1 s mean from the first to the last timestamp of the file, forward fill of at most 3 s, so up to 3 s after the last speed sample are grid seconds with the last speed): a stop is a run of at least 3 consecutive grid seconds with speed below 1.5 km/h (a missing second ends a run); a cycle is a pair of consecutive stops at least 2 s apart whose speed peak on the grid between them, the two stop-end seconds included, is at least 1.5 and at most 30 km/h and whose interior has a finite value. Drive type = the master drive_type label (descriptive); counts are per drive, not per km or per minute",
             "bins": {"max": MAX_BIN, "overflow": f"{MAX_BIN + 1} or more"}, "types": types, "all": type_block(allv),
             "captionLadder": {"numeric": "N drives; median M cycles per drive, middle half P25 to P75; S02 % have 0 to 2 cycles, S10 % have 10 or more", "moreThanHalfTwoOrFewerIf": "share0to2 > 0.5", "oneInTenHasTenOrMoreIf": "share10plus >= 0.1"},
             "reconciliation": {"auditRecord": AUDIT_RECORD, "rows": int(len(side)), "nDrivesCovered": csg["nDrivesCovered"], "sumCycles": int(side["n_cycles"].sum()), "nStopGoCycles": csg["nStopGoCycles"], "sumStops": int(side["n_stops"].sum()), "nStops": csg["nStops"],
                                "driveTypeMissing": nan_type, "identityMisses": len(miss), "identityOk": not miss},
             "provenance": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "methodHash": method_hash() if full else None, "sidecar": {"file": "stopgo_per_drive.csv", "sha256": hashlib.sha256(open(SIDECAR, "rb").read()).hexdigest(), "rows": int(len(side))}},
             "limits": ["a count of cycles on one drive, not a rate and not a property of the car; drives differ in length, low-speed time, route and season", "shares are shares of drives; drives cluster by day; no interval, test or verdict",
                        "drive types are the master's descriptive labels; no comparison between types is drawn and no cause is implied", "cycles are detected from logged speed under the M183 thresholds, not measured"]}
    return json.loads(json.dumps(block, default=float)), miss


def splice(block):
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("stopGoPerDrive", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "stopGoPerDrive"}
    A2["stopGoPerDrive"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["provenance"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M796: computed by tools/stopgo_per_drive.py from the raw bytes through the M183 census functions; additive, no published value recomputed; not M299-reproducible.", upstreamHashes={"driveMasterMd5": block["provenance"]["driveMasterMd5"]})
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["stopGoPerDrive"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "stopGoPerDrive"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)


def main():
    A = json.load(open(ARR, encoding="utf-8"))
    if "--check" in sys.argv:
        side = load_sidecar()
        block, miss = make_block(side, A, full=False)      # --check must run where only the declared files exist: the method hash is provenance and is not recomputed
        pub = A.get("stopGoPerDrive")
        same = pub is not None and json.dumps({k: v for k, v in pub.items() if k != "provenance"}, sort_keys=True) == json.dumps({k: v for k, v in block.items() if k != "provenance"}, sort_keys=True)
        print(json.dumps({"check": "stopGoPerDrive", "identityOk": not miss, "misses": miss[:3], "matchesPayload": same, "rows": int(len(side))}, default=float))
        sys.exit(0 if (not miss and same) else 2)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    side, stats = build_rows(dm, rebuild="--rebuild" in sys.argv)
    write_sidecar(side)
    side = load_sidecar()
    block, miss = make_block(side, A)
    print(json.dumps({"stats": stats, "rows": int(len(side)), "identityOk": not miss, "misses": miss[:5], "types": {t: (v["nDrives"], v["median"]) for t, v in block["types"].items()}}, default=float))
    if miss:
        print("STOP: the sidecar does not reproduce the published crawlStopGo"); sys.exit(2)
    if "--dry-run" not in sys.argv:
        splice(block); print(json.dumps({"stopGoPerDrive": "written"}))


if __name__ == "__main__":
    main()
