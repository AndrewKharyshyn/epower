#!/usr/bin/env python3
"""M513 (analyses/M513_spec.md Rev 2 R7): git attestation of the raw identity of blocks that read raw files and were NOT re-run for the backfill (generatorTractionRecon, seasonalCharts).
For each block: walk the first-parent history of summary_arrays.json back from HEAD while the block (canonical-JSON md5) stays identical to HEAD's; C = the OLDEST such commit.
Evidence recorded per block: C (sha, subject, tag), the md5 of the block at C and at HEAD, raw_manifest.json corpusHash in C's tree, and C's subject line as the run record of the milestone that produced it.
This shows which raw_manifest.json was in the tree when the block content was committed, NOT what the computation read: the attested field is written only when raw_manifest.json at C equals the live one,
with source text 'attested at M513 from git history'. Output: analyses/M513_attestation.json (read by tools/stamp_dependencies_apply.py --backfill). Read-only on the repository.
Usage: python tools/m513_attest.py [--max 40]"""
import hashlib, json, os, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "analyses", "M513_attestation.json")
BLOCKS = ("generatorTractionRecon", "seasonalCharts")


def git(*a):
    return subprocess.run(["git"] + list(a), cwd=ROOT, capture_output=True, check=True).stdout


def _tag_manifest(tag):
    try:
        return json.loads(git("show", "%s:raw_manifest.json" % tag).decode("utf-8")).get("corpusHash")
    except subprocess.CalledProcessError:
        return None


def canon(o):
    return hashlib.md5(json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mx = int(argv[argv.index("--max") + 1]) if "--max" in argv else 40
    live = json.load(open(os.path.join(ROOT, "raw_manifest.json"), encoding="utf-8"))["corpusHash"]
    head = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    head_md5 = {b: canon(head[b]) for b in BLOCKS}
    commits = git("log", "--first-parent", "--format=%H", "-n", str(mx), "--", "summary_arrays.json").decode().split()
    out, oldest, stopped = {}, {b: None for b in BLOCKS}, set()
    for c in commits:                                  # newest first; the run of identical blocks from HEAD backwards ends at the first difference
        A = json.loads(git("show", "%s:summary_arrays.json" % c).decode("utf-8"))
        for b in BLOCKS:
            if b in stopped:
                continue
            if canon(A[b]) == head_md5[b]:
                oldest[b] = c
            else:
                stopped.add(b)
    for b in BLOCKS:
        c = oldest[b]
        if not c:
            out[b] = {"attested": False, "reason": "block not identical to HEAD in any examined commit"}; continue
        try:
            man = json.loads(git("show", "%s:raw_manifest.json" % c).decode("utf-8"))
        except subprocess.CalledProcessError:
            out[b] = {"attested": False, "reason": "no raw_manifest.json in the tree at %s" % c}; continue
        subj = git("log", "-1", "--format=%s", c).decode().strip()
        tags = git("tag", "--points-at", c).decode().split()
        # run record: the stamp's own note and the CHANGELOG headings of the milestones whose entries name the producing refresh (R7: the producer ran at or before C)
        notes = (head["_artifactStamps"].get(b) or {}).get("computationStatusNote")
        heads = [l.strip()[:300] for l in open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") if l.startswith(("## M463 ", "## M466 "))]
        ok = man.get("corpusHash") == live and bool(heads) and bool(notes)
        out[b] = {"attested": ok, "commit": c, "commitSubject": subj, "tags": tags, "blockMd5AtCommitAndHead": head_md5[b],
                  "rawManifestCorpusHashAtCommit": man.get("corpusHash"), "rawManifestSnapshotIdAtCommit": man.get("snapshotId"), "liveRawManifestCorpusHash": live,
                  "source": ("attested at M513 from git history (block content last changed at commit %s %s; raw_manifest.json corpusHash in that tree equals the live one; producer-run evidence: CHANGELOG M463/M466 entries and the stamp note)" % (c[:10], ",".join(tags) or "no tag")),
                  "producerRunEvidence": {"stampNote": notes, "changelogHeadings": heads, "rawManifestCorpusHashAtTagM466": _tag_manifest("M466")},
                  "limit": "shows which raw_manifest.json was in the tree when the block content was committed, not what the computation read"}
        if ok:
            out[b]["rawManifestCorpusHash"] = man["corpusHash"]
    json.dump(out, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    print(json.dumps({b: {k: v for k, v in out[b].items() if k in ("attested", "commit", "commitSubject", "tags", "reason")} for b in BLOCKS}, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
