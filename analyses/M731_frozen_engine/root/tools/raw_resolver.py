#!/usr/bin/env python3
"""M707 (B3): ONE typed resolver from a raw drive file to its identity (the digits of the file name: 14 timestamp digits, 15 for e4ORCE captures).

Before M707 three places built `{digits: path}` or picked a file per digit key on their own (tools/new_raw_files.py, tools/ingest_core.py raw_index, tools/stage_raw.py): two differently
named files for the same timestamp silently collapsed to one (the last in directory order), so a pair with DIFFERENT bytes produced "0 new files" and a green exit.
Rules here:
  * one key, one file: nothing to do;
  * one key, several files with IDENTICAL bytes (same sha256): an accepted alias; the chosen name is deterministic (a name already in raw_manifest.json first, else the smallest name) and
    every alias and the digest are recorded (summary());
  * one key, several files with DIFFERENT bytes: RawConflict (a stop, never a pick). Includes a zero-byte or truncated duplicate, and two real drives that share a wall-clock key (DST fall-back).
Library: resolve(raw_dir, manifest_path=None) -> Resolution; Resolution.index {key: path}; .aliases {key: [other paths]}; .digests {key: sha256}.
CLI: python tools/raw_resolver.py [--raw-dir DIR] [--json]   (exit 0 clean, 3 conflict)"""
import hashlib, json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


class RawConflict(RuntimeError):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__("raw files with the same timestamp key but different bytes: " + "; ".join("%s: %s" % (k, ", ".join("%s=%s" % (n, h[:12]) for n, h in v)) for k, v in sorted(conflicts.items())))


def key_of(name):
    """Identity of a raw file: the digits of its base name without the extension."""
    return re.sub(r"\D", "", os.path.basename(str(name)).rsplit(".", 1)[0])


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _manifest_names(manifest_path):
    if not manifest_path or not os.path.exists(manifest_path):
        return set()
    out = set()
    for r in json.load(open(manifest_path, encoding="utf-8")).get("files", []):
        for k in ("canonical", "raw_name", "record_id"):
            if r.get(k):
                out.add(os.path.basename(str(r[k])))
    return out


class Resolution:
    def __init__(self, index, aliases, digests):
        self.index, self.aliases, self.digests = index, aliases, digests

    def summary(self):
        """Compact record for a candidate manifest / report: only keys that had aliases, plus counts."""
        return {"nKeys": len(self.index), "nAliasedKeys": len(self.aliases),
                "aliased": {k: {"chosen": os.path.basename(self.index[k]), "aliases": sorted(os.path.basename(a) for a in v), "sha256": self.digests[k]} for k, v in sorted(self.aliases.items())}}


def resolve(raw_dir, manifest_path=None):
    groups = {}
    for f in sorted(os.listdir(raw_dir)):
        if f.lower().endswith(".csv") and key_of(f):
            groups.setdefault(key_of(f), []).append(f)
    known = _manifest_names(manifest_path)
    index, aliases, digests, conflicts = {}, {}, {}, {}
    for k, names in groups.items():
        if len(names) == 1:
            index[k] = os.path.join(raw_dir, names[0])
            continue
        hs = [(n, _sha(os.path.join(raw_dir, n))) for n in names]
        if len({h for _, h in hs}) > 1:
            conflicts[k] = hs
            continue
        chosen = sorted(names, key=lambda n: (n not in known, n))[0]
        index[k] = os.path.join(raw_dir, chosen)
        aliases[k] = [os.path.join(raw_dir, n) for n in names if n != chosen]
        digests[k] = hs[0][1]
    if conflicts:
        raise RawConflict(conflicts)
    return Resolution(index, aliases, digests)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    raw_dir = argv[argv.index("--raw-dir") + 1] if "--raw-dir" in argv else os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
    try:
        r = resolve(raw_dir, os.path.join(ROOT, "raw_manifest.json"))
    except RawConflict as ex:
        print("STOP raw_resolver:", ex)
        return 3
    print(json.dumps(r.summary()) if "--json" in argv else "ok %d keys, %d aliased" % (len(r.index), len(r.aliases)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
