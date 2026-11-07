#!/usr/bin/env python3
"""M606 (analyses/M606_spec.md Rev 1): ambient and thermal provenance, coverage and dropout flags. Descriptive counts only; no estimator, no change to any thermal class.
Per drive and channel (HV battery intake air, engine coolant, HV coolant, engine intake air; the logger ambient PID is coverage-only), from the raw bytes (cached by raw sha256 + source hash):
columnPresent, nValid (numeric, finite, inside the pipeline window, duplicate timestamps collapsed), nOutOfWindow, nSentinel100, coverageShare (share of 10 s bins of the drive span holding a valid
sample), longestGapS (lead and trail gaps included), medianIntervalS, and a dropout flag (absent / empty / partial / gappy / ok). Raw files are sparse-wide, so coverage is defined on time, not rows.
Manual ambient ledger kinds come from the committed payload (ambientTable rows); reading times are inferred, so freshness is not observable. Outcome = the M418 hvcEngine80C classification, reused.
Usage: python tools/thermal_provenance.py [--rebuild] [--splice] [--out analyses/M606_result.json]"""
import hashlib, inspect, io, json, os, re, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (ROOT, os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
SIDECAR = os.path.join(ROOT, "thermal_provenance_sidecar.csv")
CACHE = os.path.join(ROOT, "tp_cache")
OUT = os.path.join(ROOT, "analyses", "M606_result.json")
INPUTS = ("drive_master.csv", "cadence_regime.csv", "summary_arrays.json")
BIN_S, COV_MIN, GAP_S = 10.0, 0.5, 60.0
CHANNELS = {"intake": "[BMS] HV Battery Intake Air Temperature (℃)", "engineCoolant": "Температура охолодної рідини (℃)", "hvCoolant": "[VCM] HV Coolant Temperature (℃)",
            "engineIntake": "Температура повітря, що всмоктується (℃)"}
AMBIENT_PID = "Температура оточуючого повітря (℃)"
WINDOWS = {"primary": {"intake": (-40.0, 90.0), "engineCoolant": (-40.0, 150.0), "hvCoolant": (-40.0, 120.0), "engineIntake": (-40.0, 90.0)},
           "v6": {"intake": (-40.0, 90.0), "engineCoolant": (-40.0, 200.0), "hvCoolant": (-40.0, 200.0), "engineIntake": (-40.0, 90.0)},
           "rev0": {"intake": (-40.0, 90.0), "engineCoolant": (-40.0, 130.0), "hvCoolant": (-40.0, 100.0), "engineIntake": (-40.0, 90.0)}}
SENS = {"cov25": {"cov_min": 0.25}, "cov75": {"cov_min": 0.75}, "gap30": {"gap_s": 30.0}, "gap120": {"gap_s": 120.0}, "windowV6": {"window": "windowV6"}, "windowRev0": {"window": "windowRev0"}}
OWNER_STATEMENT = {"channel": "intake", "text": "HV-battery software update reported by the owner as the root cause of the intake-air outage (owner statement, chat 2026-11-07); not verifiable from the logs", "source": "owner (Andrii), chat 2026-11-07"}
KIND_OF_MK = {"s": "single", "e": "pair", "t": "trapezoid"}


# ---------------------------------------------------------------- kernel (pure, unit-tested)
def classify_values(v, lo, hi):
    """valid mask (finite, lo <= v <= hi inclusive), count of finite values outside the window, count of the -100 sentinel."""
    v = np.asarray(v, float)
    fin = np.isfinite(v)
    ok = fin & (v >= lo) & (v <= hi)
    return ok, int((fin & ~ok).sum()), int((fin & (v == -100.0)).sum())


def channel_stats(tv, span_s):
    """tv = seconds from the drive start of the valid samples; duplicates collapsed. Coverage on 10 s bins, nb = floor(span/10) + 1. Gaps include the lead and trail edges."""
    t = np.unique(np.asarray(tv, float))
    nb = int(np.floor(span_s / BIN_S)) + 1
    out = {"nValid": int(len(t)), "bins": nb}
    if not len(t):
        out.update(binsCovered=0, coverageShare=0.0, longestGapS=None, leadGapS=None, trailGapS=None, medianIntervalS=None)
        return out
    cov = len(np.unique(np.floor(t / BIN_S).astype(int)))
    d = np.diff(t)
    lead, trail = float(t[0]), float(span_s - t[-1])
    out.update(binsCovered=int(cov), coverageShare=float(cov / nb), leadGapS=lead, trailGapS=trail,
               longestGapS=float(max([lead, trail] + ([float(d.max())] if len(d) else []))), medianIntervalS=(float(np.median(d)) if len(d) else None))
    return out


def flag(st, present, cov_min=COV_MIN, gap_s=GAP_S):
    if not present:
        return "absent"
    if st["nValid"] == 0:
        return "empty"
    if st["coverageShare"] < cov_min:
        return "partial"
    if st["longestGapS"] > gap_s:
        return "gappy"
    return "ok"


def ledger_kind(n):
    return "single" if n <= 1 else ("pair" if n == 2 else "trapezoid")


def epoch(rows):
    """rows = [(date, time_start, has_valid)] in any order; sorted by (date, time_start). First/last valid date and the drives after the last valid drive."""
    r = sorted(rows, key=lambda x: (x[0], x[1]))
    idx = [i for i, x in enumerate(r) if x[2]]
    if not idx:
        return {"firstValidDate": None, "lastValidDate": None, "nValid": 0, "nAfterLastValid": len(r)}
    return {"firstValidDate": r[idx[0]][0], "lastValidDate": r[idx[-1]][0], "nValid": len(idx), "nAfterLastValid": len(r) - 1 - idx[-1]}


def matrix(recs, channel):
    """month x stratum cells: drive count and the primary flag counts for one channel; strata are never merged."""
    out = {}
    for r in recs:
        c = out.setdefault((r["month"], r["stratum"]), {"nDrives": 0, "flags": {}})
        c["nDrives"] += 1
        f = r["flags"][channel]
        c["flags"][f] = c["flags"].get(f, 0) + 1
    return out


def build_rawmap(names):
    """digits-of-name -> raw file names; e4ORCE_* and comparison files are never matched to a master row."""
    m = {}
    for f in names:
        if f.endswith(".csv") and not f.lower().startswith("e4orce") and "comparison" not in f.lower():
            m.setdefault("".join(ch for ch in f if ch.isdigit())[:14], []).append(f)
    return m


# ---------------------------------------------------------------- per-drive extraction
def _src_hash():
    fs = (classify_values, channel_stats, flag, drive_record)
    return hashlib.sha256((repr((BIN_S, CHANNELS, WINDOWS, AMBIENT_PID)) + "".join(inspect.getsource(f) for f in fs)).encode()).hexdigest()[:16]


def drive_record(b):
    from drive_raw_cache import fast_time
    hdr = list(pd.read_csv(io.BytesIO(b), nrows=0).columns)
    if "time" not in hdr:
        return {"ok": False, "why": "no time column"}
    want = set(CHANNELS.values()) | {AMBIENT_PID, "time"}
    df = pd.read_csv(io.BytesIO(b), usecols=lambda c: c in want, low_memory=False)
    t = fast_time(df["time"], mixed=True)
    t = pd.Series(pd.to_datetime(t)).astype("datetime64[ns]")
    ok_t = t.notna().to_numpy()
    if not ok_t.any():
        return {"ok": False, "why": "no parsable time"}
    tn = t.to_numpy().astype("int64")
    t0 = tn[ok_t].min()
    sec = (tn - t0) / 1e9
    span = float((tn[ok_t].max() - t0) / 1e9)
    rec = {"ok": True, "spanS": span, "nRows": int(ok_t.sum()), "channels": {}, "flags": {}, "sens": {}}
    for key, col in CHANNELS.items():
        present = col in df.columns
        ch = {"columnPresent": bool(present)}
        wins = {}
        if present:
            v = pd.to_numeric(df[col], errors="coerce").to_numpy(float)
            nn = np.isfinite(v) & ok_t
            for wn, w in WINDOWS.items():
                okv, nout, nsent = classify_values(v[nn], *w[key])
                st = channel_stats(sec[nn][okv], span)
                st.update(nOutOfWindow=nout, nSentinel100=nsent)
                wins[wn] = st
        else:
            for wn in WINDOWS:
                wins[wn] = dict(channel_stats(np.array([]), span), nOutOfWindow=0, nSentinel100=0)
        ch.update(wins["primary"])
        rec["channels"][key] = ch
        rec["sens"][key] = {"windowV6": wins["v6"], "windowRev0": wins["rev0"]}
        rec["flags"][key] = flag(wins["primary"], present)
    # logger ambient PID: coverage only
    if AMBIENT_PID in df.columns:
        v = pd.to_numeric(df[AMBIENT_PID], errors="coerce").to_numpy(float)
        nn = np.isfinite(v) & ok_t
        rec["ambientPid"] = {"columnPresent": True, "nValid": int(len(np.unique(sec[nn])))}
    else:
        rec["ambientPid"] = {"columnPresent": False, "nValid": 0}
    return rec


# ---------------------------------------------------------------- loading
def load_records(rebuild=False):
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cr = pd.read_csv("cadence_regime.csv")[["file", "regime"]]
    cad = dict(zip(cr.file, cr.regime))
    raw_dir = os.environ.get("XT_RAW_DIR", os.path.join(ROOT, "raw"))
    rawmap = build_rawmap(os.listdir(raw_dir))
    os.makedirs(CACHE, exist_ok=True)
    sh = _src_hash()
    recs, stats = {}, {"cacheHits": 0, "extracted": 0, "noRaw": 0, "notOk": 0}
    for _, r in dm.iterrows():
        fn = r["file"]
        cand = rawmap.get("".join(ch for ch in fn if ch.isdigit())[:14])
        if not cand:
            stats["noRaw"] += 1
            continue
        b = open(os.path.join(raw_dir, cand[0]), "rb").read()
        digest = hashlib.sha256(b).hexdigest()
        cp = os.path.join(CACHE, f"{digest}_{sh}.json")
        if os.path.exists(cp) and not rebuild:
            rec = json.load(open(cp, encoding="utf-8")); stats["cacheHits"] += 1
        else:
            rec = drive_record(b)
            json.dump(rec, open(cp, "w", encoding="utf-8")); stats["extracted"] += 1
        if not rec.get("ok"):
            stats["notOk"] += 1
        c_ = cad.get(fn)
        recs[fn] = {"rec": rec, "file": fn, "rawSha256": digest, "date": str(r["date"])[:10], "timeStart": str(r["time_start"]), "month": str(r["date"])[:7],
                    "stratum": c_ if isinstance(c_, str) else "unknown", "hasMasterIntake": bool(pd.notna(r["T_intake"])) if "T_intake" in r else None}
    return dm, recs, stats


def outcomes(dm):
    """M418 hvcEngine80C classification per drive, reused unchanged: reached / rightCensored / notEligible:<reason>."""
    import compute_summary_arrays as C
    import drive_raw_cache as drc
    import thermal_support_ledger as T
    fl = drc.make_frame_loader(raw_dir=os.path.abspath(os.path.join(ROOT, "raw_only")))      # staged master-key view, as the other frame consumers (stage raw_only)
    out = {}
    for _, r in dm.iterrows():
        fn = r["file"]
        rr = T.raw_record(fl(fn), r.get("distance_km"), r.get("drive_type"), C)
        h = rr.get("hvc") if isinstance(rr, dict) else None
        if not h:
            out[fn] = "notEligible:" + str(rr.get("status", "unknown") if isinstance(rr, dict) else "unknown")
        elif h.get("status") == "accepted":
            out[fn] = "reached" if h["reached"] else "rightCensored"
        else:
            out[fn] = "notEligible:" + str(h.get("status"))
    return out


# ---------------------------------------------------------------- aggregation
def _flag_counts(sub, key, cov_min=COV_MIN, gap_s=GAP_S, window=None):
    c = {}
    for a in sub:
        r = a["rec"]
        st = r["channels"][key] if window is None else r["sens"][key][window]
        f = flag(st, r["channels"][key]["columnPresent"], cov_min, gap_s)
        c[f] = c.get(f, 0) + 1
    return c


def aggregate(recs, outc, A):
    el = [a for a in sorted(recs.values(), key=lambda x: (x["date"], x["timeStart"])) if a["rec"].get("ok")]
    res = {"population": {"drives": len(recs), "readable": len(el), "days": len({a["date"] for a in el})}, "channels": {}, "months": {}}
    strata = sorted({a["stratum"] for a in el})
    for key in CHANNELS:
        ep = epoch([(a["date"], a["timeStart"], a["rec"]["channels"][key]["nValid"] > 0) for a in el])
        blk = {"epoch": ep, "byStratum": {}, "sensitivities": {}}
        for s in strata:
            sub = [a for a in el if a["stratum"] == s]
            mi = [a["rec"]["channels"][key]["medianIntervalS"] for a in sub if a["rec"]["channels"][key]["medianIntervalS"] is not None]
            blk["byStratum"][s] = {"nDrives": len(sub), "nDays": len({a["date"] for a in sub}), "flags": _flag_counts(sub, key),
                                   "medianOfDriveMedianIntervalS": (float(np.median(mi)) if mi else None),
                                   "nOutOfWindow": int(sum(a["rec"]["channels"][key]["nOutOfWindow"] for a in sub)), "nSentinel100": int(sum(a["rec"]["channels"][key]["nSentinel100"] for a in sub))}
            for sn, kw in SENS.items():
                blk["sensitivities"].setdefault(sn, {})[s] = _flag_counts(sub, key, **kw)
        res["channels"][key] = blk
    # month x stratum matrix (primary flags, all channels), manual-ledger kinds and outcomes
    rows = {r["f"]: r for r in (A.get("ambientTable") or {}).get("rows", [])}
    mx = {}
    for a in el:
        c = mx.setdefault((a["month"], a["stratum"]), {"nDrives": 0, "days": set(), "flags": {k: {} for k in CHANNELS}, "ledgerKinds": {}, "outcome": {}})
        c["nDrives"] += 1; c["days"].add(a["date"])
        for k in CHANNELS:
            f = a["rec"]["flags"][k]; c["flags"][k][f] = c["flags"][k].get(f, 0) + 1
        kd = KIND_OF_MK.get((rows.get(a["file"]) or {}).get("mk"), "unknown")
        c["ledgerKinds"][kd] = c["ledgerKinds"].get(kd, 0) + 1
        o = outc.get(a["file"], "unknown"); c["outcome"][o] = c["outcome"].get(o, 0) + 1
    res["months"] = {f"{m}|{s}": {"nDrives": v["nDrives"], "nDays": len(v["days"]), "flags": v["flags"], "ledgerKinds": v["ledgerKinds"], "outcome": v["outcome"]} for (m, s), v in sorted(mx.items())}
    res["matrixTotals"] = {"drives": int(sum(v["nDrives"] for v in mx.values())), "readable": len(el)}
    pb = ((A.get("ambientTable") or {}).get("provenanceByCohort") or {}).get("all") or {}
    res["manualLedger"] = {"kinds": ((A.get("ambientTable") or {}).get("meanKindByCohort") or {}).get("all"), "sourceClass": pb.get("uncertaintyClass"), "readingTimes": "inferred (not logged)",
                           "freshness": "not observable from the committed ledger"}
    res["ambientPid"] = {"drivesWithColumn": int(sum(1 for a in el if a["rec"]["ambientPid"]["columnPresent"])), "drivesWithValid": int(sum(1 for a in el if a["rec"]["ambientPid"]["nValid"] > 0)), "role": "coverage only"}
    # reconciliation of the intake-air epoch with meta.intakeAir (zero tolerance) and with the master per drive
    ia = (A.get("meta") or {}).get("intakeAir") or {}
    e = res["channels"]["intake"]["epoch"]
    chk = {"nDrivesValid": (e["nValid"], ia.get("nDrivesValid")), "lastValidDate": (e["lastValidDate"], ia.get("lastValidDate")), "nDrivesAfterLastValid": (e["nAfterLastValid"], ia.get("nDrivesAfterLastValid")),
           "nDrivesNoValue": (len(el) - e["nValid"], ia.get("nDrivesNoValue"))}
    perdrive = [a["file"] for a in el if a["hasMasterIntake"] is not None and (a["rec"]["channels"]["intake"]["nValid"] > 0) != a["hasMasterIntake"]]
    hv = ((A.get("thermalSupportLedger") or {}).get("estimators") or {}).get("hvcEngine80C") or {}
    acc = hv.get("accepted") or {}
    led = {"reached": sum(v["reached"] for v in acc.values()), "rightCensored": sum(v["notReached"] for v in acc.values()), **{"notEligible:" + e["reason"]: e["n"] for e in hv.get("excluded", [])}}
    mine = {}
    for o in outc.values():
        mine[o] = mine.get(o, 0) + 1
    outcome_ok = bool(led and mine == led)
    res["reconciliation"] = {"outcomeVsThermalSupportLedger": {"mine": mine, "ledger": led, "equal": outcome_ok}, "metaIntakeAir": {k: {"raw": x, "meta": y, "equal": x == y} for k, (x, y) in chk.items()}, "perDriveMismatchesVsMasterTIntake": len(perdrive), "files": perdrive[:10],
                             "ok": bool(all(x == y for x, y in chk.values()) and not perdrive and outcome_ok)}
    return res


def write_sidecar(recs, outc):
    rows = []
    for fn, a in sorted(recs.items()):
        r = a["rec"]
        if not r.get("ok"):
            continue
        d = dict(file=fn, date=a["date"], month=a["month"], stratum=a["stratum"], raw_sha256=a["rawSha256"], span_s=r["spanS"], outcome=outc.get(fn))
        for k in CHANNELS:
            c = r["channels"][k]
            d.update({f"{k}_present": int(c["columnPresent"]), f"{k}_nvalid": c["nValid"], f"{k}_nout": c["nOutOfWindow"], f"{k}_nsent": c["nSentinel100"], f"{k}_cov": c["coverageShare"],
                      f"{k}_gap_s": c["longestGapS"], f"{k}_med_s": c["medianIntervalS"], f"{k}_flag": r["flags"][k]})
        d["ambient_pid_nvalid"] = r["ambientPid"]["nValid"]
        rows.append(d)
    pd.DataFrame(rows).to_csv(SIDECAR, index=False, float_format="%.10g", lineterminator=chr(10))
    return len(rows)


def splice(res):
    """additive write of S.thermalProvenance (+ stamp); no existing key changes."""
    import copy, datetime
    ARR = os.path.join(ROOT, "summary_arrays.json")
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    ob = {}
    for k, v in res["months"].items():
        s = k.split("|")[1]
        for o, n in v["outcome"].items():
            ob.setdefault(s, {})[o] = ob.setdefault(s, {}).get(o, 0) + n
    block = {"_provenance": "GENERATED by tools/thermal_provenance.py (M606). Do not hand-edit.", "schemaVersion": 1, "specRev": res["specRev"],
             "basis": "raw bytes; sparse-wide logger files, so coverage is the share of 10 s bins of the drive span holding a valid sample; nValid counts unique valid timestamps; windows are the pipeline's own; raw/ = sha256-verified originals (M366)",
             "inputs": {"driveMasterMd5": md5, "rawListSha256": res["rawListSha256"]}, "thresholds": res["thresholds"], "windows": res["windows"], "population": res["population"],
             "channels": res["channels"], "months": res["months"], "outcomeByStratum": ob, "outcomeRule": res["outcomeRule"], "manualLedger": res["manualLedger"], "ambientPid": res["ambientPid"],
             "ownerStatement": OWNER_STATEMENT, "reconciliation": res["reconciliation"], "extractorSourceHash": res["extractorSourceHash"], "sidecarSha256": hashlib.sha256(open(SIDECAR, "rb").read()).hexdigest(),
             "limits": ["a dropout flag is a logging fact; the logs cannot show its cause, and the only cause stated for the intake-air outage is the owner's report (ownerStatement)", "reading times of the driver-recorded ambient ledger are inferred, so freshness is not observable",
                        "the source class (vehicle_uncalibrated) is assigned by the committed ambient protocol, not checked per reading", "logging-cadence groups are never pooled; the gap thresholds act differently at the two logging cadences",
                        "engine intake air is a separate exploratory channel and is never combined with the HV-battery intake air"]}
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("thermalProvenance", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    A2["thermalProvenance"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=md5, generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M606: computed by tools/thermal_provenance.py from the raw bytes; additive, descriptive provenance and coverage only; not M299-reproducible.", upstreamHashes=dict(block["inputs"]))
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["thermalProvenance"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    with open(ARR, "w", encoding="utf-8", newline=chr(10)) as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"thermalProvenance": "written"}))


def main():
    out = OUT
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    dm, recs, stats = load_records("--rebuild" in sys.argv)
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    outc = outcomes(dm)
    res = {"milestone": "M606", "specRev": 1, "stats": stats, "extractorSourceHash": _src_hash(), "windows": WINDOWS, "thresholds": {"covMin": COV_MIN, "gapS": GAP_S, "binS": BIN_S}}
    res.update(aggregate(recs, outc, A))
    res["outcomeRule"] = "M418 hvcEngine80C (tools/thermal_support_ledger.raw_record): reached = coolant >= WARM_ENGINE_C (80 C); no cold-start gate; excluded by rule = notEligible:<reason>"
    res["sidecarRows"] = write_sidecar(recs, outc)
    res["rawListSha256"] = hashlib.sha256(json.dumps(sorted((a["file"], a["rawSha256"]) for a in recs.values())).encode()).hexdigest()
    json.dump(res, open(out, "w", encoding="utf-8"), indent=1, default=float)
    print(json.dumps({"ok": True, "stats": stats, "reconciliation": res["reconciliation"], "epochs": {k: v["epoch"] for k, v in res["channels"].items()}}, default=float))
    if not res["reconciliation"]["ok"]:
        sys.exit(2)
    if "--splice" in sys.argv:
        splice(res)


if __name__ == "__main__":
    main()
