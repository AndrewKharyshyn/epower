#!/usr/bin/env python3
"""M535 (analyses/M535_spec.md Rev 4): day-clustered intervals and the 4-type breakdown of the logged distance mix, as an additive sibling payload key observedMixDetail (+ stamp) of observedMix (which is NOT changed).
Master-only (no raw): per-drive sidecar driving_mix_sidecar.csv (tracked; file, date, drive_type, distance_km, distance_source, repaired, ens_outlier_v2) keyed to the master MD5 in driving_mix_sidecar.meta.json.
Share of logged km by drive type = ratio of sums; day-clustered percentile bootstrap (calendar day = cluster, seed 42, 4000 draws); ISO-week block sensitivity; leave-one-day-out; exclusion accounting.
Primary population = the observedMix population (ens_outlier_v2-clean, drive_type known) so the displayed shares tie out (STOP on mismatch); sensitivities: all valid-distance drives, repaired-distance share, dates up to 2026-07-14.
Usage: python tools/driving_mix.py [--dry-run] [--check]"""
import copy, datetime, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd

KEY = "observedMixDetail"
SIDECAR = os.path.join(ROOT, "driving_mix_sidecar.csv")
META = os.path.join(ROOT, "driving_mix_sidecar.meta.json")
SPEC = "analyses/M535_spec.md"
NB, SEED = 4000, 42
TYPES = ("urban", "mixed", "mixed_highway", "highway")
CLASS_OF = {"urban": "city", "mixed": "mixed", "mixed_highway": "highway", "highway": "highway"}
SNAPSHOT_DATE = "2026-07-14"
TIE_PP, TIE_KM = 0.1, 0.1


def _as_bool(s):
    return s.map(lambda v: str(v).strip().lower() in ("true", "1", "1.0")).astype(bool)


def build_sidecar(dm):
    sc = pd.DataFrame({"file": dm["file"], "date": dm["date"].astype(str), "drive_type": dm["drive_type"].fillna("unknown").astype(str), "distance_km": pd.to_numeric(dm["distance_km"], errors="coerce"),
                       "distance_source": dm["distance_source"].fillna("").astype(str), "repaired": _as_bool(dm["distance_reset_repaired"]), "ens_outlier_v2": _as_bool(dm["ens_outlier_v2"])})
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    return sc, md5


def write_sidecar(sc, md5):
    with open(SIDECAR, "w", encoding="utf-8", newline="\n") as f:
        sc.to_csv(f, index=False, lineterminator="\n")
    json.dump({"masterMd5": md5, "columns": list(sc.columns), "note": "derived from drive_master.csv only; no raw input"}, open(META, "w", encoding="utf-8", newline="\n"), indent=1)


def _day_matrix(d, cluster, cats):
    """cluster x category km matrix"""
    pv = d.pivot_table(index=cluster, columns="drive_type", values="distance_km", aggfunc="sum", fill_value=0.0)
    return pv.reindex(columns=list(cats), fill_value=0.0).values.astype(float), pv.index.values


def _shares(M, cats):
    """M: (..., ncat) km sums -> dict name -> pct arrays (types, classes, highway-blended)"""
    tot = M.sum(-1)
    ix = {c: i for i, c in enumerate(cats)}
    out = {t: 100 * M[..., ix[t]] / tot for t in cats if t in TYPES}
    out["city"] = out["urban"]
    out["highwayClass"] = out["mixed_highway"] + out["highway"]
    out["mixedClass"] = out["mixed"]
    out["highwayBlended"] = out["highwayClass"]
    if "unknown" in ix:
        out["unknown"] = 100 * M[..., ix["unknown"]] / tot
    return out


def estimate(d, cluster, cats, nb=NB):
    M, _ = _day_matrix(d, cluster, cats)
    nd = len(M)
    point = _shares(M.sum(0), cats)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, nd, (nb, nd))
    draws = _shares(M[idx].sum(1), cats)
    res = {k: {"pct": round(float(point[k]), 3), "ci95Pct": [round(float(x), 3) for x in np.percentile(draws[k], [2.5, 97.5])]} for k in point}
    # leave-one-day-out shift of the highway-class share
    tot = M.sum(0)
    base = float(point["highwayClass"])
    loo = []
    for i in range(nd):
        s = _shares(tot - M[i], cats)["highwayClass"] if nd > 1 else base
        loo.append(float(s) - base)
    return res, nd, {"maxAbsPp": round(float(np.max(np.abs(loo))), 3)}


def population(d, label, cats):
    """d: drives of the population (valid distance); returns the block"""
    d = d.copy()
    d["week"] = pd.to_datetime(d["date"]).dt.strftime("%G-W%V")
    day, nd, lodo = estimate(d, "date", cats)
    wk, nw, _ = estimate(d, "week", cats)
    km = d.groupby("drive_type")["distance_km"].sum()
    ndays_by = d.groupby("drive_type")["date"].nunique()
    ndrv_by = d.groupby("drive_type")["file"].nunique()
    rows = {}
    for k in day:
        rows[k] = {**day[k], "weekCi95Pct": wk[k]["ci95Pct"]}
    types = {t: {**rows[t], "km": round(float(km.get(t, 0.0)), 1), "nDrives": int(ndrv_by.get(t, 0)), "nDays": int(ndays_by.get(t, 0)), "fewDays": bool(ndays_by.get(t, 0) < 10)} for t in cats if t in TYPES}
    classes = {"city": rows["city"], "mixed": rows["mixedClass"], "highway": rows["highwayClass"]}
    wid = (wk["highwayClass"]["ci95Pct"][1] - wk["highwayClass"]["ci95Pct"][0]) / max(1e-9, day["highwayClass"]["ci95Pct"][1] - day["highwayClass"]["ci95Pct"][0])
    out = {"label": label, "nDrives": int(len(d)), "nDays": int(nd), "nWeeks": int(nw), "km": round(float(d["distance_km"].sum()), 1), "byType": types, "byClass": classes,
           "highwayBlended": rows["highwayBlended"], "weekToDayWidthRatioHighway": round(float(wid), 3), "leaveOneDayOutHighway": lodo}
    if "unknown" in rows:
        out["unknown"] = {**rows["unknown"], "km": round(float(km.get("unknown", 0.0)), 1)}
    return out


def compute(sc, A):
    valid = sc[np.isfinite(sc["distance_km"]) & (sc["distance_km"] > 0)]
    known = valid[valid["drive_type"].isin(TYPES)]
    clean = known[~known["ens_outlier_v2"]]
    cats = TYPES
    out = {"primary": population(clean, "observedMix population: ens_outlier_v2-clean, drive_type known, distance_km > 0", cats)}
    out["sensitivityAllValidDistance"] = population(valid, "all drives with distance_km > 0 (unknown drive_type shown separately)", TYPES + ("unknown",))
    rep = valid[valid["repaired"]]
    out["repairedDistance"] = {"nDrives": int(len(rep)), "km": round(float(rep["distance_km"].sum()), 1), "pctOfAllValidKm": round(float(100 * rep["distance_km"].sum() / valid["distance_km"].sum()), 4),
                               "distanceSources": {k: int(v) for k, v in valid.groupby("distance_source")["file"].nunique().items()}}
    old = clean[clean["date"] <= SNAPSHOT_DATE]
    out["sensitivityUpTo20260714"] = population(old, "primary population restricted to dates up to " + SNAPSHOT_DATE + " (reproduction basis of the former typed snapshot; reported, not tuned)", cats)
    acc = {"masterDrives": int(len(sc)), "nPrimary": int(len(clean)),
           "excluded": {"ensOutlierV2": {"nDrives": int((known["ens_outlier_v2"]).sum()), "km": round(float(known[known["ens_outlier_v2"]]["distance_km"].sum()), 1)},
                        "unknownDriveType": {"nDrives": int((~valid["drive_type"].isin(TYPES)).sum()), "km": round(float(valid[~valid["drive_type"].isin(TYPES)]["distance_km"].sum()), 1)},
                        "invalidDistance": {"nDrives": int(len(sc) - len(valid)), "km": 0.0}}}
    acc["reconciles"] = bool(acc["nPrimary"] + acc["excluded"]["ensOutlierV2"]["nDrives"] + acc["excluded"]["unknownDriveType"]["nDrives"] + acc["excluded"]["invalidDistance"]["nDrives"] == acc["masterDrives"])
    out["exclusionAccounting"] = acc
    # tie-out with the displayed observedMix
    om = A["observedMix"]
    pc = out["primary"]["byClass"]
    tie = {"shares": {c: {"detail": pc[c]["pct"], "observedMix": om["observedShare"][c], "ok": bool(abs(round(pc[c]["pct"], 1) - om["observedShare"][c]) <= TIE_PP)} for c in ("city", "mixed", "highway")},
           "km": {"detail": out["primary"]["km"], "observedMix": om["typedKm"], "ok": bool(abs(out["primary"]["km"] - om["typedKm"]) <= TIE_KM)},
           "n": {"detail": out["primary"]["nDrives"], "observedMix": om["n"], "ok": bool(out["primary"]["nDrives"] == om["n"])}}
    tie["passed"] = bool(all(v["ok"] for v in tie["shares"].values()) and tie["km"]["ok"] and tie["n"]["ok"])
    out["tieOut"] = tie
    tot_valid = float(valid["distance_km"].sum())
    unk_pct = float(100 * valid[~valid["drive_type"].isin(TYPES)]["distance_km"].sum() / tot_valid)
    p = out["primary"]
    out["tripwires"] = {"unknownOver2PctOfKm": bool(unk_pct > 2), "unknownPctOfKm": round(unk_pct, 3), "typeUnder10Days": [t for t, v in p["byType"].items() if v["fewDays"]],
                        "weekWiderThan1.5xDay": bool(p["weekToDayWidthRatioHighway"] > 1.5), "leaveOneDayOutHighwayOver5pp": bool(p["leaveOneDayOutHighway"]["maxAbsPp"] > 5)}
    return out


def build_block(dm, A):
    sc, md5 = build_sidecar(dm)
    r = compute(sc, A)
    sha = lambda f: hashlib.sha256(open(os.path.join(ROOT, f), "rb").read()).hexdigest()
    return sc, md5, {"estimand": "share of logged km by drive_type (ratio of sums), the three planning classes of observedMix and the highway-blended share (highway + mixed_highway)",
                     "basis": "share of logged km by drive type (day-resampled interval; day-to-day heterogeneity of a convenience sample, not representativeness); drive_type is the M21 classification of the master; distance_km as in the master",
                     "descriptive": True, "displayed": "highway class interval only (the driving-mix-bias paragraph)", "intervalNote": "compositional shares: the intervals of the types and classes are never added or contrasted",
                     "method": {"cluster": "calendar day", "draws": NB, "seed": SEED, "interval": "percentile", "sensitivity": "ISO-week block resample", "leaveOneDayOut": "highway class shift"}, **r,
                     "limits": ["convenience sample: the logged mix is not representative of real use", "no mapping to the 55/30/15 or 40/10/50 scenarios", "the day interval does not capture serial correlation inside multi-day trips (week sensitivity beside it)",
                                "the interval is not a test of the June / July trips clause"],
                     "provenance": {"spec": SPEC, "specSha256": sha(SPEC), "toolSha256": sha("tools/driving_mix.py"), "sidecar": "driving_mix_sidecar.csv", "masterMd5": md5}}


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new[KEY] = blk
    old = (A.get("_artifactStamps") or {}).get(KEY)
    if old and A.get(KEY) == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"][KEY] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M535: derived by tools/driving_mix.py from drive_master.csv only (driving_mix_sidecar.csv)", upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
        import stamp_common as _sc
        new["_artifactStamps"][KEY] = _sc.carry_declared(old, st)
    ch = [k for k in set(A) | set(new) if A.get(k) != new.get(k)]
    bad = [k for k in ch if k not in (KEY, "_artifactStamps")]
    st_bad = [k for k in set(A["_artifactStamps"]) | set(new["_artifactStamps"]) if A["_artifactStamps"].get(k) != new["_artifactStamps"].get(k) and k != KEY]
    return new, ch, bad + st_bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw_txt = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A = json.loads(raw_txt)
    sc, md5, blk = build_block(dm, A)
    if not blk["tieOut"]["passed"]:
        print(json.dumps({"STOP": "tie-out with observedMix failed", "tieOut": blk["tieOut"]}))
        return 1
    if "--check" in argv:
        have = A.get(KEY)
        keep = lambda b: {k: v for k, v in (b or {}).items() if k != "provenance"}
        ok = keep(have) == keep(blk)
        print(json.dumps({"check": KEY, "matchesPayload": ok}))
        return 0 if ok else 1
    new, ch, bad = splice(A, blk, md5)
    res = os.path.join("analyses", "M535_result.json")
    if not os.path.exists(res):                                    # run-once lock: the first output is kept
        json.dump(blk, open(res, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    print(json.dumps({"tieOut": blk["tieOut"]["passed"], "nChanged": len(ch), "outsideAllowList": bad, "tripwires": blk["tripwires"]}))
    if bad:
        return 1
    if "--dry-run" not in argv:
        write_sidecar(sc, md5)
        if ch:
            if new["observedMix"] != A["observedMix"]:
                print("STOP: observedMix changed"); return 1
            with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(new, ensure_ascii=False, indent=1) + (chr(10) if raw_txt.endswith(chr(10)) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
