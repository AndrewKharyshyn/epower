#!/usr/bin/env python3
"""M672 (N-05, spec analyses/M672_spec.md Rev 1.1): monthly between-drive logged share. Descriptive, from drive_master.csv only; no estimate, no interval.
For every pair of consecutive logged drives (ordered by date, time_start, then row order) the odometer step is classified (anomaly / R1-adjacent / zero / small backward / gap under 1 km / gap 1 to 200 km / large gap 200 to 500 km);
gaps are summed by the month of the NEXT drive and set beside the logged distance and the odometer advance. A gap holds logger start/stop latency as well as missed trips; a trip before the first or after the last logged drive is invisible.
Writes the additive payload block `betweenDriveLogging` (+ stamp) to summary_arrays.json. Usage: python tools/n05_between_drive_logging.py [--out FILE] [--master FILE] [--ledger FILE]"""
import copy, datetime, hashlib, json, os, sys, calendar
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import odometer_check as OC

ZERO_TOL = OC.TOL_WITHIN          # 0.05 km, the continuity-rule resolution
SMALL_GAP_KM = 1.0
LARGE_GAP_KM = 200.0
THIN_DAYS = 5
ANOM = ("R2", "R3", "R4")


def classify(dm):
    """Return (ordered frame, steps list). A step i links drive i-1 to drive i."""
    d = dm.copy()
    d["_row"] = np.arange(len(d))
    d = d.sort_values(["date", "time_start", "_row"], kind="stable").reset_index(drop=True)
    an = {x["file"]: x["rules"] for x in OC.continuity_anomalies(dm)}
    d["rules"] = d["file"].map(lambda f: an.get(f, []))
    d["isR1"] = d["rules"].map(lambda r: "R1" in r)
    steps = []
    for i in range(1, len(d)):
        p, n = d.iloc[i - 1], d.iloc[i]
        raw = float(n["odo_start"]) - float(p["odo_end"])
        rules = [r for r in n["rules"] if r in ANOM]
        if rules:
            cls = "anomaly"
        elif bool(p["isR1"]) or bool(n["isR1"]):
            cls = "r1Adjacent"
        elif abs(raw) <= ZERO_TOL:
            cls = "zero"
        elif raw < -ZERO_TOL:
            cls = "smallBackward"
        elif raw < SMALL_GAP_KM:
            cls = "gapUnder1km"
        elif raw <= LARGE_GAP_KM:
            cls = "gap1to200km"
        else:
            cls = "largeGap"
        steps.append({"i": i, "file": n["file"], "month": str(n["date"])[:7], "rawGapKm": raw, "cls": cls, "rules": rules})
    return d, steps


def odo_resolution(d):
    v = np.unique(np.round(np.concatenate([d["odo_start"].astype(float).values, d["odo_end"].astype(float).values]), 6))
    df = np.diff(v)
    df = df[df > 1e-9]
    return float(df.min()) if len(df) else None


def bridged_across_reset(d, steps):
    out = []
    for s in steps:
        if "R4" in s["rules"]:
            k = None
            for j in range(s["i"] - 1, 0, -1):
                if "R2" in d.iloc[j]["rules"] and "R3" in d.iloc[j]["rules"]:
                    k = j
                    break
            if k is not None:
                out.append({"file": s["file"], "bridgedKm": round(float(d.iloc[s["i"]]["odo_start"]) - float(d.iloc[k - 1]["odo_end"]), 3), "note": "R4 start minus the last end before the reset regime; one figure, never summed"})
    return out


def month_table(d, steps):
    first, last = str(d["date"].min()), str(d["date"].max())
    d = d.copy()
    d["month"] = d["date"].astype(str).str[:7]
    months = sorted(d["month"].unique())
    rows = []
    for m in months:
        y, mo = int(m[:4]), int(m[5:7])
        dim = calendar.monthrange(y, mo)[1]
        lo = max(first, "%s-01" % m)
        hi = min(last, "%s-%02d" % (m, dim))
        ncal = (datetime.date.fromisoformat(hi) - datetime.date.fromisoformat(lo)).days + 1
        g = d[d["month"] == m]
        nonr1 = g[~g["isR1"]]
        st = [s for s in steps if s["month"] == m]
        cnt = lambda c: sum(1 for s in st if s["cls"] == c)
        gu = [s["rawGapKm"] for s in st if s["cls"] == "gapUnder1km"]
        g1 = [s["rawGapKm"] for s in st if s["cls"] == "gap1to200km"]
        gap_km = float(sum(gu) + sum(g1))
        lk = float(np.nansum(g["distance_km"].astype(float)))
        oa = float((nonr1["odo_end"].astype(float) - nonr1["odo_start"].astype(float)).sum())
        row = {"month": m, "nDrives": int(len(g)), "nDrivingDays": int(g["date"].nunique()), "nCalendarDays": int(ncal),
               "drivingDayShare": round(g["date"].nunique() / ncal, 4),
               "loggedKm": round(lk, 3), "odometerAdvanceKm": round(oa, 3),
               "unloggedGapKm": round(gap_km, 3), "nGapSteps": len(gu) + len(g1),
               "gapUnder1km": {"n": len(gu), "km": round(float(sum(gu)), 3)}, "gap1to200km": {"n": len(g1), "km": round(float(sum(g1)), 3)},
               "largestGapKm": round(max(gu + g1), 3) if (gu or g1) else 0.0,
               "shareDistanceBasis": round(lk / (lk + gap_km), 6) if (lk + gap_km) > 0 else None,
               "shareOdometerBasis": round(oa / (oa + gap_km), 6) if (oa + gap_km) > 0 else None,
               "nZeroSteps": cnt("zero"), "nSmallBackwardSteps": cnt("smallBackward"), "nLargeGapSteps": cnt("largeGap"),
               "nAnomalySteps": cnt("anomaly"), "anomalyRules": sorted({r for s in st if s["cls"] == "anomaly" for r in s["rules"]}), "nR1AdjacentSteps": cnt("r1Adjacent"),
               "labels": ([] + (["thin month (fewer than %d driving days)" % THIN_DAYS] if g["date"].nunique() < THIN_DAYS else []) + (["partial month"] if (lo != "%s-01" % m or hi != "%s-%02d" % (m, dim)) else []))}
        rows.append(row)
    return rows


def validate(dm, d, steps, rows, ledger):
    v = {}
    v["V1_drives"] = sum(r["nDrives"] for r in rows) == len(dm)
    v["V2_loggedKm"] = abs(sum(r["loggedKm"] for r in rows) - float(np.nansum(dm["distance_km"].astype(float)))) < 1e-2
    v["V3_oneMonthEach"] = int(d.assign(m=d["date"].astype(str).str[:7]).groupby("file")["m"].nunique().max()) == 1
    found = {x["file"]: sorted(r for r in x["rules"] if r in ANOM) for x in OC.continuity_anomalies(dm)}
    found = {k: v_ for k, v_ in found.items() if v_}
    rec = {e["file"]: sorted(r for r in e["rules"] if r in ANOM) for e in ledger.get("anomalies", [])}
    rec = {k: v_ for k, v_ in rec.items() if v_}
    v["V4_ledger"] = found == rec
    cls = [s["cls"] for s in steps]
    v["V6_stepAccounting"] = len(steps) == len(dm) - 1 == sum(cls.count(c) for c in ("anomaly", "r1Adjacent", "zero", "smallBackward", "gapUnder1km", "gap1to200km", "largeGap"))
    # V7 telescoping per regime segment (split at anomaly steps), signed raw values of every drive and every step
    ok = True
    seg_start = 0
    cuts = [s["i"] for s in steps if s["cls"] == "anomaly"] + [len(d)]
    for c in cuts:
        a, b = seg_start, c - 1
        if b >= a:
            adv = float((d.iloc[a:b + 1]["odo_end"].astype(float) - d.iloc[a:b + 1]["odo_start"].astype(float)).sum())
            gp = float(sum(s["rawGapKm"] for s in steps if a < s["i"] <= b))
            ok = ok and abs((adv + gp) - (float(d.iloc[b]["odo_end"]) - float(d.iloc[a]["odo_start"]))) < 1e-6
        seg_start = c
    v["V7_telescoping"] = bool(ok)
    return v


def build(dm, ledger, md5):
    d, steps = classify(dm)
    rows = month_table(d, steps)
    v = validate(dm, d, steps, rows, ledger)
    assert all(v.values()), "validity rule failed: %s" % v
    gu = [s["rawGapKm"] for s in steps if s["cls"] == "gapUnder1km"]
    g1 = [s["rawGapKm"] for s in steps if s["cls"] == "gap1to200km"]
    lk = float(np.nansum(dm["distance_km"].astype(float)))
    nonr1 = d[~d["isR1"]]
    oa = float((nonr1["odo_end"].astype(float) - nonr1["odo_start"].astype(float)).sum())
    gap = float(sum(gu) + sum(g1))
    return {
        "label": "Between-drive logged share by month (descriptive; odometer steps between consecutive logged drives; gaps hold logger start/stop latency as well as missed trips)",
        "spec": "analyses/M672_spec.md Rev 1.1", "status": "descriptive",
        "reading": ["The share is bracketed by two logged drives: a trip made before the first or after the last logged drive is invisible, and a gap is not measured unlogged driving.",
                    "Driving days / calendar days counts the calendar days in the window that have at least one logged drive; it is not the share of days the car was driven.",
                    "Gaps under 1 km are within logger start/stop latency and odometer resolution; only the gaps of 1 km or more can be missed trips, and one month can dominate them. The two share bases differ by the small distance-versus-odometer difference shown in the window row (logged distance minus the odometer advance within logged drives), so they nearly coincide.",
                    "A step excluded as an anomaly (backward step, reset regime, forward jump) or as R1-adjacent hides whatever was unlogged there; such steps are counted in the payload (S.betweenDriveLogging), not quantified.",
                    "The Dataset KPI \"Logged share of lifetime odometer\" (total logged km / dash ODO) uses a different denominator, is unchanged, and is the only statement about driving outside the logged window."],
        "window": {"firstDate": str(d["date"].min()), "lastDate": str(d["date"].max()), "nDrives": int(len(dm)), "loggedKm": round(lk, 3), "odometerAdvanceKm": round(oa, 3),
                   "loggedMinusOdometerAdvanceKm": round(lk - oa, 3), "unloggedGapKm": round(gap, 3), "nGapSteps": len(gu) + len(g1),
                   "gapUnder1km": {"n": len(gu), "km": round(float(sum(gu)), 3)}, "gap1to200km": {"n": len(g1), "km": round(float(sum(g1)), 3)},
                   "shareDistanceBasis": round(lk / (lk + gap), 6), "shareOdometerBasis": round(oa / (oa + gap), 6),
                   "odometerResolutionKm": round(odo_resolution(d), 6) if odo_resolution(d) is not None else None},
        "rules": {"zeroTolKm": ZERO_TOL, "smallGapKm": SMALL_GAP_KM, "largeGapKm": LARGE_GAP_KM, "boundaries": "gap in [-0.05, 0.05] is zero; (0.05, 1) gap under 1 km; [1, 200] gap; (200, 500] large gap (kept out of the sum); R2/R3/R4 steps are anomaly steps; steps next to an R1 drive are listed separately; month = month of the next drive"},
        "months": rows,
        "anomalySteps": [{"file": s["file"], "rules": s["rules"], "rawGapKm": round(s["rawGapKm"], 3)} for s in steps if s["cls"] == "anomaly"],
        "r1AdjacentSteps": [{"file": s["file"], "rawGapKm": round(s["rawGapKm"], 3)} for s in steps if s["cls"] == "r1Adjacent"],
        "largeGapSteps": [{"file": s["file"], "rawGapKm": round(s["rawGapKm"], 3)} for s in steps if s["cls"] == "largeGap"],
        "bridgedAcrossResetRegime": bridged_across_reset(d, steps),
        "validity": v,
        "provenance": {"masterMd5": md5, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "nDrives": int(len(dm))},
    }


def stamp(A, md5):
    import stamp_common as _sc
    old = (A.get("_artifactStamps") or {}).get("betweenDriveLogging")
    st = copy.deepcopy(A["_artifactStamps"]["headroomUtilization"]) if "headroomUtilization" in A.get("_artifactStamps", {}) else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M672: derived by tools/n05_between_drive_logging.py from drive_master.csv only (spec analyses/M672_spec.md Rev 1.1); descriptive")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["betweenDriveLogging"] = _sc.carry_declared(old, st)


def main(argv):
    mp = argv[argv.index("--master") + 1] if "--master" in argv else os.path.join(ROOT, "drive_master.csv")
    lp = argv[argv.index("--ledger") + 1] if "--ledger" in argv else os.path.join(ROOT, "odometer_anomalies.json")
    dm = pd.read_csv(mp, low_memory=False)
    ledger = json.load(open(lp, encoding="utf-8"))
    md5 = hashlib.md5(open(mp, "rb").read()).hexdigest()
    block = build(dm, ledger, md5)
    if "--out" in argv:
        json.dump(block, open(argv[argv.index("--out") + 1], "w", encoding="utf-8"), indent=1)
        print("wrote block")
        return
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    old = copy.deepcopy(A)
    A["betweenDriveLogging"] = block
    stamp(A, md5)
    chk = copy.deepcopy(A); chk.pop("betweenDriveLogging"); chk["_artifactStamps"].pop("betweenDriveLogging")
    o2 = copy.deepcopy(old); o2.pop("betweenDriveLogging", None); o2["_artifactStamps"].pop("betweenDriveLogging", None)
    assert chk == o2, "unexpected change outside /betweenDriveLogging"
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True}))


if __name__ == "__main__":
    main(sys.argv[1:])
