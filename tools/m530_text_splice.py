#!/usr/bin/env python3
"""M530 (analyses/M530_spec.md Rev 2): session-ledger notes sessionGroups[17,18,19] in summary_config.json: 'corpus now N drives' -> 'corpus as of <date>: N drives' (the dated cumulative values are the ledger's own and
are not re-verified here). Text only, byte-level replacement inside the hand-curated config, idempotent. Usage: python tools/m530_text_splice.py [--dry-run] [--check]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EDITS = [(17, "corpus now 167 drives", "corpus as of Jul 21: 167 drives"), (18, "corpus now 173 drives", "corpus as of Jul 22: 173 drives"), (19, "corpus now 180 drives", "corpus as of Jul 23: 180 drives")]


def diff_paths(a, b, p=()):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            out += [p + (k,)] if (k not in a or k not in b) else diff_paths(a[k], b[k], p + (k,))
    elif isinstance(a, list) and isinstance(b, list):
        out += [p] if len(a) != len(b) else [q for i, (x, y) in enumerate(zip(a, b)) for q in diff_paths(x, y, p + (i,))]
    elif a != b:
        out.append(p)
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    raw = open("summary_config.json", "rb").read().decode("utf-8")
    C = json.loads(raw)
    new_raw, changed = raw, []
    for i, old, new in EDITS:
        note = C["sessionGroups"][i]["note"]
        if old in note:
            assert note.count(old) == 1 and new_raw.count(old) == 1, ("old text not unique", i)
            new_raw = new_raw.replace(old, new); changed.append(i)
        else:
            assert new in note, ("neither old nor new text", i)
    allowed = {("sessionGroups", i, "note") for i, _, _ in EDITS}
    bad = [p for p in diff_paths(C, json.loads(new_raw)) if p not in allowed]
    if "--check" in argv:
        print(json.dumps({"check": "m530 ledger notes", "alreadyApplied": not changed and not bad}))
        return 0 if not changed and not bad else 1
    print(json.dumps({"rowsChanged": changed, "outsideAllowList": [list(map(str, p)) for p in bad]}))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        open("summary_config.json", "wb").write(new_raw.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
