#!/usr/bin/env python3
"""Lost-leaf guard (M377a, analyses/M377_spec.md Rev 2 P6). An ingestion rebuild must not silently drop keys that the previous (committed)
summary_arrays.json carried: the M376 run lost 371 leaves (additive keys written by one-off splices, a frozen audit record, restamp notes).
A leaf of the previous arrays that is absent as ANY node (leaf or container) in the current arrays is "lost". A loss is EXPECTED only when it
matches a rule in analyses/leaf_guard_rules.json (id, rationale, milestone, pathTemplate, condition) AND the rule's data condition holds; every
other loss is UNEXPECTED and the tool exits 1. The Director owns the rule list; a rule change needs a spec.
pathTemplate: segments separated by "/", each an exact key, or a single-segment placeholder: {i} = a list index, {key} = one dict key (the
condition then checks that key). No other wildcard exists. A rule with "matchPrefix": true matches every lost leaf UNDER the template (the template
names a block, e.g. a block that is null in the current arrays).
Conditions (registered below): stamp_hash_changed | parent_null_in_current | sibling_present(sibling) | field_changed(entryDepth, field).
Usage: python tools/leaf_guard.py [--previous git:HEAD | PATH] [--current summary_arrays.json] [--rules PATH] [--out PATH]"""
import argparse, json, os, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def nodes(o, p=(), out=None):
    out = set() if out is None else out
    out.add(p)
    if isinstance(o, dict):
        for k, v in o.items():
            nodes(v, p + (k,), out)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            nodes(v, p + (i,), out)
    return out


def leaves(o, p=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, p + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, p + (i,))
    else:
        yield p


def get(o, p):
    for k in p:
        o = o[k]
    return o


def match(template, path, prefix=False):
    """Return the bound placeholders (dict) or None."""
    seg = template.split("/")
    if prefix:
        if len(path) <= len(seg):
            return None
        path = path[:len(seg)]
    elif len(seg) != len(path):
        return None
    bound = {}
    for s, k in zip(seg, path):
        if s == "{i}":
            if not isinstance(k, int):
                return None
        elif s == "{key}":
            if not isinstance(k, str):
                return None
            bound["key"] = k
        elif s != str(k):
            return None
    return bound


def cond_stamp_hash_changed(prev, cur, path, bound, rule):
    k = bound.get("key")
    try:
        a, b = prev["_artifactStamps"][k]["corpusHash"], cur["_artifactStamps"][k]["corpusHash"]
    except (KeyError, TypeError):
        return False
    return a != b


def cond_parent_null_in_current(prev, cur, path, bound, rule):
    n = len(rule["pathTemplate"].split("/")) if rule.get("matchPrefix") else 1
    n = len(path) - n if rule.get("matchPrefix") else 1
    try:
        return get(cur, path[:len(path) - n]) is None
    except (KeyError, IndexError, TypeError):
        return False


def cond_sibling_present(prev, cur, path, bound, rule):
    try:
        par = get(cur, path[:-1])
    except (KeyError, IndexError, TypeError):
        return False
    return isinstance(par, dict) and bool(par.get(rule["sibling"]))


def cond_field_changed(prev, cur, path, bound, rule):
    """The entry n levels up from the lost leaf (entryDepth = its length as a path prefix) has a field whose value differs between the previous and the current arrays."""
    ent = path[:rule["entryDepth"]]
    try:
        return get(prev, ent + (rule["field"],)) != get(cur, ent + (rule["field"],))
    except (KeyError, IndexError, TypeError):
        return False


CONDITIONS = {"field_changed": cond_field_changed, "stamp_hash_changed": cond_stamp_hash_changed, "parent_null_in_current": cond_parent_null_in_current, "sibling_present": cond_sibling_present}


def check_rules(rules):
    for r in rules:
        for k in ("id", "rationale", "milestone", "pathTemplate", "condition"):
            if not r.get(k):
                raise SystemExit(f"leaf_guard rule {r.get('id')!r}: missing {k}")
        if r["condition"] not in CONDITIONS:
            raise SystemExit(f"leaf_guard rule {r['id']!r}: unknown condition {r['condition']!r}")
        if any(("*" in s or s not in ("{i}", "{key}") and s.startswith("{")) for s in r["pathTemplate"].split("/")):
            raise SystemExit(f"leaf_guard rule {r['id']!r}: only exact keys, {{i}} and {{key}} are allowed in pathTemplate")


def guard(prev, cur, rules):
    check_rules(rules)
    cur_nodes = nodes(cur)
    lost = [p for p in leaves(prev) if p not in cur_nodes]
    expected, unexpected = {}, []
    for p in lost:
        ok = False
        for r in rules:
            b = match(r["pathTemplate"], p, bool(r.get("matchPrefix")))
            if b is not None and CONDITIONS[r["condition"]](prev, cur, p, b, r):
                expected[r["id"]] = expected.get(r["id"], 0) + 1
                ok = True
                break
        if not ok:
            unexpected.append("/".join(map(str, p)))
    return {"nPreviousLeaves": sum(1 for _ in leaves(prev)), "nLost": len(lost), "expectedByRule": expected, "nUnexpected": len(unexpected), "unexpected": unexpected}


def load_previous(spec):
    if spec.startswith("git:"):
        ref = spec[4:]
        out = subprocess.run(["git", "show", f"{ref}:summary_arrays.json"], cwd=ROOT, capture_output=True)
        if out.returncode != 0:
            raise SystemExit("git show failed: " + out.stderr.decode("utf-8", "replace")[-300:])
        return json.loads(out.stdout.decode("utf-8"))
    return json.load(open(spec, encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--previous", default="git:HEAD")
    ap.add_argument("--current", default=os.path.join(ROOT, "summary_arrays.json"))
    ap.add_argument("--rules", default=os.path.join(ROOT, "analyses", "leaf_guard_rules.json"))
    ap.add_argument("--out")
    a = ap.parse_args()
    prev = load_previous(a.previous)
    cur = json.load(open(a.current, encoding="utf-8"))
    rules = json.load(open(a.rules, encoding="utf-8"))
    rep = guard(prev, cur, rules)
    rep["previous"] = a.previous
    rep["rules"] = [r["id"] for r in rules]
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: rep[k] for k in ("nPreviousLeaves", "nLost", "expectedByRule", "nUnexpected")}, ensure_ascii=False))
    if rep["nUnexpected"]:
        print("UNEXPECTED LOSSES (first 30):", file=sys.stderr)
        for u in rep["unexpected"][:30]:
            print("  " + u, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
