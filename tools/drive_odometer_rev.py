#!/usr/bin/env python3
"""M766 (spec analyses/M766_spec.md Rev 2): the M752 odometer-agreement outputs under the REVISED jump rule P (the physical rule of M765). Auxiliary, report-only, offline.

Control R0: run with rule B (the M752 tool rule) the same code reproduces the registered M752 result leaf by leaf (coverage, selection, agreement, resolution) or the run stops (exit 3). R1: the same code with rule P per estimator
(E_int, E_br, E_near, E_near60: the stretch of rows from the last row at or before t0 to the first row at or after t1; the +16 s sensitivity: the shifted endpoint rows). R2: the P results equal the M765 P results (tolerance 0).
The P-minus-excursion sensitivities S1 (an endpoint time inside a level excursion span) and S2 (wide: between the last row before and the first row after an excursion) are reported, never primary.
Aggregates only: no drive names, dates, coordinates or absolute cloud odometer values (the anchor is carried as the difference and n only).

Usage: python tools/drive_odometer_rev.py [--store DIR] [--master FILE] [--out-dir analyses] [--nb 4000]   Exit codes: 0 done or skipped, 1 master pin, 3 control / consistency / pin failure."""
import argparse, csv, json, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import drive_odometer as dm
import odometer_jump_audit as J
import mynissan_import as mi
import mynissan_coverage as mc

ROOT = dm.ROOT
ESTIMATORS = ("E_int", "E_br", "E_near", "E_near60", "E_int_shift16")
M752_RESULT_SHA = J.M752_RESULT_SHA
M765_RESULT_REL = "analyses/M765_jump_rule.json"
EXPECTED_S1 = 22                      # M765 diagnostic (spec 7.6): a mismatch stops the run
EXPECTED_S2 = 31                      # text expectation only: a mismatch is a deviation (spec 7.6)


class Stop(Exception):
    pass


# ------------------------------------------------------------------ rule application (known-answer tested)
def endpoints_with_flags(t0, t1, ts, vs, flag_main, flag_shift):
    """drive_odometer.drive_endpoints with the jump decision supplied: flag_main for E_int, E_br, E_near, E_near60 and flag_shift for the +16 s sensitivity (rule B passes the same flag for all, as the M752 tool does)."""
    out = {}
    specs = {"E_int": ("int", "int", 0.0, flag_main), "E_br": ("br_start", "br_end", 0.0, flag_main), "E_near": ("near", "near", 0.0, flag_main),
             "E_near60": ("near60", "near60", 0.0, flag_main), "E_int_shift16": ("int", "int", dm.SHIFT_S, flag_shift)}
    for name, (ms, me, sh, flag) in specs.items():
        if flag:
            out[name] = {"start": None, "end": None, "ageStart": None, "ageEnd": None, "reasonStart": "odometer_jump", "reasonEnd": "odometer_jump", "dist": None}
            continue
        a, aa, ra = dm.odo_at(t0, ts, vs, ms, sh)
        b, ab, rb = dm.odo_at(t1, ts, vs, me, sh)
        ok = a is not None and b is not None
        out[name] = {"start": a, "end": b, "ageStart": aa, "ageEnd": ab, "reasonStart": ra, "reasonEnd": rb, "dist": (b - a) if ok else None}
    return out


def flags_for_rule(rule, t0, t1, ts, vs):
    """(flag_main, flag_shift) of a rule: B = the M752 tool rule for every estimator; P = the physical rule (shift 0 and +16 s)."""
    if rule == "B":
        b = bool(dm.jump_in_window(t0, t1, ts, vs))
        return b, b
    return bool(J.rule_flags(t0, t1, ts, vs, 0.0)["P"]), bool(J.rule_flags(t0, t1, ts, vs, dm.SHIFT_S)["P"])


def excursion_spans_wide(ts, vs):
    """S2: (time of the last row before, time of the first row after) each level excursion."""
    if len(ts) < 2:
        return []
    run = np.maximum.accumulate(vs)
    below = vs < run - dm.REGRESS_KM
    edges = np.diff(np.r_[0, below.astype(int), 0])
    starts, ends = np.where(edges == 1)[0], np.where(edges == -1)[0] - 1
    return [(float(ts[max(s - 1, 0)]), float(ts[min(e + 1, len(ts) - 1)])) for s, e in zip(starts, ends)]


def forbidden_present(res):
    """True when an M752 absolute anchor key is present in the result (spec 7.5)."""
    txt = json.dumps(res, default=float)
    return any(k in txt for k in ("cloudLastOdoKm", "cloudPlusLogged", "dashOdoKm"))


def leaf_equal(a, b, path="", out=None):
    """Deep comparison with tolerance 0; returns the list of differing paths."""
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(path + "/" + str(k))
            else:
                leaf_equal(a[k], b[k], path + "/" + str(k), out)
    elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            out.append(path)
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                leaf_equal(x, y, path + "[%d]" % i, out)
    elif a != b:
        out.append(path)
    return out


def blocks(df, ts, vs, nb, verdict_fn):
    """P0 coverage and selection, P1 agreement (the whole M752 schema), P2 resolution, computed from the per-drive frame exactly as drive_odometer.main does."""
    cov = {"drives": int(len(df))}
    for name in ESTIMATORS:
        av = df[name + "_dist"].notna()
        reasons = df.loc[~av, name + "_reason"].value_counts().to_dict()
        cov[name] = {"available": int(av.sum()), "unavailableByReason": {k: int(v) for k, v in reasons.items()}}
    sel = {"byStratum": {}, "byMonth": {}}
    for s in ("below2km", "2to10km", "10kmplus"):
        sub = df[df["stratum"] == s]
        sel["byStratum"][s] = {"drives": int(len(sub)), "available": int(sub["E_int_dist"].notna().sum())}
    for mth, sub in df.groupby("month"):
        sel["byMonth"][mth] = {"drives": int(len(sub)), "available": int(sub["E_int_dist"].notna().sum())}
    elig = df[df["clean"] & df["logged"].notna()]
    p1, words = {}, {}
    for name in ESTIMATORS:
        sub = elig[elig[name + "_dist"].notna()].copy()
        sub["delta"] = sub[name + "_dist"] - sub["logged"]
        sub["day"] = sub["date"]
        block = {"identityClass": {}, "strata": {}}
        prim = sub[sub["identity"]]
        block["primary_identity_ge2km"] = dm.summarise(prim[prim["logged"] >= dm.SHORT_KM], nb)
        block["all_ge2km"] = dm.summarise(sub[sub["logged"] >= dm.SHORT_KM], nb)
        block["identityClass"]["identity"] = dm.summarise(prim, nb)
        block["identityClass"]["notIdentity"] = {"nDrives": int((~sub["identity"]).sum()), "nDays": int(sub.loc[~sub["identity"], "day"].nunique()),
                                                 "note": "sensitivity class (trip_meter, repaired or other non-identity drives): counts only unless the floor is met"}
        for s in ("below2km", "2to10km", "10kmplus"):
            ss = prim[prim["stratum"] == s]
            block["strata"][s] = ({"nDrives": int(len(ss)), "nDays": int(ss["day"].nunique()), "status": "counts only: no agreement verdict below 2 km (resolution)"} if s == "below2km" else dm.summarise(ss, nb))
        p1[name] = block
        if name == "E_int":
            words["primary_E_int_identity_ge2km"] = {"within1pct": verdict_fn(block["primary_identity_ge2km"], dm.MARGIN_PRIMARY), "within3pct": verdict_fn(block["primary_identity_ge2km"], dm.MARGIN_WIDE)}
    dv = np.diff(vs)
    pos = dv[dv > 0]
    p2 = {"smallestPositiveCloudIncrementKm": round(float(pos.min()), 5) if len(pos) else None, "loggedResolutionKm": 0.1,
          "note": "a per-drive difference below the combined resolution is not read as disagreement"}
    return {"P0_coverage": cov, "P0_selection_check": sel, "P1_agreement": p1, "P1_verdict_wording": words, "P2_resolution": p2}


def drive_frame(master, mdf, ts, vs, rule):
    recs = []
    for m in master:
        r = mdf.loc[m["file"]]
        logged = float(r["distance_km"]) if pd.notna(r["distance_km"]) else None
        ident = (logged is not None and pd.notna(r["odo_end"]) and abs(logged - (float(r["odo_end"]) - float(r["odo_start"]))) <= dm.IDENT_KM)
        clean = (r["ens_outlier_v2"] is False) or (str(r["ens_outlier_v2"]) == "False")
        fm, fs = flags_for_rule(rule, m["t0"], m["t1"], ts, vs)
        ep = endpoints_with_flags(m["t0"], m["t1"], ts, vs, fm, fs)
        row = {"date": m["date"], "month": m["date"][:7], "t0": m["t0"], "t1": m["t1"], "logged": logged, "identity": bool(ident), "clean": bool(clean)}
        for name, e in ep.items():
            row[name + "_dist"] = e["dist"]
            row[name + "_reason"] = e["reasonStart"] if e["reasonStart"] != "ok" and e["reasonStart"] != "flat" else e["reasonEnd"]
        recs.append(row)
    df = pd.DataFrame(recs)
    df["stratum"] = df["logged"].map(lambda v: dm.stratum_of(v) if v is not None and not pd.isna(v) else None)
    return df


def sensitivity(df, spans_s1, spans_s2, nb):
    """P minus the drives with an endpoint inside an excursion span (S1 strict, S2 wide): agreement of the primary estimator."""
    out = {}
    for lab, spans in (("S1_strict", spans_s1), ("S2_wide", spans_s2)):
        drop = df.apply(lambda r: J.in_excursion(r["t0"], spans) or J.in_excursion(r["t1"], spans), axis=1)
        sub = df[df["clean"] & df["logged"].notna() & df["E_int_dist"].notna() & ~drop].copy()
        sub["delta"] = sub["E_int_dist"] - sub["logged"]
        sub["day"] = sub["date"]
        prim = sub[sub["identity"]]
        s = dm.summarise(prim[prim["logged"] >= dm.SHORT_KM], nb)
        out[lab] = {"drives_with_an_endpoint_inside_an_excursion": int(drop.sum()), "available_all_drives_after": int((df["E_int_dist"].notna() & ~drop).sum()), "primary_identity_ge2km": s,
                    "verdict_words": {"within1pct": J.verdict_three(s, dm.MARGIN_PRIMARY), "within3pct": J.verdict_three(s, dm.MARGIN_WIDE)}}
    return out


DEVIATIONS = [
    "the M752 audit-count fields (7 jump-excluded, n 420, 586 available) are not used under the revised rule; the jump-rule difference is carried as the Director's disclosure sentence of M765",
    "E_near and E_near60 use the endpoint rows of their own windows under P; their nearest row is one of the bracketing rows, so the stretch equals the bracketing stretch (spec 7.7 a); they are not displayed",
    "the within-1-% and within-3-% wording is the three-valued function of M765 (verdict_three), not the two-valued M752 wording; counts and intervals are unchanged by this",
    "the anchor is carried as the difference and n only (spec 7.8); the absolute fields of the M752 result are not copied",
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=mi.default_store())
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "analyses"))
    ap.add_argument("--nb", type=int, default=dm.NB_DEFAULT)
    a = ap.parse_args(argv)
    if not os.path.exists(os.path.join(a.store, "manifest.json")):
        print("drive_odometer_rev: no cloud store, skipped (optional)")
        return 0
    t_start = time.time()
    try:
        if dm.md5(a.master) != dm.REGISTERED_MASTER:
            print("drive_odometer_rev: master pin failed")
            return 1
        if dm.sha256(os.path.join(HERE, "drive_odometer.py")) != J.M752_TOOL_SHA:
            raise Stop("tools/drive_odometer.py differs from the M752 tool sha256")
        if dm.sha256(os.path.join(a.store, "manifest.json")) != J.STORE_MANIFEST_SHA:
            raise Stop("the cloud store manifest differs from the registered one")
        reg_path = os.path.join(a.out_dir, "M752_odometer_agreement.json")
        if dm.sha256(reg_path) != M752_RESULT_SHA:
            raise Stop("the registered M752 result differs from its pinned sha256")
        reg = json.load(open(reg_path, encoding="utf-8"))
        m765 = json.load(open(os.path.join(a.out_dir, "M765_jump_rule.json"), encoding="utf-8"))
        rows = [(t, mc.fnum(x.get("StatusDistanceTotalizerComputed", ""))) for t, x in mi.load_stream(a.store, "Odometer")]
        conf = set()
        cp = os.path.join(a.store, "conflicts.csv")
        if os.path.exists(cp):
            for r in csv.DictReader(open(cp, encoding="utf-8", newline="")):
                if r["stream"] == "Odometer":
                    conf.add(mi.to_epoch(r["timestamp_utc"]))
        ts, vs, cnt = dm.accepted_odo(rows, conf)
        dm.check_gain(ts, vs)
        master = mc.load_master(a.master)
        mdf = pd.read_csv(a.master, usecols=["file", "distance_km", "odo_start", "odo_end", "ens_outlier_v2"], low_memory=False).set_index("file")
        # R0 control: rule B reproduces the registered M752 numbers leaf by leaf
        dfB = drive_frame(master, mdf, ts, vs, "B")
        bB = blocks(dfB, ts, vs, a.nb, lambda s, m: "")
        diffs = []
        for k in ("P0_coverage", "P0_selection_check", "P1_agreement", "P2_resolution"):
            diffs += leaf_equal(json.loads(json.dumps(bB[k], default=float)), reg[k], k)
        if diffs:
            raise Stop("control R0: the M752 result is not reproduced under rule B (%d leaves differ, first %s)" % (len(diffs), diffs[:3]))
        # R1 the revised rule
        dfP = drive_frame(master, mdf, ts, vs, "P")
        bP = blocks(dfP, ts, vs, a.nb, J.verdict_three)
        # R2 consistency with M765 (tolerance 0)
        j2 = m765["J2"]["P"]
        pI = bP["P1_agreement"]["E_int"]["primary_identity_ge2km"]
        chk = []
        chk += leaf_equal(json.loads(json.dumps(pI, default=float)), j2["E_int"]["primary_identity_ge2km"], "E_int")
        chk += leaf_equal(json.loads(json.dumps(bP["P1_agreement"]["E_br"]["primary_identity_ge2km"], default=float)), j2["E_br"]["primary_identity_ge2km"], "E_br")
        chk += leaf_equal(json.loads(json.dumps(bP["P1_agreement"]["E_int_shift16"]["primary_identity_ge2km"], default=float)), j2["E_int_shift16"]["primary_identity_ge2km"], "shift16")
        for name in ("E_int", "E_br", "E_int_shift16"):
            if bP["P0_coverage"][name]["available"] != j2[name]["available_all_drives"]:
                chk.append(name + "/available")
        for mth, cell in m765["J2_availability_by_month"]["P"].items():
            if isinstance(cell, dict) and bP["P0_selection_check"]["byMonth"].get(mth) != cell:
                chk.append("byMonth/" + mth)
        if chk:
            raise Stop("consistency R2: the P results differ from M765 (%s)" % chk[:3])
        spans1, spans2 = J.excursion_spans(ts, vs), excursion_spans_wide(ts, vs)
        s1 = int(sum(1 for r in dfP.itertuples() if J.in_excursion(r.t0, spans1) or J.in_excursion(r.t1, spans1)))
        if s1 != EXPECTED_S1:
            raise Stop("consistency R2: the S1 count %d differs from the M765 diagnostic %d" % (s1, EXPECTED_S1))
        sens = sensitivity(dfP, spans1, spans2, a.nb)
        s2 = sens["S2_wide"]["drives_with_an_endpoint_inside_an_excursion"]
        devs = list(DEVIATIONS)
        if s2 != EXPECTED_S2:
            devs.append("the S2 (wide) count is %d, the text expectation was %d (spec 7.6: reported as a deviation, not a stop)" % (s2, EXPECTED_S2))
        cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))["vehicle"]
        after = [(r.t0, r.t1, r.logged) for r in dfP.itertuples() if r.logged is not None and not pd.isna(r.logged) and r.t1 > ts[-1]]
        anc = dm.anchor(float(cfg["odometerKm"]), float(vs[-1]), float(ts[-1]), after)
        p3 = {"differenceKm": anc["differenceKm"], "n": anc["n"], "note": "the anchor does not depend on the jump rule; carried as the difference and n only"}
        res = {"milestone": "M766", "spec": "analyses/M766_spec.md Rev 2", "rule": "P (revised rule, M765)", "role": "the M752 odometer-agreement outputs under the revised jump rule P; report-only",
               "masterMd5": dm.REGISTERED_MASTER, "storeManifestSha256": J.STORE_MANIFEST_SHA, "m752ToolSha256": J.M752_TOOL_SHA, "m752ResultSha256": M752_RESULT_SHA,
               "m765ResultSha256": dm.sha256(os.path.join(a.out_dir, "M765_jump_rule.json")), "toolSha256": dm.sha256(os.path.abspath(__file__)), "seed": dm.SEED, "nBoot": a.nb,
               "control_R0": {"rule": "B", "reproduced_leaf_by_leaf": True, "blocks": ["P0_coverage", "P0_selection_check", "P1_agreement", "P2_resolution"]},
               "consistency_R2": {"equals_M765_P": True, "S1_count": s1},
               "P0_coverage": bP["P0_coverage"], "P0_selection_check": bP["P0_selection_check"], "P1_agreement": bP["P1_agreement"], "P1_verdict_wording": bP["P1_verdict_wording"],
               "P2_resolution": bP["P2_resolution"], "P3_anchor": p3,
               "P_vs_B_counts": {"jump_flagged_B": m765["J1"]["crosstab"]["rules"]["B"]["flagged"], "jump_flagged_B1_strictly_inside": m765["J1"]["crosstab"]["rules"]["B1"]["flagged"],
                                 "jump_flagged_P": m765["J1"]["crosstab"]["rules"]["P"]["flagged"], "R2": m765["R2"]},
               "excursionSensitivity": sens, "excursions_recorded": int(len(spans1)), "negative_steps": int(cnt.get("negativeSteps", 0)), "level_excursions": int(cnt.get("levelExcursions", 0)),
               "maxExcursionKm": cnt.get("maxExcursionKm"), "deviations_from_spec": devs,
               "scope": "report-only: no master column, payload or dashboard change inside this result; never substituted into distance_km or the logged-share KPI", "seconds": round(time.time() - t_start, 1)}
        bad = J.scan_privacy(res)
        if bad or forbidden_present(res):
            raise Stop("privacy scan failed: %s" % bad[:3])
        if dm.md5(a.master) != dm.REGISTERED_MASTER:
            raise Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        with open(os.path.join(a.out_dir, "M766_odometer_agreement_P.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, default=float)
        print("drive_odometer_rev: R0 ok | R2 ok | P n %d, relative %.3f %% | S1 %d S2 %d | %.0f s" % (pI["nDrives"], 100 * pI["relative"]["est"], s1, s2, res["seconds"]))
        return 0
    except (Stop, dm.Stop) as e:
        print("drive_odometer_rev: STOP (%s)" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
