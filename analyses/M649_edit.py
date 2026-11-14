"""M649 (P-03) edits. ASCII only."""
def rep(t, o, n):
    assert t.count(o) == 1, (o[:80], t.count(o))
    return t.replace(o, n)

# ---- m321: acknowledgement stop right after update
p = 'tools/m321_ladder_monitor.py'
t = open(p, encoding='utf-8', newline='').read(); nl = '\r\n' if '\r\n' in t[:3000] else '\n'; S = t.replace('\r\n', '\n')
S = rep(S, '''def gate(arrays, root=ROOT):
    """-> (fails, warns). Spec item 7."""''', '''def ack_failure(mon, root=ROOT):
    """M649 (P-03): the acknowledgement part of the gate alone -> a failure text, or None. Used by `update` so a W2/W3 (new-spec trigger) without a valid
    acknowledgement stops the ingestion at the ladder-monitor stage instead of at the final release gate. Same predicate as gate()."""
    if not mon or mon.get("status") != "warn-newspec":
        return None
    path = os.path.join(root, "analyses", "M321_acknowledgements.json")
    acks = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    if any(ack_valid(a, mon, root) for a in acks):
        return None
    return ("M321: W2/W3 active (%s) without a valid acknowledgement record for warningSetHash %s%s" % ("; ".join(mon.get("warnings", [])), str(mon.get("warningSetHash"))[:12],
            " [STOP RULE: the ref must be a reviewed analyses/M###_spec.md]" if stop_rule_sides(mon) else ""))


def gate(arrays, root=ROOT):
    """-> (fails, warns). Spec item 7."""''')
S = rep(S, '''                      "arrays_keys_changed_vs_HEAD": diff, "socHysteresisV2_keys_changed_vs_HEAD": sub}))
''', '''                      "arrays_keys_changed_vs_HEAD": diff, "socHysteresisV2_keys_changed_vs_HEAD": sub}))
    bad = ack_failure(block)                    # M649 (P-03): stop here, not only at the release gate; the monitor block stays written (report-only), the ingestion halts
    if bad:
        print("STOP " + bad, file=sys.stderr)
        sys.exit(1)
''')
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', nl))

# ---- ingest_core: keep the arrays as a candidate when the estimator gate stops
p = 'tools/ingest_core.py'
t = open(p, encoding='utf-8', newline='').read(); nl = '\r\n' if '\r\n' in t[:3000] else '\n'; S = t.replace('\r\n', '\n')
S = rep(S, '''ACK = {"reason": None, "recal": None}
''', '''ACK = {"reason": None, "recal": None}


def estimator_gate_keep(prev, arrays, ack=None, run_dir=None):
    """M649 (P-03): estimator_gate, but when it stops the freshly computed arrays are written to <run_dir>/candidate_summary_arrays.json first (NOT canonical;
    summary_arrays.json is restored from the backup by main), so a stop on an unacknowledged estimator change no longer discards ~10 minutes of computation
    and the change can be reviewed on the candidate. The Gate is re-raised unchanged."""
    try:
        return estimator_gate(prev, arrays, ack)
    except Gate:
        if run_dir and os.path.isdir(run_dir):
            write_json(os.path.join(run_dir, "candidate_summary_arrays.json"), arrays)
        raise
''')
S = rep(S, 'EST_CHANGES[:] = estimator_gate(prev, arrays, ACK["reason"])', 'EST_CHANGES[:] = estimator_gate_keep(prev, arrays, ACK["reason"], RUN["dir"])')
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', nl))
print('ok')
