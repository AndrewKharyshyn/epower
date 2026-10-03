"""M349 Rev 2 item 5: read-only inventory of scripts that share the `float(master.get('I_offset_A_applied') or 0.0)` NaN-propagating pattern.
For each: does the pattern exist, does its output file exist/is tracked, does the output mention either affected drive, is the output consumed by the payload.
Writes analyses/M349_inventory.json. No fixes (follow-up reusing fuel_recon.resolve_offset)."""
import json, os, re, subprocess
DR = ['20260813_145651', '20260813_150341']
SCRIPTS = {'speed_split.py': 'speed_split.json', 'crossval_gtr.py': 'crossval_gtr_out.json', 'sensitivity_gtr.py': 'sensitivity_gtr_out.json',
           'simultaneity_gtr.py': 'simultaneity_gtr_out.json', 'tools/gtr_closure_diag.py': 'analyses/M336_closure_diag.json'}
arr = open('summary_arrays.json', encoding='utf-8').read()
out = {}
for sc, of in SCRIPTS.items():
    src = open(sc, encoding='utf-8').read()
    r = {'script': sc, 'output': of, 'pattern': bool(re.search(r"I_offset_A_applied['\"]?\)?,? ?(0\.0)?\)? or 0\.0|\) or 0\.0", src)),
         'skipsNaNOffsetExplicitly': 'isna(m.get("I_offset_A_applied"))' in src or "isna(m.get('I_offset_A_applied'))" in src}
    r['outputExists'] = os.path.isfile(of)
    r['outputTracked'] = bool(subprocess.run(['git', 'ls-files', '--error-unmatch', of], capture_output=True).returncode == 0) if r['outputExists'] else False
    txt = open(of, encoding='utf-8', errors='replace').read() if r['outputExists'] else ''
    r['outputMentionsAffectedDrives'] = {d: (d in txt) for d in DR}
    key = os.path.splitext(os.path.basename(of))[0]
    r['payloadCitesOutputFile'] = (os.path.basename(of) in arr)
    out[sc] = r
G = json.loads(arr)['generatorTractionRecon']
for sc, k in (('speed_split.py', 'speedSplit'), ('crossval_gtr.py', 'crossval'), ('sensitivity_gtr.py', 'sensitivity'), ('simultaneity_gtr.py', 'simultaneity')):
    out[sc]['payloadBlockKey'] = 'generatorTractionRecon.' + k; out[sc]['payloadBlockPresent'] = k in G
    out[sc]['status'] = 'payload block carried forward from an earlier run; the script output file is not in the repo, so whether the block includes the two drives cannot be established from the repo (follow-up: rerun with resolve_offset)'
out['_note'] = 'Inventory only. A script whose output does not mention a drive may still include it in an aggregate; a follow-up applies resolve_offset and reruns each. speed_split block in the payload is carried forward (stale) and was not touched.'
json.dump(out, open('analyses/M349_inventory.json', 'w', encoding='utf-8', newline='\n'), indent=1)
for k, v in out.items():
    if k != '_note': print(k, {x: v[x] for x in ('pattern', 'skipsNaNOffsetExplicitly', 'outputExists', 'outputTracked', 'outputMentionsAffectedDrives', 'payloadCitesOutputFile')})
