"""M351: script-checked triage of the pulled-out M326 rows still open (identifier present in code/payload? -> applicable / obsolete).
Writes analyses/M351_triage.tsv. A row is OBSOLETE only if its named identifier no longer exists anywhere; otherwise applicable (group per spec)."""
import re
FILES = ['xtrail_summary.jsx', 'compute_summary_arrays.py', 'seasonal_core.py', 'compute_seasonal.py', 'build_assumptions_registry.py',
         'tools/build_ambient_table.py', 'records_resistance.py', 'degradation_trends.py', 'summary_arrays.json']
TXT = {f: open(f, encoding='utf-8', errors='replace').read() for f in FILES}
ROWS = [  # id, group, identifier regex the ledger action names, short action
 ('p22.12', 'A', r'clusterRobustOLS', 'label the published interval cluster-robust normal (z)'),
 ('p23.16', 'A', r'riskColdEngineBattery', 'p<0.001 through one formatter'),
 ('F31.r1', 'A', r'vreg_R_pack_mohm', 'relabel IID residual-model reference distribution; drop noise verdict; day dependence'),
 ('F22.r1', 'obsolete?', r'ciHalfWidthMohmPerMo', 'rename ciHalfWidthMohmPerMo (builder+jsx)'),
 ('F13.3', 'B', r'uncertaintyClass', 'expose ambient source counts per cohort'),
 ('p21.5', 'B', r'endpoint|time-weighted', 'label ambient chart definition (endpoint-pair vs time-weighted)'),
 ('p21.6', 'B', r'ambient_time_mean_kind|vehicle_sensor', 'show ambient_time_mean_kind; relabel vehicle_sensor'),
 ('D-S7', 'B', r'great majority', 'fix "no fuel-rate PID on the great majority" (263/489)'),
 ('p17.13', 'B', r'great majority|MAF handful', 'script-generate fuel coverage'),
 ('F18.r1', 'C', r'"klass"', 'per-constant class measured/external/assumed'),
 ('p15.4', 'C', r'usedBy', 'registry usedBy gross/GTC -> net draw; +0.34% variant'),
 ('Cs-1', 'D', r'odometer', 'split logged km from paired/EV-eligible; odometer source date'),
 ('Cs-21', 'D', r'maskLabel|phase', 'per-phase mask labels; signed net and positive energies'),
 ('F08.r1', 'D', r'inferenceAvailable', 'observed/eligible/inferenceAvailable per cohort'),
 ('B-HandoffSequence', 'D', r'[Hh]andoff', 'marginal medians are not one sequence; timing-resolution band'),
 ('p25.2', 'D', r'cannot identify', 'script-bound "What the data cannot identify" box'),
 ('F21.r1', 'D', r'C-rate', 'A and kW primary axes; C-rate secondary'),
 ('p16.7', 'D', r'toFixed|significant', 'sensible significant figures in display'),
 ('D-13', 'D', r'sign crossings', 'rename engine-start proxy (sign crossings) -> reversals/100 km (check M344 relabel)'),
]
ADD = {'F08.r1', 'p25.2', 'F13.3'}
REMOVE = {'F22.r1', 'D-S7', 'p17.13', 'D-13'}
out = ['id\tgroup\tidentifier\tfoundIn\tstatus\taction']
for i, g, pat, act in ROWS:
    found = {f: len(re.findall(pat, t)) for f, t in TXT.items() if re.search(pat, t)}
    if i in ADD:      # the identifier is what the row asks to ADD: absence means pending, presence means (partly) done
        st = 'pending (identifier to add is absent)' if not found else 'check (identifier present: partly done?)'
    elif i in REMOVE: # the identifier is what the row asks to remove/rename: absence means already done or obsolete
        st = 'obsolete or already done (identifier absent)' if not found else 'applicable'
    else:
        st = 'applicable' if found else 'check (identifier absent)'
    out.append('\t'.join([i, g, pat, ';'.join(f'{k}:{v}' for k, v in found.items()) or '-', st, act]))
open('analyses/M351_triage.tsv', 'w', encoding='utf-8', newline='\n').write('\n'.join(out) + '\n')
print('\n'.join(l.split('\t')[0] + ' ' + l.split('\t')[4] for l in out[1:]))
