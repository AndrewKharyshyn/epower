# Blind-audit extraction (written from the spec + legacy block only). Writes one per-step table.
import sys, os, numpy as np, pandas as pd
from multiprocessing import Pool
REPO = r"C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\Repo\xtrail-repo"
RAWDIR = os.path.join(REPO, "raw_only")
OUT = sys.argv[1]
C = {
 'I': '[BMS] HV Battery Current (A)', 'V': '[BMS] HV Battery voltage (V)',
 'T1': '[BMS] HV Battery Temperature Sensor 1 (℃)', 'T2': '[BMS] HV Battery Temperature Sensor 2 (℃)',
 'T3': '[BMS] HV Battery Temperature Sensor 3 (℃)', 'T4': '[BMS] HV Battery Temperature Sensor 4 (℃)',
 'speedV': '[VCM] Vehicle Speed (km/h)', 'speedO': 'Швидкість автомобіля (km/h)',
 'rpm': 'Оберти двигуна (rpm)',
}
RNG = {'speed': (0, 260), 'rpm': (0, None), 'V': (200, 450), 'I': (None, None),
       'T1': (-40, 90), 'T2': (-40, 90), 'T3': (-40, 90), 'T4': (-40, 90)}
MASS = {'highway': 2000.0, 'mixed_highway': 2000.0, 'urban': 1890.0, 'mixed': 1890.0}
FALLBACK_MASS = 1950.0   # to be checked against VEHICLE_MASS_KG in the script (unknown class)

def parse_time(s):
    try:
        return pd.to_datetime(s, format="%H:%M:%S.%f", errors="raise") + (pd.Timestamp.now().normalize() - pd.Timestamp("1900-01-01"))
    except (ValueError, TypeError):
        return pd.to_datetime(s, errors="coerce", format="mixed")

def gated(x, lo, hi):
    if lo is not None: x = x.where(x >= lo)
    if hi is not None: x = x.where(x <= hi)
    return x

def one(args):
    k, fn, dtype, day, fallback_mass = args
    path = os.path.join(RAWDIR, fn)
    hdr = pd.read_csv(path, nrows=0).columns
    want = ['time'] + [v for v in C.values() if v in hdr]
    df = pd.read_csv(path, usecols=want, low_memory=False)
    if 'time' not in df: return None
    # speed priority (native VCM if >=20 non-null numeric samples else OBD)
    spd_raw = None
    if C['speedV'] in df and pd.to_numeric(df[C['speedV']], errors='coerce').notna().sum() >= 20:
        spd_raw = C['speedV']
    elif C['speedO'] in df:
        spd_raw = C['speedO']
    elif C['speedV'] in df:
        spd_raw = C['speedV']
    t = parse_time(df['time'])
    raw = {}
    for nm, src in [('speed', spd_raw), ('rpm', C['rpm']), ('I', C['I']), ('V', C['V']),
                    ('T1', C['T1']), ('T2', C['T2']), ('T3', C['T3']), ('T4', C['T4'])]:
        raw[nm] = pd.to_numeric(df[src], errors='coerce') if (src is not None and src in df) else None
    ff = {}
    for nm, s in raw.items():
        if s is None: ff[nm] = None; continue
        lo, hi = RNG['speed'] if nm == 'speed' else RNG[nm]
        ff[nm] = gated(s.ffill(limit=15), lo, hi)
    g1 = pd.DataFrame({'t': t})
    for nm in ['speed', 'rpm', 'I', 'V', 'T1', 'T2', 'T3', 'T4']:
        g1[nm] = ff[nm].values if ff[nm] is not None else np.nan
    g1 = g1.dropna(subset=['t']).set_index('t')
    hz = g1.resample('1s').mean().ffill(limit=15)
    # native sample times per channel
    nat = {}
    for nm in ['speed', 'rpm', 'I', 'V']:
        s = raw[nm]
        if s is None: nat[nm] = np.array([], dtype='int64'); continue
        lo, hi = RNG[nm]
        ok = gated(s, lo, hi).notna() & t.notna()
        nat[nm] = np.sort(t[ok].values.astype('datetime64[ns]').astype('int64'))
    rq = hz.dropna(subset=['speed', 'I', 'V'])
    if len(rq) < 4: return None
    sp = rq['speed'].values
    rpmv = rq['rpm'].values
    rp = np.nan_to_num(rpmv, nan=0.0)
    Iv, Vv = rq['I'].values, rq['V'].values
    eng_off = rp <= 300
    vprev = np.concatenate([sp[:1], sp[:-1]])
    decel = sp < vprev
    P = (-Iv) * Vv / 1000.0
    cap = np.where(P < 0, -P, 0) / 3600.0
    m = MASS.get(dtype, fallback_mass)
    ke = 0.5 * m * ((vprev / 3.6) ** 2 - (sp / 3.6) ** 2) / 3.6e6
    step = eng_off & decel & (sp > 0) & (ke > 0)
    idx = np.where(step)[0]
    if len(idx) == 0: return None
    secs = rq.index.values.astype('datetime64[ns]').astype('int64')   # grid second start (ns)
    prev_secs = np.concatenate([secs[:1], secs[:-1]])
    Tm = rq[['T1', 'T2', 'T3', 'T4']]
    Tpack = Tm.mean(axis=1).values
    nprobe = Tm.notna().sum(axis=1).values
    def age(chan, ref):    # seconds from latest native sample (time < ref) to ref; 1e9 if none
        a = nat[chan]
        j = np.searchsorted(a, ref, side='left') - 1
        out = np.full(len(ref), 1e9)
        ok = j >= 0
        out[ok] = (ref[ok] - a[j[ok]]) / 1e9
        return out
    ref_c = secs[idx] + 10**9
    ref_p = prev_secs[idx] + 10**9
    d = pd.DataFrame({
        'k': k, 'day': day, 'speed': sp[idx], 'vprev': vprev[idx], 'ke': ke[idx], 'cap': cap[idx],
        'I': Iv[idx], 'V': Vv[idx], 'Tpack': Tpack[idx], 'nprobe': nprobe[idx],
        'rpm_nan': np.isnan(rpmv[idx]), 'gap': (secs[idx] - prev_secs[idx]) / 1e9,
        'age_spd': age('speed', ref_c), 'age_spd_prev': age('speed', ref_p),
        'age_I': age('I', ref_c), 'age_V': age('V', ref_c), 'age_rpm': age('rpm', ref_c), 'sec': secs[idx]})
    return d

if __name__ == '__main__':
    dm = pd.read_csv(os.path.join(REPO, 'drive_master.csv'), encoding='utf-8')
    jobs = [(i, r.file, r.drive_type, r.date, FALLBACK_MASS) for i, r in enumerate(dm.itertuples())]
    with Pool(4) as p:
        res = p.map(one, jobs, chunksize=4)
    out = pd.concat([r for r in res if r is not None], ignore_index=True)
    out.to_pickle(OUT)
    print(len(out), out.k.nunique(), out.day.nunique())
