#!/usr/bin/env python3
"""M363 (spec analyses/M363_spec.md Rev 2): leaf string updates only, from the single sources: comparisonCube.metrics.starts_100km.{label,estimand} from m297_comparison_cube.METRICS and
engineStartRate.publishedEngineStartsByType.note from tools/engine_start_rate.published_note. Deep-diff asserts no other leaf changes. Usage: python tools/m363_splice.py"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import m297_comparison_cube as CC
import engine_start_rate as E
A = json.load(open("summary_arrays.json", encoding="utf-8"))
old = copy.deepcopy(A)
m = next(x for x in CC.METRICS if x[0] == "starts_100km")
cm = A["comparisonCube"]["metrics"]["starts_100km"]
cm["label"] = m[1]
cm["estimand"] = m[6]
pub = {x["label"]: x for x in (A.get("engineStartsByType") or [])}
A["engineStartRate"]["publishedEngineStartsByType"]["note"] = E.published_note(pub)
ALLOW = {"/comparisonCube/metrics/starts_100km/label", "/comparisonCube/metrics/starts_100km/estimand", "/engineStartRate/publishedEngineStartsByType/note"}


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), path
        for k in a:
            walk(a[k], b[k], f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{i}]")
    elif a != b:
        assert path in ALLOW, (path, a, b)


walk(old, A)
with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(A, f, ensure_ascii=False, indent=1)
print("updated:", sorted(ALLOW))
