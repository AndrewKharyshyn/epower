#!/usr/bin/env python3
"""M585 (spec analyses/M585_spec.md Rev 1): attribution controls for one consumer stage. For the stage `tools/<tool>.py` (arguments as in tools/ingest_stages.json) three variants are run from the committed
payload, each followed by a restore of the stage outputs:
  old       the tool at git HEAD (OLD inline rule, 1.05 s) -> must reproduce the committed leaves byte-exact (stamp timestamps ignored)
  new       the tool in the working tree (central regime reader)
  new_excl  the working-tree tool with the drive `2026-11-04_08-01-15.csv` removed from every drive_master.csv read, in-process (production inputs untouched)
Output: analyses/M585_controls_<tool>.json (changed / lost / added leaf paths per comparison). Usage: python tools/m585_controls.py <tool> [args...]  (e.g. dependence_sensitivity, cell_spread_step: m573_cell_spread_step --splice)
Analysis only; it restores the tracked outputs with git checkout after every variant."""
import hashlib, json, os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DRIVE = "2026-11-04_08-01-15.csv"
STAMP_TIME_KEYS = {"generatedAt", "computedAt", "includedInReleaseAt"}


def sh(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def leaves(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in STAMP_TIME_KEYS:
                continue
            yield from leaves(v, p + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, p + "/" + str(i))
    else:
        yield p, o


def leaf_map(path):
    return dict(leaves(json.load(open(path, encoding="utf-8"))))


def compare(a, b):
    """a, b: snapshots {arrays: leafmap, files: {out: sha}, jsons: {out: leafmap}}; leaves are compared inside summary_arrays.json and the other json outputs, other outputs by content hash."""
    out = {"changed": [], "lost": [], "added": [], "nLeaves": len(a["arrays"])}
    for name, x, y in [("summary_arrays.json", a["arrays"], b["arrays"])] + [(o, a["jsons"].get(o, {}), b["jsons"].get(o, {})) for o in sorted(set(a["jsons"]) | set(b["jsons"]))]:
        kx, ky = set(x), set(y)
        out["changed"] += ["%s:%s" % (name, k) for k in sorted(kx & ky) if x[k] != y[k]]
        out["lost"] += ["%s:%s" % (name, k) for k in sorted(kx - ky)]
        out["added"] += ["%s:%s" % (name, k) for k in sorted(ky - kx)]
    out["filesWithDifferentContent"] = sorted(o for o in a["files"] if o not in ("summary_arrays.json",) and a["files"][o] != b["files"].get(o))
    return out


def main():
    tool, args = sys.argv[1], sys.argv[2:]
    outputs = ["summary_arrays.json"] + [x for x in sys.argv[0:0]]
    stages = json.load(open(os.path.join(ROOT, "tools", "ingest_stages.json"), encoding="utf-8"))
    stages = stages["stages"] if isinstance(stages, dict) else stages
    st = next(s for s in stages if any(tool in c for c in s["cmd"]))
    outs = [o for o in st.get("outputs", [])]
    tracked = sh(["git", "ls-files"] + outs).stdout.split()
    py = sys.executable
    base_arrays = os.path.join(ROOT, "summary_arrays.json")
    sh(["git", "checkout", "--", "summary_arrays.json"] + tracked)

    def snapshot():
        files, jsons = {}, {}
        for o in outs:
            fp = os.path.join(ROOT, o)
            if not os.path.exists(fp):
                files[o] = None
                continue
            files[o] = hashlib.sha256(open(fp, "rb").read()).hexdigest()[:16]
            if o.endswith(".json") and o != "summary_arrays.json":
                jsons[o] = leaf_map(fp)
        return {"arrays": leaf_map(base_arrays), "files": files, "jsons": jsons}

    committed = snapshot()

    def restore():
        sh(["git", "checkout", "--", "summary_arrays.json"] + tracked)

    result = {"tool": tool, "args": args, "driveExcluded": DRIVE, "stageOutputs": outs}
    snaps = {}
    # old: tool at HEAD, run under a temporary name inside tools/ (ROOT resolves to the repo)
    old_src = sh(["git", "show", "HEAD:tools/%s.py" % tool]).stdout
    old_name = "_m585_old_%s.py" % tool
    old_path = os.path.join(ROOT, "tools", old_name)
    open(old_path, "w", encoding="utf-8", newline="\n").write(old_src)
    try:
        r = sh([py, os.path.join("tools", old_name)] + args)
        result["oldReturncode"] = r.returncode
        snaps["old"] = snapshot() if r.returncode == 0 else None
        if r.returncode != 0:
            result["oldTail"] = (r.stdout + r.stderr)[-600:]
    finally:
        os.remove(old_path)
        restore()
    r = sh([py, os.path.join("tools", tool + ".py")] + args)
    result["newReturncode"] = r.returncode
    snaps["new"] = snapshot() if r.returncode == 0 else None
    if r.returncode != 0:
        result["newTail"] = (r.stdout + r.stderr)[-600:]
    restore()
    code = ("import runpy, sys, os, pandas as pd\n"
            "o = pd.read_csv\n"
            "def rc(p, *a, **k):\n"
            "    d = o(p, *a, **k)\n"
            "    if isinstance(p, str) and os.path.basename(p) == 'drive_master.csv' and 'file' in d.columns:\n"
            "        d = d[d['file'] != %r].reset_index(drop=True)\n"
            "    return d\n"
            "pd.read_csv = rc\n"
            "sys.argv = ['%s.py'] + %r\n"
            "runpy.run_path(os.path.join('tools', '%s.py'), run_name='__main__')\n") % (DRIVE, tool, args, tool)
    r = sh([py, "-c", code])
    result["newExclReturncode"] = r.returncode
    snaps["new_excl"] = snapshot() if r.returncode == 0 else None
    if r.returncode != 0:
        result["newExclTail"] = (r.stdout + r.stderr)[-600:]
    restore()
    result["oldVsCommitted"] = compare(committed, snaps["old"]) if snaps.get("old") else None
    result["newVsCommitted"] = compare(committed, snaps["new"]) if snaps.get("new") else None
    result["newExclVsCommitted"] = compare(committed, snaps["new_excl"]) if snaps.get("new_excl") else None
    result["newVsNewExcl"] = compare(snaps["new"], snaps["new_excl"]) if snaps.get("new") and snaps.get("new_excl") else None
    def vals(a, b, paths):
        out = {}
        for x in paths:
            name, k = x.split(":", 1)
            ma = a["arrays"] if name == "summary_arrays.json" else a["jsons"].get(name, {})
            mb = b["arrays"] if name == "summary_arrays.json" else b["jsons"].get(name, {})
            out[x] = [ma.get(k), mb.get(k)]
        return out
    if snaps.get("new"):
        result["newVsCommittedValues"] = vals(committed, snaps["new"], result["newVsCommitted"]["changed"])
    if snaps.get("new") and snaps.get("new_excl"):
        result["newVsNewExclValues"] = vals(snaps["new"], snaps["new_excl"], result["newVsNewExcl"]["changed"])
    result["oldReproducesCommittedByteExact"] = bool(result["oldVsCommitted"] and not (result["oldVsCommitted"]["changed"] or result["oldVsCommitted"]["lost"] or result["oldVsCommitted"]["added"] or result["oldVsCommitted"]["filesWithDifferentContent"]))
    with open(os.path.join(ROOT, "analyses", "M585_controls_%s.json" % tool), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    s = lambda c: None if c is None else {"changed": len(c["changed"]), "lost": len(c["lost"]), "added": len(c["added"]), "files": len(c["filesWithDifferentContent"])}
    print(json.dumps({"tool": tool, "oldByteExact": result["oldReproducesCommittedByteExact"], "old": s(result["oldVsCommitted"]), "new": s(result["newVsCommitted"]), "newExcl": s(result["newExclVsCommitted"]), "newVsExcl": s(result["newVsNewExcl"]),
                      "rc": [result.get("oldReturncode"), result.get("newReturncode"), result.get("newExclReturncode")]}))


if __name__ == "__main__":
    main()
