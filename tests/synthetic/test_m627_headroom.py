"""M627 known-answer tests (implements analyses/M626_spec.md Rev 1 / 1.1, section 3): loader names, metric conversion, unit gate, ceiling flag, per-era statistics."""
import io, os, sys
import numpy as np, pandas as pd
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
import compute_summary_arrays as C

I_COL, V_COL = '[BMS] HV Battery Current (A)', '[BMS] HV Battery voltage (V)'
HP_IN, HP_OUT = C._HDRM_PP_COLS['hp']
KW_IN, KW_OUT = C._HDRM_PP_COLS['kW']

# conversion constants: metric hp gives 63.75 kW from the logged ceiling, the mechanical factor does not
assert abs(86.6758781031239 * C._HDRM_HP_TO_KW - 63.75) < 1e-4
assert abs(86.6758781031239 * C._HDRM_HP_MECH_TO_KW - 63.75) > 0.8


def make_csv(cols, n=200, charge_kw=20.0, discharge_kw=30.0):
    """n rows at 1 s: first half charging (I < 0 raw is charge-positive after M11? the loader treats P_kw > 0.1 as charge), second half discharging; V = 300 V."""
    t = pd.date_range('2026-10-05 10:00:00', periods=n, freq='1s')
    half = n // 2
    P = np.r_[np.full(half, charge_kw), np.full(n - half, -discharge_kw)]
    df = pd.DataFrame({'time': t.strftime('%H:%M:%S.%f').str[:-3], I_COL: P * 1000.0 / 300.0, V_COL: 300.0})
    for name, vals in cols.items():
        df[name] = vals
    return df.to_csv(index=False).encode('utf-8')


def run(cols):
    return C._headroom_utilization_events(make_csv(cols), 'synthetic.csv')


# (kW)-only file: era kW, utilisation exact: charge 20 kW / 40 kW limit = 0.5; discharge 30 / 60 = 0.5
cols = {KW_IN: np.full(200, 40.0), KW_OUT: np.full(200, 60.0)}
ev = run(cols)
assert ev is not None and ev['unit']['charge']['era'] == 'kW' and ev['unit']['discharge']['era'] == 'kW'
assert all(abs(r['util'] - 0.5) < 1e-9 for r in ev['charge']) and all(abs(r['util'] - 0.5) < 1e-9 for r in ev['discharge'])
assert ev['unit']['charge']['nOnGrid'] == ev['unit']['charge']['nSamples'] == 200 and ev['unit']['charge']['nAtCeiling'] == 0

# (hp)-only file: the same limits written in hp (metric): 40 kW = 40 / 0.73549875 hp; converted back exactly; era hp; the mechanical factor would put the values off the 0.05 kW grid
cols = {HP_IN: np.full(200, 40.0 / C._HDRM_HP_TO_KW), HP_OUT: np.full(200, 60.0 / C._HDRM_HP_TO_KW)}
ev = run(cols)
assert ev['unit']['charge']['era'] == 'hp' and abs(ev['charge'][0]['pp_kw'] - 40.0) < 1e-9
assert ev['unit']['charge']['nOnGrid'] == 200 and ev['unit']['charge']['nOnGridMechanical'] == 0

# a file with both pairs: (kW) is used; agreeing pairs pass, a disagreement above 0.05 kW stops
cols = {KW_IN: np.full(200, 40.0), KW_OUT: np.full(200, 60.0), HP_IN: np.full(200, 40.0 / C._HDRM_HP_TO_KW), HP_OUT: np.full(200, 60.0 / C._HDRM_HP_TO_KW)}
ev = run(cols)
assert ev['unit']['charge']['era'] == 'kW'
cols[HP_IN] = np.full(200, 41.0 / C._HDRM_HP_TO_KW)
try:
    run(cols)
    raise AssertionError('a disagreeing pair must stop')
except C.HeadroomUnitError:
    pass

# a file with neither pair: None (decided from the header); a (Short) pair is not read
assert run({}) is None
assert run({'[BMS] Input possible power (Short) (hp)': np.full(200, 50.0)}) is None

# ceiling flag: 63.75 kW and the 63.8 kW of the 0.1 kW-grid files are at the ceiling, 63.65 is not
vals = np.r_[np.full(50, 63.75), np.full(50, 63.8), np.full(50, 63.65), np.full(50, 40.0)]
ev = run({KW_IN: vals, KW_OUT: np.full(200, 60.0)})
assert ev['unit']['charge']['nAtCeiling'] == 100, ev['unit']['charge']
# only the first 100 rows charge (the loader's I > 0): events with limit at the ceiling are marked by pp_kw
assert all(r['pp_kw'] >= 63.7 for r in ev['charge'] if abs(r['pp_kw'] - 63.65) > 1e-6 and r['pp_kw'] > 63.7)

# summary: two files, one per era, from an in-memory loader; the unit gate passes; per-era statistics, coverage and ceiling are present; the numbers equal hand values
blobs = {
    'a.csv': make_csv({HP_IN: np.full(200, 40.0 / C._HDRM_HP_TO_KW), HP_OUT: np.full(200, 60.0 / C._HDRM_HP_TO_KW)}),
    'b.csv': make_csv({KW_IN: np.full(200, 40.0), KW_OUT: np.full(200, 60.0)}),
    'c.csv': make_csv({}),
}
dm = pd.DataFrame({'file': ['a.csv', 'b.csv', 'c.csv'], 'date': ['2026-09-20', '2026-10-05', '2026-10-06']})
out = C._headroom_utilization_summary(dm, raw_loader=lambda fn: blobs[fn])
assert out['nFilesScanned'] == 3 and out['nFilesCovered'] == 2
assert out['coverage']['drivesWithChannel'] == 2 and out['coverage']['drivesWithoutChannel'] == 1 and set(out['coverage']['byEra']) == {'hp', 'kW'}
assert out['coverage']['byEra']['hp']['dateFrom'] == '2026-09-20' and out['coverage']['byEra']['kW']['dateTo'] == '2026-10-05'
assert out['unit']['passed'] is True and out['unit']['eras']['hp']['share'] == 1.0
assert abs(out['chargeUtilization']['median'] - 0.5) < 1e-9 and abs(out['eras']['hp']['charge']['median'] - 0.5) < 1e-9 and out['eras']['kW']['discharge']['nDrives'] == 1
assert out['outputCeilingConstant'] is True and out['outputLimitByEra']['kW']['constant'] is True and out['outputLimitByEra']['hp']['rangeKw'] == [60.0, 60.0]
assert 'hard constant' not in out['methodology'].lower() and out['methodology'].lower().count('capability') == 1 and 'not a physical capability' in out['methodology']

# a drive that carries the channel but has no usable I-V pairing: counted by header (drivesWithChannel, era, unit and ceiling samples), not analysed
nov = pd.read_csv(io.BytesIO(make_csv({KW_IN: np.full(200, 63.75), KW_OUT: np.full(200, 60.0)})))
nov[V_COL] = np.nan
blobs['d.csv'] = nov.to_csv(index=False).encode('utf-8')
dm4 = pd.DataFrame({'file': ['a.csv', 'b.csv', 'c.csv', 'd.csv'], 'date': ['2026-09-20', '2026-10-05', '2026-10-06', '2026-10-07']})
out4 = C._headroom_utilization_summary(dm4, raw_loader=lambda fn: blobs[fn])
assert out4['coverage']['drivesWithChannel'] == 3 and out4['coverage']['drivesAnalysed'] == 2 and out4['coverage']['byEra']['kW']['drives'] == 2
assert out4['ceiling']['byEra']['kW']['inputSamplesAtCeiling'] == 200 and out4['unit']['eras']['kW']['nSamples'] == 800

# unit gate failure stops: samples that are off every 0.05 kW multiple
bad = make_csv({KW_IN: np.full(200, 40.013), KW_OUT: np.full(200, 60.013)})
try:
    C._headroom_utilization_summary(pd.DataFrame({'file': ['x.csv'], 'date': ['2026-10-05']}), raw_loader=lambda fn: bad)
    raise AssertionError('the unit gate must stop')
except C.HeadroomUnitError:
    pass
# per-era quarter-grid share and the 0.1 kW-grid observation: a kW file on a 0.1 kW grid (49.2 is off the 0.25 kW grid, on the 0.05 kW grid)
g01 = make_csv({KW_IN: np.full(200, 49.2), KW_OUT: np.full(200, 60.0)})
out5 = C._headroom_utilization_summary(pd.DataFrame({'file': ['g.csv', 'h.csv'], 'date': ['2026-09-10', '2026-10-05']}), raw_loader=lambda fn: {'g.csv': g01, 'h.csv': blobs['b.csv']}[fn])
ue = out5['unit']['eras']['kW']
assert ue['filesOffQuarterKwGrid'] == 1 and ue['offQuarterDateFrom'] == '2026-09-10' and ue['shareOnQuarterKwGrid'] < 1.0 and ue['share'] == 1.0
assert out5['chargeUtilization']['belowCeiling']['nDrives'] == 2 and 'descriptive' in out5['chargeUtilization']['belowCeiling']['label']
print("PASS test_m627_headroom")
