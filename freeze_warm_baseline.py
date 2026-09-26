"""
freeze_warm_baseline.py  —  capture the authoritative warm-only baseline.
The frozen file is the regression anchor: existing warm calculations must not
change on future seasonal runs except where a documented correction is
intentionally introduced (handoff test #16). Re-run ONLY with an explicit,
logged reason.
"""
import json, os, hashlib, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
a = json.load(open(os.path.join(HERE, "seasonal_arrays.json")))
cfg = json.load(open(os.path.join(HERE, "seasonal_config.json")))
warm = a["cohorts"]["Warm"]
master_md5 = hashlib.md5(open(os.path.join(HERE, "drive_master.csv"), "rb").read()).hexdigest()

frozen = {
    "_purpose": "Warm-only regression anchor. DO NOT regenerate without a logged, "
                "documented correction. Future seasonal runs are asserted against this.",
    "frozenAtUtc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "seasonalCoreVersion": cfg["seasonalCoreVersion"],
    "thermalRegimeVersion": cfg["thermalRegimeVersion"],
    "thresholds": cfg["thermalThresholds"],
    "sourceMasterMd5": master_md5,
    "warm": {
        "n_drives": warm["coverage"]["n_drives"],
        "km": warm["coverage"]["km"],
        "independent_days": warm["coverage"]["independent_days"],
        "date_range": warm["coverage"]["date_range"],
        "ambient_range_c": warm["coverage"]["ambient_range_c"],
        "metrics": {k: v.get("value") for k, v in warm["metrics"].items()},
    },
}
out = os.path.join(HERE, "warm_baseline_freeze.json")
json.dump(frozen, open(out, "w"), indent=2)
print("froze warm baseline:", out)
print(json.dumps(frozen["warm"], indent=2))
