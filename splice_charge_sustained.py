#!/usr/bin/env python3
"""M283 splice — add the sustained-CHARGE record, de-stale the single-sample
charge note. Isolation-diffed: only `records` (1 row added + 1 note edited) and
`_artifactStamps.records.generatedAt` change."""
import json, copy, datetime

SRC = 'summary_arrays.json'
d = json.load(open(SRC))
before = copy.deepcopy(d)

recs = d['records']
# locate the single-sample charge record
ci = next(i for i, r in enumerate(recs) if r['metric'] == 'Peak charge current')

# --- 1. new sustained-charge record (mirrors the sustained-discharge record) ---
new_rec = {
    "metric": "Peak charge current — sustained (rolling 1/5/10/30 s)",
    "value": "213 \u2192 137 A",
    "note": (
        "Rolling-mean sustained charge-current peaks across the 396 "
        "current-carrying drives, on the same |I|<900 A artifact-gated 1 Hz "
        "basis as the master's peak-current channel (see the note above): "
        "213.0 A (1 s, 36.4C) \u00b7 194.6 A (5 s, 33.5C) \u00b7 167.2 A "
        "(10 s, 28.8C) \u00b7 137.0 A (30 s, 23.5C). In contrast to the "
        "discharge side (205 \u2192 83 A, decaying to 40% of the instantaneous "
        "peak over 30 s), the pack SUSTAINS charge far better \u2014 137 A / "
        "23.5C at 30 s is 64% of its 1 s peak \u2014 consistent with charge "
        "being fed by comparatively steady regen and generator-surplus banking "
        "rather than the brief launch transients that set the discharge peaks. "
        "The artifact gate is load-bearing here: an UNgated raw pass reports "
        "~1050 A on 9 drives at the 1 s and 5 s windows (an impossible >179C "
        "for charge acceptance \u2014 1\u20134 single-sample logging-artifact "
        "spikes per drive), which the |I|<900 A per-sample gate removes "
        "cleanly (no real gated sample lies between 213 A and the ~1050 A "
        "artifact cluster, so the threshold is uncritical); those 9 drives' "
        "true gated charge peaks are all \u2264188 A and set no record \u2014 a "
        "direct vindication of the audit's \u201csingle-sample maxima are often "
        "artifacts\u201d point. Amperes are measured; C-rate is derived from the "
        "assumed CAP_KWH = 2.1 kWh (unverified). 1 s set on Jun19, 5/10 s on "
        "Aug30, 30 s on Jun13."
    ),
}
recs.insert(ci + 1, new_rec)

# --- 2. de-stale the single-sample charge note (drop the 'pending' deferral) ---
old_tail = (
    " (Sustained rolling-window charge peaks are not reported here: an "
    "unfiltered raw pass surfaces physically-impossible >1000 A charge spikes "
    "on a handful of drives \u2014 logging artifacts \u2014 so a defensible "
    "sustained charge peak needs the pipeline's artifact gating; pending.)"
)
new_tail = (
    " Sustained rolling-window charge peaks are now reported in the record "
    "below (213 \u2192 137 A over 1\u201330 s), computed on the pipeline's "
    "|I|<900 A artifact-gated 1 Hz basis \u2014 the gate being what makes them "
    "defensible: an unfiltered raw pass surfaces physically-impossible >1000 A "
    "charge spikes on 9 drives (single-sample logging artifacts), removed here."
)
r9 = recs[ci]
assert old_tail in r9['note'], 'single-sample charge deferral tail not found verbatim'
r9['note'] = r9['note'].replace(old_tail, new_tail)

# --- 3. provenance: bump the records stamp generatedAt (content changed) ---
d['_artifactStamps']['records']['generatedAt'] = \
    datetime.datetime.now(datetime.timezone.utc).isoformat()

# --- isolation diff ---
def flat(o, p=''):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flat(v, p + '/' + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from flat(v, p + '[%d]' % i)
    else:
        yield p, o

fb = dict(flat(before)); fa = dict(flat(d))
keys = set(fb) | set(fa)
changed = [k for k in keys if fb.get(k) != fa.get(k)]
top = sorted({k.split('[')[0].split('/')[1] for k in changed})
print('changed leaves:', len(changed))
print('changed top-level keys:', top)
# every changed leaf must be under /records or /_artifactStamps/records/generatedAt
bad = [k for k in changed
       if not (k.startswith('/records') or k == '/_artifactStamps/records/generatedAt')]
print('out-of-scope changed leaves:', bad)
assert not bad, 'isolation violation'
assert set(top) <= {'records', '_artifactStamps'}, top

json.dump(d, open(SRC, 'w'), ensure_ascii=False, indent=1)
print('OK — records %d -> %d ; wrote %s' % (len(before['records']), len(recs), SRC))
