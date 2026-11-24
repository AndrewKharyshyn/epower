#!/usr/bin/env python3
"""M767 (spec analyses/M767_spec.md Rev 2): grade-class SHARES of the covered driving (the use that the M762 result allows). Auxiliary, report-only, offline.

E1 step-count share by class (PRIMARY) and km-weighted share (secondary, labelled new) on the frozen M762 primary step set with day-clustered percentile bootstrap intervals (seed 42, 4000 draws); E2 cohort shares (in the result only, never displayed);
E3 the four product shares per class with their minimum and maximum (a bracket, not an interval) and the flag 'source-dependent' when another product lies outside the FABDEM day interval; E4 coverage of the logged kilometres and the selection of the covered
driving (month, length, cohort, drive-level speed mix), the steps excluded above 8 pp and the FABDEM sensitivities on the pre-mask and the no-GLO-flag sets. Control R1: the stages and the FABDEM step shares equal the M762 result (tolerance 0).
Aggregates only: no coordinates, tracks, per-drive geometry or dates (months only).

Usage: python tools/dem_grade_shares.py --run [--cache FILE] [--nb 4000]   Exit codes: 0 done or skipped, 1 master pin, 3 control or manifest failure."""
import argparse, json, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import dem_step_grade as dsg
import dem_crosscheck as X
import odometer_jump_audit as J

SEED, NB_DEFAULT = 42, 4000
CLASS_NAMES = ("below -3 pp", "-3 to -1 pp", "-1 to 1 pp", "1 to 3 pp", "above 3 pp")
FLOORS = {"days": 30, "km": 100.0, "steps": 1000}
CELL_FLOORS = {"steps": 20, "days": 5}                       # spec 3 R2: a cell below it is counts only
SOURCES = ("F", "N", "A", "G")
REGISTERED_N = 717
REGISTERED_FILES_SHA = "65878488cfab9652252cb7f4c4e607fdd1af4c69c74eca64c0e95f461da2e0a8"   # sha256 of the sorted canonical file names of the registered master (M767 addendum Rev 3)
RETEST_RESULT = "grade_shares_retest.json"


class Stop(Exception):
    pass


def classes5(g):
    return np.digitize(np.asarray(g, float), dsg.CLASS_EDGES)


def day_counts(cls, w, di, nd, k=5):
    """Per-day sums of the weight w by class: array [nd, k]."""
    out = np.zeros((nd, k))
    ok = (cls >= 0) & (cls < k) & np.isfinite(w)
    np.add.at(out, (di[ok], cls[ok]), w[ok])
    return out


def share_block(cls, w, days, W, k=5):
    """Shares of the weight w by class (steps: w = 1; km: w = step length) with day-clustered percentile intervals: returns point shares [k] and draws [nb, k]."""
    ud, di = X.day_index(days)
    C = day_counts(cls, w, di, len(ud), k)
    pt = C.sum(0) / C.sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        tot = W @ C
        dr = tot / tot.sum(1, keepdims=True)
    return pt, dr, len(ud)


def pct_ci(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))] if len(x) > 20 else [None, None]


def class_support(cls, days, km, drives, c):
    m = cls == c
    nd, ns, kmc = len(set(np.asarray(days)[m])), int(m.sum()), float(np.asarray(km)[m].sum())
    return {"steps": ns, "days": int(nd), "drives": int(len(set(np.asarray(drives)[m]))), "km": kmc,
            "interval_shown": bool(ns >= CELL_FLOORS["steps"] and nd >= CELL_FLOORS["days"])}


def shares_table(df, gcol, nb, W_cache):
    """E1 on a step frame: step share (primary) and km share (secondary) by class, with intervals and the support of each class."""
    cls = classes5(df[gcol].values)
    days = df["day"].values
    ud, _ = X.day_index(days)
    if len(ud) not in W_cache:
        W_cache[len(ud)] = X.boot_weights(len(ud), nb)
    W = W_cache[len(ud)]
    ps, ds, nd = share_block(cls, np.ones(len(df)), days, W)
    pk, dk, _ = share_block(cls, df["d_m"].values / 1000.0, days, W)
    rows = []
    for c in range(5):
        sup = class_support(cls, days, df["d_m"].values / 1000.0, df["drive"].values, c)
        rows.append({"class": CLASS_NAMES[c], "support": sup,
                     "step_share_pct": {"est": float(100 * ps[c]), "ci95": [None if v is None else float(100 * v) for v in pct_ci(ds[:, c])] if sup["interval_shown"] else [None, None]},
                     "km_share_pct": {"est": float(100 * pk[c]), "ci95": [None if v is None else float(100 * v) for v in pct_ci(dk[:, c])] if sup["interval_shown"] else [None, None]}})
    return {"n_steps": int(len(df)), "n_days": int(nd), "km": float(df["d_m"].sum() / 1000.0), "rows": rows}


def bracket_and_flags(df, nb, W_cache, f_rows):
    """E3: step share by class for each of the four products on the same steps, their min and max, and 'source-dependent' when another product lies outside FABDEM's day interval."""
    out = []
    shares = {}
    for k in SOURCES:
        cls = classes5(df["g" + k].values)
        shares[k] = np.array([float(np.mean(cls == c)) for c in range(5)]) * 100.0
    for c in range(5):
        vals = {k: float(shares[k][c]) for k in SOURCES}
        lo, hi = f_rows[c]["step_share_pct"]["ci95"]
        dep = None
        if lo is not None and hi is not None:
            dep = bool(any((v < lo or v > hi) for k, v in vals.items() if k != "F"))
        out.append({"class": CLASS_NAMES[c], "by_product_step_share_pct": vals, "bracket_min": min(vals.values()), "bracket_max": max(vals.values()), "source_dependent": dep})
    return out


def coverage_tables(prim, dmaster, canonical, cohort_of):
    """E4: covered km against the logged km of the registered master, by month and length stratum; the cohort and drive-level speed-class mix of the covered versus the whole logged driving."""
    lg = dmaster[dmaster["file"].isin(canonical)].copy()
    lg["km"] = pd.to_numeric(lg["distance_km"], errors="coerce").fillna(0.0)
    lg["month"] = lg["date"].astype(str).str[:7]
    cov = prim.groupby("drive")["d_m"].sum() / 1000.0
    lg["cov_km"] = lg["file"].map(cov).fillna(0.0)
    lg["stratum"] = np.where(lg["km"] < 2.0, "below 2 km", np.where(lg["km"] < 10.0, "2 to 10 km", "10 km and longer"))
    lg["cohort"] = lg["file"].map(cohort_of).fillna("unknown")
    tot_km, cov_km = float(lg["km"].sum()), float(lg["cov_km"].sum())
    out = {"logged_km": tot_km, "covered_km": cov_km, "covered_share_of_logged_km_pct": 100.0 * cov_km / tot_km, "drives": int(len(lg)), "drives_with_a_covered_step": int((lg["cov_km"] > 0).sum())}
    for key in ("month", "stratum", "cohort"):
        g = lg.groupby(key).agg(logged=("km", "sum"), covered=("cov_km", "sum"), drives=("file", "count"))
        cells = {}
        for name, r in g.iterrows():
            cells[str(name)] = {"drives": int(r["drives"]), "logged_km": float(r["logged"]), "covered_km": float(r["covered"]), "covered_share_pct": float(100.0 * r["covered"] / r["logged"]) if r["logged"] > 0 else None} if r["drives"] >= 3 else "suppressed (fewer than 3 drives)"
        out["by_" + key] = cells
    # drive-level speed-class mix (the master's time-weighted urban and highway fractions) weighted by km: the whole logged driving, the covered part and the uncovered remainder
    pu = pd.to_numeric(lg["pct_urban"], errors="coerce").fillna(0.0).values
    ph = pd.to_numeric(lg["pct_highway"], errors="coerce").fillna(0.0).values
    def mix(w):
        s = float(np.sum(w))
        if s <= 0:
            return None
        u, h = float(np.sum(w * pu) / s), float(np.sum(w * ph) / s)
        return {"urban_pct": u, "highway_pct": h, "mixed_pct": 100.0 - u - h}
    unc = np.maximum(lg["km"].values - lg["cov_km"].values, 0.0)
    out["drive_level_speed_class_mix_km_weighted"] = {"all_logged": mix(lg["km"].values), "covered": mix(lg["cov_km"].values), "uncovered_remainder": mix(unc),
                                                      "note": "drive-level: the master's time-weighted urban and highway fractions of each drive weighted by its kilometres; an approximation of the speed mix of the covered and uncovered kilometres"}
    return out


def step_sets(df):
    """The frozen M762 selection (first/last, speed, common support, NUM mask, GLO flag, 8 pp exclusion): (stages, base, cs, nasok, gloOK, prim)."""
    base = df[~df["first"] & ~df["last"] & (df["vmin_kmh"] >= dsg.V_MIN_KMH)]
    cs = base[np.isfinite(base["gF"]) & np.isfinite(base["gN"]) & np.isfinite(base["gA"])]
    nasok = cs[np.isfinite(cs["dh_num"])]
    gloOK = nasok[np.isfinite(nasok["dh_glo"])]
    prim = gloOK[gloOK["gF"].abs() <= dsg.GRADE_EXCL_PP]
    stages = {"all_steps_before_exclusions": int(len(df)), "after_first_last_speed": int(len(base)), "common_support_F_N_A_finite": int(len(cs)), "after_nasadem_num_srtm_mask": int(len(nasok)),
              "after_glo30_unflagged_mask": int(len(gloOK)), "after_fabdem_grade_8pp_exclusion": int(len(prim))}
    return stages, base, cs, nasok, gloOK, prim


def control_r1(df, m762):
    """Control R1 on a step table: the M762 C1 stages and C6 FABDEM shares and misclassification (tolerance 0)."""
    stages, base, cs, nasok, gloOK, prim = step_sets(df)
    if stages != m762["C1_step_stages"]:
        raise Stop("control R1: the step stages differ from the M762 result: %s" % stages)
    clF = classes5(prim["gF"].values)
    f_shares = [float(np.mean(clF == c)) for c in range(5)]
    if f_shares != m762["C6_class_shares"]["F"]["step_share"]:
        raise Stop("control R1: the FABDEM step shares differ from the M762 C6 result")
    mis = {k: float(np.mean(clF != classes5(prim["g" + k].values))) for k in ("N", "A", "G")}
    if mis["N"] != m762["C6_misclassification_vs_fabdem"]["N"] or mis["A"] != m762["C6_misclassification_vs_fabdem"]["A"]:
        raise Stop("control R1: the misclassification rates differ from the M762 result")
    return stages, base, cs, nasok, gloOK, prim, clF, f_shares, mis


def registered_files(canonical):
    """The registered 717 drives = the first REGISTERED_N canonical files of the master (ingestions append); verified by the sha256 of their sorted names."""
    import hashlib
    reg = list(canonical[:REGISTERED_N])
    if len(reg) != REGISTERED_N or hashlib.sha256("\n".join(sorted(reg)).encode()).hexdigest() != REGISTERED_FILES_SHA:
        raise Stop("retest: the first %d canonical drives of the master are not the registered set" % REGISTERED_N)
    return reg


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dem-dir", default=os.environ.get("XT_DEM_DIR") or "")
    ap.add_argument("--store", default=None)
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or "")
    ap.add_argument("--out-dir", default=os.path.join(HERE, "..", "analyses"))
    ap.add_argument("--master", default=os.path.join(HERE, "..", "drive_master.csv"))
    ap.add_argument("--seasonal", default=os.path.join(HERE, "..", "seasonal_drive_master.csv"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    ap.add_argument("--cache", default="")
    ap.add_argument("--retest", action="store_true", help="M746 Rev 5: run on a later master (the registered result and pin are never touched; needs --out-dir outside analyses)")
    a = ap.parse_args(argv)
    for sub in ("fabdem", "nasadem", "aw3d30", "glo30"):
        if not a.dem_dir or not os.path.isdir(os.path.join(a.dem_dir, sub)):
            print("dem_grade_shares: DEM directories missing, skipped (optional)")
            return 0
    if not a.run:
        print(__doc__)
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    t_start = time.time()
    try:
        a.store = a.store or dsg.mi.default_store()
        if not os.path.exists(os.path.join(a.store, "manifest.json")) or not os.path.isdir(a.raw_dir):
            print("dem_grade_shares: no cloud store or raw directory, skipped (optional)")
            return 0
        man_path = os.path.join(HERE, "..", "analyses", "M762_dem_manifest.json")
        m762_path = os.path.join(HERE, "..", "analyses", "M762_dem_crosscheck.json")
        X.verify_manifest(a.dem_dir, man_path)
        master_md5 = dsg.mc.md5(a.master)
        if master_md5 != dsg.PINNED_MD5 and not a.retest:
            print("dem_grade_shares: master pin failed")
            return 1
        if a.retest and os.path.abspath(a.out_dir) == os.path.abspath(os.path.join(HERE, "..", "analyses")):
            print("dem_grade_shares: a retest never writes into analyses/ itself (use a scratch --out-dir)")
            return 1
        m762 = json.load(open(m762_path, encoding="utf-8"))
        c0 = X.integrity_stage(a.dem_dir)
        sf, sn, sa, sg, numS, edm, flm, tmp = X.build_surfaces(a.dem_dir)
        try:
            dems = {"F": sf, "N": sn, "A": sa, "G": sg, "num": X.num_mask(numS),
                    "glo": X.glo_unflagged_mask(edm, flm, c0["glo30_masks"]["EDM"]["unflagged_code"], c0["glo30_masks"]["FLM"]["unflagged_code"])}
            if a.cache and os.path.exists(a.cache):
                import pickle
                df, _fixes = pickle.load(open(a.cache, "rb"))
            else:
                df, fixes = X.collect_multi(a, dems)
                if a.cache:
                    import pickle
                    pickle.dump((df, fixes), open(a.cache, "wb"))
        finally:
            import shutil
            getattr(sa.loader, "close", lambda: None)()
            shutil.rmtree(tmp, ignore_errors=True)
        df = X._grades(df)
        canonical = [m["file"] for m in dsg.mc.load_master(a.master)]
        nested = None
        if a.retest:
            reg = set(registered_files(canonical))
            control_r1(df[df["drive"].isin(reg)], m762)                    # nested control: the registered drives reproduce M762 C1/C6 exactly
            nested = {"registered_drives": REGISTERED_N, "stages_and_shares_equal_M762": True}
        if a.retest:
            stages, base, cs, nasok, gloOK, prim = step_sets(df)
            clF = classes5(prim["gF"].values)
            f_shares = [float(np.mean(clF == c)) for c in range(5)]
            mis = {k: float(np.mean(clF != classes5(prim["g" + k].values))) for k in ("N", "A", "G")}
        else:
            stages, base, cs, nasok, gloOK, prim, clF, f_shares, mis = control_r1(df, m762)
        W_cache = {}
        e1 = shares_table(prim, "gF", a.nb, W_cache)
        e3 = bracket_and_flags(prim, a.nb, W_cache, e1["rows"])
        e2 = {}
        for coh in sorted(set(prim["cohort"])):
            sub = prim[prim["cohort"] == coh]
            sup_ok = bool(len(sub) >= FLOORS["steps"] and len(set(sub["day"])) >= FLOORS["days"] and sub["d_m"].sum() / 1000.0 >= FLOORS["km"])
            e2[str(coh)] = shares_table(sub, "gF", a.nb, W_cache) if sup_ok else {"counts_only": True, "n_steps": int(len(sub)), "n_days": int(len(set(sub["day"]))), "km": float(sub["d_m"].sum() / 1000.0),
                                                                                    "step_counts_by_class": [int((classes5(sub["gF"].values) == c).sum()) for c in range(5)]}
        dmaster = pd.read_csv(a.master, low_memory=False)
        canonical = [m["file"] for m in dsg.mc.load_master(a.master)]
        cohort_of = {}
        if os.path.exists(a.seasonal):
            sd = pd.read_csv(a.seasonal, usecols=["file", "thermal_regime"])
            cohort_of = dict(zip(sd["file"], sd["thermal_regime"]))
        e4 = coverage_tables(prim, dmaster, canonical, cohort_of)
        excluded = gloOK[gloOK["gF"].abs() > dsg.GRADE_EXCL_PP]
        e4["steps_excluded_above_8pp"] = {"n_steps": int(len(excluded)), "share_of_steps_after_masks_pct": float(100.0 * len(excluded) / len(gloOK)), "below_minus_8": int((excluded["gF"] < -dsg.GRADE_EXCL_PP).sum()), "above_8": int((excluded["gF"] > dsg.GRADE_EXCL_PP).sum())}
        e4["fabdem_sensitivities_step_share_pct"] = {"pre_mask_set_%d_steps" % len(cs): [float(100 * np.mean(classes5(cs["gF"].values) == c)) for c in range(5)],
                                                     "no_glo_flag_set_%d_steps" % len(nasok[nasok["gF"].abs() <= dsg.GRADE_EXCL_PP]): [float(100 * np.mean(classes5(nasok[nasok["gF"].abs() <= dsg.GRADE_EXCL_PP]["gF"].values) == c)) for c in range(5)],
                                                     "primary_set_%d_steps" % len(prim): [float(100 * v) for v in f_shares]}
        res = {"milestone": "M767", "spec": "analyses/M767_spec.md Rev 2", "masterMd5": master_md5, "m762ResultSha256": X.sha256_file(m762_path), "m762ManifestSha256": X.sha256_file(man_path),
               "toolSha256": X.sha256_file(os.path.abspath(__file__)), "seed": SEED, "nBoot": a.nb, "control_R1": {"stages_equal_M762": True, "fabdem_step_shares_equal_M762_C6": True, "misclassification_equal_M762": True},
               "C1_step_stages": stages, "E1_shares_primary_steps_secondary_km": e1, "E2_cohorts_result_only": e2, "E3_products": e3, "E4_coverage_and_selection": e4,
               "three_class_and_five_class_misclassification_vs_fabdem_pct": {"five_class": {k: 100.0 * v for k, v in mis.items()}},
               "limits": ["inter-product DEM error only, assumption-conditional (uncorrelated errors); common-mode error is not identified; not the error against the road grade",
                          "shares describe the COVERED driving (cloud-step scale, steps of 300 to 900 m at 8 km/h or more with a cloud position pair), not all driving",
                          "not per-step labels: the class of a step differs between FABDEM and NASADEM or AW3D30 on the shown share of steps",
                          "GLO-30 is FABDEM's base (not independent); FABDEM is the most central product, so random DEM noise moves share out of the -1 to 1 class and the bracket is not symmetric",
                          "the NASADEM mask removed water only; FABDEM's own building and forest removals are not masked; AW3D30 has no mask and its portal licence is 'not provided' (internal use only)",
                          "the M757 placebo failure stands; regeneration, apparent KE recovery, fuel and traction energy by grade class stay locked (M762 8.8 and R4)"],
               "deviations_from_spec": ["the speed mix of the covered versus the uncovered kilometres is a DRIVE-LEVEL approximation (the master's time-weighted urban and highway fractions weighted by drive kilometres), because the step windows of the uncovered parts are not available"],
               "seconds": round(time.time() - t_start, 1)}
        if a.retest:
            res.update({"milestone": "M746 retest of M767", "spec": "analyses/M746_spec.md Rev 5 and analyses/M767_retest_addendum.md", "retest": True, "registeredMd5": dsg.PINNED_MD5, "registeredDrives": REGISTERED_N,
                        "drives": len(canonical), "nestedControl": nested,
                        "retestLabel": "retest on %d drives (master MD5 %s...)" % (len(canonical), master_md5[:8]),
                        "scopeNote": "descriptive monitoring only: a repeated look at the data, no confirmatory reading; the registered result is not replaced; M726: not read by the winter session"})
        bad = J.scan_privacy(res)
        if bad:
            raise Stop("privacy scan failed: %s" % bad[:3])
        if dsg.mc.md5(a.master) != master_md5:
            raise Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        with open(os.path.join(a.out_dir, RETEST_RESULT if a.retest else "M767_grade_class_shares.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, default=lambda o: None if o != o else str(o))
        print("dem_grade_shares: R1 ok | covered %.1f %% of the logged km | flat class %.1f %%" % (e4["covered_share_of_logged_km_pct"], e1["rows"][2]["step_share_pct"]["est"]))
        return 0
    except (Stop, X.Stop) as e:
        print("dem_grade_shares: STOP (%s)" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
