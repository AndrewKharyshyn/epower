"""M627 edit #3 (Director conditions): per-era 0.25 kW share and the 0.1 kW-grid file observation in the payload; belowCeiling with drives / days and a descriptive label; raw-file note."""
p = 'compute_summary_arrays.py'
s = open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in s[:5000] else '\n'


def N(t):
    return t.replace('\n', nl)


def rep(old, new):
    global s
    o, n = N(old), N(new)
    assert s.count(o) == 1, (old[:70], s.count(o))
    s = s.replace(o, n)


rep("_HDRM_GRID_KW = 0.05                   # converted samples are expected on a multiple of 0.05 kW (the 0.25 kW and the 0.1 kW grids both are)",
    "_HDRM_GRID_KW = 0.05                   # converted samples are expected on a multiple of 0.05 kW (the 0.25 kW and the 0.1 kW grids both are)\n_HDRM_QUARTER_KW = 0.25                # the usual grid (255 x 0.25 kW); files with samples off it are reported as a data-quality observation")
rep("        u = {'era': era, 'nSamples': int(len(pp)), 'nOnGrid': _hdrm_on_grid(pp['pp_kw']),",
    "        u = {'era': era, 'nSamples': int(len(pp)), 'nOnGrid': _hdrm_on_grid(pp['pp_kw']), 'nOnQuarterGrid': _hdrm_on_grid(pp['pp_kw'], grid=_HDRM_QUARTER_KW),")
# summary: accumulate per era the quarter-grid counts and the files off it
rep("            d = unit.setdefault(u['era'], {'nSamples': 0, 'nOnGrid': 0, 'nOnGridMechanical': 0,",
    "            d = unit.setdefault(u['era'], {'nSamples': 0, 'nOnGrid': 0, 'nOnQuarter': 0, 'filesOffQuarter': set(), 'nOnGridMechanical': 0,")
rep("            d['nOnGrid'] += u['nOnGrid']\n", "            d['nOnGrid'] += u['nOnGrid']\n            d['nOnQuarter'] += u['nOnQuarterGrid']\n            if u['nOnQuarterGrid'] < u['nSamples']:\n                d['filesOffQuarter'].add((fn, day))\n")
rep("        g = {'nSamples': int(d['nSamples']), 'nOnGrid': int(d['nOnGrid']), 'share': round(share, 6) if share is not None else None}",
    "        offd = sorted(dd for _, dd in d['filesOffQuarter'] if dd)\n"
    "        g = {'nSamples': int(d['nSamples']), 'nOnGrid': int(d['nOnGrid']), 'share': round(share, 6) if share is not None else None,\n"
    "             'shareOnQuarterKwGrid': round(d['nOnQuarter'] / d['nSamples'], 6) if d['nSamples'] else None,\n"
    "             'filesOffQuarterKwGrid': int(len({f for f, _ in d['filesOffQuarter']})), 'offQuarterDateFrom': offd[0] if offd else None, 'offQuarterDateTo': offd[-1] if offd else None}")
# belowCeiling: drives / days and a descriptive label
rep("    o['belowCeiling'] = ({'nEvents': int(len(below)), 'median': round(float(np.median([r['util'] for r in below])), 3),\n                          'p95': round(float(np.percentile([r['util'] for r in below], 95)), 3)} if below else None)",
    "    o['belowCeiling'] = ({'nEvents': int(len(below)), 'nDrives': int(len({r['file'] for r in below})), 'nDays': int(len({r['day'] for r in below})),\n                          'median': round(float(np.median([r['util'] for r in below])), 3),\n                          'p95': round(float(np.percentile([r['util'] for r in below], 95)), 3),\n                          'label': 'conditional on the reported limit being below the ceiling; descriptive, not a censoring correction'} if below else None)")
rep("           'drivesWithoutChannel': int(n_scanned - n_channel), 'denominator': 'drive_master rows (the corpus)', 'selection': 'header (a possible-power column of either name); not by date',",
    "           'drivesWithoutChannel': int(n_scanned - n_channel), 'denominator': 'drive_master rows (the corpus)', 'selection': 'header (a possible-power column of either name); not by date',\n           'rawFilesNote': 'counts refer to the drive_master rows; raw files outside the corpus (auxiliary and comparison-only) are not scanned',")
open(p, 'w', encoding='utf-8', newline='').write(s)
print('ok')
