#!/usr/bin/env python3
"""M713c (spec analyses/M712_spec.md Rev 1.1): the day-block replay engine of the exposure scenario model.

Whole calendar days of the logged window are the replay unit (drive sequence, clock times, gaps, per-slice current statistics stay intact). A synthetic 365-day year is drawn from the season pools with an
exponential tilt on day km (odometer anchoring), every drawn day is shifted to the target month's ambient (repo monthly climate normal, an external assumption, plus the pre-registered shift table), and the
pack temperature is carried through drive and park by the state model (tools/exposure_state.py parameters, park = M709 model). All outputs are MODEL-DERIVED exposure indices; nothing here is an ageing or
end-of-life estimate (M114 stands). Capacity bases 5 Ah rated and 2.1 kWh legacy are both verified:false.
Intervals (spec Rev 1.1 C1): E-real = predictive distribution of single replayed-year totals (one bootstrap pool + one synthetic year per draw, the prototype's interval); E-exp = the expected annual exposure of
the scenario, the day-pool bootstrap of the MEAN of N_INNER replayed years per pool. Neither contains assumption uncertainty (Sobol / tornado: tools/scenario_sensitivity.py).
Fresh code under tools/; the prototype (analyses/exposure_scenarios_2026-11-16, untracked) is comparison-only data.
Usage: python tools/scenario_engine.py [--dir analyses/M713] [--mode production|prototype] [--draws N] [--scenarios S2,S3b,...] [--out FILE]"""
import argparse, hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import park_model as PM
import exposure_state as ES
import scenario_frame as SF

SEED, NBOOT = 42, 4000
N_INNER = 8
CAP_AH_RATED, CAP_KWH_LEGACY = 5.0, 2.1
V_NOM = 360.0                                        # pack voltage that turns the BMS charge limit (kW) into a C-rate (median logged pack voltage)
EAS = (40.0, 50.0, 60.0)
COLD_THR = (10.0, 5.0, 0.0, -10.0)
DIM = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
TLAB, TBINS, SOCLAB = SF.TLAB, SF.TBINS, SF.SOCLAB
W_SUM_BAL = np.array([0, 0, 0, 0, 0.5, 1, 1, 1, 0.5, 0, 0, 0], float)   # share of summer-pattern days by target month (owner: Jun-Aug summer, May / Sep half and half, Oct-Apr autumn pattern)
MID_DOY = np.cumsum(DIM) - DIM / 2.0
PROTOTYPE_AMBIG = ("2026-05-19", "2026-06-08")        # the prototype's ASSUMPTION window (spec Q5: data rule primary, this window a sensitivity / the binding reproduction)


def arrh(Tc, Ea_kj=50.0, Tref=25.0):
    return SF.arrh(Tc, Ea_kj, Tref)


def park_path(T0, gap, clock0, Abar0, slope, amp, hpk, tau, off, M=24):
    """Midpoint-rule sample of the parked path: (T at M midpoints [.., M], dt hours)."""
    fr = (np.arange(M) + 0.5) / M
    t = np.asarray(gap, float)[..., None] * fr
    e = lambda a: np.asarray(a, float)[..., None]
    return PM.park_T(e(T0), t, e(clock0), e(Abar0), e(slope), e(amp), e(hpk), e(tau), e(off)), np.asarray(gap, float) / M


def month_of_doy():
    return np.repeat(np.arange(12), DIM)


def month_shift(d):
    s = np.zeros(12)
    for k_, v in d.items():
        s[k_ - 1] = v
    return np.repeat(s, DIM)


# ----------------------------------------------------------------------------------------- model inputs -------------------------------------------------
class Model:
    """Inputs of the replay: day pools, per-day drive arrays, ambient reconstruction, climate normal, odometer factors and the default parameter set."""

    def __init__(self, D, Z, AR, amb, normals, odo, params, pool_rule="data", odo_km=None):
        self.K = int(Z["K"])
        self.NCB = Z["ahc_cb"].shape[2]
        self.KYIV = np.asarray(normals, float)
        D = D.merge(AR[["key", "Abar_s", "Abar_e", "amp", "hpk", "h0", "h1"]], on="key", how="left").merge(amb[["key", "A0", "A1"]], on="key", how="left")
        self.D, self.Z = D.reset_index(drop=True), Z
        first, last = D["day"].min(), D["day"].max()
        cal = pd.DataFrame({"date": pd.date_range(first, last)})
        cal["day"] = cal["date"].dt.strftime("%Y-%m-%d")
        cal["month"] = cal["date"].dt.month
        cal["doy"] = cal["date"].dt.dayofyear
        D = self.D
        bad_drive = (Z["icov"] < 0.5) | D["T_start"].isna().values | D["A0"].isna().values
        bad_days = set(D.loc[bad_drive, "day"])
        if pool_rule == "prototype":
            amb_days = set(pd.date_range(*PROTOTYPE_AMBIG).strftime("%Y-%m-%d"))
            unl_days = set(odo["unloggedDays"])
            cal["excl"] = np.where(cal["day"].isin(bad_days), "missing channels", np.where(cal["day"].isin(amb_days), "ambiguous logging", np.where(cal["day"].isin(unl_days), "unlogged (odometer)", "")))
        else:
            unl_days, nocov = set(odo["unloggedDays"]), set(odo["noOdometerCoverDays"])
            cal["excl"] = np.where(cal["day"].isin(bad_days), "missing channels", np.where(cal["day"].isin(unl_days), "unlogged (odometer)", np.where(cal["day"].isin(nocov), "no odometer cover", "")))
        self.cal, nd = cal, len(cal)
        self.nd = nd
        self.MAXD = int(D.groupby("day").size().max())
        MAXD, K = self.MAXD, self.K
        P = {k: np.zeros((nd, MAXD)) for k in ["valid", "dt", "h0", "dur", "A", "km", "kwh_per_ah", "soc_end", "eng_starts", "dAs", "dAe"]}
        P |= {k: np.zeros((nd, MAXD, K)) for k in ["i2", "ahc", "ahd", "soc", "ep10c", "ep20c", "ep10d", "ep20d"]}
        P["cb"] = np.zeros((nd, MAXD, K, self.NCB))
        P["cbC"] = np.zeros((nd, MAXD, K, self.NCB))
        P["ahS"] = np.zeros((nd, MAXD, len(SOCLAB)))
        dayidx = {d: i for i, d in enumerate(cal["day"])}
        D["slot"] = D.groupby("day").cumcount()
        dayA = pd.Series({d_: np.mean(np.r_[g["Abar_s"].values, g["Abar_e"].values]) for d_, g in D.groupby("day")})       # NaN-propagating on purpose (days without ambient are interpolated)
        cal["Abar"] = cal["day"].map(dayA)
        cal["Abar"] = cal["Abar"].interpolate(limit_direction="both")
        self.BIAS = float((cal["Abar"] - self.normal_at(cal["doy"])).mean())
        cal["anom"] = cal["Abar"] - self.normal_at(cal["doy"]) - self.BIAS
        for i, rw in D.iterrows():
            a, j = dayidx[rw["day"]], int(rw["slot"])
            P["valid"][a, j] = 1
            P["dt"][a, j] = rw["dur_h"] / K
            P["h0"][a, j] = rw["h0"]
            P["dur"][a, j] = rw["dur_h"]
            P["A"][a, j] = (rw["A0"] + rw["A1"]) / 2 if np.isfinite(rw["A0"]) else 15.0
            P["dAs"][a, j] = rw["Abar_s"] - cal["Abar"].values[a] if np.isfinite(rw["Abar_s"]) else 0.0
            P["dAe"][a, j] = rw["Abar_e"] - cal["Abar"].values[a] if np.isfinite(rw["Abar_e"]) else 0.0
            P["km"][a, j] = rw["km"]
            P["kwh_per_ah"][a, j] = rw["kwh"] / rw["ah"] if rw["ah"] > 0 else 0.36
            P["soc_end"][a, j] = rw["soc_end"] if np.isfinite(rw["soc_end"]) else 60.0
            P["eng_starts"][a, j] = rw["eng_starts"]
            for k_ in ["i2", "ahc", "ahd", "soc", "ep10c", "ep20c", "ep10d", "ep20d"]:
                P[k_][a, j] = np.nan_to_num(Z[k_][i], nan=(60.0 if k_ == "soc" else 0.0))
            P["cb"][a, j] = Z["ahc_cb"][i]
            P["cbC"][a, j] = Z["ahcC_cb"][i]
            P["ahS"][a, j] = [rw["ah_S_%s" % l] for l in SOCLAB]
        with np.errstate(all="ignore"):
            P["cbrep"] = np.where(P["cb"] > 0, P["cbC"] / P["cb"], 0.0)
        self.P = P
        ok = (cal["excl"] == "").values
        self.ok = ok
        self.POOL = {"summer": np.flatnonzero(ok & (cal["month"] <= 8).values), "autumn": np.flatnonzero(ok & (cal["month"] >= 9).values), "all": np.flatnonzero(ok), "window": np.arange(nd)}
        self.DAYKM = P["km"].sum(axis=1)
        self.SRC_SUMMER = (cal["month"] <= 8).values
        self.params = dict(params)
        self.ODO_KM = float(odo_km) if odo_km else None
        self.odo = odo

    def normal_at(self, doy):
        x = np.r_[MID_DOY[-1] - 365, MID_DOY, MID_DOY[0] + 365]
        y = np.r_[self.KYIV[-1], self.KYIV, self.KYIV[0]]
        return np.interp(doy, x, y)


def default_params(state, odo, offset_mode="one", prototype_park=None):
    """Default parameter set from state_params.json (M713b), the odometer factors and the M709 park model. offset_mode 'one' = one offset all seasons (M709); a dict prototype_park
    {'tau','off_s','off_a'} reproduces the superseded prototype constants (G-S3, binding on identical inputs)."""
    S = state["params_for_scenarios"]
    off = S["park"]["off"]
    d = dict(tau_p=S["park"]["tau"], off_s=off, off_a=off, off_w=off, alpha=S["drive"]["alpha"], tau_d=S["drive"]["tau_d"], c0=S["drive"]["c0"], c1=S["drive"]["c1"], EaR=S["EaR"],
             amp_s=S["diurnal"]["summer"][0], hpk_s=S["diurnal"]["summer"][1], amp_a=S["diurnal"]["autumn"][0], hpk_a=S["diurnal"]["autumn"][1], amp_w_scale=0.7,
             kappa=0.0, der=1.0, pin_b0=S["pin"]["b0"], pin_bT=S["pin"]["bT"], pin_bS=S["pin"]["bS"], tlo_off=1.5,
             f_s=odo["factors"]["f_s_summerWindow"], f_a=odo["factors"]["f_a_laterIntervalsWithoutUnlogged"], gamma=1.0, w_off=0.0)
    if prototype_park:
        d.update(tau_p=prototype_park["tau"], off_s=prototype_park["off_s"], off_a=prototype_park["off_a"], off_w=prototype_park["off_a"])
    return d


# ----------------------------------------------------------------------------------------- simulation ---------------------------------------------------
def simulate(M, src, tgt_shift, par, src_is_summer_pool, use_transform=True):
    """src [B,365] source day index per synthetic day; tgt_shift [B,365] or [365] extra ambient shift (C); par dict of scalars or [B] arrays; src_is_summer_pool [B,365] bool (which odometer factor applies)."""
    P, cal, K = M.P, M.cal, M.K
    Bn = src.shape[0]
    p = {k: (np.broadcast_to(np.asarray(v, float), (Bn,)).copy()) for k, v in par.items()}
    mo = month_of_doy()
    doy = np.arange(365) + 1.0
    Nt = M.normal_at(doy)
    acc = {k: np.zeros(Bn) for k in ["km", "n_drv", "ahc", "ahd", "kwh", "drive_h", "park_h", "eng_starts", "ep10c", "ep20c", "ep10d", "ep20d", "capAh", "ws15", "ws10", "ws0", "ah_wu15",
                                     "park_soc_af", "ccs10", "ccs0", "ccs10_nd", "ccs0_nd", "Tmin_year", "park_lt0_h", "park_Tsum"]}
    acc["Tmin_year"] += 99
    NT, NCB = len(TLAB), M.NCB
    acc["ahT"] = np.zeros((Bn, NT)); acc["ahcT"] = np.zeros((Bn, NT)); acc["hT"] = np.zeros((Bn, NT)); acc["pkT"] = np.zeros((Bn, NT)); acc["ahS"] = np.zeros((Bn, len(SOCLAB)))
    acc["arr_cyc"] = np.zeros((Bn, 3)); acc["arr_drv"] = np.zeros((Bn, 3)); acc["arr_pk"] = np.zeros((Bn, 3)); acc["coldAhc"] = np.zeros((Bn, len(COLD_THR)))
    edges = np.array(TBINS[1:-1])
    T = np.full(Bn, np.nan); t_prev = np.zeros(Bn); A_prev = np.zeros(Bn); soc_prev = np.full(Bn, 60.0); have = np.zeros(Bn, bool)
    amp_prev = np.zeros(Bn); hpk_prev = np.zeros(Bn); off_prev = np.zeros(Bn)
    ar = np.arange(Bn)
    shift = np.broadcast_to(np.asarray(tgt_shift, float), (Bn, 365))
    for d in range(365):
        s = src[:, d]
        m = mo[d]
        if use_transform:
            Aday = Nt[d] + shift[:, d] + cal["anom"].values[s]
            dA = Aday - cal["Abar"].values[s]
        else:
            Aday = cal["Abar"].values[s]
            dA = np.zeros(Bn)
        if use_transform:
            summ = (m >= 5) & (m <= 7)
            wint = (m == 11) | (m <= 1)
            amp = p["amp_s"] if summ else p["amp_a"] * (p["amp_w_scale"] if wint else 1.0)
            hpk = p["hpk_s"] if summ else p["hpk_a"]
            off = p["off_s"] if summ else (p["off_w"] if wint else p["off_a"])
        else:
            ss = M.SRC_SUMMER[s]
            amp = np.where(ss, p["amp_s"], p["amp_a"]); hpk = np.where(ss, p["hpk_s"], p["hpk_a"]); off = np.where(ss, p["off_s"], p["off_a"])
        fext = np.where(src_is_summer_pool[:, d], p["f_s"], p["f_a"])
        for j in range(M.MAXD):
            v = P["valid"][s, j] > 0
            if not v.any():
                break
            ix = ar[v]
            sj = s[ix]
            t0 = d * 24.0 + P["h0"][sj, j]
            A_s = Aday[ix] + P["dAs"][sj, j]
            A_e = Aday[ix] + P["dAe"][sj, j]
            hv = have[ix]
            gap = np.where(hv, np.maximum(t0 - t_prev[ix], 1e-3), 0.0)
            if hv.any():
                i2_ = ix[hv]
                g2 = gap[hv]
                slope = (A_s[hv] - A_prev[i2_]) / g2
                path, dtp = park_path(T[i2_], g2, t_prev[i2_] % 24, A_prev[i2_], slope, amp_prev[i2_], hpk_prev[i2_], p["tau_p"][i2_], off_prev[i2_], M=24)
                bi = np.digitize(path, edges)
                acc["pkT"] += np.bincount((i2_[:, None] * NT + bi).ravel(), weights=np.repeat(dtp, 24), minlength=Bn * NT).reshape(Bn, NT)
                for e_, ea in enumerate(EAS):
                    af = arrh(path, ea)
                    acc["arr_pk"][i2_, e_] += af.sum(axis=1) * dtp
                    if ea == 50.0:
                        acc["park_soc_af"][i2_] += af.sum(axis=1) * dtp * np.exp(p["gamma"][i2_] * (soc_prev[i2_] - 50.0) / 100.0)
                acc["park_h"][i2_] += g2
                acc["park_lt0_h"][i2_] += (path < 0).sum(axis=1) * dtp
                acc["park_Tsum"][i2_] += path.sum(axis=1) * dtp
                T[i2_] = PM.park_T(T[i2_], g2, t_prev[i2_] % 24, A_prev[i2_], slope, amp_prev[i2_], hpk_prev[i2_], p["tau_p"][i2_], off_prev[i2_])
            nh = ix[~hv]
            if len(nh):
                T[nh] = A_s[~hv] + off[nh]
            Tst = T[ix]
            acc["Tmin_year"][ix] = np.minimum(acc["Tmin_year"][ix], Tst)
            A_dr = P["A"][sj, j] + dA[ix]
            cool = np.maximum(0.0, 15.0 - A_dr) - np.maximum(0.0, 15.0 - P["A"][sj, j])
            mult = np.exp(p["kappa"][ix] * cool)
            fx = fext[ix]
            Tc = p["c0"][ix] + p["c1"][ix] * A_dr
            dt = P["dt"][sj, j]
            kk = 1 - np.exp(-dt / p["tau_d"][ix])
            Tcur = Tst.copy()
            acc["ws15"][ix] += (Tst < 15) * fx
            acc["ws10"][ix] += (Tst < 10) * fx
            acc["ws0"][ix] += (Tst < 0) * fx
            for k in range(K):
                q = P["i2"][sj, j, k] * mult ** 2
                dT = p["alpha"][ix] * ES.fR(Tcur, p["EaR"][ix]) * q * dt + (Tc - Tcur) * kk
                Tm = Tcur + 0.5 * dT
                Tcur = Tcur + dT
                ac = P["ahc"][sj, j, k] * mult * fx
                ad = P["ahd"][sj, j, k] * mult * fx
                bi = np.digitize(Tm, edges)
                flat = ix * NT + bi
                acc["ahT"] += np.bincount(flat, weights=ac + ad, minlength=Bn * NT).reshape(Bn, NT)
                acc["ahcT"] += np.bincount(flat, weights=ac, minlength=Bn * NT).reshape(Bn, NT)
                acc["hT"] += np.bincount(flat, weights=dt * fx, minlength=Bn * NT).reshape(Bn, NT)
                for e_, ea in enumerate(EAS):
                    af = arrh(Tm, ea)
                    acc["arr_cyc"][ix, e_] += af * (ac + ad)
                    acc["arr_drv"][ix, e_] += af * dt * fx
                for c_, thr in enumerate(COLD_THR):
                    acc["coldAhc"][ix, c_] += np.where(Tm < thr, ac, 0.0)
                acc["ah_wu15"][ix] += np.where(Tm < 15, ac + ad, 0.0)
                cold10 = Tm < 10
                if cold10.any():
                    capkw = np.clip(p["pin_b0"][ix] + p["pin_bT"][ix] * (Tm - p["tlo_off"][ix]) + p["pin_bS"][ix] * (P["soc"][sj, j, k] - 60.0), 0.5, 64.6) * p["der"][ix]
                    capC = capkw * 1000.0 / V_NOM / CAP_AH_RATED
                    cb = P["cb"][sj, j, k] * (mult * fx)[:, None]
                    rep = P["cbrep"][sj, j, k] * mult[:, None]
                    nd_ = (cb * rep).sum(axis=1)
                    de_ = (cb * np.minimum(rep, capC[:, None])).sum(axis=1)
                    acc["ccs10"][ix] += np.where(cold10, de_, 0.0); acc["ccs10_nd"][ix] += np.where(cold10, nd_, 0.0)
                    acc["ccs0"][ix] += np.where(Tm < 0, de_, 0.0); acc["ccs0_nd"][ix] += np.where(Tm < 0, nd_, 0.0)
                    acc["capAh"][ix] += np.where(cold10, (cb * (rep > capC[:, None])).sum(axis=1), 0.0)
                for e in ("ep10c", "ep20c", "ep10d", "ep20d"):
                    acc[e][ix] += P[e][sj, j, k] * fx
            acc["ahc"][ix] += P["ahc"][sj, j].sum(axis=1) * mult * fx
            acc["ahd"][ix] += P["ahd"][sj, j].sum(axis=1) * mult * fx
            ah_dr = (P["ahc"][sj, j].sum(axis=1) + P["ahd"][sj, j].sum(axis=1)) * mult * fx
            acc["kwh"][ix] += ah_dr * P["kwh_per_ah"][sj, j]
            acc["ahS"][ix] += P["ahS"][sj, j] * (mult * fx)[:, None]
            acc["km"][ix] += P["km"][sj, j] * fx
            acc["n_drv"][ix] += fx
            acc["drive_h"][ix] += P["dur"][sj, j] * fx
            acc["eng_starts"][ix] += P["eng_starts"][sj, j] * fx
            T[ix] = Tcur; t_prev[ix] = t0 + P["dur"][sj, j]; A_prev[ix] = A_e; soc_prev[ix] = P["soc_end"][sj, j]; have[ix] = True
            amp_prev[ix] = amp[ix]; hpk_prev[ix] = hpk[ix]; off_prev[ix] = off[ix]
    return acc


def summarise(acc):
    o = {}
    ah = acc["ahc"] + acc["ahd"]
    o["annual_km"] = acc["km"]; o["drives"] = acc["n_drv"]; o["ah_throughput"] = ah; o["ah_charge"] = acc["ahc"]
    o["gtc_5Ah_rated"] = ah / CAP_AH_RATED; o["fce_5Ah_rated"] = ah / CAP_AH_RATED / 2
    o["gtc_2p1kWh_legacy"] = acc["kwh"] / CAP_KWH_LEGACY; o["fce_2p1kWh_legacy"] = acc["kwh"] / CAP_KWH_LEGACY / 2
    o["gtc_5Ah_per_km"] = ah / CAP_AH_RATED / acc["km"]
    for i, l in enumerate(TLAB):
        o["ah_T_%s" % l] = acc["ahT"][:, i]
    for i, l in enumerate(SOCLAB):
        o["ah_SoC_%s" % l] = acc["ahS"][:, i]
    o["ahShare_T_lt10"] = acc["ahT"][:, :3].sum(axis=1) / ah; o["ahShare_T_lt0"] = acc["ahT"][:, 0] / ah
    o["ahShare_T_ge35"] = acc["ahT"][:, 8:].sum(axis=1) / ah; o["ahShare_T_ge40"] = acc["ahT"][:, 9:].sum(axis=1) / ah
    o["hotTail_ah_ge35"] = acc["ahT"][:, 8:].sum(axis=1); o["hotTail_ah_ge40"] = acc["ahT"][:, 9:].sum(axis=1)
    for c_, thr in enumerate(COLD_THR):
        o["coldCharge_ah_lt%d" % int(thr)] = acc["coldAhc"][:, c_]
    o["coldChargeIndex_AhxC_lt10"] = acc["ccs10"]; o["coldChargeIndex_AhxC_lt0"] = acc["ccs0"]
    o["coldChargeIndex_AhxC_lt10_noDerating"] = acc["ccs10_nd"]; o["coldChargeIndex_AhxC_lt0_noDerating"] = acc["ccs0_nd"]
    o["chargeAh_aboveExtrapolatedLimit_lt10"] = acc["capAh"]
    o["warmups_Tstart_lt15"] = acc["ws15"]; o["warmups_Tstart_lt10"] = acc["ws10"]; o["starts_Tstart_lt0"] = acc["ws0"]; o["ah_in_warmup_lt15"] = acc["ah_wu15"]
    for e_, ea in enumerate(EAS):
        o["arrCycleDose_AhEq_Ea%d" % int(ea)] = acc["arr_cyc"][:, e_]
        o["arrCycleAF_Ea%d" % int(ea)] = acc["arr_cyc"][:, e_] / ah
        o["arrCalendar_driveHoursEq_Ea%d" % int(ea)] = acc["arr_drv"][:, e_]
        o["arrCalendar_parkedHoursEq_Ea%d" % int(ea)] = acc["arr_pk"][:, e_]
        o["arrCalendarAF_year_Ea%d" % int(ea)] = (acc["arr_drv"][:, e_] + acc["arr_pk"][:, e_]) / (acc["drive_h"] + acc["park_h"])
        o["parkedShareOfCalendarDose_Ea%d" % int(ea)] = acc["arr_pk"][:, e_] / (acc["arr_drv"][:, e_] + acc["arr_pk"][:, e_])
    o["arrCalendar_parked_SoCweighted_hoursEq_Ea50"] = acc["park_soc_af"]
    o["parked_meanPackT"] = acc["park_Tsum"] / acc["park_h"]; o["parked_hours_lt0"] = acc["park_lt0_h"]
    o["parked_hours_ge30"] = acc["pkT"][:, 7:].sum(axis=1); o["parked_hours_lt10"] = acc["pkT"][:, :3].sum(axis=1)
    o["drive_hours"] = acc["drive_h"]; o["engine_starts"] = acc["eng_starts"]
    o["episodes_chg_gt10C"] = acc["ep10c"]; o["episodes_chg_gt20C"] = acc["ep20c"]; o["episodes_dis_gt10C"] = acc["ep10d"]; o["episodes_dis_gt20C"] = acc["ep20d"]
    o["coldest_start_T"] = acc["Tmin_year"]
    return o


# ----------------------------------------------------------------------------------------- draws, tilt, scenarios -------------------------------------
def draw_days(M, Bn, w_sum, rng, tilt=0.0, pools=("summer", "autumn"), counts=None, w_off=None):
    """Whole-day block draws. counts: optional {pool: [Bn, n] day multiplicities} (a given bootstrap pool per simulation); else a fresh multinomial pool resample per simulation. Returns src [B,365], is_summer_pool [B,365]."""
    mo = month_of_doy()
    src = np.zeros((Bn, 365), int)
    iss = np.zeros((Bn, 365), bool)
    cdfs = {}
    for nm in pools:
        pl = M.POOL[nm]
        n = len(pl)
        cnt = counts[nm] if counts is not None else rng.multinomial(n, np.ones(n) / n, size=Bn).astype(float)
        w = cnt * np.exp(tilt * M.DAYKM[pl] / 100.0)[None, :]
        cdfs[nm] = (np.cumsum(w, axis=1) / w.sum(axis=1, keepdims=True), pl)
    u1 = rng.random((Bn, 365))
    u2 = rng.random((Bn, 365))
    for d in range(365):
        ws = w_sum[mo[d]] if w_off is None else np.where(w_sum[mo[d]] > 0, w_sum[mo[d]], w_off)       # w_off: share of summer-pattern (long-trip) days in the autumn-pattern months (assumption range)
        pick_s = (u1[:, d] < ws) if len(pools) > 1 else np.full(Bn, pools[0] == "summer")
        for nm, flag in (("summer", True), ("autumn", False)) if len(pools) > 1 else ((pools[0], pools[0] == "summer"),):
            cdf, pl = cdfs[nm]
            sel = np.flatnonzero(pick_s == flag) if len(pools) > 1 else np.arange(Bn)
            if len(sel):
                k_ = (u2[sel, d][:, None] > cdf[sel]).sum(axis=1)
                src[sel, d] = pl[np.minimum(k_, len(pl) - 1)]
                iss[sel, d] = (nm == "summer") if nm in ("summer", "autumn") else M.SRC_SUMMER[src[sel, d]]
    return src, iss


def expected_km(M, w_sum, tilt, f_s, f_a):
    tot = 0.0
    for m in range(12):
        for nm, wgt, f in (("summer", w_sum[m], f_s), ("autumn", 1 - w_sum[m], f_a)):
            pl = M.POOL[nm]
            w = np.exp(tilt * M.DAYKM[pl] / 100.0)
            tot += DIM[m] * wgt * f * (w * M.DAYKM[pl]).sum() / w.sum()
    return tot


def solve_tilt(M, target, w_sum, f_s, f_a):
    lo, hi = -5.0, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if expected_km(M, w_sum, mid, f_s, f_a) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def scenarios(odo_km):
    """The scenario grid of spec section 7 (shift table and season map frozen in analyses/M712_ranges.json)."""
    return {
        "S0_window_annualised_asLogged": dict(note="naive annualisation of the logged window: every month draws from ALL window days (no exclusion), no temperature transform, no odometer calibration", pools=("window",), transform=False, par=dict(f_s=1.0, f_a=1.0)),
        "S1_autumn_like_year": dict(note="all months use the Sep-Nov day pool with the monthly normal ambient (untilted)", w_sum=np.zeros(12)),
        "S2_balanced_owner_expected": dict(note="PRIMARY: Jun-Aug summer pattern, May and Sep half and half, Oct-Apr autumn pattern, repo monthly normals, unlogged-distance factors, day draw tilted to the odometer lifetime mean", w_sum=W_SUM_BAL, km=odo_km),
        "S2u_balanced_untilted": dict(note="as S2 without the tilt", w_sum=W_SUM_BAL),
        "S2b_balanced_loggedBasis": dict(note="as S2u without the unlogged-distance factors (logged distance only)", w_sum=W_SUM_BAL, par=dict(f_s=1.0, f_a=1.0)),
        "S3a_mild_winter": dict(note="S2 with Dec-Feb +4 C (Nov, Mar +2 C)", w_sum=W_SUM_BAL, km=odo_km, shift={12: 4, 1: 4, 2: 4, 11: 2, 3: 2}),
        "S3b_cold_winter": dict(note="S2 with Dec-Feb -6 C (Nov, Mar -3 C)", w_sum=W_SUM_BAL, km=odo_km, shift={12: -6, 1: -6, 2: -6, 11: -3, 3: -3}),
        "S3c_severe_winter": dict(note="S2 with Dec-Feb -12 C (Nov, Mar -6 C)", w_sum=W_SUM_BAL, km=odo_km, shift={12: -12, 1: -12, 2: -12, 11: -6, 3: -6}),
        "S4_hot_summer_plus3": dict(note="S2 with Jun-Aug +3 C", w_sum=W_SUM_BAL, km=odo_km, shift={6: 3, 7: 3, 8: 3}),
        "S5_high_km_25k": dict(note="S2 tilted to 25,000 km per year", w_sum=W_SUM_BAL, km=25000),
        "S6_low_km_12k": dict(note="S2 tilted to 12,000 km per year", w_sum=W_SUM_BAL, km=12000),
        "S7_summer_like_year": dict(note="all months use the May-Aug day pool with the monthly normal ambient (contrast case)", w_sum=np.ones(12)),
    }


def run_scenario(M, sc, Bn, seed=SEED, par_override=None, counts=None):
    """One scenario: E-real draws (one bootstrap pool + one synthetic year per simulation). Returns (summarised outputs, tilt)."""
    rng = np.random.default_rng(seed)
    par = dict(M.params)
    par.update(sc.get("par", {}))
    if par_override:
        par.update(par_override)
    w_sum = sc.get("w_sum", W_SUM_BAL)
    tilt = solve_tilt(M, sc["km"], w_sum, par["f_s"], par["f_a"]) if "km" in sc else 0.0
    src, iss = draw_days(M, Bn, w_sum, rng, tilt=tilt, pools=sc.get("pools", ("summer", "autumn")), counts=counts)
    acc = simulate(M, src, month_shift(sc.get("shift", {})), par, iss, use_transform=sc.get("transform", True))
    return summarise(acc), tilt


def run_expected(M, sc, n_pool=500, n_inner=N_INNER, seed=SEED, par_override=None):
    """E-exp: n_pool day-pool bootstrap resamples; per pool the MEAN of n_inner replayed years (fixed seed). Returns {metric: array[n_pool]} (extremes such as coldest_start_T are E-real only and omitted)."""
    rng = np.random.default_rng(seed + 1)
    pools = sc.get("pools", ("summer", "autumn"))
    counts = {nm: rng.multinomial(len(M.POOL[nm]), np.ones(len(M.POOL[nm])) / len(M.POOL[nm]), size=n_pool).astype(float) for nm in pools}
    rep = {nm: np.repeat(c, n_inner, axis=0) for nm, c in counts.items()}
    o, tilt = run_scenario(M, sc, n_pool * n_inner, seed=seed + 2, par_override=par_override, counts=rep)
    return {k: v.reshape(n_pool, n_inner).mean(axis=1) for k, v in o.items() if k != "coldest_start_T"}, tilt


def ci(x, nd=4):
    x = np.asarray(x, float)
    r = lambda v: None if not np.isfinite(v) else round(float(v), nd)
    return [r(np.nanmean(x)), r(np.nanpercentile(x, 2.5)), r(np.nanpercentile(x, 97.5))]


def observed_sequence(M):
    """The observed eligible day sequence (calendar order) padded with an empty pool day to 365: used by the replay identity (G-S0) and the consistency check (G-S2)."""
    ok = M.ok
    seq = np.flatnonzero(ok)[None, :]
    pad = np.zeros((1, 365), int)
    n_ = min(seq.shape[1], 365)
    pad[0, :n_] = seq[0, :n_]
    empty = np.flatnonzero((M.P["valid"].sum(axis=1) == 0) & ok)
    pad[0, n_:] = empty[0] if len(empty) else seq[0, 0]
    return pad, n_


def replay_identity(M):
    """G-S0: no temperature transform, no tilt, every eligible day once in calendar order, no odometer factors: km, Ah, kWh and engine starts of the replay equal the frame sums over the same days exactly."""
    pad, n_ = observed_sequence(M)
    par = dict(M.params, f_s=1.0, f_a=1.0)
    acc = simulate(M, pad, 0.0, par, M.SRC_SUMMER[pad], use_transform=False)
    days = M.cal.loc[M.ok, "day"].values[:n_]
    # padded empty days carry no drives; compare against the frame over the replayed days
    Dk = M.D[M.D["day"].isin(days)]
    chk = {"km": (float(acc["km"][0]), float(Dk["km"].sum())), "ah": (float(acc["ahc"][0] + acc["ahd"][0]), float(Dk["ah"].sum())), "kwh": (float(acc["kwh"][0]), float(Dk["kwh"].sum())),
           "eng_starts": (float(acc["eng_starts"][0]), float(Dk["eng_starts"].sum())), "drives": (float(acc["n_drv"][0]), float(len(Dk)))}
    chk["maxAbsRelDiff"] = max(abs(a - b) / max(abs(b), 1e-12) for a, b in chk.values())
    return chk


# ----------------------------------------------------------------------------------------- loading ---------------------------------------------------------
def project_rule_ratios(D):
    """Per-drive ratios of the PROJECT integration rule to the engine's zero-order-hold frame: Ah from the Ah sidecar (ah_throughput.csv), kWh from the master gross_throughput_kwh; drives without a project
    value keep the zero-order-hold value (ratio 1)."""
    sc = pd.read_csv(os.path.join(ROOT, "ah_throughput.csv"), usecols=["file", "ah_throughput"])
    sc["key"] = sc["file"].map(SF.key14)
    m = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), usecols=["file", "gross_throughput_kwh"], low_memory=False)
    m["key"] = m["file"].map(SF.key14)
    X = D[["key", "ah", "kwh"]].merge(sc[["key", "ah_throughput"]], on="key", how="left").merge(m[["key", "gross_throughput_kwh"]], on="key", how="left")
    r_ah = np.where(np.isfinite(X["ah_throughput"]) & (X["ah"] > 0), X["ah_throughput"] / X["ah"].where(X["ah"] > 0), 1.0)
    kwh_proj = np.where(np.isfinite(X["gross_throughput_kwh"]), X["gross_throughput_kwh"], X["kwh"] * r_ah)
    return r_ah, kwh_proj


def apply_project_rule(D, Z):
    """Rescale a frame to the project integration rule (spec Rev 1.1 C2): drive Ah, kWh, slice Ah and charge-by-C-rate Ah scale with the per-drive ratio; currents and temperatures are unchanged."""
    r_ah, kwh_proj = project_rule_ratios(D)
    D = D.copy()
    D["ah"] = D["ah"] * r_ah
    D["kwh"] = kwh_proj
    for l in SOCLAB:
        D["ah_S_%s" % l] = D["ah_S_%s" % l] * r_ah
    Z = {k: Z[k] for k in Z.files}
    for k in ("ahc", "ahd"):
        Z[k] = Z[k] * r_ah[:, None]
    for k in ("ahc_cb", "ahcC_cb"):
        Z[k] = Z[k] * r_ah[:, None, None]
    return D, Z


def load_model(dir_, mode="production", ambient_csv=None, prototype_park=None, integration="zoh", pool_rule=None):
    """mode 'production': data pool rule (Q5), one offset (M709), the production ambient reconstruction, odometer target derived from the dash odometer.
    mode 'prototype': the prototype pool rule (assumption window 2026-05-19..06-08), odometer target 21,132 km, optional prototype ambient CSV (comparison-only) and prototype park constants."""
    D = pd.read_csv(os.path.join(dir_, "exposure_drives.csv"), dtype={"key": str}, parse_dates=["start", "end"], low_memory=False)
    Z = np.load(os.path.join(dir_, "exposure_slices.npz"), allow_pickle=True)
    assert list(Z["keys"]) == list(D["key"])
    if integration == "project":
        D, Z = apply_project_rule(D, Z)
    else:
        Z = {k: Z[k] for k in Z.files}
    state = json.load(open(os.path.join(dir_, "state_params.json"), encoding="utf-8"))
    odo = json.load(open(os.path.join(dir_, "odometer_check.json"), encoding="utf-8"))
    E = pd.DataFrame({"key": D["key"], "local0": D["start"], "day": D["day"], "dur_s": D["dur_h"] * 3600})
    amb = PM.ambient_samples(E)
    AR, _ = PM.reconstruct_ambient(E)
    if ambient_csv:
        X = pd.read_csv(ambient_csv, dtype={"key": str})
        AR = X[["key", "Abar_s", "Abar_e", "amp", "hpk", "h0", "h1"]].copy()
    normals = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["seasonalLife"]["assumptions"]["monthlyTempC"]
    cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))["vehicle"]
    years = (pd.Timestamp(cfg["odometerAsOf"]) - pd.Timestamp(cfg["registered"])).days / 365.25
    odo_km = 21132.0 if mode == "prototype" else cfg["odometerKm"] / years
    params = default_params(state, odo, prototype_park=prototype_park)
    M = Model(D, Z, AR, amb, normals, odo, params, pool_rule=pool_rule or ("prototype" if mode == "prototype" else "data"), odo_km=odo_km)
    M.state = state
    return M


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "analyses", "M713"))
    ap.add_argument("--mode", default="production", choices=["production", "prototype"])
    ap.add_argument("--draws", type=int, default=NBOOT)
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--out", default=None)
    ap.add_argument("--ambient-csv", default=None)
    ap.add_argument("--prototype-park", action="store_true")
    ap.add_argument("--integration", default="zoh", choices=["zoh", "project"])
    ap.add_argument("--pool-rule", default=None, choices=[None, "data", "prototype"])
    a = ap.parse_args(argv)
    pp = {"tau": 7.553961890995577, "off_s": 1.1632995967688304, "off_a": 3.4050103071067173} if a.prototype_park else None
    M = load_model(a.dir, a.mode, a.ambient_csv, pp, a.integration, a.pool_rule)
    sc_all = scenarios(M.ODO_KM)
    names = [n for n in sc_all if not a.scenarios or any(n.startswith(x) for x in a.scenarios.split(","))]
    res = {"milestone": "M713c", "spec": "analyses/M712_spec.md", "mode": a.mode, "draws": a.draws, "seed": SEED, "odoKmTarget": M.ODO_KM, "pools": {k: int(len(v)) for k, v in M.POOL.items()},
           "excludedDays": M.cal[M.cal["excl"] != ""].groupby("excl").size().to_dict(), "defaults": {k: round(float(v), 5) for k, v in M.params.items()},
           "intervalMeaning": {"E-real": "predictive distribution of single replayed-year totals (one day-pool bootstrap + one synthetic year per draw)", "E-exp": "day-pool bootstrap of the mean of N_INNER replayed years per pool"},
           "integration": a.integration, "identity": replay_identity(M), "scriptSha256": hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest()}
    for nm in names:
        sc = sc_all[nm]
        o, tilt = run_scenario(M, sc, a.draws)
        res[nm] = {"note": sc["note"], "tilt_per100km": round(float(tilt), 4), "E_real": {k: ci(v) for k, v in o.items()}}
        print(nm, "km", res[nm]["E_real"]["annual_km"], "gtc5", res[nm]["E_real"]["gtc_5Ah_rated"], flush=True)
    out = a.out or os.path.join(a.dir, "scenario_results_%s.json" % a.mode)
    json.dump(res, open(out, "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
