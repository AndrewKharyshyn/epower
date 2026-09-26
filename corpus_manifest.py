"""corpus_manifest.py  (M106)

Corrected release-manifest generator.

Audit P0-04: the previous manifest logic iterated over drive_master filenames
only, so raw files that are NOT in the master (comparison-only D captures, the
segregated e-4ORCE cross-check file, or any stray orphan) were structurally
invisible and the manifest reported oneToOne=true regardless. This module
instead ENUMERATES THE RAW DIRECTORY and diffs against the master, then records
every non-canonical file as a typed, machine-readable exclusion.

Classification (applied to the raw filename BEFORE canonicalization, because the
canonicalizer would otherwise collapse '..._B_D_comparison.csv' onto a canonical
'YYYYMMDD_HHMMSS.csv' name and hide it):

    role = 'canonical'        -> a primary-corpus drive; must appear in master 1:1
    role = 'comparison_only'  -> D-mode B/D capture, excluded by design (mode='D')
    role = 'auxiliary'        -> segregated cross-vehicle rail (e-4ORCE); never
                                 admissible to the primary corpus
    role = 'orphan'           -> a 2026*.csv on disk with no master row (defect)
    role = 'missing'          -> a master row with no raw file on disk (defect)

Each record carries the release-manifest schema the audit asked for:
record_id, raw_name, sha256, bytes, rows, role, mode, exclusion_reason.
"""
import os, re, glob, json, hashlib, datetime as _dt

_DATE_DIGITS_RE = re.compile(
    r'(\d{4})\D?(\d{2})\D?(\d{2})\D+(\d{2})\D?(\d{2})\D?(\d{2})')

def _canonical(fn):
    base = os.path.basename(fn)
    m = _DATE_DIGITS_RE.search(base)
    if not m:
        return base
    y, mo, d, hh, mm, ss = m.groups()
    return f"{y}{mo}{d}_{hh}{mm}{ss}.csv"

def _sha256_and_rows(path, _buf=1 << 20):
    """Stream the file once: sha256 over raw bytes + data-row count
    (newlines minus the header, floored at 0)."""
    h = hashlib.sha256()
    nl = 0
    size = 0
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(_buf)
            if not chunk:
                break
            h.update(chunk)
            nl += chunk.count(b'\n')
            size += len(chunk)
    # trailing line without newline -> add 1; then subtract header row
    with open(path, 'rb') as f:
        f.seek(max(0, size - 1))
        last = f.read(1)
    if size and last != b'\n':
        nl += 1
    rows = max(nl - 1, 0)
    return h.hexdigest(), size, rows


def _norm_hash(path):
    """Serialization-invariant content hash (M268, audit BLOCK #2).

    sha256 over a canonicalised view of the file so it survives the transfer
    re-serialisations that break the raw-byte sha256 (BOM insertion, CRLF/CR
    line endings, trailing per-line whitespace, trailing blank lines) while
    still detecting any real change to a cell value. Two files that carry the
    same tabular DATA hash identically here even if one was re-encoded in
    transit -- which is exactly the audit's observation (all 421 row counts
    matched; only 98/421 raw-byte sha256 did)."""
    with open(path, 'rb') as f:
        b = f.read()
    if b.startswith(b'\xef\xbb\xbf'):        # strip UTF-8 BOM
        b = b[3:]
    b = b.replace(b'\r\n', b'\n').replace(b'\r', b'\n')   # normalise EOL
    lines = [ln.rstrip() for ln in b.split(b'\n')]           # strip trailing ws
    while lines and lines[-1] == b'':                          # drop trailing blanks
        lines.pop()
    norm = b'\n'.join(lines)
    return hashlib.sha256(norm).hexdigest()

def _classify(base):
    """Return (role, mode, reason) from the raw filename, pre-canonicalization."""
    low = base.lower()
    if '_comparison' in low:                      # 20260730_220651_B_D_comparison.csv
        return 'comparison_only', 'D', (
            'D-mode B/D comparison capture; excluded from the primary '
            'corpus by standing rule (filename convention + code guard). D/B '
            'investigation discontinued 2026-08-09; retained on disk, not analysed.')
    # M207 (F-05): e4orce_master.csv / e4orce_ambient.csv are DERIVED aggregate
    # artefacts produced by ingest_e4orce.py, NOT raw auxiliary captures. The
    # prior startswith('e4orce') branch mislabelled them 'auxiliary', inflating
    # typedExclusions from the true 9 e-4ORCE captures to 11.
    if low in ('e4orce_master.csv', 'e4orce_ambient.csv'):
        return 'derived', 'unknown', (
            'e-4ORCE aggregate artefact (ingest_e4orce.py output), not a raw '
            'capture and not a corpus member; excluded from typedExclusions.')
    if low.startswith('e4orce'):                  # e4ORCE_20260807_073756.csv
        return 'auxiliary', 'unknown', (
            'e-4ORCE AWD cross-check rail; segregated from the primary corpus. '
            'Only CAP_KWH-invariant quantities are admissible for cross-vehicle '
            'comparison. Ingested via ingest_e4orce.py into a separate master.')
    return 'canonical', 'B', ''                   # e-POWER FWD default duty is B/eco

def build(raw_dir, master_csv=None, out_path=None, parent_snapshot=None,
          pattern='*.csv', master_df=None):
    import pandas as pd
    dm = master_df if master_df is not None else pd.read_csv(master_csv)
    # 2026-09-16 finding (recurrence of the M252 dash-timestamp defect):
    # drive_master.csv stores the raw AS-INGESTED filename (dash format for
    # the 2026-09-11-onward archive-native exports, e.g.
    # '2026-09-11_07-42-27.csv'), but on-disk files are matched here via
    # _canonical(base), which always normalizes to 'YYYYMMDD_HHMMSS.csv'.
    # Comparing a normalized on-disk id against an UNnormalized master set
    # means every dash-format canonical file matches nothing -> reported as
    # both 'orphan' (on disk) and 'missing' (in master) simultaneously, for
    # every dash-named drive (43/43 here: the 7 Sep-11 drives + all 36 of
    # the 2026-09-12..16 batch). Normalize both sides through the same
    # _canonical() so matching is apples-to-apples again.
    master_files = set(_canonical(f) for f in dm['file'].astype(str))

    on_disk = sorted(glob.glob(os.path.join(raw_dir, pattern)))
    records = []
    canon_seen = {}          # canonical -> record (canonical role only)

    for path in on_disk:
        base = os.path.basename(path)
        # Only date-stamped drives or the e-4ORCE rail are raw inputs;
        # skip pipeline artefacts (drive_master.csv, ledgers, masters).
        if not (_DATE_DIGITS_RE.search(base) or base.lower().startswith('e4orce')):
            continue
        role, mode, reason = _classify(base)
        canon = _canonical(base) if role in ('canonical',) else None
        sha, nbytes, rows = _sha256_and_rows(path)
        norm_h = _norm_hash(path)
        rec = {
            'record_id': canon or base,
            'raw_name': base,
            'canonical': canon,
            'sha256': sha,
            'normHash': norm_h,
            'bytes': nbytes,
            'rows': rows,
            'role': role,
            'mode': mode,
            'exclusion_reason': reason,
        }
        if role == 'canonical':
            if canon not in master_files:
                rec['role'] = 'orphan'
                rec['exclusion_reason'] = (
                    'On disk as a 2026*.csv but no matching drive_master row.')
            canon_seen[canon] = rec
        records.append(rec)

    # master rows with no raw file on disk
    missing = sorted(master_files - set(canon_seen))
    for mf in missing:
        records.append({
            'record_id': mf, 'raw_name': None, 'canonical': mf,
            'sha256': None, 'bytes': None, 'rows': None,
            'role': 'missing', 'mode': None,
            'exclusion_reason': 'drive_master row with no raw file on disk.'})

    # corpus hash = sha256 over the sorted canonical shas (order-stable)
    canon_recs = [r for r in records if r['role'] == 'canonical']
    corpus_hash = hashlib.sha256(
        ''.join(sorted(r['sha256'] for r in canon_recs)).encode()).hexdigest()
    content_hash = hashlib.sha256(
        ''.join(sorted(r['normHash'] for r in canon_recs)).encode()).hexdigest()

    roles = {}
    for r in records:
        roles[r['role']] = roles.get(r['role'], 0) + 1

    orphans = [r['raw_name'] for r in records if r['role'] == 'orphan']
    integrity = {
        'nCanonical': roles.get('canonical', 0),
        'nComparisonOnly': roles.get('comparison_only', 0),
        'nAuxiliary': roles.get('auxiliary', 0),
        'nOrphan': roles.get('orphan', 0),
        'nMissing': roles.get('missing', 0),
        'nMasterRows': int(len(dm)),
        'nFilesOnDisk': len(on_disk),
        'oneToOneCanonical': roles.get('orphan', 0) == 0 and roles.get('missing', 0) == 0,
        'clean': roles.get('orphan', 0) == 0 and roles.get('missing', 0) == 0,
    }
    snap = _dt.datetime.now(_dt.timezone.utc)
    manifest = {
        'snapshotId': f"{snap.strftime('%Y-%m-%d')}_{corpus_hash[:16]}",
        'generatedUtc': snap.isoformat(),
        'parentSnapshot': parent_snapshot,
        'corpusHash': corpus_hash,
        'contentHash': content_hash,
        'contentHashNote': ('serialization-invariant sha256 over sorted per-file normHash; '
                            'survives BOM/CRLF/whitespace re-encoding in transit, unlike corpusHash (raw bytes). '
                            'A reviewer whose transferred bundle fails the byte sha256 can recompute normHash to confirm data identity.'),
        'roles': roles,
        'integrity': integrity,
        'orphanDetail': orphans,
        'missingDetail': missing,
        'typedExclusions': [
            {k: r[k] for k in ('raw_name', 'role', 'mode', 'sha256', 'normHash', 'rows',
                               'exclusion_reason')}
            for r in records if r['role'] in ('comparison_only', 'auxiliary')],
        'appendOnly': True,
        'note': ('Raw directory is ENUMERATED (M106), then diffed against '
                 'drive_master. Non-canonical files are typed, not hidden. '
                 f'oneToOneCanonical covers the {roles.get("canonical", 0)} '
                 'primary drives only; comparison-only and auxiliary files are '
                 'intentional, documented exclusions.'),
        'files': records,
    }
    if out_path:
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=1, ensure_ascii=False)
    return manifest


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw-dir', default='.')
    ap.add_argument('--master', default='drive_master.csv')
    ap.add_argument('--out', default='raw_manifest.json')
    ap.add_argument('--parent', default=None)
    a = ap.parse_args()
    m = build(a.raw_dir, a.master, a.out, a.parent)
    print(json.dumps(m['integrity'], indent=1))
    print('snapshotId:', m['snapshotId'])
