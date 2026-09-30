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
import argparse, datetime, hashlib, json, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P = lambda f: os.path.join(ROOT, f)


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
        s.update(corpusHash=live, generatedAt=now, carriedForward=True, basisNDrives=int(basis),
                 computationStatusNote=f"{a.milestone}: CARRIED FORWARD at the {basis}-drive basis (not recomputed on the live corpus): {note}")
        done["carried"].append(k)
    with open(P("summary_arrays.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1))
    print(json.dumps(done, indent=1))


if __name__ == "__main__":
    main()
