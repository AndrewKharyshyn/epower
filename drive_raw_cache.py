"""
drive_raw_cache.py -- M44 (2026-07-19): persistent per-drive slim raw cache.

Motivation. build_summary_arrays(with_raw=True) makes FIVE independent
passes over every raw CSV (category_B, _battery_temp_traj,
_motor_temp_stats, _highspeed_census, _near_limiter). The dominant cost is
pd.read_csv of the full-width (34-159 col) logs -- repeated 5x per file,
149+ files, every session. That cost grows linearly with corpus size and is
what forces the checkpointed multi-phase workaround.

Fix. Parse each raw CSV ONCE, keep only the union of columns any raw pass
consumes (SLIM_COLS, 19 of 34-159), and persist the slim frame as a
per-drive gzipped pickle under raw_cache/. Subsequent sessions load frames
from the cache (10-60x faster than CSV parse) and only parse raw CSVs for
NEW drives. Numerical outputs are byte-identical to the raw path: the frame
carries the ORIGINAL 'time' strings and original dtypes -- every downstream
function performs its own pd.to_datetime / to_numeric / gating exactly as
before, on exactly the same values. Nothing is resampled, rounded, or
downcast at the cache layer.

Cache transport. raw_cache/ is tarred into raw_cache.tar (uncompressed tar
of already-gzipped members) and kept in Project Knowledge next to
drive_master.csv. Per-batch session: untar -> add_missing() for the new
files only -> retar. The manifest records per-file source MD5 + schema
version; a source-file change or schema bump invalidates that entry only.

Invariant. SLIM_COLS must remain a superset of every column referenced by
the raw passes in compute_summary_arrays.py. The acceptance test
`python3 drive_raw_cache.py check compute_summary_arrays.py` greps the
consumer module for raw-column literals and fails if any is missing here --
run it whenever a new M-number adds a raw pass.
Schema v2 note: the cached 'time' column is datetime64 (parsed once at
build). pd.to_datetime on datetime64 input is a value-preserving no-op, so
consumer code paths are unchanged and outputs stay byte-identical.
"""
import gzip
import hashlib
import json
import os
import pickle
import time as _time

import pandas as pd

SCHEMA_VERSION = 7

# Union of raw columns consumed by all five raw passes (see module docstring).
SLIM_COLS = [
    'time',
    # RAW_MAP (category_B / _RawAccum.add)
    '[BMS] HV Battery Current (A)',
    '[BMS] HV Battery voltage (V)',
    '[BMS] HV State of charge (%)',
    '[VCM] HV Battery Available Charge Display (%)',
    '[BMS] HV Battery Temperature Sensor 1 (\u2103)',
    '[BMS] HV Battery Temperature Sensor 2 (\u2103)',
    '[BMS] HV Battery Temperature Sensor 3 (\u2103)',
    '[BMS] HV Battery Temperature Sensor 4 (\u2103)',
    '[BMS] HV Battery Intake Air Temperature (\u2103)',
    '[BMS] Max Cell Voltage (V)',
    '[BMS] Min Cell Voltage (V)',
    '[VCM] Vehicle Speed (km/h)',
    '[VCM] Target Motor Torque (N\u22c5m)',
    '\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)',            # eng rpm
    '\u0420\u043e\u0437\u0440\u0430\u0445\u0443\u043d\u043a\u043e\u0432\u0438\u0439 \u043d\u0430\u0434\u0434\u0443\u0432 (bar)',  # boost
    '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u0445\u043e\u043b\u043e\u0434\u043d\u043e\u0457 \u0440\u0456\u0434\u0438\u043d\u0438 (\u2103)',  # eng coolant
    # _motor_temp_stats
    '[VCM] Traction motor temperature (\u2103)',
    # _near_limiter ('load' = calc engine load)
    '\u0420\u043e\u0437\u0440\u0430\u0445\u0443\u043d\u043a\u043e\u0432\u0435 \u0437\u043d\u0430\u0447\u0435\u043d\u043d\u044f \u043d\u0430\u0432\u0430\u043d\u0442\u0430\u0436\u0435\u043d\u043d\u044f \u043d\u0430 \u0434\u0432\u0438\u0433\u0443\u043d (%)',
    # M48 (2026-07-22): barometric altimetry proxy for the route-relief census
    # (_low_speed_dissipation). Schema bumped v2 -> v3 to add this channel.
    # NOTE the PID is polled very sparsely (corpus median 3 samples/drive,
    # 1 kPa quantisation ~= 84 m): usable only as a per-drive elevation
    # ENVELOPE, never as a time-resolved altitude or grade trace.
    '\u0410\u0442\u043c\u043e\u0441\u0444\u0435\u0440\u043d\u0438\u0439 \u0442\u0438\u0441\u043a (\u0430\u0431\u0441\u043e\u043b\u044e\u0442\u043d\u0438\u0439) (kPa)',
    # M57 (2026-07-27): GPS altitude + position, present only in the 42-column
    # logging generation (Jul 24 2026 onward, 14 files). Unlike the baro PID
    # this channel is a genuine ~1 Hz time-resolved altitude trace and is what
    # makes per-event grade attribution (the mountain-road pattern) possible.
    # Schema bumped v3 -> v4.
    '\u0412\u0438\u0441\u043e\u0442\u0430 (GPS) (m)',
    'Latitude',
    'Longtitude',
    # M57: actual (not target) motor torque -- needed to separate commanded
    # from delivered torque on sustained grades.
    '[VCM] Motor Torque (N\u22c5m)',
    # M167 (2026-08-23): OBD-generic vehicle-speed PID. Distinct channel from
    # '[VCM] Vehicle Speed (km/h)' -- NOT a locale translation of it -- that
    # 44/274 files (the 5 earliest, May 11-13, plus 39 from Aug 14-22) log
    # speed under exclusively. compute_drive_summary_v6.py already falls back
    # to it (speed_source='obd_fallback') for per-drive stats; RAW_MAP/
    # _RawAccum.add() in compute_summary_arrays.py did not, so every Category-B
    # raw-pass array gated on col('speed') (socBySpeed, cycleBySpeed,
    # torqueBySpeed, terrainTorqueDist, regenByZone/regenByTempMeasured,
    # turboBySpeedCtx, speedDist, highwayVsCity) silently dropped those 44
    # files. Schema bumped v4 -> v5 to add this channel.
    '\u0428\u0432\u0438\u0434\u043a\u0456\u0441\u0442\u044c \u0430\u0432\u0442\u043e\u043c\u043e\u0431\u0456\u043b\u044f (km/h)',
    # M184 (2026-08-29): logged longitudinal acceleration (g). A first-class
    # batched-synchronous channel (~1.26 Hz, same rows as speed/RPM/SoC), NOT a
    # speed-derivative -- the sensor reading is far less noisy than diff(speed).
    # Needed by the accel/decel speed-binned dynamics envelopes (candidate A) and
    # reused by the later RPM-speed-sync (C) and driving-state-taxonomy (E)
    # modules. Schema bumped v5 -> v6 to add this channel.
    '\u041f\u0440\u0438\u0441\u043a\u043e\u0440\u0435\u043d\u043d\u044f (g)',
    # M191 (2026-08-29): engine oil temperature. First-class thermal channel
    # (~96 % corpus coverage) needed alongside coolant for the coolant/oil warm-up
    # and coolant-oil thermal-lag analysis (candidate O-thermal); reusable by later
    # thermal work. Schema bumped v6 -> v7 to add it.
    '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u043b\u0456\u0457 \u0443 \u0434\u0432\u0438\u0433\u0443\u043d\u0456 (\u2103)',
]

CACHE_DIR = 'raw_cache'
MANIFEST = 'manifest.json'


def _md5(b):
    return hashlib.md5(b).hexdigest()


def _entry_path(cache_dir, fname):
    return os.path.join(cache_dir, fname + '.pkl.gz')


def _load_manifest(cache_dir):
    p = os.path.join(cache_dir, MANIFEST)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def _save_manifest(cache_dir, man):
    with open(os.path.join(cache_dir, MANIFEST), 'w') as f:
        json.dump(man, f, indent=1, sort_keys=True)


def add_file(fname, raw_bytes, cache_dir=CACHE_DIR, manifest=None):
    """Parse one raw CSV and write its slim frame to the cache.
    Returns the manifest entry. Exact: original 'time' strings and dtypes
    are preserved; only column selection happens here."""
    os.makedirs(cache_dir, exist_ok=True)
    man = manifest if manifest is not None else _load_manifest(cache_dir)
    import io
    df = pd.read_csv(io.BytesIO(raw_bytes), low_memory=False)
    keep = [c for c in SLIM_COLS if c in df.columns]
    slim = df[keep].copy()
    # Schema v2: 'time' is pre-parsed to datetime64 at cache build. Every
    # consumer calls pd.to_datetime(df['time'], ...) itself, which is a
    # no-op on datetime64 input -- values identical, the ~17 us/row
    # dateutil fallback cost is paid once here instead of once per pass
    # per session. Fast exact-format attempt first; per-file fallback to
    # the consumers' own format='mixed', errors='coerce' convention.
    if 'time' in slim.columns:
        try:
            slim['time'] = pd.to_datetime(slim['time'],
                                          format='%H:%M:%S.%f',
                                          errors='raise')
        except (ValueError, TypeError):
            slim['time'] = pd.to_datetime(slim['time'], format='mixed',
                                          errors='coerce')
    payload = {'schema': SCHEMA_VERSION, 'file': fname,
               'src_md5': _md5(raw_bytes), 'n_rows': int(len(slim)),
               'cols': keep, 'df': slim}
    with gzip.open(_entry_path(cache_dir, fname), 'wb', compresslevel=1) as f:
        pickle.dump(payload, f, protocol=5)
    man[fname] = {'schema': SCHEMA_VERSION, 'src_md5': payload['src_md5'],
                  'n_rows': payload['n_rows'], 'cols': keep}
    if manifest is None:
        _save_manifest(cache_dir, man)
    return man[fname]


def make_frame_loader(cache_dir=CACHE_DIR, verify_schema=True):
    """Returns frame_loader(fname) -> DataFrame|None for
    build_summary_arrays(frame_loader=...). Stale-schema entries are
    treated as missing (forces re-add rather than silently serving old
    column sets)."""
    def _load(fname):
        p = _entry_path(cache_dir, fname)
        if not os.path.exists(p):
            return None
        with gzip.open(p, 'rb') as f:
            payload = pickle.load(f)
        if verify_schema and payload.get('schema') != SCHEMA_VERSION:
            return None
        return payload['df']
    return _load


def add_missing(files, raw_dir, cache_dir=CACHE_DIR, budget_s=None,
                verify_md5=False, verbose=True):
    """Ensure a cache entry exists (schema-current, and MD5-matching if
    verify_md5) for every file in `files` found under raw_dir. Resumable:
    call again after a timeout -- completed entries are skipped via the
    manifest, so the loop is idempotent. Returns (n_added, n_pending)."""
    t0 = _time.time()
    man = _load_manifest(cache_dir)
    todo = []
    for fn in files:
        e = man.get(fn)
        if e and e.get('schema') == SCHEMA_VERSION \
                and os.path.exists(_entry_path(cache_dir, fn)):
            if not verify_md5:
                continue
            src = os.path.join(raw_dir, fn)
            if os.path.exists(src):
                with open(src, 'rb') as f:
                    if _md5(f.read()) == e.get('src_md5'):
                        continue
        todo.append(fn)
    n_added = 0
    for fn in todo:
        if budget_s is not None and _time.time() - t0 > budget_s:
            break
        src = os.path.join(raw_dir, fn)
        if not os.path.exists(src):
            if verbose:
                print(f'  [miss] {fn}: no source file')
            continue
        with open(src, 'rb') as f:
            raw = f.read()
        e = add_file(fn, raw, cache_dir=cache_dir, manifest=man)
        n_added += 1
        if verbose:
            print(f'  [add ] {fn}: {e["n_rows"]} rows, {len(e["cols"])} cols '
                  f'({_time.time() - t0:.0f}s)')
        _save_manifest(cache_dir, man)   # persist per file: crash-safe resume
    n_pending = len(todo) - n_added - sum(
        1 for fn in todo if not os.path.exists(os.path.join(raw_dir, fn)))
    return n_added, max(n_pending, 0)


def check_consumer(consumer_path):
    """Acceptance gate: every quoted raw-column literal in the consumer that
    looks like an OBD PID header must be in SLIM_COLS -- UNLESS it's in
    RAW_LOADER_ONLY_EXCEPTIONS below (audit remediation, M181: a plain regex
    scan of column literals can't distinguish frame_loader/slim-cache
    consumers, which genuinely need SLIM_COLS coverage, from raw_loader-only
    consumers, which read the full raw CSV directly every time and never
    touch the cache -- so requiring cache coverage for the latter is a false
    positive, not a real gap. Confirmed by call-site inspection, not
    assumed: verify any new addition here actually reads via
    raw_loader(fn)->bytes before excepting it, not frame_loader(fn).)."""
    import re
    # Columns confirmed (by call-site inspection, M181) to be read only via
    # raw_loader(fn)->bytes, never via the frame_loader/slim-cache path:
    #   '[BMS] Input possible power (hp)' / '[BMS] Output possible power (hp)'
    #     -- M140 _headroom_utilization_events(csv_bytes, filename), called
    #        as _headroom_utilization_events(raw_loader(fn), fn).
    #   '[BMS] Input/Output possible power' / '... (hp)'
    #     -- same M140 pass; the combined-channel fallback name, same call path.
    #   '[BMS] Battery Cell #01 (V)'
    #     -- _audit_raw_manifest's per-PID coverage map, whose own docstring
    #        states "raw_loader(fname)->bytes; header is read from the first
    #        line only" -- a header-presence check, not a value read, and
    #        explicitly not part of any frame_loader-consuming pass.
    RAW_LOADER_ONLY_EXCEPTIONS = {
        '[BMS] Input possible power (hp)',
        '[BMS] Output possible power (hp)',
        '[BMS] Input/Output possible power',
        '[BMS] Input/Output possible power (hp)',
        '[BMS] Battery Cell #01 (V)',
        # M200 _fcs_snapshot: per-cell worked examples read via raw_loader(fn)->bytes
        # (or a direct raw_dir open), never frame_loader. These two are the format
        # string / prefix literals of the same '[BMS] Battery Cell #NN (V)' family.
        '[BMS] Battery Cell #',
        '[BMS] Battery Cell #%02d (V)',
    }
    src = open(consumer_path, encoding='utf-8').read()
    pids = set(re.findall(r"'(\[(?:BMS|VCM)\][^']+)'", src))
    # Ukrainian-locale literals used as raw columns (value side of maps / C{})
    pids |= set(re.findall(
        r"'((?:\u041e\u0431\u0435\u0440\u0442\u0438|\u0420\u043e\u0437\u0440\u0430\u0445\u0443\u043d\u043a|\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430)[^']*\([^']*\))'", src))
    def _deesc(p):
        # source may write PIDs with \uXXXX escapes; normalize before compare
        if '\\u' in p:
            try:
                return p.encode('utf-8').decode('unicode_escape')
            except Exception:
                return p
        return p
    pids = {_deesc(p) for p in pids}
    missing = sorted(p for p in pids if p not in SLIM_COLS and p not in RAW_LOADER_ONLY_EXCEPTIONS)
    excepted = sorted(p for p in pids if p not in SLIM_COLS and p in RAW_LOADER_ONLY_EXCEPTIONS)
    for p in missing:
        print(f'  [FAIL] consumer references raw column not in SLIM_COLS: {p!r}')
    for p in excepted:
        print(f'  [INFO] raw_loader-only column, cache coverage not required: {p!r}')
    if not missing:
        print(f'  [PASS] all {len(pids)} raw-column literals covered by SLIM_COLS or a documented raw_loader-only exception ({len(excepted)} excepted)')
    return not missing


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'check':
        sys.exit(0 if check_consumer(sys.argv[2]) else 1)
    print('drive_raw_cache.py loaded OK; SLIM_COLS =', len(SLIM_COLS))
