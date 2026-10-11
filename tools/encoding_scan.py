#!/usr/bin/env python3
"""M401 (audit D7): ratchet for text-mode file I/O without an explicit encoding (Windows default cp1251/cp1252 breaks UTF-8 repo files; tools/run_ingest.py sets PYTHONUTF8=1 for stages only).
Counts calls open(...) in text mode, Path.read_text and Path.write_text without encoding= in the tracked *.py files (AST). tools/encoding_baseline.json holds the per-file counts at M401
(script-written by --write-baseline); the guard test fails when any file has MORE un-encoded calls than its baseline (a new file has baseline 0). Existing calls are not rewritten here.
Usage: python tools/encoding_scan.py [--write-baseline]"""
import ast, json, os, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = os.path.join(ROOT, "tools", "encoding_baseline.json")


def tracked_py():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout.split()
    return sorted(out)


def count_file(path):
    try:
        tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
    except (SyntaxError, UnicodeDecodeError, OSError):
        return 0
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn, kws = node.func, {k.arg for k in node.keywords}
        is_open = isinstance(fn, ast.Name) and fn.id == "open"
        is_pl = isinstance(fn, ast.Attribute) and fn.attr in ("read_text", "write_text")
        if not (is_open or is_pl) or "encoding" in kws:
            continue
        if is_open:
            mode = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = node.args[1].value
            for k in node.keywords:
                if k.arg == "mode" and isinstance(k.value, ast.Constant):
                    mode = k.value.value
            if mode and "b" in str(mode):
                continue
        n += 1
    return n


def scan():
    return {f: c for f in tracked_py() if (c := count_file(f))}


if __name__ == "__main__":
    cur = scan()
    if "--write-baseline" in sys.argv:
        json.dump({"_note": "M401 (audit D7) ratchet baseline: un-encoded text-mode I/O calls per tracked .py file; may only go down. Written by tools/encoding_scan.py --write-baseline.",
                   "total": sum(cur.values()), "files": cur}, open(BASE, "w", encoding="utf-8", newline="\n"), indent=1, sort_keys=True)
    print(json.dumps({"files": len(cur), "total": sum(cur.values())}))
