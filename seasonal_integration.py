"""
seasonal_integration.py  —  additive production splice (array layer)
====================================================================
Injects the cohort-array layer into the production summary_arrays.json as ONE new
top-level key `seasonalCohorts`, using the project's additive-splice discipline:
compute only the new key, leaf-level splice, assert every pre-existing key BYTE-identical
(no run_pipeline, no ML refit, drive_master untouched). This is the array half of the
dashboard splice; the JSX tab binds to arrays.seasonalCohorts.
"""
import json, os, hashlib, copy

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_ARRAYS = os.path.join(HERE, "summary_arrays.json")     # production copy (read-only in)
OUT_ARRAYS = os.path.join(HERE, "summary_arrays.seasonal.json")


def _canon(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_seasonal_cohorts():
    """Assemble the compact seasonalCohorts payload from the proven cohort layer."""
    import cohort_arrays as CA
    ca = CA.build()
    dep = json.load(open(os.path.join(HERE, "seasonal_arrays.json")))["seasonalDependency"]
    cfg = json.load(open(os.path.join(HERE, "seasonal_config.json")))
    return {
        "_schema": "seasonalCohorts.v1",
        "cohorts": ca["cohorts"],
        "thresholds": cfg["thermalThresholds"],
        "allYearEnabled": False,
        "cohortLabelAll": cfg["cohorts"]["allLabel"],
        "adjustedContrastAvailable": ca["adjustedContrastAvailable"],
        "charts": ca["charts"],
        "dataReadyCharts": ca["dataReadyCharts"],
        "phase2Charts": ca["phase2Charts"],
        "warmupCharts": ca["warmupCharts"],
        "frozenCharts": ca["frozenCharts"],
        "stagedCharts": ca["stagedCharts"],
        "regenView": dep["phenomenonViews"]["regen"],
        "dependencyCoverage": dep["coverage"],
    }


def splice(src=SRC_ARRAYS, out=OUT_ARRAYS):
    if not os.path.exists(src):
        return {"status": "no_production_arrays", "note": "summary_arrays.json not staged"}
    prod = json.load(open(src))
    before_keys = set(prod.keys())
    before_canon = {k: _canon(v) for k, v in prod.items()}

    payload = build_seasonal_cohorts()
    spliced = copy.deepcopy(prod)
    spliced["seasonalCohorts"] = payload   # additive: ONE new top-level key

    # ---- stamp the new key (M235/F09 gate: every top-level key needs a corpusHash) ----
    stamps = spliced.get("_artifactStamps")
    if isinstance(stamps, dict) and stamps:
        template = stamps.get("meta") or next(iter(stamps.values()))
        seasonal_stamp = copy.deepcopy(template)
        seasonal_stamp["computationStatus"] = "computed"
        stamps["seasonalCohorts"] = seasonal_stamp   # inherits live corpus/config hashes

    # ---- integrity: every pre-existing key byte-identical EXCEPT _artifactStamps,
    #      which may change only by adding the seasonalCohorts stamp entry ----
    changed = []
    for k in before_keys:
        if k == "_artifactStamps":
            old = json.loads(before_canon[k]); new = spliced[k]
            extra = set(new) - set(old)
            preexisting_same = all(_canon(old[e]) == _canon(new[e]) for e in old)
            if not (extra == {"seasonalCohorts"} and preexisting_same):
                changed.append(k)
        elif before_canon[k] != _canon(spliced[k]):
            changed.append(k)
    added = [k for k in spliced.keys() if k not in before_keys]

    json.dump(spliced, open(out, "w"), ensure_ascii=False, separators=(",", ":"))
    return {
        "status": "ok" if (not changed and added == ["seasonalCohorts"]) else "INTEGRITY_FAIL",
        "existing_keys": len(before_keys),
        "existing_keys_changed": changed,
        "keys_added": added,
        "out": out,
        "out_key_count": len(spliced),
    }


if __name__ == "__main__":
    print(json.dumps(splice(), indent=2))
