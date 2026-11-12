#!/usr/bin/env python3
"""M624 (spec analyses/M624_spec.md Rev 1, W1-03) additive leaf-level splice of the per-bin spread and support leaves of the warm-up curves:
  thermalWarmupLag.warmupCurves.{coolant,oil}{P25C,P75C,Supported}  and  .methodology
  seasonalCharts.charts.ThermalWarmupLag.data.{all,warm,shoulder,cold}.(same leaves)
Recomputed with the builder (compute_summary_arrays._thermal_warmup_lag) on the SAME cohort subsets as tools/regen_seasonal_raw.py (load_subsets), WITHOUT running that tool (its bookkeeping side effects are not wanted). Refuses (exit 3, nothing written) unless every
existing leaf of each block is reproduced exactly (only the new leaves and the methodology text may differ) and the deep diff of the payload lies inside the allow-list.
Usage: python tools/m624_splice.py [--dry-run] [--json PATH]"""
import copy, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
NEW = ("coolantP25C", "coolantP75C", "oilP25C", "oilP75C", "coolantSupported", "oilSupported")


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from walk(a.get(k), b.get(k), f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from walk(x, y, f"{path}[{i}]")
    elif a != b:
        yield path


def stop(msg):
    print("STOP:", msg)
    sys.exit(3)


def allowed(path):
    parts = path.strip("/").split("/")
    if parts[0] == "thermalWarmupLag":
        rest = parts[1:]
    elif parts[:3] == ["seasonalCharts", "charts", "ThermalWarmupLag"] and len(parts) > 4 and parts[3] == "data" and parts[4] in ("all", "warm", "shoulder", "cold"):
        rest = parts[5:]
    else:
        return False
    if rest[:1] == ["methodology"]:
        return True
    return len(rest) >= 2 and rest[0] == "warmupCurves" and rest[1].split("[")[0] in NEW


def main(argv):
    import compute_summary_arrays as C
    import drive_raw_cache as drc
    import regen_seasonal_raw as R
    p = "summary_arrays.json"
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    B = copy.deepcopy(A)
    _dm, subsets = R.load_subsets()
    fl = drc.make_frame_loader(raw_dir=os.path.abspath("raw_only"))
    blocks = {}
    for c in ("all", "warm", "shoulder", "cold"):
        if c in subsets:
            blocks[c] = json.loads(json.dumps(C._thermal_warmup_lag(subsets[c], frame_loader=fl)))
    data = B["seasonalCharts"]["charts"]["ThermalWarmupLag"]["data"]
    targets = [("top", B["thermalWarmupLag"], blocks["all"])] + [(c, data[c], blocks[c]) for c in blocks if c in data]
    for name, tgt, new in targets:
        for k, v in new.items():
            if k == "warmupCurves":
                for kk, vv in v.items():
                    if kk in NEW:
                        tgt["warmupCurves"][kk] = vv
                    elif tgt["warmupCurves"].get(kk) != vv:
                        stop(f"{name}: existing warmupCurves.{kk} not reproduced")
            elif k == "methodology":
                tgt[k] = v
            elif tgt.get(k) != v:
                stop(f"{name}: existing leaf {k} not reproduced")
    if data["all"]["warmupCurves"] != B["thermalWarmupLag"]["warmupCurves"]:
        stop("the 'all' cohort copy differs from the top-level block")
    changed = list(walk(A, B))
    bad = [d for d in changed if not allowed(d)]
    if bad:
        stop(f"deep-diff outside the allow-list: {bad[:6]}")
    res = {"changedLeaves": len(changed), "paths": changed, "cohorts": sorted(blocks), "newLeavesAll": {k: B["thermalWarmupLag"]["warmupCurves"][k] for k in NEW}}
    print(json.dumps(res, indent=1)[:3500])
    if "--json" in argv:
        json.dump(res, open(argv[argv.index("--json") + 1], "w", encoding="utf-8", newline="\n"), indent=1)
    if "--dry-run" not in argv and changed:
        open(p, "w", encoding="utf-8", newline="").write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
