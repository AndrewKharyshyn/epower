#!/usr/bin/env python3
"""M528 (analyses/M528_spec.md Rev 2): dated narrative strings that read as "current": 4 edits in summary_config.json drivingMixNote and 2 in generatorTractionRecon._provenance (payload).
Text only, idempotent; the payload deep diff must be exactly the one leaf; the config diff must be that one string. Neither string has a writer script (hand-curated / frozen).
Usage: python tools/m528_text_splice.py [--dry-run] [--check]"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

CFG_EDITS = [
    ("Current dataset distance mix (audit 2026-07-14):", "Dataset distance mix at the 2026-07-14 audit:"),
    ("corrects the DISTANCE mix toward typical daily use, but every cycle-intensity figure feeding it is from May–Jul (warm-season) data only.",
     "reweights the DISTANCE mix toward typical daily use, but at that date every cycle-intensity figure feeding it was from May–Jul (warm-season) data only (the logged corpus began 2026-05-11)."),
    ("have NOT been recomputed on the current 194-drive corpus; treat them as indicative of the warm-season bias, not as current shares.",
     "have NOT been recomputed since: the corpus was 194 drives at that date (M62, 2026-07-28) and is larger now; treat them as indicative of the warm-season bias at that date, not as current shares."),
]
PROV_EDITS = [
    ("rpmFinding freshly recomputed from the current 374-drive rpmDistribution.", "rpmFinding recomputed at that date from the then-current 374-drive rpmDistribution."),
]
PROV_APPEND = " Later entries and generatorTractionRecon.staleBlocks supersede the state described here (rpmFinding: superseded by rpmOptBand, M525)."
PROV_PATH = ("generatorTractionRecon", "_provenance")
CFG_PATH = ("drivingMixNote",)


def apply_text(s, edits, append=None):
    changed = False
    for old, new in edits:
        if old in s:
            assert s.count(old) == 1, ("old text not unique", old[:50])
            s = s.replace(old, new); changed = True
        else:
            assert new in s, ("neither old nor new text found", old[:50])
    if append and not s.endswith(append):
        s = s + append; changed = True
    return s, changed


def splice_payload(A):
    new = copy.deepcopy(A)
    s, ch = apply_text(new[PROV_PATH[0]][PROV_PATH[1]], PROV_EDITS, PROV_APPEND)
    new[PROV_PATH[0]][PROV_PATH[1]] = s
    return new, ch


def diff_paths(a, b, p=()):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            if k not in a or k not in b:
                out.append(p + (k,))
            else:
                out += diff_paths(a[k], b[k], p + (k,))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(p)
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                out += diff_paths(x, y, p + (i,))
    elif a != b:
        out.append(p)
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A = json.loads(raw)
    new, ch_p = splice_payload(A)
    bad = [p for p in diff_paths(A, new) if p != PROV_PATH]
    cfg_raw = open("summary_config.json", "rb").read().decode("utf-8")
    C = json.loads(cfg_raw)
    note, ch_c = apply_text(C[CFG_PATH[0]], CFG_EDITS)
    # config: byte-level replacement inside the raw text (the file is hand-curated; no re-serialisation)
    cfg_new = cfg_raw
    for old, new_s in CFG_EDITS:
        o = json.dumps(old, ensure_ascii=False)[1:-1]; n = json.dumps(new_s, ensure_ascii=False)[1:-1]
        if o in cfg_new:
            assert cfg_new.count(o) == 1, ("config text not unique", old[:50])
            cfg_new = cfg_new.replace(o, n)
    assert (json.loads(cfg_new)[CFG_PATH[0]] == note)
    cfg_other = [p for p in diff_paths(C, json.loads(cfg_new)) if p != CFG_PATH]
    if "--check" in argv:
        ok = not ch_p and not ch_c and not bad and not cfg_other
        print(json.dumps({"check": "m528 dated narratives", "alreadyApplied": ok}))
        return 0 if ok else 1
    print(json.dumps({"payloadLeafChanged": ch_p, "configStringChanged": ch_c, "payloadOutsideAllowList": [list(map(str, p)) for p in bad], "configOutsideAllowList": [list(map(str, p)) for p in cfg_other]}))
    if bad or cfg_other:
        return 1
    if "--dry-run" in argv:
        return 0
    if ch_p:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + (chr(10) if raw.endswith(chr(10)) else ""))
    if ch_c:
        with open("summary_config.json", "wb") as f:
            f.write(cfg_new.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
