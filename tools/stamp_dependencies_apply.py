#!/usr/bin/env python3
"""M513 (analyses/M513_spec.md Rev 2): re-derive the stamps of the declared blocks (tools/stamp_dependencies.json) from their declared dependencies and keep the prior identity in `stampLineage`.
Writes ONLY /_artifactStamps/<declared blocks> (asserted by a deep comparison of everything else); never changes a block, drive_master.csv, raw_manifest.json or a raw file.
Raw identity (readsRaw blocks): in an ingestion run (XT_RUN_STAGES_OK set by tools/run_ingest.py) the live raw_manifest corpusHash is written only when every producer stage of the block ran OK in this run
(source "ingest run <XT_RUN_STARTED_AT>: producer stages ok") and computedAt is the run start (never later than the block's calculation, never the stamping time); otherwise the prior declared raw
identity is carried. Outside a run (--backfill) a raw identity is written only from analyses/M513_attestation.json (git-attested, per block), else it stays absent.
Usage: python tools/stamp_dependencies_apply.py [--backfill] [--dry-run] [--milestone M513]   Idempotent: a second run changes nothing."""
import copy, datetime, hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stamp_common as SC

ATTEST = os.path.join(ROOT, "analyses", "M513_attestation.json")
REPLAY = os.path.join(ROOT, "analyses", "M513_replay.json")
ATTESTED_BLOCKS = ("generatorTractionRecon", "seasonalCharts")      # not re-run (a GTR re-run would trigger the M466 flip/acknowledgement route): git attestation instead of a sandbox replay


def _arg(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def derive_all(A, cfg, deps, live_master, live_manifest, env, root, backfill=False, attest=None, milestone="M513", replay=None):
    """Returns (new _artifactStamps, report). A is not modified."""
    stamps = copy.deepcopy(A["_artifactStamps"])
    ok_stages = set(filter(None, (env.get("XT_RUN_STAGES_OK") or "").split(",")))
    run_at = env.get("XT_RUN_STARTED_AT")
    now_iso = env.get("XT_STAMP_NOW") or datetime.datetime.now(datetime.timezone.utc).isoformat()
    report = {}
    for k, d in deps.items():
        if k not in stamps:
            report[k] = "no stamp"; continue
        s = stamps[k]
        prior = s.get("declaredIdentity") or {}
        raw_hash, raw_src, computed_at, note = prior.get("rawManifestCorpusHash"), prior.get("rawIdentitySource"), s.get("computedAt") if s.get("dependencies") else None, s.get("computedAtNote") if s.get("dependencies") else None
        raw_dep = d.get("readsRaw") or d.get("readsRawManifest")
        ran = bool(ok_stages) and all(p in ok_stages for p in d.get("producerStages", [])) and bool(run_at)
        if ran:
            computed_at, note = run_at, None
            if raw_dep:
                raw_hash, raw_src = live_manifest, "ingest run %s: producer stages %s ran OK; raw_manifest.json corpusHash of this run" % (run_at, ",".join(d["producerStages"]))
        elif backfill:
            at = (attest or {}).get(k)
            if raw_dep and at and at.get("rawManifestCorpusHash"):
                raw_hash, raw_src = at["rawManifestCorpusHash"], at["source"]
            if d.get("ownTime"):
                b = A
                for p in d["ownTime"].split("."):
                    b = b.get(p) if isinstance(b, dict) else None
                if b:
                    computed_at, note = b, None
            if computed_at is None and not note:
                note = ("the block carries no calculation time and no ingest run record exists for it; the stamp time is the stamping pass, not the computation (M513 backfill)")
        if backfill and not ran:                # the backfill needs evidence per block: a byte-identical sandbox replay, or the git attestation for the blocks that are not re-run
            if k in ATTESTED_BLOCKS or k in (attest or {}):
                evid = bool((attest or {}).get(k, {}).get("attested"))
            else:
                rb = ((replay or {}).get("blocks") or {}).get(k) or {}
                evid = bool(rb.get("identical")) and (replay or {}).get("masterMd5") == live_master
                if evid and raw_dep and deps.get(k, {}).get("sidecar") and rb.get("rawIdentityEvidence", {}).get("matches"):
                    raw_hash, raw_src = live_manifest, "sandbox / read-only replay at M518: the block is reproduced from the tracked sidecar, and every sidecar row's raw sha256 equals the sha256 of the same canonical file in the live raw_manifest.json (analyses/M513_replay.json rawIdentityEvidence)"
                elif evid and raw_dep and not deps.get(k, {}).get("sidecar"):
                    raw_hash, raw_src = live_manifest, "replayed at M513 in a sandbox: the producer reproduces the block byte-for-byte on the live raw_manifest.json (analyses/M513_replay.json)"
            if not evid:
                report[k] = {"skipped": "no replay / attestation evidence for this block; stamp left as it was"}
                continue
        ident = SC.identity(d, live_master, cfg, root, raw_hash, raw_src)
        new, appended = SC.derive_stamp(s, ident, milestone, "identity values changed (master, raw manifest, config section or input file)" , now_iso)
        new["computedAt"], new["computedAtNote"] = computed_at, note
        if note is None:
            new.pop("computedAtNote", None)
        if new.get("computedAt") is None and not new.get("computedAtNote"):
            new["computedAtNote"] = "calculation time not recorded"
        stamps[k] = new
        report[k] = {"lineageAppended": appended, "rawIdentity": ("written" if (raw_dep and raw_hash) else ("absent" if raw_dep else "not a dependency")), "ran": ran}
    return stamps, report


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    backfill, dry = "--backfill" in argv, "--dry-run" in argv
    ms = _arg(argv, "--milestone", "M513")
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, "r", encoding="utf-8", newline="").read()
    A = json.loads(raw)
    cfg = json.load(open(os.path.join(ROOT, "summary_config.json"), encoding="utf-8"))
    deps = SC.load_deps()
    live_master = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    live_manifest = json.load(open(os.path.join(ROOT, "raw_manifest.json"), encoding="utf-8")).get("corpusHash")
    attest = json.load(open(ATTEST, encoding="utf-8")) if os.path.exists(ATTEST) else {}
    replay = json.load(open(REPLAY, encoding="utf-8")) if os.path.exists(REPLAY) else {}
    new, report = derive_all(A, cfg, deps, live_master, live_manifest, os.environ, ROOT, backfill, attest, ms, replay)
    B = copy.deepcopy(A)
    B["_artifactStamps"] = new
    assert {k: v for k, v in A.items() if k != "_artifactStamps"} == {k: v for k, v in B.items() if k != "_artifactStamps"}, "wrote outside /_artifactStamps"
    assert all(new[k] == A["_artifactStamps"][k] for k in new if k not in deps), "touched an undeclared stamp"
    changed = sorted(k for k in deps if k in new and new[k] != A["_artifactStamps"][k])
    print(json.dumps({"declared": len(deps), "changed": changed, "report": report}, indent=1))
    if not dry and changed:
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
