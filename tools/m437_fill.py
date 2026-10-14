#!/usr/bin/env python3
"""M437 (spec analyses/M437_spec.md Rev 2, M435 follow-up): sensitivity of the time-to-threshold headline cells to the forward-fill limit F in {0, 3*, 6} s and, as a reason-count table, to the
trip-end tolerance X in {5, 10*, 30} s. S0 = (F 3, X 10) stays the record; no setting is chosen. Pure functions over per-drive records built by tools/m435_tte.tte_record with a grid of limit F.
  grids(fr, C, fills)          1 Hz coolant/oil grids for several fill limits from ONE resample (F = 3 equals compute_summary_arrays._twl_grid)
  sample_intervals(fr, C)      seconds between consecutive valid samples of the coolant and the oil channel
  build_block(...)             the additive block `fillSensitivity`; raises FillCheckError (stop condition) on a failed check
Facts the checks rely on (spec section 2): ffill(limit=F) fills the first F seconds of every gap, so a filled second repeats an earlier value and the first second at or above a threshold is always a
sampled second: event times cannot move with F; only the cold-start population (>= 30 valid coolant seconds), the censoring time and the trip-end / channel-loss split can."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tools"))
import m435_tte as M
import time_to_threshold as T

FILLS = (0, 3, 6)
TOLS = (5, 10, 30)
S0_FILL, S0_TOL = 3, 10
CELLS = (("coolant", 80), ("oil", 70))
H = 600
STOP_NOTE = "a failed check stops the run and goes to the Director; nothing is displayed"


class FillCheckError(RuntimeError):
    pass


def grids(fr, C, fills=FILLS):
    """{F: grid} from one resample; None if the frame has no time or coolant column (as `_twl_grid`)."""
    if fr is None or "time" not in fr.columns or C._TWL_COOL not in fr.columns:
        return None
    keep = {C._TWL_COOL: "cool", C._TWL_OIL: "oil"}
    cols = {c: n for c, n in keep.items() if c in fr.columns}
    g = fr.set_index(C._ft(fr["time"]))
    base = g[list(cols)].rename(columns=cols).apply(pd.to_numeric, errors="coerce").resample("1s").mean()
    return {F: (base if F == 0 else base.ffill(limit=F)) for F in fills}


def sample_intervals(fr, C):
    out = {}
    if fr is None or "time" not in fr.columns:
        return out
    t = pd.to_datetime(C._ft(fr["time"]))
    for name, col in (("coolant", C._TWL_COOL), ("oil", C._TWL_OIL)):
        if col in fr.columns:
            v = pd.to_numeric(fr[col], errors="coerce").notna().values
            tt = t[v]
            if len(tt) > 1:
                out[name] = np.diff(tt.values.astype("datetime64[ns]").astype("int64")) / 1e9
    return out


def records_for_drive(fr, C, fills=FILLS):
    gs = grids(fr, C, fills)
    if gs is None:
        return {F: {"status": "noFrameOrCoolantChannel"} for F in fills}, {}
    return {F: M.tte_record(fr, C, g=gs[F]) for F in fills}, sample_intervals(fr, C)


# ------------------------------------------------------------------------------------------------ helpers
def _entry(rec, fluid, thr):
    if rec.get("status") != "cold":
        return None
    f = rec["coolant"] if fluid == "coolant" else rec["oil"]
    if f is None:
        return None
    x = f["thr"][str(thr)]
    return {"t": x["t"], "e": x["e"], "reason": x["reason"], "lastValidS": f["lastValidS"], "tripEndS": f["tripEndS"],
            "startC": rec["startC"] if fluid == "coolant" else f["startC"], "lag": rec["lagFirstValidS"] if fluid == "coolant" else f["lagFirstValidS"], "afterGap": x["afterGap"]}


def _reason_at(ent, X):
    if ent["e"]:
        return "event"
    return "tripEnd" if ent["tripEndS"] - ent["lastValidS"] <= X else "channelLoss"


def _status600(ent):
    if ent["e"] and ent["t"] <= H:
        return "reachedBy600"
    if (not ent["e"]) and ent["t"] < H:
        return "censoredBefore600"
    return "atRiskAt600"


def _row(c):
    h = next(x for x in c["horizons"] if x["h"] == H)
    out = {"n": c["n"], "days": c["days"], "reached": c["reached"], "censoredTripEnd": c["censoredTripEnd"], "censoredChannelLoss": c["censoredChannelLoss"],
           "eventsAfterGapOver10s": c["eventsAfterGapOver10s"], "supported600": h["supported"], "atRisk600": [h["atRisk"], h["atRiskDays"]],
           "median": {"point": c["median"]["point"], "shown": c["median"]["shown"], "text": c["median"]["text"]}}
    if h["supported"]:
        out.update({"E1": h["E1"], "E2": h["E2"], "boundHigh": h["bounds"]["high"], "tilt": {k: h["tilt"][k] for k in ("0.5", "2")}, "reading": h["reading"], "readingClasses": h["readingClasses"]})
    return out


def _paired(a, b, fluid, thr, dF):
    """a = S0 records, b = variant records (same drive order)."""
    dropped, added = {"reachedBy600": 0, "censoredBefore600": 0, "atRiskAt600": 0}, {"reachedBy600": 0, "censoredBefore600": 0, "atRiskAt600": 0}
    ev_changed = cens_changed = reason_changed = 0
    max_shift = 0.0
    r_dir = {"tripEndToChannelLoss": 0, "channelLossToTripEnd": 0}
    for ra, rb in zip(a, b):
        ea, eb = _entry(ra, fluid, thr), _entry(rb, fluid, thr)
        if ea is not None and eb is None:
            dropped[_status600(ea)] += 1
        elif eb is not None and ea is None:
            added[_status600(eb)] += 1
        elif ea is not None and eb is not None:
            if ea["e"] != eb["e"] or (ea["e"] and ea["t"] != eb["t"]):
                ev_changed += 1
            elif not ea["e"]:
                if ea["t"] != eb["t"]:
                    cens_changed += 1
                    max_shift = max(max_shift, abs(ea["t"] - eb["t"]))
                ra_, rb_ = _reason_at(ea, S0_TOL), _reason_at(eb, S0_TOL)
                if ra_ != rb_:
                    reason_changed += 1
                    r_dir["tripEndToChannelLoss" if ra_ == "tripEnd" else "channelLossToTripEnd"] += 1
    return {"dropped": dropped, "added": added, "nDropped": sum(dropped.values()), "nAdded": sum(added.values()), "eventTimeChanged": ev_changed,
            "censoringTimeChanged": cens_changed, "maxCensoringShiftS": _r(max_shift, 1), "maxAllowedShiftS": abs(dF), "reasonChanged": reason_changed, "reasonChangedDirection": r_dir}


_r = M._r


# ------------------------------------------------------------------------------------------------ block
def build_block(recs_by_F, days, intervals, main_block, C):
    """recs_by_F: {F: [record per drive]} aligned with `days`; intervals: list of per-drive dicts from sample_intervals; main_block: the M435 block (G1)."""
    idx_all = range(len(days))
    settings, pooled = {}, {}
    for F in FILLS:
        cold = [i for i in idx_all if recs_by_F[F][i].get("status") == "cold"]
        uni = np.array(sorted({days[i] for i in cold}))
        counts = T.day_counts(uni, M.B_DRAWS, M.SEED) if len(uni) else None
        row = {}
        for fl, thr in CELLS:
            ents = [(i, _entry(recs_by_F[F][i], fl, thr)) for i in idx_all]
            ents = [(i, e) for i, e in ents if e is not None]
            if not ents:
                continue
            t = [e["t"] for _, e in ents]; ev = [e["e"] for _, e in ents]; d = [days[i] for i, _ in ents]
            rs = [e["reason"] for _, e in ents]; ag = [e["afterGap"] for _, e in ents]; sc = [e["startC"] for _, e in ents]; lg = [e["lag"] for _, e in ents]
            c = M.analyze_cell(t, ev, d, rs, ag, sc, lg, fl, thr, counts, uni)
            c.pop("_cell"); c.pop("_S")
            pooled[(F, fl, thr)] = c
            row["%s/%d" % (fl, thr)] = _row(c)
            row["%s/%d" % (fl, thr)]["reasonByTolerance"] = {str(X): {"tripEnd": sum(1 for _, e in ents if not e["e"] and _reason_at(e, X) == "tripEnd"),
                                                                        "channelLoss": sum(1 for _, e in ents if not e["e"] and _reason_at(e, X) == "channelLoss")} for X in TOLS}
        settings[str(F)] = row
    paired = {}
    for F in FILLS:
        if F == S0_FILL:
            continue
        paired[str(F)] = {"%s/%d" % (fl, thr): _paired(recs_by_F[S0_FILL], recs_by_F[F], fl, thr, F - S0_FILL) for fl, thr in CELLS}
    # reasonChanged over the whole (F, X) grid (C2): drives censored in both S0 and the variant whose label under (F, X) differs from their label under (3, 10)
    reason_grid = {}
    for F in FILLS:
        for X in TOLS:
            if (F, X) == (S0_FILL, S0_TOL):
                continue
            cellres = {}
            for fl, thr in CELLS:
                n_ch, dirs = 0, {"tripEndToChannelLoss": 0, "channelLossToTripEnd": 0}
                for ra, rb in zip(recs_by_F[S0_FILL], recs_by_F[F]):
                    ea, eb = _entry(ra, fl, thr), _entry(rb, fl, thr)
                    if ea is None or eb is None or ea["e"] or eb["e"]:
                        continue
                    la, lb = _reason_at(ea, S0_TOL), _reason_at(eb, X)
                    if la != lb:
                        n_ch += 1
                        dirs["tripEndToChannelLoss" if la == "tripEnd" else "channelLossToTripEnd"] += 1
                cellres["%s/%d" % (fl, thr)] = {"reasonChanged": n_ch, "direction": dirs}
            reason_grid["F%d_X%d" % (F, X)] = cellres
    # statement and ranges (spec section 5)
    statement, ranges = {}, {}
    for fl, thr in CELLS:
        k = "%s/%d" % (fl, thr)
        rows = {F: settings[str(F)].get(k) for F in FILLS}
        st = {}
        for reading in ("F<0.5", "F>=0.5"):
            cls = {F: (rows[F]["readingClasses"][reading] if rows[F] and rows[F]["supported600"] else "unsupported") for F in FILLS}
            same = len(set(cls.values())) == 1 and "unsupported" not in cls.values()
            st[reading] = {"classByFill": {str(F): v for F, v in cls.items()}, "same": bool(same),
                           "text": ("the reading class is the same in all 3 fill settings" if same else "the reading class differs between fill settings: " + "; ".join("F=%d %s" % (F, v) for F, v in cls.items()))}
        st["sameBothReadings"] = bool(all(v["same"] for v in st.values()))
        first = {r_: next(iter(st[r_]["classByFill"].values())) for r_ in ("F<0.5", "F>=0.5")}
        if st["sameBothReadings"]:
            st["text"] = ("%s, %d s: in each of the 3 fill settings, fewer than half reached: %s; half or more reached: %s; the class is the same in all 3 settings and this concerns the fill convention only, it does not reduce the censoring dependence"
                          % (k.replace("/", " ") + " C", H, first["F<0.5"], first["F>=0.5"]))
        else:
            st["text"] = "%s, %d s: the reading class differs between fill settings (see the classes by fill)" % (k.replace("/", " ") + " C", H)
        d0 = paired["0"][k]
        st["fillZeroNote"] = ("fill 0 s drops %d short, sparsely sampled cold starts (none reached by %d s); the higher shares at fill 0 s are a population effect, not faster warm-up" % (d0["nDropped"], H)
                              if d0["dropped"]["reachedBy600"] == 0 else "fill 0 s drops %d cold starts, %d of them reached by %d s (see the paired counts)" % (d0["nDropped"], d0["dropped"]["reachedBy600"], H))
        statement[k] = st
        rg = {}
        for q in ("E1", "E2"):
            vals = [(F, rows[F][q]["point"]) for F in FILLS if rows[F] and rows[F]["supported600"]]
            if vals:
                lo = min(vals, key=lambda x: x[1]); hi = max(vals, key=lambda x: x[1])
                rg[q] = {"min": lo[1], "minAtFill": lo[0], "minCi95": rows[lo[0]][q]["ci95"], "max": hi[1], "maxAtFill": hi[0], "maxCi95": rows[hi[0]][q]["ci95"]}
        ranges[k] = rg
    # checks (G1 and the stop conditions)
    chk = {"eventTimeChangedZero": all(p["eventTimeChanged"] == 0 for v in paired.values() for p in v.values()),
           "nestingAddedZeroAtF0": all(paired["0"][k]["nAdded"] == 0 for k in paired["0"]), "nestingDroppedZeroAtF6": all(paired["6"][k]["nDropped"] == 0 for k in paired["6"]),
           "censoringShiftWithinFillDelta": all(float(p["maxCensoringShiftS"] or 0) <= p["maxAllowedShiftS"] for v in paired.values() for p in v.values())}
    g1 = True
    for fl, thr in CELLS:
        m = main_block["cohorts"]["all"][fl][str(thr)]
        mh = next(x for x in m["horizons"] if x["h"] == H)
        r = settings[str(S0_FILL)]["%s/%d" % (fl, thr)]
        g1 = g1 and r["n"] == m["n"] and r["reached"] == m["reached"] and r["censoredTripEnd"] == m["censoredTripEnd"] and r["censoredChannelLoss"] == m["censoredChannelLoss"] and r["median"]["point"] == m["median"]["point"]
        if mh["supported"]:
            g1 = g1 and r["E1"]["point"] == mh["E1"]["point"] and r["E2"]["point"] == mh["E2"]["point"] and r["boundHigh"]["point"] == mh["bounds"]["high"]["point"] and r["readingClasses"] == mh["readingClasses"]
    chk["g1EqualsM435Block"] = bool(g1)
    chk["allOk"] = all(chk.values())
    if not chk["allOk"]:
        raise FillCheckError("M437 checks failed (%s): %s" % (STOP_NOTE, {k: v for k, v in chk.items() if v is False}))
    si = {}
    for name in ("coolant", "oil"):
        arrs = [d[name] for d in intervals if name in d and len(d[name])]
        if arrs:
            allv = np.concatenate(arrs)
            si[name] = {"medianS": _r(np.median(allv), 3), "p95S": _r(np.percentile(allv, 95), 3), "nIntervals": int(allv.size)}
    return {"spec": "analyses/M437_spec.md", "methodVersion": "M437-r2", "fills": list(FILLS), "tolerances": list(TOLS), "record": {"fill": S0_FILL, "toleranceS": S0_TOL},
            "headlineCells": ["%s/%d" % c for c in CELLS], "h": H,
            "label": "range over declared conventions, not a confidence interval; S0 stays the record; no setting is chosen",
            "settings": settings, "pairedVsRecord": paired, "reasonChangedByFillAndTolerance": reason_grid, "statement": statement, "ranges": ranges, "sampleIntervalS": si, "checks": chk,
            "reading": ("Sensitivity of the observed share and the Kaplan-Meier (product-limit) estimate to the forward-fill limit (0, 3, 6 s); range over declared conventions, not a confidence interval; "
                        "the trip-end tolerance changes only the reason split."),
            "labels": {"censoringTimeChanged": "drives censored in both the record and the variant whose censoring time (last valid second) differs; it is not the count over all drives present in both",
                       "reasonChanged": "drives censored in both whose trip-end / channel-loss label under the variant (F, X) differs from their label under the record (3, 10)"},
            "limits": ["the fill range of 0-6 s is below the 95th percentile of the coolant sample interval, so longer gaps stay missing in every setting: the grid does not cover the coolant gap distribution","the fill grid is a declared planning choice; a logger interval above 1 s couples fill and tolerance", "ranges are of point estimates; the bootstrap resample sets differ between settings",
                       "at F = 0 the 30 valid-second rule counts raw samples (about 78 s at the median coolant interval), so F = 0 changes the cold-start population by dropping short, sparsely sampled drives; the higher shares at F = 0 are a population effect", "informative censoring is addressed by the M435 bounds and tilt rows, not here", "headline cells of cohort all only"]}


# ------------------------------------------------------------------------------------------------ CLI (standalone rebuild for the audit)
def main(argv):
    import hashlib, json
    import compute_summary_arrays as C
    import drive_raw_cache as drc
    os.chdir(ROOT)
    out_path = argv[argv.index("--out") + 1] if "--out" in argv else "analyses/M437_result.json"
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw_dir = os.environ.get("XT_RAW_DIR_STAGED") or os.path.join(ROOT, "raw_only")
    fl = drc.make_frame_loader(raw_dir=raw_dir)
    days = list(dm["date"].astype(str).str[:10])
    recs_by_F = {F: [] for F in FILLS}; ints, main = [], []
    for fn in dm["file"]:
        fr = fl(fn)
        main.append(M.tte_record(fr, C))
        r, iv = records_for_drive(fr, C)
        for F in FILLS:
            recs_by_F[F].append(r[F])
        ints.append(iv)
    sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False).set_index("file")["thermal_regime"]
    regimes = [sdm.get(fn) for fn in dm["file"]]
    mb = M.build_block(main, [{} for _ in main], days, regimes, C)
    blk = build_block(recs_by_F, days, ints, mb, C)
    res = {"_provenance": {"spec": "analyses/M437_spec.md", "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "script": "tools/m437_fill.py", "nDrives": len(dm),
                           "label": "raw/ = sha256-verified originals (M366); " + M.LABEL}, "block": blk}
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps({"checks": blk["checks"], "sameBothReadings": {k: s_["sameBothReadings"] for k, s_ in blk["statement"].items()}}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
