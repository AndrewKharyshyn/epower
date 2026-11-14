#!/usr/bin/env python3
"""M610a (spec analyses/M610_spec.md Rev 1, section 3.A and R1): static order lint of tools/ingest_stages.json.

A stage must run after every stage it depends on. Two kinds of dependency are checked:
  needs   an explicit per-stage list `needs: [stage ids]` (block-level dependencies inside the shared summary_arrays.json, which no file-level inference can see;
          e.g. `thermal_provenance` reconciles with the `thermalSupportLedger` block that `thermal_support_ledger` refreshes).
  files   repository files named as string constants in the stage's static code closure that are a declared `outputs` entry of ANOTHER stage: that stage must come first,
          unless the reading stage lists the file in `reads_prior_state` (a reasoned waiver: the stage deliberately reads the carried, pre-refresh state; "*" waives every file,
          used only by the read-only pre-run stage `static_preflight`).
          Files written by 3 or more stages (shared accumulators such as summary_arrays.json) are not checked at file level (reported under `shared`; use `needs`).
Violations make the exit code 1; file-level findings already listed in the pending-review baseline (analyses/M610_stage_needs.json, key fileLevelBaseline) are reported as `baselined`, so the file-level rule is a ratchet (a NEW finding fails), while `needs` is a hard rule. `candidates` (a stage whose own source names a top-level payload key that another LATER stage's source also names) are a review aid for the
`needs` table, never a failure.
Usage: python tools/stage_order.py [--json PATH] [--stages PATH] [--root DIR]      Library: lint(stages, root) -> dict."""
import argparse, ast, functools, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT_DEFAULT = os.path.abspath(os.path.join(HERE, ".."))
SHARED_MIN_WRITERS = 3
_PATH_RE = re.compile(r"^[\w./\\-]+$")


def load_stages(path):
    d = json.load(open(path, encoding="utf-8"))
    return d["stages"] if isinstance(d, dict) else d


def _script_files(stage, cp):
    files = set()
    for a in stage["cmd"]:
        r = cp._resolve(a.replace("\\", "/")) if _PATH_RE.match(a) else None
        if r:
            files |= set(cp.closure(r, tuple(getattr(cp, "narrow_for", lambda s: ())(stage))))
    return sorted(f for f in files if f.endswith(".py"))


@functools.lru_cache(maxsize=None)
def _string_constants_cached(root, rel, stamp):          # M650 (P-04): every stage closure re-parsed the same files; parse each file once per process (the key carries mtime and size, so an edited file is re-read)
    return _string_constants_uncached(root, rel)


def _string_constants(root, rel):
    try:
        st = os.stat(os.path.join(root, rel)); stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    return _string_constants_cached(root, rel, stamp)


def _string_constants_uncached(root, rel):
    try:
        tree = ast.parse(open(os.path.join(root, rel), encoding="utf-8", errors="replace").read())
    except (OSError, SyntaxError):
        return set()
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 200}


def load_baseline(root):
    p = os.path.join(root, "analyses", "M610_stage_needs.json")
    if not os.path.isfile(p):
        return set()
    return {(x["stage"], x["file"]) for x in json.load(open(p, encoding="utf-8")).get("fileLevelBaseline", [])}


def _declared(stages, idx, out):
    """M650 (P-04): reads / writes declared at payload-key granularity. Tokens: `arrays:<top-level key of summary_arrays.json>` or a repository file.
    A stage that declares `reads: [token]` must come after EVERY stage that declares the token in `writes` (or, for a file token, in `outputs`), unless it lists the token in `reads_prior_state`
    (kind declared_read_before_write). Stamping-final rule: once a stage marked `stamps: true` has run, no later stage may write the payload (`summary_arrays.json` in `outputs` or an `arrays:` token in `writes`)
    unless it is itself marked `stamps: true` (kind payload_write_after_stamp), so the stamps describe the final payload."""
    writers = {}
    for s in stages:
        for tok in list(s.get("writes") or []) + [o.replace("\\", "/") for o in (s.get("outputs") or [])]:
            writers.setdefault(tok, []).append(s["id"])
    for s in stages:
        waived = set((x or "").replace("\\", "/") for x in (s.get("reads_prior_state") or []))
        for tok in s.get("reads") or []:
            if tok in waived or "*" in waived:
                continue
            ws = [w for w in writers.get(tok, []) if w != s["id"]]
            late = [w for w in ws if idx[w] > idx[s["id"]]]
            if late:
                out["violations"].append({"kind": "declared_read_before_write", "stage": s["id"], "token": tok, "writers": ws, "stageIndex": idx[s["id"]], "firstLaterWriterIndex": min(idx[w] for w in late)})
    stamp_idx = [idx[s["id"]] for s in stages if s.get("stamps")]
    if stamp_idx:
        first = min(stamp_idx)
        for s in stages:
            if idx[s["id"]] > first and not s.get("stamps"):
                wr = [o for o in (s.get("outputs") or []) if o.replace("\\", "/") == "summary_arrays.json"] + [w for w in (s.get("writes") or []) if w.startswith("arrays:")]
                if wr:
                    out["violations"].append({"kind": "payload_write_after_stamp", "stage": s["id"], "writes": wr, "stageIndex": idx[s["id"]], "firstStampIndex": first})


def lint(stages, root=ROOT_DEFAULT, payload_keys=None, file_level=True, baseline=None):
    import ingest_checkpoint as ICP
    cp = ICP.Checkpoints(root, stages)
    idx = {s["id"]: i for i, s in enumerate(stages)}
    out = {"violations": [], "shared": [], "candidates": [], "stages": len(stages)}
    if len(idx) != len(stages):
        out["violations"].append({"kind": "duplicate_stage_id"})
    for s in stages:
        for n in s.get("needs", []) or []:
            if n not in idx:
                out["violations"].append({"kind": "needs_unknown", "stage": s["id"], "needs": n})
            elif idx[n] >= idx[s["id"]]:
                out["violations"].append({"kind": "needs_after", "stage": s["id"], "needs": n, "stageIndex": idx[s["id"]], "needsIndex": idx[n]})
    _declared(stages, idx, out)
    if not file_level:
        out["ok"] = not out["violations"]
        return out
    base = load_baseline(root) if baseline is None else baseline
    writers = {}
    for s in stages:
        for o in s.get("outputs") or []:
            writers.setdefault(o.replace("\\", "/"), []).append(s["id"])
    shared = {f for f, w in writers.items() if len(w) >= SHARED_MIN_WRITERS}
    out["shared"] = sorted(shared)
    consts = {}
    for s in stages:
        names = set()
        for f in _script_files(s, cp):
            names |= {c.replace("\\", "/") for c in _string_constants(root, f)}
        consts[s["id"]] = names
        waived = set((x or "").replace("\\", "/") for x in (s.get("reads_prior_state") or []))
        own = set(o.replace("\\", "/") for o in (s.get("outputs") or []))
        for f, w in writers.items():
            if f in shared or "*" in waived or f in waived or f in own or f not in names:
                continue
            later = [t for t in w if t != s["id"] and idx[t] > idx[s["id"]]]
            if later and not any(idx[t] < idx[s["id"]] for t in w):
                rec = {"kind": "reads_before_writer", "stage": s["id"], "file": f, "writers": w, "firstWriterIndex": min(idx[t] for t in w), "stageIndex": idx[s["id"]]}
                (out.setdefault("baselined", []) if (s["id"], f) in base else out["violations"]).append(rec)
    if payload_keys:
        for s in stages:
            for t in stages:
                if idx[t["id"]] <= idx[s["id"]] or t["id"] in (s.get("needs") or []):
                    continue
                common = sorted(k for k in payload_keys if k in consts[s["id"]] and k in consts[t["id"]])
                if common:
                    out["candidates"].append({"reader_or_writer": s["id"], "later": t["id"], "keys": common[:6]})
    out["ok"] = not out["violations"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages")
    ap.add_argument("--root", default=ROOT_DEFAULT)
    ap.add_argument("--json")
    ap.add_argument("--write-baseline", action="store_true", help="(re)write the file-level baseline from the current findings (status unreviewed)")
    ap.add_argument("--candidates", action="store_true", help="also compute the (slow, noisy) payload-key candidate list for the needs review")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    stages = load_stages(a.stages or os.path.join(root, "tools", "ingest_stages.json"))
    keys = None
    if a.candidates:
        keys = set(json.load(open(os.path.join(root, "summary_arrays.json"), encoding="utf-8")))
    res = lint(stages, root, keys, baseline=set() if a.write_baseline else None)
    if a.write_baseline:
        bp = os.path.join(root, "analyses", "M610_stage_needs.json")
        base = [{"stage": v["stage"], "file": v["file"], "status": "unreviewed"} for v in res["violations"] if v["kind"] == "reads_before_writer"]
        json.dump({"note": "M610a: file-level order findings of tools/stage_order.py present when the lint was introduced; status unreviewed = pending the Director review table (spec E3). A new finding not listed here fails the lint.", "fileLevelBaseline": base}, open(bp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        res["violations"] = [v for v in res["violations"] if v["kind"] != "reads_before_writer"]
        res["ok"] = not res["violations"]
    if a.json:
        json.dump(res, open(a.json, "w", encoding="utf-8"), indent=1)
    print(json.dumps({"ok": res["ok"], "stages": res["stages"], "violations": res["violations"], "sharedFiles": len(res["shared"]), "candidates": len(res["candidates"])}, ensure_ascii=False)[:3000])
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
