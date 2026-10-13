#!/usr/bin/env python3
"""Re-issue artifact stamps for summary_arrays.json blocks after an ingestion (M310).

The build_html artifact-stamp gate (M220.2) requires every stamped key's corpusHash to equal the live drive_master.csv MD5. Blocks
that other stages regenerate on the new corpus, and blocks that are deliberately carried forward, both keep the previous stamp
unless it is re-issued here. This tool re-issues it WITH disclosure: a regenerated block gets a note naming its generator; a
carried block additionally gets carriedForward=true, basisNDrives and the reason, so it cannot be mistaken for a recomputed one.
It never changes block content (except --inject-json KEY=FILE, which replaces one block by the JSON a generator wrote).

Usage: python tools/restamp_blocks.py --milestone M310 \\
         --regen KEY="note" ... --carried KEY=BASIS_N="note" ... [--inject-json KEY=FILE ...]
Idempotent. Prints a JSON summary of what was re-stamped."""
import argparse, datetime, hashlib, json, os, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P = lambda f: os.path.join(ROOT, f)


def write_retry(path, text, tries=6, pause=1.5):
    """M426: Windows can refuse to re-open a just-written 3 MB payload for writing (OSError 13 / 22: a transient section mapping, e.g. by a real-time virus scanner) at this
    stage, which stopped two full ingestions. The text is complete in memory and nothing was truncated when the open fails, so a bounded retry is safe; any other error, or
    the last failure, is raised unchanged."""
    for i in range(tries):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return
        except OSError as e:
            if i == tries - 1 or e.errno not in (13, 22):
                raise
            time.sleep(pause * (i + 1))


def kv(s):
    k, v = s.split("=", 1)
    return k, v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--milestone", required=True)
    ap.add_argument("--regen", action="append", default=[], metavar='KEY="note"')
    ap.add_argument("--carried", action="append", default=[], metavar='KEY=BASIS_N="note"')
    ap.add_argument("--inject-json", action="append", default=[], metavar="KEY=FILE")
    a = ap.parse_args()
    live = hashlib.md5(open(P("drive_master.csv"), "rb").read()).hexdigest()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    A = json.load(open(P("summary_arrays.json"), encoding="utf-8"))
    st = A["_artifactStamps"]
    done = {"regenerated": [], "carried": [], "injected": [], "corpusHash": live}
    for spec in a.inject_json:
        k, f = kv(spec)
        A[k] = json.load(open(P(f) if not os.path.isabs(f) else f, encoding="utf-8"))
        done["injected"].append(k)
    for spec in a.regen:
        k, note = kv(spec)
        s = st[k]
        s.update(corpusHash=live, generatedAt=now, computationStatus="computed",
                 computationStatusNote=f"{a.milestone}: {note}")
        s.pop("carriedForward", None)
        done["regenerated"].append(k)
    for spec in a.carried:
        k, rest = kv(spec)
        basis, note = rest.split("=", 1)
        s = st[k]
        s.update(corpusHash=live, generatedAt=now, computationStatus="carriedForward", carriedForward=True, basisNDrives=int(basis),   # M419 (F06): the status is set with the flag
                 computationStatusNote=f"{a.milestone}: CARRIED FORWARD at the {basis}-drive basis (not recomputed on the live corpus): {note}")
        done["carried"].append(k)
    write_retry(P("summary_arrays.json"), json.dumps(A, ensure_ascii=False, indent=1))
    print(json.dumps(done, indent=1))


if __name__ == "__main__":
    main()
