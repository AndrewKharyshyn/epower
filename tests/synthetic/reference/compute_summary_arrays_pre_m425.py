"""M425 reference: the three engine-start functions of compute_summary_arrays EXACTLY as they were before M425 (verbatim copy of main at M424). tests/synthetic/test_start_event_scan.py executes this source
in the namespace of compute_summary_arrays and compares the results with the current functions. Do not edit."""

def _buffer_impulse_events(fr, min_peak_excess_a=3.0, excess_thresh_a=1.5,
                            pre_off_s=3.0, baseline_win=(8.0, 2.0),
                            search_win=(1.0, 8.0)):
    """Per-drive engine-start buffer-impulse detection on a cached slim
    frame. Returns a list of event dicts. See the M116 note above this
    function for the full methodology."""
    if (fr is None or _BUFIMP_RPM_COL not in fr.columns
            or _BUFIMP_I_COL not in fr.columns or _BUFIMP_V_COL not in fr.columns):
        return []
    rpm = fr[['time', _BUFIMP_RPM_COL]].dropna().reset_index(drop=True)
    rpm.columns = ['time', 'rpm']
    I = fr[['time', _BUFIMP_I_COL]].dropna().reset_index(drop=True)
    I.columns = ['time', 'I_raw']
    I['I_dis'] = -I['I_raw']            # M11: raw is charge-positive
    V = fr[['time', _BUFIMP_V_COL]].dropna().reset_index(drop=True)
    V.columns = ['time', 'V']
    if len(rpm) < 2 or len(I) < 2 or len(V) < 2:
        return []

    r = rpm['rpm'].values
    t = rpm['time'].values
    starts = []
    for i in range(1, len(r)):
        if r[i] > 800 and r[i-1] <= 100:
            t0 = pd.Timestamp(t[i])
            back = rpm.loc[(rpm['time'] >= t0 - pd.Timedelta(seconds=pre_off_s))
                           & (rpm['time'] < t0), 'rpm']
            if len(back) > 0 and (back <= 100).all():
                starts.append(t0)

    events = []
    for t0 in starts:
        base_I = I[(I['time'] >= t0 - pd.Timedelta(seconds=baseline_win[0]))
                   & (I['time'] < t0 - pd.Timedelta(seconds=baseline_win[1]))]['I_dis']
        if len(base_I) == 0:
            continue
        baseline = float(base_I.median())

        seg = I[(I['time'] >= t0 - pd.Timedelta(seconds=search_win[0]))
                & (I['time'] <= t0 + pd.Timedelta(seconds=search_win[1]))].copy()
        seg = seg.sort_values('time').reset_index(drop=True)
        if len(seg) < 2:
            continue
        seg = pd.merge_asof(seg, V.sort_values('time'), on='time',
                             direction='nearest', tolerance=pd.Timedelta(seconds=3))
        seg['excess'] = (seg['I_dis'] - baseline).clip(lower=0)
        above = seg['excess'] > excess_thresh_a
        if not above.any():
            continue
        first_idx = int(above.values.argmax())
        end_idx = first_idx
        while end_idx < len(above) - 1 and above.iloc[end_idx + 1]:
            end_idx += 1
        imp = seg.iloc[first_idx:end_idx + 1].reset_index(drop=True)
        if len(imp) < 2:
            continue
        peak_excess = float(imp['excess'].max())
        if peak_excess < min_peak_excess_a:
            continue
        peak_pos = imp['excess'].idxmax()
        peak_v = float(imp.loc[peak_pos, 'V'])

        dt_h = imp['time'].diff().dt.total_seconds().fillna(0) / 3600.0
        p_kw = (imp['excess'] * imp['V']) / 1000.0
        energy_wh = 0.0
        for k in range(1, len(imp)):
            energy_wh += 0.5 * (p_kw.iloc[k] + p_kw.iloc[k-1]) * dt_h.iloc[k] * 1000
        duration_s = float((imp['time'].iloc[-1] - imp['time'].iloc[0]).total_seconds())
        recovery_s = float((imp['time'].iloc[-1] - imp['time'].loc[peak_pos]).total_seconds())

        events.append({
            't0': t0.isoformat(), 'baselineA': round(baseline, 2),
            'peakExcessA': round(peak_excess, 2),
            'peakExcessKw': round(peak_excess * peak_v / 1000.0, 3),
            'energyWh': round(energy_wh, 3),
            'durationS': round(duration_s, 2),
            'recoveryS': round(recovery_s, 2),
        })
    return events


def _ramp_latency_events(fr, plateau_bin_rpm=250, min_plateau_s=3.0, pre_off_s=3.0):
    """Per-drive engine-start ramp/plateau segmentation on a cached slim
    frame. Returns a list of event dicts. See the M118 note above this
    function for the full methodology."""
    if fr is None or _RAMPLAT_RPM_COL not in fr.columns:
        return []
    fr, _ = _apply_speed_priority(fr)      # M167
    rpm = fr[['time', _RAMPLAT_RPM_COL]].dropna().reset_index(drop=True)
    rpm.columns = ['time', 'rpm']
    if len(rpm) < 2:
        return []
    spd = None
    if _RAMPLAT_SPD_COL in fr.columns:
        spd = fr[['time', _RAMPLAT_SPD_COL]].dropna().reset_index(drop=True)
        spd.columns = ['time', 'speed']

    r = rpm['rpm'].values
    t = rpm['time'].values
    starts = []
    for i in range(1, len(r)):
        if r[i] > 800 and r[i-1] <= 100:
            t0 = pd.Timestamp(t[i])
            back = rpm.loc[(rpm['time'] >= t0 - pd.Timedelta(seconds=pre_off_s))
                           & (rpm['time'] < t0), 'rpm']
            if len(back) > 0 and (back <= 100).all():
                starts.append((i, t0))

    events = []
    for start_idx, t0 in starts:
        seg = rpm.iloc[start_idx:].reset_index(drop=True)
        stop_pos = len(seg) - 1
        for j in range(1, len(seg)):
            if seg['rpm'].iloc[j] <= 100 and seg['rpm'].iloc[j-1] <= 100:
                stop_pos = j - 1
                break
        cyc = seg.iloc[:stop_pos + 1].reset_index(drop=True)
        if len(cyc) < 2:
            continue

        bins = (cyc['rpm'] / plateau_bin_rpm).round().astype(int)
        plateaus = []
        cur_bin = bins.iloc[0]
        run_start = 0
        for k in range(1, len(bins)):
            if bins.iloc[k] != cur_bin:
                plateaus.append((run_start, k - 1, cur_bin))
                cur_bin = bins.iloc[k]
                run_start = k
        plateaus.append((run_start, len(bins) - 1, cur_bin))

        qualifying = []
        for (a, b, bv) in plateaus:
            dur = (cyc['time'].iloc[b] - cyc['time'].iloc[a]).total_seconds()
            if dur >= min_plateau_s:
                qualifying.append({
                    'binRpm': int(bv * plateau_bin_rpm),
                    'durationS': round(dur, 2),
                    'startTime': cyc['time'].iloc[a], 'endTime': cyc['time'].iloc[b],
                })
        if not qualifying:
            continue

        ramp_latency_s = (qualifying[0]['startTime'] - t0).total_seconds()

        transitions = []
        for p1, p2 in zip(qualifying[:-1], qualifying[1:]):
            spd_val = None
            if spd is not None:
                near = spd[(spd['time'] >= p1['endTime'] - pd.Timedelta(seconds=2))
                          & (spd['time'] <= p1['endTime'] + pd.Timedelta(seconds=2))]
                if len(near):
                    spd_val = float(near['speed'].mean())
            transitions.append({'fromRpm': p1['binRpm'], 'toRpm': p2['binRpm'],
                                 'speedKmh': round(spd_val, 1) if spd_val is not None else None})

        events.append({
            't0': t0.isoformat(),
            'rampLatencyS': round(max(0.0, ramp_latency_s), 2),
            'firstPlateauRpm': qualifying[0]['binRpm'],
            'nPlateaus': len(qualifying),
            'plateauDwellsS': [p['durationS'] for p in qualifying],
            'transitions': transitions,
        })
    return events


def _engine_start_triggers(fr, pre_off_s=3.0):
    """Return the set of engine-start trigger timestamps (ISO strings) using
    the IDENTICAL sustained-off -> running logic shared by _buffer_impulse_events
    and _ramp_latency_events. This is the pre-eligibility trigger population;
    both detectors' event sets are subsets of it by construction."""
    if fr is None or _BUFIMP_RPM_COL not in fr.columns:
        return []
    rpm = fr[['time', _BUFIMP_RPM_COL]].dropna().reset_index(drop=True)
    rpm.columns = ['time', 'rpm']
    if len(rpm) < 2:
        return []
    r = rpm['rpm'].values
    t = rpm['time'].values
    out = []
    for i in range(1, len(r)):
        if r[i] > 800 and r[i-1] <= 100:
            t0 = pd.Timestamp(t[i])
            back = rpm.loc[(rpm['time'] >= t0 - pd.Timedelta(seconds=pre_off_s))
                           & (rpm['time'] < t0), 'rpm']
            if len(back) > 0 and (back <= 100).all():
                out.append(t0.isoformat())
    return out
