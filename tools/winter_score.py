#!/usr/bin/env python3
"""M726 (analyses/M726_spec.md Rev 2), guard G2: the scoring framework of the M717 winter freeze, FAIL-CLOSED.
It loads ONLY the freeze file analyses/M717_winter_predictions.json (its sha256 must equal the value recorded in the CHANGELOG) and its frozen inputs: for every source named in the freeze file the live file is used only if its sha256 equals the
freeze record, otherwise the byte-exact frozen copy named by analyses/M717_frozen_sources/index.json (sha256 verified); any other source, and any live file such as analyses/M713/*.json or summary_arrays.json used for predictions, is REFUSED.
A cell below the freeze's support rule (at least 10 drives (pairs) on at least 5 days) prints 'not evaluable' and NO number; a scored cell is labelled 'interpolation check' (inside the temperature / ambient range of the frozen basis) or 'extrapolation test'.
Implemented here: the loader and its refusals, the scoring-set selection (shared with the monitor), the support check, the comparison of an estimate and its day-cluster interval with a band, and the labels.
NOT implemented (stated deviation, M726 CHANGELOG): the extractors of the observed quantities of P1-P7 from the drive master (restart pairs, probe-window resistance ratio, limit-register samples, matched autumn-winter Ah per km, engine-on slope).
Until they are written, specified and frozen (sha256 recorded in the CHANGELOG before the first scoring look) every cell answers 'not evaluable (extractor not frozen)'.
Usage: python tools/winter_score.py [--check]"""
import hashlib, json, os, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
FREEZE = "analyses/M717_winter_predictions.json"
INDEX = "analyses/M717_frozen_sources/index.json"
SUPPORT_DRIVES, SUPPORT_DAYS = 10, 5
LIVE_REFUSED_PREFIXES = ("analyses/M713/", "summary_arrays.json", "summary_config.json", "seasonal_arrays.json")


class Refused(Exception):
    pass


def sha(path):
    return hashlib.sha256(open(os.path.join(ROOT, path), "rb").read()).hexdigest()


def load_freeze(changelog_text=None):
    """The freeze file, verified against the sha256 recorded in the CHANGELOG."""
    h = sha(FREEZE)
    if changelog_text is None:
        changelog_text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    if h not in changelog_text:
        raise Refused("the freeze file sha256 is not recorded in the CHANGELOG: " + h)
    return json.load(open(os.path.join(ROOT, FREEZE), encoding="utf-8"))


def read_source(freeze, key):
    """Bytes of one frozen input: the live file only when its sha256 equals the freeze record, else the frozen copy (sha256 verified). Anything else is refused."""
    if key not in freeze["sources"]:
        raise Refused("not a source of the freeze: " + key)
    rec = freeze["sources"][key]
    path, want = rec["path"], rec["sha256"]
    if os.path.exists(os.path.join(ROOT, path)) and sha(path) == want:
        return open(os.path.join(ROOT, path), "rb").read()
    idx = json.load(open(os.path.join(ROOT, INDEX), encoding="utf-8"))
    if key in idx and idx[key]["sha256"] == want and idx[key]["path"] == path:
        copy = idx[key]["frozenCopy"]
        if sha(copy) != want:
            raise Refused("the frozen copy differs from the freeze record: " + key)
        return open(os.path.join(ROOT, copy), "rb").read()
    raise Refused("no live file or frozen copy matches the freeze record for " + key)


def refuse_live(path):
    """The scoring code must never read a live file for a prediction: raises for the live outputs that the ingestion regenerates."""
    p = path.replace("\\", "/")
    if any(p.startswith(x) or ("/" + x) in p for x in LIVE_REFUSED_PREFIXES) and "M717_frozen_sources" not in p:
        raise Refused("live file refused for scoring: " + path)
    return path


REGISTRY = "analyses/M732_extractor_registry.json"          # v5 (M732, scoring module v6); the M726 / M727 / M728 / M731 registries are superseded, kept as history


def extractors_frozen(pid=None, changelog_text=None):
    """(ok, reason). Scoring may print a number only when an extractor registry exists (the sha256 of every extractor module, written by the extractor milestone) AND the sha256 of the registry file is recorded in the CHANGELOG
    (frozen before the first scoring look). Without it every cell is 'not evaluable (extractor not frozen)' (Director M726 decision).
    v2 (M727): the registry lists the covered prediction ids (`predictions`); a prediction that is not listed stays 'not evaluable (extractor not frozen)'."""
    if not os.path.exists(os.path.join(ROOT, REGISTRY)):
        return False, "no extractor registry"
    h = sha(REGISTRY)
    if changelog_text is None:
        changelog_text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    if h not in changelog_text:
        return False, "the extractor registry sha256 is not recorded in the CHANGELOG"
    reg = json.load(open(os.path.join(ROOT, REGISTRY), encoding="utf-8"))
    if pid is not None and pid not in (reg.get("predictions") or []):
        return False, "prediction %s is not covered by the extractor registry" % pid
    for m, want in (reg.get("modules") or {}).items():
        if not os.path.exists(os.path.join(ROOT, m)) or sha(m) != want:
            return False, "an extractor module differs from the registry: " + m
    return True, "frozen"


def support_ok(n_drives, n_days):
    return bool(n_drives >= SUPPORT_DRIVES and n_days >= SUPPORT_DAYS)


def region(cell_min, basis_min):
    """'interpolation check' when the scored cell lies inside the temperature (or ambient) range of the frozen basis, else 'extrapolation test' (spec section 2)."""
    return "interpolation check" if cell_min >= basis_min else "extrapolation test"


def evaluate_cell(pid, n_drives, n_days, estimate=None, ci=None, band=None, cell_min=None, basis_min=None, rule="ci"):
    """One cell of one prediction. Below the support rule: 'not evaluable', no number. rule='ci' (P2): the day-cluster interval inside the frozen band is 'within the band', wholly outside 'outside the band', otherwise 'inconclusive'.
    rule='point' (P3, P7; M727 spec section 3): the POINT estimate inside the frozen interval is 'within the band', else 'outside the band'; whether the observed interval lies inside it is reported beside (`ciInside`).
    Nothing is scored unless the extractor registry freezes this prediction (extractors_frozen(pid)); the region label is attached."""
    if not support_ok(n_drives, n_days):
        return {"prediction": pid, "status": "not evaluable", "reason": "below the support rule (%d drives on %d days; needs %d on %d)" % (n_drives, n_days, SUPPORT_DRIVES, SUPPORT_DAYS)}
    ok, why = extractors_frozen(pid)
    if not ok or estimate is None or band is None or (rule == "ci" and ci is None):
        return {"prediction": pid, "status": "not evaluable", "reason": "extractor not frozen" + ("" if ok else " (" + why + ")")}
    blo, bhi = band
    reg = region(cell_min, basis_min) if (cell_min is not None and basis_min is not None) else None
    if rule == "point":
        st = "within the band" if blo <= estimate <= bhi else "outside the band"
        ci_inside = None if ci is None else bool(ci[0] >= blo and ci[1] <= bhi)
        return {"prediction": pid, "status": st, "rule": "point inside the frozen interval", "estimate": estimate, "ci95": ci, "ciInside": ci_inside, "band": [blo, bhi], "region": reg}
    lo, hi = ci
    st = "within the band" if (lo >= blo and hi <= bhi) else ("outside the band" if (hi < blo or lo > bhi) else "inconclusive")
    return {"prediction": pid, "status": st, "rule": "interval inside the frozen band", "estimate": estimate, "ci95": [lo, hi], "band": [blo, bhi], "region": reg}


CHECK6 = "analyses/M731_consistency_check.json"


def p6_tol():
    """The frozen tolerance of the P6 count rule: `tolC` of the last passing run of the frozen-basis check (a file hashed in the registry)."""
    p = os.path.join(ROOT, CHECK6)
    if not os.path.exists(p):
        return None
    runs = [r for r in json.load(open(p, encoding="utf-8"))["runs"] if r.get("allCriteriaPassed")]
    return None if not runs else float(runs[-1]["C-P6c"]["tolC"])


def score_all(frame, freeze, basis_ambient_min=-1.0, basis_probe_min=1.0, nb=4000, realised_band_fn=None, p6_sidecar_fn=None, p2_v4_fn=None, p1_sidecar_fn=None):
    """M727 / M731: scores the predictions covered by the extractor registry on the scoring set of the frame (clean drives that start after F + 1 h; autumn comparison = clean Sep-Nov drives before F - 1 h). Reads the frozen predictions and the frozen
    parameters from the freeze file only. Cells below the support rule, or not covered by the registry, are 'not evaluable' and carry no number."""
    import winter_exposure_monitor as WM
    import winter_extractors as WE
    cl = frame[frame["clean"]].copy()
    _, _, scoring = WM.sets(cl)
    winter = cl[scoring]
    st = pd.to_datetime(cl["start"])
    autumn = cl[(cl["month"] >= 9) & (cl["month"] <= 11) & (st < WM.F - WM.GUARD)]
    P = freeze["predictions"]
    out = []
    for pid in ("P1", "P2", "P3", "P4", "P5", "P6", "P7"):
        if pid not in ("P1", "P2", "P3", "P4", "P5", "P6", "P7"):
            out.append({"prediction": pid, "status": "not evaluable", "reason": "extractor not frozen (not covered by the registry)"})
            continue
        ok, why = extractors_frozen(pid)
        if not ok:
            out.append({"prediction": pid, "status": "not evaluable", "reason": "extractor not frozen (" + why + ")"})
            continue
        if pid == "P1":
            import winter_p1 as W1
            st = pd.to_datetime(frame["start"])
            allw = frame[(st > WM.F + WM.GUARD).values]               # every drive of the scoring window, clean or not (the chain needs the unlogged-use joins)
            if p1_sidecar_fn is None or len(allw) < SUPPORT_DRIVES:
                out.append({"prediction": pid, "status": "not evaluable", "reason": "below the support rule or no P1 sidecar (%d drives in the scoring window)" % len(allw)})
                continue
            sc = p1_sidecar_fn(allw)
            cell = W1.extract_p1(sc, freeze["params"], nb=nb)
            cell["prediction"] = pid
            out.append(cell)
        elif pid == "P2":
            e = WE.extract_p2(winter, nb)
            cell = evaluate_cell(pid, e["nDrives"], e["nDays"], e["estimate"], e["ci95"], P["P2"]["bandAhShareBelow10C"], rule="ci") | {"scoredAgainst": "the frozen band, not the realised-ambient band (optimistic-leaning)"}
            if cell["status"] != "not evaluable" and realised_band_fn is not None:
                rb = realised_band_fn(winter)
                cell["realisedBand"] = {k: rb.get(k) for k in ("status", "reason", "windowMatched", "annual", "thinMonths", "flags", "table", "scenario")}
                if rb.get("status") == "ok":
                    r_ = evaluate_cell(pid, e["nDrives"], e["nDays"], e["estimate"], e["ci95"], rb["windowMatched"], rule="ci")
                    cell["frozenBandStatus"] = cell["status"]
                    cell["status"] = r_["status"]
                    cell["scoredAgainst"] = "the realised-ambient window-matched band (model-derived, S2 with realised shifts); the frozen annual band is beside it"
                if p2_v4_fn is not None and rb.get("status") == "ok":
                    v4 = p2_v4_fn(winter, lambda band: evaluate_cell(pid, e["nDrives"], e["nDays"], e["estimate"], e["ci95"], band, rule="ci")["status"], rb["windowMatched"])
                    cell["v4"] = v4
                    cell["v3Status"] = cell["status"]
                    cell["status"] = v4["status"]
                    cell["scoredAgainst"] += "; registry v4: path-carry bound and offset-adjusted sensitivity applied (M736)"
            out.append(cell)
        elif pid == "P3":
            e = WE.extract_p3(winter, freeze["params"]["R_T"]["EaR_kJmol"], freeze["params"]["R_T"]["R25_mohm"], nb=nb)
            out.append(evaluate_cell(pid, e["nDrives"], e["nDays"], e.get("estimate"), e.get("ci95"), P["P3"]["interval"], rule="point") | {"label": e.get("label"), "uncorrected": e.get("uncorrected")})
        elif pid == "P4":
            import winter_extractors_b as WB
            e = WB.extract_p4(winter, nb)
            if e.get("status") != "fitted":
                out.append({"prediction": pid, "status": "not evaluable", "reason": e.get("reason", "no cell"), "nDrives": e["nDrives"], "nDays": e["nDays"]})
            elif not support_ok(e["nDrives"], e["nDays"]):
                out.append({"prediction": pid, "status": "not evaluable", "reason": "below the support rule (%d drives on %d days; needs %d on %d)" % (e["nDrives"], e["nDays"], SUPPORT_DRIVES, SUPPORT_DAYS)})
            else:
                stm = []
                for name, ok_, est, ci_, band in (("register at 0 C and SoC 60", e["evaluable0C"], e["b0KwAt0CSoc60"], e["b0Ci95"], P["P4"]["kW_at_0C"][1:3]),
                                                   ("register at -10 C and SoC 60", e["evaluableMinus10C"], e["kwAtMinus10C"], e["kwAtMinus10CCi95"], P["P4"]["envelope_at_minus10C"])):
                    if not ok_:
                        stm.append({"statement": name, "status": "not evaluable", "reason": "no data near the temperature (coldest probe %.1f C)" % e["coldestProbeMinC"]})
                    else:
                        inside = bool(band[0] <= est <= band[1])
                        stm.append({"statement": name, "status": "within the band" if inside else "outside the band", "rule": "point inside the frozen interval", "estimate": est, "ci95": ci_, "band": list(band),
                                    "ciInside": bool(ci_[0] >= band[0] and ci_[1] <= band[1]), "region": region(e["coldestProbeMinC"], basis_probe_min)})
                ev = [s for s in stm if s["status"] != "not evaluable"]
                st = "not evaluable" if not ev else ("outside the band" if any(s["status"] == "outside the band" for s in ev) else "within the band")
                out.append({"prediction": pid, "status": st, "statements": stm, "nDrives": e["nDrives"], "nDays": e["nDays"], "regressionSeconds": e["regressionSeconds"],
                            "pinWeightedMeanTminC": e["pinWeightedMeanTminC"], "reading": "BMS-reported register, model-derived intercept of a re-fitted plane, not delivered power; within is not validated"})
        elif pid == "P6":
            import winter_p6 as W6
            tol = p6_tol()
            wn = winter if "p6_n_s" in winter.columns else winter.merge(p6_sidecar_fn(winter), on="key", how="left", suffixes=("", "_p6")) if p6_sidecar_fn is not None else None
            if wn is None or tol is None:
                out.append({"prediction": pid, "status": "not evaluable", "reason": "no P6 sidecar or no frozen tolerance"})
                continue
            e = W6.extract_p6(wn, tol, nb)
            out.append({"prediction": pid, **e, "limitMap": "frozen map extrapolated below the observed range"} if e.get("status") == "fitted" else {"prediction": pid, "status": "not evaluable", "reason": e.get("reason"), "nDrives": e["nDrives"], "nDays": e["nDays"]})
        elif pid == "P7":
            e = WE.extract_p7(winter, nb)
            if e.get("estimate") is None:
                out.append({"prediction": pid, "status": "not evaluable", "reason": e.get("reason", "too few drives"), "nDrives": e["nDrives"], "nDays": e["nDays"]})
            else:
                lo = P["P7"]["points_per_C_cooling_ambientBelow20C"]
                out.append(evaluate_cell(pid, e["nDrives"], e["nDays"], e["estimate"], e["ci95"], [lo[1], lo[2]], cell_min=e["ambientRangeC"][0], basis_min=basis_ambient_min, rule="point"))
        else:
            e = WE.extract_p5(winter, autumn, nb)
            if e.get("status") == "not evaluable":
                out.append({"prediction": pid, "status": "not evaluable", "reason": e.get("reason")})
            elif not support_ok(e["nWinter"], e["nWinterDays"]):
                out.append({"prediction": pid, "status": "not evaluable", "reason": "below the support rule (%d drives on %d days; needs %d on %d)" % (e["nWinter"], e["nWinterDays"], SUPPORT_DRIVES, SUPPORT_DAYS)})
            else:
                out.append({"prediction": pid, "status": e["status"], "p025": e["p025"], "statistic": e["statistic"], "fixedCellVariant": e["fixedCellVariant"], "reading": e["reading"]})
    return out


def main(argv=None):
    freeze = load_freeze()
    for k in freeze["sources"]:
        if k == "prototypeThermalParams" and not os.path.exists(os.path.join(ROOT, freeze["sources"][k]["path"])):
            continue
        read_source(freeze, k)
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import winter_extractors as WE
    import winter_p2_band as WB2
    import winter_p6 as W6
    import winter_p2_v4 as W4
    import winter_p1 as W1
    raw_dir = os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
    cols = ["key"] + [c for c in W6.COLUMNS["P6"] if c != "day"]

    def sidecar(w):
        return W6.build_sidecar(raw_dir, keys=set(w["key"]), out=None)[cols]
    out = score_all(WE.load_frame(ROOT), freeze, realised_band_fn=WB2.realised_band, p6_sidecar_fn=sidecar, p2_v4_fn=lambda w, ev, ep: W4.p2_v4(w, W4.band_fn_engine, ev, expected_primary=ep),
                    p1_sidecar_fn=lambda w: W1.build_sidecar(raw_dir, list(w["key"])))
    print(json.dumps({"freezeSha256": sha(FREEZE), "cells": out}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
