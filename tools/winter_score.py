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


REGISTRY = "analyses/M726_extractor_registry.json"


def extractors_frozen(changelog_text=None):
    """(ok, reason). Scoring may print a number only when an extractor registry exists (the sha256 of every extractor module, written by the extractor milestone) AND the sha256 of the registry file is recorded in the CHANGELOG
    (frozen before the first scoring look). Without it every cell is 'not evaluable (extractor not frozen)' (Director M726 decision)."""
    if not os.path.exists(os.path.join(ROOT, REGISTRY)):
        return False, "no extractor registry"
    h = sha(REGISTRY)
    if changelog_text is None:
        changelog_text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    if h not in changelog_text:
        return False, "the extractor registry sha256 is not recorded in the CHANGELOG"
    reg = json.load(open(os.path.join(ROOT, REGISTRY), encoding="utf-8"))
    for m, want in (reg.get("modules") or {}).items():
        if not os.path.exists(os.path.join(ROOT, m)) or sha(m) != want:
            return False, "an extractor module differs from the registry: " + m
    return True, "frozen"


def support_ok(n_drives, n_days):
    return bool(n_drives >= SUPPORT_DRIVES and n_days >= SUPPORT_DAYS)


def region(cell_min, basis_min):
    """'interpolation check' when the scored cell lies inside the temperature (or ambient) range of the frozen basis, else 'extrapolation test' (spec section 2)."""
    return "interpolation check" if cell_min >= basis_min else "extrapolation test"


def evaluate_cell(pid, n_drives, n_days, estimate=None, ci=None, band=None, cell_min=None, basis_min=None):
    """One cell of one prediction. Below the support rule: 'not evaluable', no number. Otherwise the estimate and its day-cluster interval are compared with the frozen band: the interval inside the band is 'within the band',
    the interval outside the band is 'outside the band', otherwise 'inconclusive'; the label of the region is attached. No cell is evaluable without an estimate (extractor not frozen)."""
    if not support_ok(n_drives, n_days):
        return {"prediction": pid, "status": "not evaluable", "reason": "below the support rule (%d drives on %d days; needs %d on %d)" % (n_drives, n_days, SUPPORT_DRIVES, SUPPORT_DAYS)}
    ok, why = extractors_frozen()
    if not ok or estimate is None or ci is None or band is None:
        return {"prediction": pid, "status": "not evaluable", "reason": "extractor not frozen" + ("" if ok else " (" + why + ")")}
    lo, hi = ci
    blo, bhi = band
    st = "within the band" if (lo >= blo and hi <= bhi) else ("outside the band" if (hi < blo or lo > bhi) else "inconclusive")
    return {"prediction": pid, "status": st, "estimate": estimate, "ci95": [lo, hi], "band": [blo, bhi], "region": region(cell_min, basis_min) if (cell_min is not None and basis_min is not None) else None}


def main(argv=None):
    freeze = load_freeze()
    for k in freeze["sources"]:
        if k == "prototypeThermalParams" and not os.path.exists(os.path.join(ROOT, freeze["sources"][k]["path"])):
            continue
        read_source(freeze, k)
    out = [{"prediction": p, "status": "not evaluable", "reason": "extractor not frozen"} for p in sorted(freeze["predictions"])]
    print(json.dumps({"freezeSha256": sha(FREEZE), "cells": out}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
