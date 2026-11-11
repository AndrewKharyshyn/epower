#!/usr/bin/env python3
"""M613 / M610b pilot tools (Director ruling 2026-11-11, required change 5): a state hash for the non-interference check of a collect pass (A1) and the normalised output hash used by the pass-versus-real
comparator (required change 6).

snapshot(root): git HEAD, a hash of the index (`git ls-files -s`), the sha256 of the bytes of every tracked file (worktree content), the sha256 of every untracked non-ignored file, an inventory of
`raw_only/`, of `runs/.checkpoints/` (relative path -> size) and of every cache directory (relpath -> sha256 of each file; every top-level *_cache directory).
compare(pre, post): problems list. Tracked/untracked content, index, HEAD, raw_only and the checkpoint inventory must be equal; a cache entry that existed before and is MODIFIED or DELETED fails; entries
ADDED by the pass are allowed and listed (the caches are content keyed, so an addition cannot change a result).
normalised_sha(path): sha256 of the file bytes, or for a .json file of the canonical JSON with the pre-registered run-time stamp leaves (TIMESTAMP_LEAVES, found by a scan of the 45 JSON stage outputs on
2026-11-11: every leaf whose string value is an ISO date-time) dropped; any other difference is a difference.
Usage: python tools/state_hash.py snapshot --out FILE | compare PRE.json POST.json"""
import hashlib, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DEFAULT = os.path.abspath(os.path.join(HERE, ".."))


def cache_dirs(root):
    """Every top-level directory named *_cache (the git-ignored content-keyed caches: raw_cache, regen_cache, probe_cache, capacity_cache, ...)."""
    return sorted(d for d in os.listdir(root) if d.endswith("_cache") and os.path.isdir(os.path.join(root, d)))


TIMESTAMP_LEAVES = frozenset(("generatedAt", "includedInReleaseAt", "computedAt", "supersededAt", "generatedAtUtc", "generated", "created", "generatedUtc", "verifiedAt"))


def _git(root, *args):
    return subprocess.run(["git", "-C", root] + list(args), capture_output=True, check=True).stdout


def _sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _inventory(base, hashed=True):
    out = {}
    if os.path.isdir(base):
        for d, dirs, files in os.walk(base):
            dirs.sort()
            for f in sorted(files):
                p = os.path.join(d, f)
                rel = os.path.relpath(p, base).replace(os.sep, "/")
                out[rel] = _sha_file(p) if hashed else os.path.getsize(p)
    return out


def snapshot(root):
    root = os.path.abspath(root)
    tracked = [x for x in _git(root, "ls-files", "-z").decode("utf-8", "replace").split("\0") if x]
    untracked = [x for x in _git(root, "ls-files", "-z", "--others", "--exclude-standard").decode("utf-8", "replace").split("\0") if x]
    return {"head": _git(root, "rev-parse", "HEAD").decode().strip(),
            "index": hashlib.sha256(_git(root, "ls-files", "-s", "-z")).hexdigest(),
            "tracked": {f: (_sha_file(os.path.join(root, f)) if os.path.isfile(os.path.join(root, f)) else None) for f in tracked},
            "untracked": {f: _sha_file(os.path.join(root, f)) for f in untracked if os.path.isfile(os.path.join(root, f))},
            "raw_only": _inventory(os.path.join(root, "raw_only")),
            "checkpoints": _inventory(os.path.join(root, "runs", ".checkpoints"), hashed=False),
            "caches": {c: _inventory(os.path.join(root, c)) for c in cache_dirs(root)}}


def compare(pre, post):
    problems, added = [], []
    for k in ("head", "index"):
        if pre[k] != post[k]:
            problems.append("%s differs" % k)
    for k in ("tracked", "untracked", "raw_only", "checkpoints"):
        a, b = pre[k], post[k]
        for f in sorted(set(a) | set(b)):
            if a.get(f) != b.get(f):
                problems.append("%s: %s %s" % (k, f, "added" if f not in a else "deleted" if f not in b else "modified"))
    for c in sorted(set(pre["caches"]) | set(post["caches"])):
        a, b = pre["caches"].get(c, {}), post["caches"].get(c, {})
        for f in sorted(set(a) | set(b)):
            if f in a and a[f] != b.get(f):
                problems.append("cache %s/%s: a pre-existing entry was %s" % (c, f, "deleted" if f not in b else "modified"))
            elif f not in a:
                added.append("%s/%s" % (c, f))
    return {"ok": not problems, "problems": problems[:50], "nProblems": len(problems), "addedCacheEntries": added[:200], "nAddedCacheEntries": len(added)}


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in TIMESTAMP_LEAVES}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def normalised_sha(path):
    if not os.path.isfile(path):
        return None
    if path.endswith(".json"):
        try:
            with open(path, encoding="utf-8") as f:
                o = json.load(f)
            return hashlib.sha256(json.dumps(_strip(o), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
        except ValueError:
            pass
    return _sha_file(path)[:16]


def main(argv):
    if not argv or argv[0] not in ("snapshot", "compare"):
        print(__doc__)
        return 2
    if argv[0] == "snapshot":
        out = argv[argv.index("--out") + 1]
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(snapshot(ROOT_DEFAULT), f)
        print("snapshot written", out)
        return 0
    with open(argv[1], encoding="utf-8") as f:
        pre = json.load(f)
    with open(argv[2], encoding="utf-8") as f:
        post = json.load(f)
    res = compare(pre, post)
    print(json.dumps(res, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
