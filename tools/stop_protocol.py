#!/usr/bin/env python3
"""M610b (spec analyses/M610_spec.md Rev 1, B1 + B2 only; chain promotion B3 is M610d and is NOT here): stop records and the collect pass.

A stage tool that would stop on a gate that needs a ruling (an acknowledgeable escalation) asks `try_collect(...)` right before its stop. Outside a collect pass the answer is
always False and the tool stops exactly as before (same message, same exit code). In a collect pass (`run_ingest.py --collect-stops`) the answer is True only when the runner's
token is valid: the tool then has written a stop record, writes NO splice for that stage (R7: ack content may shape output bytes) and exits 0, and the runner goes on to the next
stage, so all escalations of a batch are found in one pass. The runner always rolls the tree back at the end of a collect pass and never commits (R6).

Collect mode is a runner-issued token, not an XT_* variable (R6): the runner writes `runs/<ts>/collect.token` and passes the token and the run directory in INGEST_COLLECT_TOKEN /
INGEST_COLLECT_DIR to the stage processes only. `collect_active()` is true only while that file exists and holds the same token; it is removed when the pass ends, so a stale variable
cannot switch a later run into collect mode. `release_check.py` fails while a collect token file exists.

Record (B1): runs/<ts>/stops/<seq>__<stage>__<gate>.json = {stage, gate, kind: "escalation", facts (< 2 KB, copied from the tool's computed result), ackEnv, ackSchema, withheld,
artifacts, upstream: [recordSha256 of every earlier record of the pass (R8)], recordSha256}. A ruling "do not acknowledge" on a record voids every later record and draft brief.
Records are information for the Director; they are never an acknowledgement and are never read as one."""
import hashlib, json, os, shutil, sys, uuid

TOKEN_ENV = "INGEST_COLLECT_TOKEN"
DIR_ENV = "INGEST_COLLECT_DIR"
TOKEN_FILE = "collect.token"
MAX_FACTS_BYTES = 2048
PROVISIONAL_NOTE = ("PROVISIONAL, NEVER PUBLISHED. Produced by a collect pass (run_ingest.py --collect-stops): every stop was assumed to be acknowledged and its splice was withheld, "
                    "so facts of later stops are computed on a state that omits the earlier stops' effects. The real run after the rulings is authoritative.")


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def collect_active(env=None):
    env = os.environ if env is None else env
    tok, d = env.get(TOKEN_ENV), env.get(DIR_ENV)
    if not tok or not d:
        return False
    try:
        with open(os.path.join(d, TOKEN_FILE), encoding="utf-8") as f:
            return f.read().strip() == tok
    except OSError:
        return False


def issue_token(run_dir):
    tok = uuid.uuid4().hex
    with open(os.path.join(run_dir, TOKEN_FILE), "w", encoding="utf-8", newline="\n") as f:
        f.write(tok + "\n")
    return tok


def close_token(run_dir):
    try:
        os.remove(os.path.join(run_dir, TOKEN_FILE))
    except OSError:
        pass


def load_records(run_dir):
    d = os.path.join(run_dir, "stops")
    if not os.path.isdir(d):
        return []
    out = []
    for n in sorted(os.listdir(d)):
        if n.endswith(".json"):
            with open(os.path.join(d, n), encoding="utf-8") as f:
                out.append(json.load(f))
    return out


def build_record(stage, gate, facts, ack_env, ack_schema, withheld, artifacts, upstream):
    if len(json.dumps(facts, ensure_ascii=False).encode("utf-8")) >= MAX_FACTS_BYTES:
        raise ValueError("stop facts must be < %d bytes (copy the few values a Director needs, not the result)" % MAX_FACTS_BYTES)
    rec = {"stage": stage, "gate": gate, "kind": "escalation", "facts": facts, "ackEnv": list(ack_env) if isinstance(ack_env, (list, tuple)) else ack_env,
           "ackSchema": ack_schema, "withheld": sorted(withheld), "artifacts": sorted(artifacts), "upstream": list(upstream)}
    rec["recordSha256"] = _sha(rec)
    return rec


def record_stop(stage, gate, facts, ack_env, ack_schema=None, withheld=(), artifacts=(), env=None):
    """Write the stop record; None (and nothing written) outside a valid collect pass. `facts` may be a function: it is called only inside a valid pass."""
    env = os.environ if env is None else env
    if not collect_active(env):
        return None
    if callable(facts):                                    # Director R2: facts are built ONLY in a valid collect pass; the default stop path computes nothing extra
        facts = facts()
    run_dir = env[DIR_ENV]
    existing = load_records(run_dir)
    rec = build_record(stage, gate, facts, ack_env, ack_schema, withheld, artifacts, [r["recordSha256"] for r in existing])
    d = os.path.join(run_dir, "stops")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "%03d__%s__%s.json" % (len(existing) + 1, stage, gate)), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
    return rec


def try_collect(stage, gate, facts, ack_env, ack_schema=None, withheld=(), artifacts=(), env=None):
    """True iff a valid collect pass is running and the stop was recorded; the caller then exits 0 without splicing. False: the caller stops exactly as before."""
    return record_stop(stage, gate, facts, ack_env, ack_schema, withheld, artifacts, env) is not None


def check_ack_binding(record_sha256, ack):
    """For the later chain promotion (M610d) and for audit: an ack is bound to a stop record iff it carries that record's hash."""
    return isinstance(ack, dict) and ack.get("recordSha256") == record_sha256


def finish_pass(run_dir, root):
    """Runner side, end of a collect pass (before the rollback): provisional artifacts, stops.json, one draft brief per stop. Returns the summary dict."""
    recs = load_records(run_dir)
    prov = os.path.join(run_dir, "provisional")
    if recs:
        os.makedirs(prov, exist_ok=True)
        with open(os.path.join(prov, "PROVISIONAL_NEVER_PUBLISHED.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(PROVISIONAL_NOTE + "\n")
    for r in recs:
        for rel in r.get("artifacts", []):
            src = os.path.join(root, rel)
            if os.path.isfile(src):
                dst = os.path.join(prov, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
    bd = os.path.join(run_dir, "briefs")
    for i, r in enumerate(recs, 1):
        os.makedirs(bd, exist_ok=True)
        brief = {"order": i, "of": len(recs), "record": r, "provisional": PROVISIONAL_NOTE if i > 1 else "first stop of the pass: facts computed on the pre-batch state",
                 "rule": "rulings are issued in stage order; 'do not acknowledge' on this record voids every later record and brief; a batch brief never replaces the per-stop ruling or the blind audit"}
        with open(os.path.join(bd, "%03d_%s.json" % (i, r["stage"])), "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(brief, indent=1, ensure_ascii=False) + "\n")
    summary = {"count": len(recs), "firstStopStage": recs[0]["stage"] if recs else None, "stages": [r["stage"] for r in recs], "recordSha256": [r["recordSha256"] for r in recs]}
    with open(os.path.join(run_dir, "stops.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(dict(summary, records=recs), indent=1, ensure_ascii=False) + "\n")
    return summary


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
