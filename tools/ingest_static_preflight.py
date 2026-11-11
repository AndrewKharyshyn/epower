#!/usr/bin/env python3
"""M610a (spec analyses/M610_spec.md Rev 1, R3): cheap, read-only checks that can be decided BEFORE the first ingestion stage, so a missing input or a wording violation costs seconds
instead of the hours after which the late gates (release_check, leaf_guard, build_html) would have found it. Writes nothing. Exit 0 only if every check passes.
Checks:
  stage_list         every stage script exists, ids are unique, `needs` entries exist and come first (tools/stage_order.py, needs rules only; the file-level ratchet runs in CI)
  ambients           every raw CSV not yet in raw_manifest.json has a canonical `ambientByDrive` entry in summary_config.json (len >= 2, numeric), and `vehicle.odometerAsOf` equals the date of
                     the newest new drive (standing ODO rule, owner 2026-11-03)
  language_sources   summary_config.json string values and xtrail_summary.jsx strings do not hit a language_gate rule whose scope covers config / jsx (the same A2 rule scopes as semantic_gate.py)
  ack_inputs         every XT_ACK_* variable that names a .json file points to a file that exists and parses, and the ruling it cites (`ruling`) exists
  leaf_guard_rules   analyses/leaf_guard_rules.json parses
NOT decidable before the run (listed in the report with the reason, they stay late gates): STAMP_POLICY coverage (depends on which stamps the new corpus makes stale), REQUIRED_BLOCKS and
leaf_guard diffs (depend on the recomputed arrays), build_html compile and semantic_gate B-D (need the rebuilt payload and dashboard).
Usage: python tools/ingest_static_preflight.py [--root DIR] [--json]"""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DEFAULT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
NOT_PRERUNNABLE = {"stamp_policy_coverage": "depends on which _artifactStamps the new corpus makes stale",
                   "required_blocks_and_leaf_guard_diff": "depend on the recomputed summary_arrays.json",
                   "build_html_compile_and_semantic_gate_B_D": "need the rebuilt payload and dashboard"}


def jload(p):
    return json.load(open(p, encoding="utf-8"))


def check_stage_list(root):
    import stage_order as SO
    stages = SO.load_stages(os.path.join(root, "tools", "ingest_stages.json"))
    problems = []
    for s in stages:
        for a in s["cmd"][1:2]:
            if re.match(r"^[\w./\\-]+\.(py|js|sh)$", a) and not os.path.isfile(os.path.join(root, a.replace("\\", "/"))):
                problems.append("stage %s: script %s not found" % (s["id"], a))
    res = SO.lint(stages, root, file_level=False)
    problems += ["%s %s" % (v["kind"], {k: x for k, x in v.items() if k != "kind"}) for v in res["violations"]]
    return problems


def newest_date(files):
    ds = []
    for f in files:
        m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})", f)
        if m:
            ds.append("%s-%s-%s" % m.groups())
    return max(ds) if ds else None


def check_ambients(root):
    import new_raw_files as NR
    raw = os.environ.get("XT_RAW_DIR") or os.path.join(root, "raw")
    new = NR.new_files(raw, os.path.join(root, "raw_manifest.json")) if os.path.isdir(raw) else []
    if not new:
        return [], 0
    cfg = jload(os.path.join(root, "summary_config.json"))
    amb = cfg.get("ambientByDrive") or {}
    problems = []
    for f in new:
        k = f.replace(" ", "_")
        v = amb.get(k)
        if v is None:
            problems.append("no ambientByDrive entry for %s" % k)
        elif not (isinstance(v, list) and len(v) >= 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)):
            problems.append("ambientByDrive[%s] is not canonical (list of >= 2 numbers): %r" % (k, v))
    nd = newest_date(new)
    asof = (cfg.get("vehicle") or {}).get("odometerAsOf")
    if nd and asof != nd:
        problems.append("vehicle.odometerAsOf is %r but the newest new drive date is %s (the ODO given with an ingestion is as of the newest drive; set odometerKm and odometerAsOf before the run)" % (asof, nd))
    return problems, len(new)


def check_language(root):
    sys.path.insert(0, root)
    import language_gate as LG
    cfgh = LG.scan_payload(jload(os.path.join(root, "summary_config.json")))
    code, _comm = LG.scan_jsx(open(os.path.join(root, "xtrail_summary.jsx"), encoding="utf-8").read())
    problems = []
    for r in LG.RULES:
        if "config" in r.scope and r.rid in cfgh:
            problems.append("config: rule %s hit: %s" % (r.rid, cfgh[r.rid][0]))
        if "jsx" in r.scope and r.rid in code:
            problems.append("jsx: rule %s hit" % r.rid)
    return problems


def check_acks(root):
    problems = []
    for k, v in sorted(os.environ.items()):
        if k.startswith("XT_ACK_") and v.lower().endswith(".json"):
            if not os.path.isfile(v):
                problems.append("%s: file %s not found" % (k, v))
                continue
            try:
                a = jload(v)
            except ValueError as ex:
                problems.append("%s: %s does not parse (%s)" % (k, os.path.basename(v), ex))
                continue
            r = a.get("ruling") if isinstance(a, dict) else None
            if isinstance(a, dict) and not r:
                problems.append("%s: no ruling cited" % k)
            elif r and not os.path.isfile(os.path.join(root, r)):
                problems.append("%s: cited ruling %s not found" % (k, r))
    return problems


def check_leaf_rules(root):
    p = os.path.join(root, "analyses", "leaf_guard_rules.json")
    if not os.path.isfile(p):
        return []
    try:
        jload(p)
        return []
    except ValueError as ex:
        return ["leaf_guard_rules.json does not parse: %s" % ex]


def check_label(n_new, env=None):
    """M611: a run that ingests new drives needs XT_INGEST_LABEL=M### (restamp_ingest and gtr_carry_label stop on it; a missing label cost a 124-minute run in the Nov 2026 ingestion)."""
    if not n_new:
        return []
    v = (env if env is not None else os.environ).get("XT_INGEST_LABEL", "")
    if not re.fullmatch(r"M\d+[a-z]?", v or ""):
        return ["%d new raw file(s) but XT_INGEST_LABEL is %s (expected the milestone id of this ingestion, e.g. M608)" % (n_new, repr(v) if v else "not set")]
    return []


def run(root):
    out = {"checks": [], "notPrerunnable": NOT_PRERUNNABLE}
    n_new = 0
    for name, fn in (("stage_list", check_stage_list), ("ambients", check_ambients), ("language_sources", check_language), ("ack_inputs", check_acks), ("leaf_guard_rules", check_leaf_rules)):
        try:
            r = fn(root)
            if name == "ambients":
                r, n_new = r
            out["checks"].append({"name": name, "ok": not r, "problems": r})
        except Exception as ex:                                 # a check that cannot run is a failed check, never a silent pass
            out["checks"].append({"name": name, "ok": False, "problems": ["check could not run: %r" % (ex,)]})
    out["checks"].append({"name": "ingest_label", "ok": not check_label(n_new), "problems": check_label(n_new)})
    out["nNewRawFiles"] = n_new
    out["ok"] = all(c["ok"] for c in out["checks"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT_DEFAULT)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = run(os.path.abspath(a.root))
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        for c in res["checks"]:
            print("%-18s %s" % (c["name"], "ok" if c["ok"] else "FAIL"))
            for p in c["problems"][:10]:
                print("    - " + p)
        print("new raw files: %d; not decidable before the run: %s" % (res["nNewRawFiles"], ", ".join(res["notPrerunnable"])))
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
