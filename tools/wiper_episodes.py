#!/usr/bin/env python3
"""M772 (spec analyses/M772_spec.md Rev 2): wiper EPISODES from the cloud Vehicle_Information stream (span rule: at least two adjacent on-rows, step at most 35 s, a stop or a missing code splits a run) and one fixed LONG-SOAK start flag
(3 hours or more after the previous logged drive of the full master). Retest of the M771 support gate; the registered M771 result is never written. Auxiliary, report-only, offline.

Nested control (hard gate): from the streams the tool reproduces the M771 gate counts and the dark-proxy contrast (-0.114 with the flag over the whole master, -0.373 within the sample); a mismatch stops and writes nothing.
Wiper wording: a precipitation, spray or washing proxy; never rain. Aggregates only: no per-drive rows, dates or file names.
Usage: python tools/wiper_episodes.py --run [--store DIR] [--out-dir analyses] [--nb 4000]   Exit codes: 0 done, 1 master pin, 3 stop."""
import argparse, json, os, sys, time, bisect
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import payload_energy as PE
import weather_proxy as W
import mynissan_import as mi
import mynissan_coverage as mc

SEED, NB_DEFAULT = 42, 4000
PINNED_MD5 = PE.PINNED_MD5
STEP_MAX_S = 35.0
HOLE_SENS_S = 90.0
PAD_S = 60.0
MIN_ROWS = W.MIN_ROWS
SOAK_H = (3.0, 2.0, 6.0)                                # primary first
GAP_BINS_H = (1, 3, 6, 12, 24)


# ------------------------------------------------------------------ episodes
def episodes(rows, step_max=STEP_MAX_S, strict_span=False, codes=None):
    """rows: time-ordered (t, code, moving) of ONE drive window; code None = missing. A run = adjacent rows (step at most step_max) that are moving with a non-missing, non-zero code (restricted to `codes` if given).
    A run of at least two rows is an EPISODE (strict_span: also first-to-last more than 30 s). Returns (n_episodes, n_on_rows_in_episodes, n_on_rows_total, n_valid_moving_rows)."""
    n_valid = n_on = n_in_ep = n_ep = 0
    run = []
    def close():
        nonlocal n_ep, n_in_ep, run
        if len(run) >= 2 and (not strict_span or run[-1] - run[0] > 30.0):
            n_ep += 1
            n_in_ep += len(run)
        run = []
    prev_t = None
    for t, code, moving in rows:
        if prev_t is not None and t - prev_t > step_max:
            close()
        prev_t = t
        if not moving or code is None:
            close()
            continue
        n_valid += 1
        if code != 0.0 and (codes is None or code in codes):
            n_on += 1
            run.append(t)
        else:
            if code != 0.0:
                n_on += 1
            close()
    close()
    return n_ep, n_in_ep, n_on, n_valid


def episode_class(n_ep, n_on, n_valid):
    """'wet' = at least one episode; 'dry' = no non-zero code at all; 'isolated' = on-rows but no episode (excluded from the contrast); 'few' = fewer than 10 valid moving rows."""
    if n_valid < MIN_ROWS:
        return "few"
    if n_ep >= 1:
        return "wet"
    return "isolated" if n_on > 0 else "dry"


# ------------------------------------------------------------------ long-soak flag
def soak_flags(t0, t1, thresholds_h=SOAK_H):
    """t0, t1: start and end epochs of the drives, any order; returns {threshold: array of 1.0 (long soak), 0.0, NaN for the first drive of the master (unknown)} in the input order. Computed over the FULL list."""
    t0 = np.asarray(t0, float)
    t1 = np.asarray(t1, float)
    order = np.argsort(t0, kind="mergesort")
    gap = np.full(len(t0), np.nan)
    s0, s1 = t0[order], t1[order]
    gap_sorted = np.concatenate([[np.nan], s0[1:] - s1[:-1]])
    gap[order] = gap_sorted
    out = {}
    for h in thresholds_h:
        f = np.where(np.isnan(gap), np.nan, (gap >= h * 3600.0).astype(float))
        out[h] = f
    return out, gap


def gap_bins(gap):
    g = gap[np.isfinite(gap)] / 3600.0
    edges = [0.0] + list(GAP_BINS_H) + [float("inf")]
    return {"%g_to_%s_h" % (a, ("%g" % b) if b != float("inf") else "inf"): int(((g >= a) & (g < b)).sum()) for a, b in zip(edges[:-1], edges[1:])}


# ------------------------------------------------------------------ streams
def drive_rows(store, master_path, pad=PAD_S):
    """Per drive: the M771-definition counts (moving rows with a non-missing code, share of non-zero) and the episode counts under the primary, strict and 90 s rules and code 6 only, read from the pinned store."""
    master = mc.load_master(master_path)
    spd = mc.Series([(t, mc.speed_kmh(x["SpeedDisplayedValueinkmh"])) for t, x in mi.load_stream(store, "Trip_Information") if mc.speed_kmh(x["SpeedDisplayedValueinkmh"]) is not None])
    veh = [(t, x) for t, x in mi.load_stream(store, "Vehicle_Information")]
    vt = [t for t, _ in veh]

    def moving(t):
        n = spd.nearest(t, 20)
        return bool(n and n[1] >= 10)

    out = []
    for d in master:
        lo, hi = d["t0"] - pad, d["t1"] + pad
        i0, i1 = bisect.bisect_left(vt, lo), bisect.bisect_right(vt, hi)
        rows = []
        for t, x in veh[i0:i1]:
            raw = x.get("StatusWipingFront", "")
            code = None if raw in ("", None) else mc.fnum(raw)
            rows.append((t, code, moving(t)))
        mv = [r for r in rows if r[2]]
        valid = [r for r in mv if r[1] is not None]
        share = (sum(1 for r in valid if r[1] != 0.0) / len(valid)) if valid else None
        e_p = episodes(rows)
        e_s = episodes(rows, strict_span=True)
        e_h = episodes(rows, step_max=HOLE_SENS_S)
        e_6 = episodes(rows, codes={6.0})
        out.append({"file": d["file"], "t0": d["t0"], "t1": d["t1"], "moving_n_veh": len(mv), "wiper_nonzero_share": (round(share, 3) if share is not None else float("nan")),
                    "class_primary": episode_class(e_p[0], e_p[2], e_p[3]), "class_strict": episode_class(e_s[0], e_s[2], e_s[3]), "class_hole90": episode_class(e_h[0], e_h[2], e_h[3]),
                    "class_code6": episode_class(e_6[0], e_6[2], e_6[3]), "n_valid": e_p[3], "n_on": e_p[2], "n_ep": e_p[0]})
    return pd.DataFrame(out)


# ------------------------------------------------------------------ analysis
def merged_frame(d0, drv):
    """The M771 frame (tools/weather_proxy.load) with the stream-derived shares and counts replacing the coverage-file ones."""
    d = d0.drop(columns=["wiper_nonzero_share", "moving_n_veh"], errors="ignore").merge(drv[["file", "wiper_nonzero_share", "moving_n_veh", "class_primary", "class_strict", "class_hole90", "class_code6", "t0", "t1"]], on="file", how="left")
    return d


def nested_control(d, m771, nb):
    """Hard gate: the M771 gate counts and the dark-proxy contrast reproduced from the stream-derived shares."""
    e_all, e_fuel = W.eligible(d), W.eligible(d, need_fuel=True)
    for x in (e_all, e_fuel):
        x["wet"] = W.wet_label(x["wiper_nonzero_share"], x["moving_n_veh"], 0.05)
    g = W.gate(e_all, e_fuel)
    ref = m771["G_support_gate"]["thresholds"]["0.05"]
    got = g["thresholds"]["0.05"]
    checks = {"eligible_drives": (int(len(e_all)), int(m771["C_integrity"]["drives_eligible"])), "wet_drives": (got["wet_proxy_drives"], ref["wet_proxy_drives"]), "wet_days": (got["wet_proxy_days"], ref["wet_proxy_days"]),
              "fuel_wet_drives": (got["fuel_basis_wet_proxy_drives"], ref["fuel_basis_wet_proxy_drives"]), "fuel_wet_days": (got["fuel_basis_wet_proxy_days"], ref["fuel_basis_wet_proxy_days"]), "dry": (got["dry_reference_drives"], ref["dry_reference_drives"])}
    bad = {k: v for k, v in checks.items() if v[0] != v[1]}
    if bad:
        raise W.T.Stop("nested control failed (M771 counts not reproduced from the streams): %s" % bad)
    a3, a3s = dark_contrasts(e_all, nb)
    ref3 = m771["A3_exploratory"]["fuel_L_per_100km"]["difference_after_adjustment"]
    ref3s = m771["A3_exploratory"]["sensitivity_first_of_day_within_sample"]["difference_after_adjustment"]
    if abs(a3["calendar_whole_master"]["difference_after_adjustment"] - ref3) > 1e-6 or abs(a3s["difference_after_adjustment"] - ref3s) > 1e-6:
        raise W.T.Stop("nested control failed (the dark-proxy contrast differs from M771)")
    return {"passed": True, "counts_equal": {k: v[0] for k, v in checks.items()}, "dark_contrast_equal_M771": True}


def dark_contrasts(e_all, nb, soak=None, variants=None):
    """Dark-proxy fuel contrasts with the M771 wet-exclusion set: the calendar flag over the whole master (M771 primary), the calendar flag within the sample (M771 sensitivity), and, when given, the soak variants."""
    ed = e_all.copy()
    ed["wet"] = W.wet_label(ed["wiper_nonzero_share"], ed["moving_n_veh"], 0.05)
    dk = W.dark_label(ed["lowbeam_share"], ed["moving_n_veh"], ed["wet"])
    ed["wet"] = dk
    sub = ed[ed["fuel_L_per_100km"].notna() & ed["wet"].isin([0.0, 1.0])].copy()
    res = {"calendar_whole_master": W.boot_diff(sub, "fuel_L_per_100km", nb)}
    s2 = sub.copy()
    s2["first_of_day"] = (s2.sort_values(["day", "time_start"]).groupby("day").cumcount().reindex(s2.index) == 0).astype(float)
    within = W.boot_diff(s2, "fuel_L_per_100km", nb)
    if variants:
        for name, flag in variants.items():
            sv = sub.copy()
            sv["first_of_day"] = flag.reindex(sv.index)
            sv = sv[sv["first_of_day"].notna()]
            res[name] = W.boot_diff(sv, "fuel_L_per_100km", nb)
    return res, within


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--store", default=None)
    ap.add_argument("--out-dir", default=os.path.join(HERE, "..", "analyses"))
    ap.add_argument("--master", default=os.path.join(HERE, "..", "drive_master.csv"))
    ap.add_argument("--fuel", default=os.path.join(HERE, "..", "fuel_recon_master.csv"))
    ap.add_argument("--payload", default=os.path.join(HERE, "..", "analyses", "M753_drive_payload.csv"))
    ap.add_argument("--seasonal", default=os.path.join(HERE, "..", "seasonal_drive_master.csv"))
    ap.add_argument("--coverage", default=os.path.join(HERE, "..", "analyses", "M729_cloud_coverage.csv"))
    ap.add_argument("--m771", default=os.path.join(HERE, "..", "analyses", "M771_weather_proxy.json"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    a = ap.parse_args(argv)
    if not a.run:
        print(__doc__)
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    t_start = time.time()
    try:
        if PE.md5(a.master) != PINNED_MD5:
            print("wiper_episodes: master pin failed")
            return 1
        store = a.store or mi.default_store()
        if not os.path.exists(os.path.join(store, "manifest.json")):
            print("wiper_episodes: no cloud store, skipped (optional)")
            return 0
        import odometer_jump_audit as J
        m771 = json.load(open(a.m771, encoding="utf-8"))
        d0 = W.load(a.master, a.fuel, a.payload, a.seasonal, a.coverage)
        drv = drive_rows(store, a.master)
        d = merged_frame(d0, drv)
        res = {"milestone": "M772", "spec": "analyses/M772_spec.md Rev 2", "masterMd5": PINNED_MD5, "toolSha256": PE.sha256(os.path.abspath(__file__)), "seed": SEED, "nBoot": a.nb,
               "inputs": {"store_manifest_sha256": PE.sha256(os.path.join(store, "manifest.json")), "m771_result_sha256": PE.sha256(a.m771)}}
        res["nested_control"] = nested_control(d, m771, a.nb)
        # long-soak flags over the FULL master
        ordr = d.sort_values("t0")
        flags, gap = soak_flags(d["t0"].values, d["t1"].values)
        for h, f in flags.items():
            d["soak_%g" % h] = f
        e_all = W.eligible(d)
        e_fuel = W.eligible(d, need_fuel=True)
        # G'
        gp = {"definitions": {}}
        for name, col in (("primary_adjacent_rows", "class_primary"), ("strict_timestamp_span", "class_strict"), ("hole_limit_90s", "class_hole90"), ("code6_only", "class_code6")):
            cnt = {"wet_proxy_drives": int((e_all[col] == "wet").sum()), "wet_proxy_days": int(e_all.loc[e_all[col] == "wet", "day"].nunique()), "isolated_only_drives": int((e_all[col] == "isolated").sum()),
                   "dry_reference_drives": int((e_all[col] == "dry").sum()), "fuel_basis_wet_proxy_drives": int((e_fuel[col] == "wet").sum()), "fuel_basis_wet_proxy_days": int(e_fuel.loc[e_fuel[col] == "wet", "day"].nunique())}
            gp["definitions"][name] = cnt
        p = gp["definitions"]["primary_adjacent_rows"]
        gp["floor"] = {"drives": W.FLOOR_DRIVES, "days": W.FLOOR_DAYS}
        gp["passed"] = bool(p["fuel_basis_wet_proxy_drives"] >= W.FLOOR_DRIVES and p["fuel_basis_wet_proxy_days"] >= W.FLOOR_DAYS)
        gp["any_activity_drives"] = int(((e_all["class_primary"] == "wet") | (e_all["class_primary"] == "isolated")).sum())
        gp["comparison_M771_share_definition"] = m771["G_support_gate"]["thresholds"]["0.05"]
        res["G_prime_support_gate"] = gp
        # A1'
        if gp["passed"]:
            ef = e_fuel[e_fuel["class_primary"].isin(["wet", "dry"])].copy()
            ef["wet"] = (ef["class_primary"] == "wet").astype(float)
            ef["first_of_day"] = ef["soak_3"]
            ef = ef[ef["first_of_day"].notna()]
            r = W.boot_diff(ef, "fuel_L_per_100km", a.nb)
            dry_mean = float(ef.loc[ef["wet"] == 0.0, "fuel_L_per_100km"].mean())
            r["reading"] = W.T.reading(r["mde"], W.EXPECT_LOWER_PCT / 100.0 * dry_mean)
            r["sign_note"] = W.T.sign_note(r["difference_after_adjustment"], r["ci95"], expected_negative=False)
            res["A1_prime"] = r
        else:
            res["A1_prime"] = {"counts_only": True, "reason": "below the floor of %d wet-proxy drives on %d days on the fuel basis" % (W.FLOOR_DRIVES, W.FLOOR_DAYS), "fuel_basis_wet_proxy_drives": p["fuel_basis_wet_proxy_drives"],
                               "fuel_basis_wet_proxy_days": p["fuel_basis_wet_proxy_days"], "reading": "not supported at this support"}
        # A3' : only the flag varies
        variants = {"long_soak_3h": d["soak_3"], "long_soak_2h": d["soak_2"], "long_soak_6h": d["soak_6"]}
        a3, a3_within = dark_contrasts(e_all, a.nb, variants=variants)
        res["A3_prime_dark_proxy_fuel"] = {"label": "darkness and visibility proxy, exploratory, no pre-registered expectation; the M771 wet-exclusion set; only the flag varies", "definitions": a3,
                                           "calendar_flag_within_sample_M771_sensitivity": a3_within, "spread_note": "the spread across the definitions is the finding; none is picked"}
        # C
        cal = d0.set_index("file")["first_of_day"].reindex(d["file"]).values
        s3 = d["soak_3"].values
        res["C_integrity"] = {"gap_bins_hours": gap_bins(gap), "drives_flag_differs_calendar_vs_3h": int(np.sum((cal == 1.0) != (s3 == 1.0)) - np.sum(np.isnan(s3))),
                              "first_drive_of_master": "unknown, excluded from the soak contrasts", "long_soak_3h_share_by_class": {c: float(np.nanmean(d.loc[d["cls"] == c, "soak_3"].values)) for c in PE.CLASSES if (d["cls"] == c).any()}}
        res["limits"] = ["a wiper episode is a precipitation, spray or washing proxy; the wiper mode and the codes are not named here; no weather-service data",
                         "the long-soak flag (3 hours or more after the previous logged drive; assumed cooling time) over-labels long soaks when driving is unlogged; M769 to M771 used the calendar first-drive-of-day flag",
                         "association only; 'not supported' is not 'no weather effect'; fuel is logged / app-calculated; the registered M771 result is not changed",
                         "cloud-to-drive clock alignment is unvalidated (M729); month fixed effects are nearly collinear with the wet proxy",
                         "not an article figure"]
        res["seconds"] = round(time.time() - t_start, 1)
        bad = J.scan_privacy(res)
        if bad:
            raise W.T.Stop("privacy scan failed: %s" % bad[:3])
        if PE.md5(a.master) != PINNED_MD5:
            raise W.T.Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        with open(os.path.join(a.out_dir, "M772_wiper_episodes.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, default=lambda o: None if o != o else str(o))
        print("wiper_episodes: nested control passed | primary wet-proxy drives %d (fuel basis %d on %d days) | gate %s" % (p["wet_proxy_drives"], p["fuel_basis_wet_proxy_drives"], p["fuel_basis_wet_proxy_days"], "passed" if gp["passed"] else "not passed"))
        return 0
    except W.T.Stop as e:
        print("wiper_episodes: STOP (%s)" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
