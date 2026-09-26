#!/usr/bin/env python3
"""verify_provenance.py -- independent check of raw_manifest.json (audit BLOCK #2 / M268).
Recomputes sha256 + normHash + bytes + rows of every canonical raw file on disk and compares
with the manifest; recomputes corpusHash / contentHash. Read-only.
Usage: python3 verify_provenance.py MANIFEST.json RAW_DIR OUT.json"""
import sys, os, json, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus_manifest as cm
man = json.load(open(sys.argv[1])); raw = sys.argv[2]
canon = [r for r in man['files'] if r['role'] == 'canonical']
res = dict(nManifestCanonical=len(canon), missingOnDisk=[], shaMismatch=[], normMismatch=[],
           bytesMismatch=[], rowsMismatch=[])
sh, nh = [], []
for r in canon:
    p = os.path.join(raw, r['raw_name'])
    if not os.path.exists(p):
        res['missingOnDisk'].append(r['raw_name']); continue
    s, b, n = cm._sha256_and_rows(p); h = cm._norm_hash(p)
    sh.append(s); nh.append(h)
    if s != r['sha256']: res['shaMismatch'].append(r['raw_name'])
    if h != r['normHash']: res['normMismatch'].append(r['raw_name'])
    if b != r['bytes']: res['bytesMismatch'].append(r['raw_name'])
    if n != r['rows']: res['rowsMismatch'].append(r['raw_name'])
ondisk = sorted(f for f in os.listdir(raw) if f.endswith('.csv'))
res['nOnDiskCsv'] = len(ondisk)
res['onDiskNotInManifest'] = sorted(set(ondisk) - {r['raw_name'] for r in canon})
res['nShaMatch'] = len(sh) - len(res['shaMismatch'])
res['nNormMatch'] = len(nh) - len(res['normMismatch'])
res['corpusHashRecomputed'] = hashlib.sha256(''.join(sorted(sh)).encode()).hexdigest()
res['contentHashRecomputed'] = hashlib.sha256(''.join(sorted(nh)).encode()).hexdigest()
res['corpusHashManifest'] = man['corpusHash']; res['contentHashManifest'] = man['contentHash']
res['corpusHashMatch'] = res['corpusHashRecomputed'] == man['corpusHash']
res['contentHashMatch'] = res['contentHashRecomputed'] == man['contentHash']
# manifest self-consistency
res['manifestSelfCorpus'] = hashlib.sha256(''.join(sorted(r['sha256'] for r in canon)).encode()).hexdigest() == man['corpusHash']
res['manifestSelfContent'] = hashlib.sha256(''.join(sorted(r['normHash'] for r in canon)).encode()).hexdigest() == man['contentHash']
json.dump(res, open(sys.argv[3], 'w'), indent=1)
print(json.dumps({k: (v if not isinstance(v, list) else (len(v), v[:5])) for k, v in res.items()}, indent=1))
