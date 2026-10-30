#!/usr/bin/env python3
"""M537 (analyses/M537_spec.md Rev 2): splice of the additive sub-leaf emulation.seedSensitivity.unionOverStudies (read from analyses/M532_emulation_seed_sensitivity.json and analyses/M534_pool_seed_size.json) and of
the union-spread statement into powerFade.cadenceSensitivity and fadeModes.power.trend.cadenceSensitivity. Pattern of tools/m533_cadence_splice.py: regenerate the block through the changed functions of
compute_summary_arrays from the leaves already in the payload, insert the new sub-leaf explicitly (the walk stops on key-set differences), deep-diff and splice ONLY the sub-leaf, the two statements and the two
trend-note tails; any other difference STOPS. Stored source hashes of the leaf are passed as expected (mismatch -> not_available). The powerFade slope / interval leaves are asserted byte-unchanged.
Usage: python tools/m537_cadence_splice.py [--dry-run] [--check]"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import compute_summary_arrays as C

P = "summary_arrays.json"
STMT_START = "HV-current-density adjustment (M170) is partial:"
STALE_CLAUSE = ", stale: the clean-drive count is now"


def _walk(o, n, path, changed):
    if isinstance(o, dict) and isinstance(n, dict):
        if set(o) != set(n):
            raise SystemExit("STOP: key set differs at %s: %s" % (path, sorted(set(o) ^ set(n))))
        for k in n:
            if isinstance(o[k], (dict, list)) and isinstance(n[k], type(o[k])):
                _walk(o[k], n[k], path + "." + k, changed)
            elif o[k] != n[k]:
                o[k] = n[k]
                changed.append(path + "." + k)
    elif isinstance(o, list) and isinstance(n, list):
        if len(o) != len(n):
            raise SystemExit("STOP: list length at " + path)
        for i, (a, b) in enumerate(zip(o, n)):
            if isinstance(a, (dict, list)):
                _walk(a, b, "%s[%d]" % (path, i), changed)
            elif a != b:
                o[i] = b
                changed.append("%s[%d]" % (path, i))
    elif o != n:
        raise SystemExit("STOP: type change at " + path)


def splice(A):
    """returns (new payload, changed leaf paths, paths outside the allow list)."""
    A = copy.deepcopy(A)
    before = copy.deepcopy(A)
    locs = [("powerFade.cadenceSensitivity", lambda: A["powerFade"]["cadenceSensitivity"]), ("fadeModes.power.trend.cadenceSensitivity", lambda: A["fadeModes"]["power"]["trend"]["cadenceSensitivity"])]
    changed = []
    for name, get in locs:
        cur = get()
        cs = {k: v for k, v in cur.items() if k not in ("emulation", "statement")}
        emu = C._powerfade_emulation_snapshot(int(cur["nClean"]))
        old_ss = (cur.get("emulation") or {}).get("seedSensitivity")
        if old_ss is not None:
            emu["seedSensitivity"] = C._powerfade_seed_sensitivity(emu, old_ss.get("sourceSha256"))
            if emu["seedSensitivity"].get("status") == "ok":
                emu["seedSensitivity"]["unionOverStudies"] = C._powerfade_union_over_studies(emu, (old_ss.get("unionOverStudies") or {}).get("sourceSha256"))
        new = json.loads(json.dumps(C._powerfade_cadence_block(cs, emu), default=float))
        if old_ss is None:
            cur["emulation"]["seedSensitivity"] = new["emulation"]["seedSensitivity"]
            changed.append(name + ".emulation.seedSensitivity")
        elif "unionOverStudies" not in old_ss:                         # the walk stops on key-set differences: insert the new sub-leaf explicitly
            old_ss["unionOverStudies"] = new["emulation"]["seedSensitivity"]["unionOverStudies"]
            changed.append(name + ".emulation.seedSensitivity.unionOverStudies")
        _walk(cur, new, name, changed)
    note_locs = [("powerFade.note", lambda: A["powerFade"], lambda: A["powerFade"]["cadenceSensitivity"]["statement"]),
                 ("fadeModes.power.trend.note", lambda: A["fadeModes"]["power"]["trend"], lambda: A["fadeModes"]["power"]["trend"]["cadenceSensitivity"]["statement"])]
    for name, holder, stmt in note_locs:
        h = holder()
        i = h["note"].find(STMT_START)
        if i < 0:
            raise SystemExit("STOP: statement tail not found in " + name)
        new_note = h["note"][:i] + stmt()
        if new_note != h["note"]:
            h["note"] = new_note
            changed.append(name)
    allowed_prefix = tuple(n + ".emulation" for n, _ in locs)
    allowed = {n + ".statement" for n, _ in locs} | {n for n, _, _ in note_locs}
    bad = [c for c in changed if c not in allowed and not c.startswith(allowed_prefix)]
    # extra assertions: the powerFade slope / interval leaves outside cadenceSensitivity and note are byte-unchanged
    for top in (("powerFade",), ("fadeModes", "power", "trend")):
        b, a = before, A
        for k in top:
            b, a = b[k], a[k]
        for k in set(b) | set(a):
            if k in ("cadenceSensitivity", "note"):
                continue
            if b.get(k) != a.get(k):
                bad.append(".".join(top) + "." + k)
    for name, get in locs:
        if STALE_CLAUSE in get()["statement"]:
            bad.append(name + ".statement still carries the stale clause")
    return A, changed, bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    raw = open(P, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    new, changed, bad = splice(A)
    if "--check" in argv:
        print(json.dumps({"check": "m537 cadence union spread", "alreadyApplied": not changed and not bad}))
        return 0 if not changed and not bad else 1
    print(json.dumps({"nChanged": len(changed), "changed": changed, "outsideAllowList": bad}, indent=1))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open(P, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + (chr(10) if raw.endswith(chr(10)) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
