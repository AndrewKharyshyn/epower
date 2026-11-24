#!/usr/bin/env python3
"""M765 (spec analyses/M765_spec.md Rev 2): resolve the odometer jump-rule difference behind note X1 (17 versus 7 jump-excluded drives; 418 versus 420 drives). Auxiliary, report-only, offline.

Stages: J0 control (the M752 tool outcome reproduced from the pinned store and master), J1 decomposition (availability A, the tool's jump test B, the strict-inside test B1, B with positive steps at dt <= 0 B2, B3 = B1 + B2 (audit-like),
the physical rule P: a jump between the last row at or before t0 and the first row at or after t1), J2 impact (the E_int / E_br / +16 s agreements under B, B1, B3 and P), decision words (R1 to R4 of the spec).
Aggregates only in the result (public repository): no drive names, dates, coordinates or absolute cloud odometer values; step sizes only as size classes.

Usage: python tools/odometer_jump_audit.py [--store DIR] [--master FILE] [--out-dir analyses] [--nb 4000]
Exit codes: 0 done or skipped (no store), 1 master pin failed, 3 control or pin failure."""
import argparse, csv, json, os, re, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import drive_odometer as dm
import mynissan_import as mi
import mynissan_coverage as mc

ROOT = dm.ROOT
CAP, REG, VMAX = dm.CAP_S, dm.REGRESS_KM, mc.PHYSICAL_MAX_KMH
M752_TOOL_SHA = "741bc24b8ac4eeed7bbdf98f93658a9ff66f6487e01f59418aa8b6ade7ae9037"
M752_RESULT_SHA = "60c2a3277af28eca113c7e26ac349b2eb3dd6a7c2d389df3042601ca187b6967"
STORE_MANIFEST_SHA = "7cbab168a882a561f55005e27a6fe484b91eb450c7e1bc2a2b6e0a37b25b3a96"
PREDICTIONS = {"unavailable_by_A": 124, "B_and_unavailable_by_A": 8, "B_and_available_by_A": 9, "B3_and_available_by_A": 7}   # spec 7.2 (frozen before any run)
RULES = ("B", "B1", "B2", "B3", "P")


# ------------------------------------------------------------------ jump rules (known-answer tested)
def step_flags(ts, vs, a, b):
    """Flags over the consecutive rows a .. b-1 (slice [a, b)): negative step, positive step implying more than VMAX (dt > 0, tool margin), positive step at dt <= 0."""
    a, b = max(int(a), 0), min(int(b), len(ts))
    if b - a < 2:
        return False, False, False, 0.0
    dv, dt = np.diff(vs[a:b]), np.diff(ts[a:b])
    neg = dv < -REG
    fast = (dv > REG) & (dt > 0) & (dv > dt * VMAX / 3600.0 + REG)
    dtle0 = (dv > REG) & (dt <= 0)
    big = np.abs(dv[neg | fast | dtle0]).max() if (neg | fast | dtle0).any() else 0.0
    return bool(neg.any()), bool(fast.any()), bool(dtle0.any()), float(big)


def rule_flags(t0, t1, ts, vs, shift=0.0):
    """B (tool: window [t0 - CAP, t1 + CAP] plus one row beyond each end), B1 (rows strictly inside the window), B2 (B plus positive steps at dt <= 0), B3 (B1 plus dt <= 0; audit-like reconstruction),
    P (physical rule: the rows from the last row at or before t0 - shift to the first row at or after t1 - shift, steps negative, fast, or positive at dt <= 0)."""
    i0 = int(np.searchsorted(ts, t0 - CAP, side="left"))
    i1 = int(np.searchsorted(ts, t1 + CAP, side="right"))
    out = {}
    out["B"] = bool(dm.jump_in_window(t0, t1, ts, vs))
    n1, f1, d1, _ = step_flags(ts, vs, i0, i1)
    out["B1"] = n1 or f1
    _, _, d2, _ = step_flags(ts, vs, max(i0 - 1, 0), min(i1 + 1, len(ts)))
    out["B2"] = out["B"] or d2
    out["B3"] = out["B1"] or d1
    j0 = int(np.searchsorted(ts, t0 - shift, side="right")) - 1
    j1 = int(np.searchsorted(ts, t1 - shift, side="left"))
    if j0 < 0 or j1 >= len(ts):
        out["P"] = False
    else:
        n, f, d, _ = step_flags(ts, vs, j0, j1 + 1)
        out["P"] = n or f or d
    return out


def flagged_location(t0, t1, ts, vs, flags):
    """Where the flagged step of a drive lies (exclusive classes): inside_drive_span, endpoint_stretch, window_not_in_stretch, extra_edge_rows_only, dt_le_0_only."""
    if flags["P"]:
        a = int(np.searchsorted(ts, t0, side="left"))
        b = int(np.searchsorted(ts, t1, side="right"))
        n, f, d, _ = step_flags(ts, vs, a, b)
        return "inside_drive_span" if (n or f or d) else "endpoint_stretch"
    if flags["B1"]:
        return "window_not_in_stretch"
    if flags["B"]:
        return "extra_edge_rows_only"
    return "dt_le_0_only"


def size_class(ts, vs, t0, t1):
    """Largest flagged step in the stretch examined (any rule), as a size class only."""
    i0 = int(np.searchsorted(ts, t0 - CAP, side="left")) - 1
    i1 = int(np.searchsorted(ts, t1 + CAP, side="right")) + 1
    _, _, _, big = step_flags(ts, vs, i0, i1)
    return "below_1km" if big < 1.0 else ("1_to_10km" if big < 10.0 else "above_10km")


def availability(t0, t1, ts, vs, modes=("int", "int"), shift=0.0):
    """Availability by the bracket test alone (no jump test): (ok, reason, dist). Reason = the first failing endpoint's reason, as in drive_odometer.drive_endpoints."""
    a, _, ra = dm.odo_at(t0, ts, vs, modes[0], shift)
    b, _, rb = dm.odo_at(t1, ts, vs, modes[1], shift)
    if a is None or b is None:
        return False, (ra if ra not in ("ok", "flat") else rb), None
    return True, "ok", b - a


def excursion_spans(ts, vs):
    """(t_start, t_end) of every level excursion (a stretch below the running maximum by more than REG) as in drive_odometer.accepted_odo."""
    if len(ts) < 2:
        return []
    run = np.maximum.accumulate(vs)
    below = vs < run - REG
    edges = np.diff(np.r_[0, below.astype(int), 0])
    starts, ends = np.where(edges == 1)[0], np.where(edges == -1)[0] - 1
    return [(float(ts[s]), float(ts[e])) for s, e in zip(starts, ends)]


def in_excursion(t, spans):
    return any(a <= t <= b for a, b in spans)


# ------------------------------------------------------------------ aggregation (known-answer tested)
def crosstab(recs):
    """recs: per-drive dicts with unavailable_A (bool), flags (dict of rule -> bool). Counts for J1 and the frozen H1 predictions."""
    n = len(recs)
    una = sum(1 for r in recs if r["unavailable_A"])
    out = {"drives": n, "unavailable_by_A": una, "available_by_A": n - una, "rules": {}}
    for k in RULES:
        fl = [r for r in recs if r["flags"][k]]
        out["rules"][k] = {"flagged": len(fl), "flagged_and_unavailable_by_A": sum(1 for r in fl if r["unavailable_A"]), "flagged_and_available_by_A": sum(1 for r in fl if not r["unavailable_A"])}
    pair = {}
    for a, b in (("B", "B3"), ("B", "P"), ("B3", "P"), ("B", "B1")):
        pair["%s_not_%s" % (a, b)] = sum(1 for r in recs if r["flags"][a] and not r["flags"][b] and not r["unavailable_A"])
        pair["%s_not_%s" % (b, a)] = sum(1 for r in recs if r["flags"][b] and not r["flags"][a] and not r["unavailable_A"])
    out["available_by_A_flagged_by_one_rule_only"] = pair
    return out


def h1_check(ct, outside_span):
    obs = {"unavailable_by_A": ct["unavailable_by_A"], "B_and_unavailable_by_A": ct["rules"]["B"]["flagged_and_unavailable_by_A"],
           "B_and_available_by_A": ct["rules"]["B"]["flagged_and_available_by_A"], "B3_and_available_by_A": ct["rules"]["B3"]["flagged_and_available_by_A"]}
    return {"predicted": dict(PREDICTIONS), "observed": obs, "h1_confirmed": bool(obs == PREDICTIONS), "outside_span_drives": int(outside_span),
            "falsified_by_cross_tab": bool(obs["B_and_unavailable_by_A"] < 8)}


def verdict_three(summary, margin):
    """Three-valued wording (Director ruling C1): 'above m %' when the whole interval of the aggregate relative difference lies above the margin, 'interval includes m %' when it straddles the margin, 'consistent within +-m %' when it lies inside; the 0.25 km median criterion is appended as in M752."""
    if "relative" not in summary:
        return "not estimable at this support"
    lo, hi = summary["relative"]["ci95"]
    est = "aggregate relative difference %.2f %% [%.2f, %.2f]" % (100 * summary["relative"]["est"], 100 * lo, 100 * hi)
    m = 100 * margin
    if lo > margin:
        word = "%s: the interval lies above %g %%" % (est, m)
    elif hi < -margin:
        word = "%s: the interval lies below -%g %%" % (est, m)
    elif lo >= -margin and hi <= margin:
        word = "consistent within +-%g %%" % m
    else:
        word = "%s: the interval includes %g %%" % (est, m)
    if summary["medianAbs"]["est"] > dm.MEDIAN_ABS_KM:
        word += "; median |difference| %.2f km above %.2f km" % (summary["medianAbs"]["est"], dm.MEDIAN_ABS_KM)
    return word


def scan_privacy(obj):
    """Fails on a value in the absolute-odometer range or a string that looks like a full date or a drive file name."""
    bad = []

    def walk(o, p=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if re.search(r"\d{4}-\d{2}-\d{2}", str(k)):
                    bad.append(("key", p + "/" + str(k)))
                walk(v, p + "/" + str(k))
        elif isinstance(o, (list, tuple)):
            for i, v in enumerate(o):
                walk(v, p + "[%d]" % i)
        elif isinstance(o, str):
            if re.search(r"\d{4}-\d{2}-\d{2}", o) or re.search(r"\.csv\b", o):
                bad.append(("str", p))
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            if 30000.0 <= abs(o) <= 80000.0:
                bad.append(("odometer_range", p))
    walk(obj)
    return bad


# ------------------------------------------------------------------ run
def _summary(df, name, nb, flags_col):
    """E_int / E_br / +16 s agreement with the drives flagged by one rule made unavailable."""
    sub = df[df["clean"] & df["logged"].notna() & df[name + "_dist0"].notna() & ~df[flags_col]].copy()
    sub["delta"] = sub[name + "_dist0"] - sub["logged"]
    sub["day"] = sub["date"]
    prim = sub[sub["identity"]]
    s = dm.summarise(prim[prim["logged"] >= dm.SHORT_KM], nb)
    out = {"available_all_drives": int((df[name + "_dist0"].notna() & ~df[flags_col]).sum()), "primary_identity_ge2km": s,
           "verdict_words": {"within1pct": verdict_three(s, dm.MARGIN_PRIMARY), "within3pct": verdict_three(s, dm.MARGIN_WIDE)}}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store())
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--nb", type=int, default=dm.NB_DEFAULT)
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.store, "manifest.json")):
        print("odometer_jump_audit: no cloud store, skipped (optional)")
        return 0
    t_start = time.time()
    try:
        if dm.md5(a.master) != dm.REGISTERED_MASTER:
            print("odometer_jump_audit: master pin failed")
            return 1
        if dm.sha256(os.path.join(HERE, "drive_odometer.py")) != M752_TOOL_SHA:
            raise dm.Stop("tools/drive_odometer.py differs from the M752 tool sha256")
        if dm.sha256(os.path.join(a.store, "manifest.json")) != STORE_MANIFEST_SHA:
            raise dm.Stop("the cloud store manifest differs from the registered one")
        reg_path = os.path.join(a.out_dir, "M752_odometer_agreement.json")
        if dm.sha256(reg_path) != M752_RESULT_SHA:
            raise dm.Stop("the registered M752 result differs from its pinned sha256")
        reg = json.load(open(reg_path, encoding="utf-8"))
        rows = [(t, mc.fnum(x.get("StatusDistanceTotalizerComputed", ""))) for t, x in mi.load_stream(a.store, "Odometer")]
        conf = set()
        cp = os.path.join(a.store, "conflicts.csv")
        if os.path.exists(cp):
            for r in csv.DictReader(open(cp, encoding="utf-8", newline="")):
                if r["stream"] == "Odometer":
                    conf.add(mi.to_epoch(r["timestamp_utc"]))
        ts, vs, cnt = dm.accepted_odo(rows, conf)
        dm.check_gain(ts, vs)
        spans = excursion_spans(ts, vs)
        master = mc.load_master(a.master)
        mdf = pd.read_csv(a.master, usecols=["file", "distance_km", "odo_start", "odo_end", "ens_outlier_v2"], low_memory=False).set_index("file")
        recs, rows_df = [], []
        for m in master:
            r = mdf.loc[m["file"]]
            logged = float(r["distance_km"]) if pd.notna(r["distance_km"]) else None
            ident = (logged is not None and pd.notna(r["odo_end"]) and abs(logged - (float(r["odo_end"]) - float(r["odo_start"]))) <= dm.IDENT_KM)
            clean = (r["ens_outlier_v2"] is False) or (str(r["ens_outlier_v2"]) == "False")
            fl = rule_flags(m["t0"], m["t1"], ts, vs)
            flp16 = rule_flags(m["t0"], m["t1"], ts, vs, dm.SHIFT_S)["P"]
            okA, reasonA, dist0 = availability(m["t0"], m["t1"], ts, vs, ("int", "int"), 0.0)
            _, _, dist_br0 = availability(m["t0"], m["t1"], ts, vs, ("br_start", "br_end"), 0.0)
            _, _, dist160 = availability(m["t0"], m["t1"], ts, vs, ("int", "int"), dm.SHIFT_S)
            tool_ep = dm.drive_endpoints(m["t0"], m["t1"], ts, vs)
            rec = {"unavailable_A": not okA, "reasonA": reasonA, "flags": fl, "t0": m["t0"], "t1": m["t1"], "month": m["date"][:7],
                   "logged": logged, "tool_dist": tool_ep["E_int"]["dist"], "tool_reason": tool_ep["E_int"]["reasonStart"] if tool_ep["E_int"]["dist"] is None else "ok"}
            recs.append(rec)
            row = {"date": m["date"], "logged": logged, "identity": bool(ident), "clean": bool(clean), "E_int_dist0": dist0, "E_br_dist0": dist_br0, "E_int_shift16_dist0": dist160,
                   "B": fl["B"], "B1": fl["B1"], "B2": fl["B2"], "B3": fl["B3"], "P": fl["P"], "P16": flp16, "E_int_dist_tool": tool_ep["E_int"]["dist"]}
            rows_df.append(row)
        df = pd.DataFrame(rows_df)
        # J0 control: the M752 outcome reproduced from the same rows
        cov = {}
        for rec in recs:
            key = "available" if rec["tool_dist"] is not None else (rec["tool_reason"] if rec["tool_reason"] else "unavailable")
            cov[key] = cov.get(key, 0) + 1
        reg_cov = reg["P0_coverage"]["E_int"]
        if cov.get("available", 0) != reg_cov["available"] or cov.get("odometer_jump", 0) != reg_cov["unavailableByReason"].get("odometer_jump", -1):
            raise dm.Stop("control J0: the M752 availability counts are not reproduced")
        sub = df[df["clean"] & df["logged"].notna() & df["E_int_dist_tool"].notna()].copy()
        sub["delta"] = sub["E_int_dist_tool"] - sub["logged"]
        sub["day"] = sub["date"]
        prim = sub[sub["identity"]]
        s0 = dm.summarise(prim[prim["logged"] >= dm.SHORT_KM], a.nb)
        rp = reg["P1_agreement"]["E_int"]["primary_identity_ge2km"]
        if s0["nDrives"] != rp["nDrives"] or s0["nDays"] != rp["nDays"] or s0["relative"] != rp["relative"] or s0["median"] != rp["median"]:
            raise dm.Stop("control J0: the M752 primary agreement is not reproduced")
        # J1
        ct = crosstab(recs)
        outside = sum(1 for r in recs if r["unavailable_A"] and r["reasonA"] == "outside_span")
        h1 = h1_check(ct, outside)
        loc, sizes, lstr = {}, {}, {}
        for r, row in zip(recs, rows_df):
            anyflag = any(r["flags"][k] for k in RULES)
            if anyflag and not r["unavailable_A"]:
                lc = flagged_location(r["t0"], r["t1"], ts, vs, r["flags"])
                loc[lc] = loc.get(lc, 0) + 1
                sz = size_class(ts, vs, r["t0"], r["t1"])
                sizes[sz] = sizes.get(sz, 0) + 1
                if r["logged"] is not None:
                    st = dm.stratum_of(r["logged"])
                    lstr[st] = lstr.get(st, 0) + 1
        exc = sum(1 for r in recs if in_excursion(r["t0"], spans) or in_excursion(r["t1"], spans))
        # J2
        j2 = {}
        for k in ("B", "B1", "B3", "P"):
            j2[k] = {"E_int": _summary(df, "E_int", a.nb, k), "E_br": _summary(df, "E_br", a.nb, k), "E_int_shift16": _summary(df, "E_int_shift16", a.nb, "P16" if k == "P" else k)}
        # availability by month for B and P (cells below 3 drives suppressed)
        bym = {}
        for k in ("B", "P"):
            tab = {}
            for r, row in zip(recs, rows_df):
                av = (not r["unavailable_A"]) and not row[k]
                c = tab.setdefault(r["month"], [0, 0])
                c[0] += 1
                c[1] += int(av)
            bym[k] = {m: ({"drives": v[0], "available": v[1]} if v[0] >= 3 else "suppressed (fewer than 3 drives)") for m, v in tab.items()}
        # R2 / R3
        avail = lambda: [(r, row) for r, row in zip(recs, rows_df) if not r["unavailable_A"]]
        over = lambda k: int(sum(1 for r, row in avail() if row[k] and not row["P"]))
        under = lambda k: int(sum(1 for r, row in avail() if row["P"] and not row[k]))
        r2 = {"rule_flagged_P_keeps": {k: over(k) for k in ("B", "B1", "B3")}, "P_flagged_rule_keeps": {k: under(k) for k in ("B", "B1", "B3")},
              "reading": "B over-exclusive (%d), under-exclusive (%d); B3 over-exclusive (%d), under-exclusive (%d) relative to P (available-by-A drives only)" % (over("B"), under("B"), over("B3"), under("B3")),
              "note": "a zero 'P_flagged_rule_keeps' for B does not mean P never excludes more: against B3, P excludes %d drives that B3 keeps" % under("B3")}
        regI = reg["P1_agreement"]["E_int"]["primary_identity_ge2km"]
        pI = j2["P"]["E_int"]["primary_identity_ge2km"]
        rd = lambda x: round(100 * x, 2)
        shown = lambda s_: [s_["nDrives"], s_["nDays"], round(s_["median"]["est"], 2), [round(c, 2) for c in s_["median"]["ci95"]], rd(s_["relative"]["est"]), [rd(c) for c in s_["relative"]["ci95"]]] if "relative" in s_ else None
        trig = shown(pI) != shown(regI) or j2["P"]["E_int"]["available_all_drives"] != reg_cov["available"] or j2["P"]["E_int"]["verdict_words"] != reg["P1_verdict_wording"]["primary_E_int_identity_ge2km"]
        r3 = {"registered_displayed": shown(regI), "P_displayed": shown(pI), "replacement_trigger": bool(trig),
              "P_relative_ci_lower_below_1pct": bool("relative" in pI and 100 * pI["relative"]["ci95"][0] < 1.0),
              "P_estimate_inside_M752_interval": bool("relative" in pI and regI["relative"]["ci95"][0] <= pI["relative"]["est"] <= regI["relative"]["ci95"][1])}
        res = {"milestone": "M765", "spec": "analyses/M765_spec.md Rev 2", "masterMd5": dm.REGISTERED_MASTER, "storeManifestSha256": STORE_MANIFEST_SHA, "m752ToolSha256": M752_TOOL_SHA, "m752ResultSha256": M752_RESULT_SHA,
               "toolSha256": dm.sha256(os.path.abspath(__file__)), "seed": dm.SEED, "nBoot": a.nb,
               "J0_control": {"reproduced": True, "availability_by_tool_order": cov, "primary_agreement_equals_registered": True},
               "J1": {"crosstab": ct, "h1": h1, "available_by_A_flagged_location": loc, "flagged_step_size_class": sizes, "flagged_logged_km_stratum": lstr,
                      "diagnostic_drives_with_an_endpoint_inside_a_recorded_excursion": int(exc), "recorded_excursions": int(len(spans)), "negative_steps": int(cnt.get("negativeSteps", 0))},
               "J2": j2, "J2_availability_by_month": bym, "R2": r2, "R3": r3,
               "disclosures": ["H1 was derived from the registered totals and the rule texts; P was frozen before any per-drive look; B, B1, B3 and P are reported side by side and P is not chosen because of its result (spec 7.8)",
                               "B3 is a reconstruction of the audit rule from its rules_inferred text, not the auditor's code (spec 7.4); a 6-drive availability difference between the M752 audit (586 available) and A minus the B3 flags (592) is NOT resolved and concerns only how faithfully B3 copies the audit rule, not P",
                               "H1 (order of reasons) was falsified: the frozen predictions are not met (spec 7.2, 7.3); the 17 versus 7 comes from the extra window rows of the tool rule B (B2 = B and B3 = B1)",
                               "the three-valued within-1-% wording (above / interval includes / within) replaces the M752 two-valued wording for every rule in this result (Director ruling C1, spec 8); counts are unchanged",
                               "P can miss a level excursion that starts before the first endpoint row; the excursion sensitivity (22 drives, 31 under a wider definition) is pre-registered for the replacement milestone (Director C2)",
                               "the excursion count is a diagnostic, not a rule: P can miss an excursion that starts before the first endpoint row (spec 7.6)"],
               "privacy": "counts, rates and size classes only; no drive names, dates, coordinates or absolute cloud odometer values", "seconds": round(time.time() - t_start, 1)}
        bad = scan_privacy(res)
        if bad:
            raise dm.Stop("privacy scan failed: %s" % bad[:3])
        if dm.md5(a.master) != dm.REGISTERED_MASTER:
            raise dm.Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        with open(os.path.join(a.out_dir, "M765_jump_rule.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, default=float)
        print("odometer_jump_audit: H1 %s | R2 %s | replacement trigger %s" % (h1["h1_confirmed"], r2["reading"], r3["replacement_trigger"]))
        return 0
    except dm.Stop as e:
        print("odometer_jump_audit: STOP (%s)" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
