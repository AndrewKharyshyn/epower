#!/usr/bin/env python3
"""Normalise line endings of pipeline outputs to the committed convention (Windows text-mode writes produce CRLF; the repo's
canonical bytes are LF, and the corpus MD5 anchor is taken over those bytes).

For every tracked file that differs from HEAD: if the HEAD blob has NO CRLF and the working file has CRLF, rewrite CRLF -> LF
(refuses if a lone CR exists, i.e. not a pure line-ending difference). Files whose HEAD blob already uses CRLF are left alone.
--rehash OLD_MD5: after normalising, replace every occurrence of OLD_MD5 (32-hex and 12-hex forms) in tracked TEXT files that differ
from HEAD by the current drive_master.csv MD5 (used once when a CRLF master hash was already embedded in stamps).
Usage: python tools/normalize_eol.py [--rehash OLD_MD5] [--dry-run]. Prints a JSON summary."""
import argparse, hashlib, json, os, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEXT = (".csv", ".json", ".txt", ".md", ".html", ".jsx", ".js", ".py", ".sh")


def git(*a):
    return subprocess.check_output(["git", *a], cwd=ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rehash")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    changed = [p for p in git("diff", "--name-only").decode().splitlines() if p.lower().endswith(TEXT)]
    fixed, skipped, refused = [], [], []
    for p in changed:
        fp = os.path.join(ROOT, p)
        if not os.path.exists(fp):
            continue
        w = open(fp, "rb").read()
        try:
            h = git("show", "HEAD:" + p)
        except subprocess.CalledProcessError:
            continue
        if b"\r\n" in w and b"\r\n" not in h:
            if w.replace(b"\r\n", b"").count(b"\r"):
                refused.append(p)
                continue
            if not a.dry_run:
                open(fp, "wb").write(w.replace(b"\r\n", b"\n"))
            fixed.append(p)
        else:
            skipped.append(p)
    out = {"normalised_to_LF": fixed, "left_as_is": skipped, "refused_lone_CR": refused}
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    out["drive_master_md5"] = md5
    if a.rehash and not a.dry_run:
        old, n32, n12, files = a.rehash, 0, 0, []
        for p in changed:
            fp = os.path.join(ROOT, p)
            if not os.path.exists(fp) or p == "drive_master.csv":
                continue
            s = open(fp, encoding="utf-8", newline="").read()
            c32, c12 = s.count(old), s.count(old[:12])
            if c32 or c12:
                s = s.replace(old, md5).replace(old[:12], md5[:12])
                open(fp, "w", encoding="utf-8", newline="").write(s)
                n32 += c32
                n12 += c12
                files.append(p)
        out["rehash"] = {"old": old, "new": md5, "n32": n32, "n12_total": n12, "files": files}
    print(json.dumps(out, indent=1))
    sys.exit(1 if refused else 0)


if __name__ == "__main__":
    main()
