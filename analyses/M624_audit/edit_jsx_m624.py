"""One-off editor used to apply the M624 jsx edits (kept for the record; idempotency is NOT provided: anchors must match once)."""
p = 'xtrail_summary.jsx'
s = open(p, encoding='utf-8', newline='').read()
n_ok = 0


def rep(old, new, count=1):
    global s, n_ok
    for o, nw in ((old, new), (old.replace('\n', '\r\n'), new.replace('\n', '\r\n'))):
        if s.count(o) == count:
            s = s.replace(o, nw)
            n_ok += 1
            return
    raise SystemExit("anchor not found/unique: " + old[:80] + " count=" + str(s.count(old)) + "/" + str(s.count(old.replace('\n', '\r\n'))))


# 1 axis + domain + segments
rep('''  const allT = cool.concat(oil).filter(v => v != null);
  const yMax = Math.max(90, ...allT) * 1.02, yMin = Math.min(30, ...allT) - 2;
  const xB = i => PL + (nb > 1 ? (i / (nb - 1)) * pw : pw / 2);
  const yT = v => PT + ph - ((v - yMin) / (yMax - yMin)) * ph;
  const line = arr => arr.map((v, i) => v == null ? null : `${xB(i)},${yT(v)}`).filter(Boolean).join(" ");
''', '''  const cP25 = cw.coolantP25C || [], cP75 = cw.coolantP75C || [], oP25 = cw.oilP25C || [], oP75 = cw.oilP75C || [];
  const cSup = cw.coolantSupported || [], oSup = cw.oilSupported || [];
  const allT = cool.concat(oil, cP25, cP75, oP25, oP75).filter(v => v != null);          // M624 (R7): the y domain covers the whiskers
  const yMax = Math.max(90, ...allT) * 1.02, yMin = Math.min(30, ...allT) - 2;
  // M624: x is elapsed time (bin mid-time over the last bin edge), not the bin index
  const tMaxS = bins.length ? bins[bins.length - 1] : 900;
  const midS = i => (bins[i] + bins[i + 1]) / 2;
  const xB = i => PL + (midS(i) / tMaxS) * pw;
  const yT = v => PT + ph - ((v - yMin) / (yMax - yMin)) * ph;
  // the polyline is split at empty bins (a gap is not drawn as a trend)
  const segs = arr => { const out = []; let cur = []; arr.forEach((v, i) => { if (v == null) { if (cur.length) out.push(cur); cur = []; } else cur.push(`${xB(i)},${yT(v)}`); }); if (cur.length) out.push(cur); return out; };
  const lastIdx = arr => { for (let i = arr.length - 1; i >= 0; i--) if (arr[i] != null) return i; return -1; };
  const cLast = lastIdx(cool), oLast = lastIdx(oil);
  const kmCoh = S.thermalSupportLedger?.timeToThreshold?.cohorts?.[_coh];
''')

# 2 intro
rep('''        Extends the coolant warm-up analysis with the engine <strong style={{ color: "#ea580c" }}>oil</strong>
        {" "}trajectory and the <strong style={{ color: "#0f172a" }}>coolant–oil lag</strong>. Oil carries more
        thermal mass and is heated indirectly, so it warms well behind the coolant — the gap gates truly-warm
        engine operation long after the coolant gauge reads normal. On {C.nColdStart} cold-start drives
        ({C.nWithOil} with oil temp), {C.nDays} days.
''', '''        Extends the coolant warm-up analysis with the engine <strong style={{ color: "#ea580c" }}>oil</strong>
        {" "}trajectory and the <strong style={{ color: "#0f172a" }}>coolant–oil lag</strong> (time between the coolant and
        the oil reaching 70 °C). Cold start = coolant at the start below {C.coldStartMaxC} °C, and a drive needs at least
        30 valid 1 s coolant samples. A possible reading of the lag is the larger thermal mass of the oil; that is not tested here.
        {" "}{C.nColdStart} cold-start drives ({C.nWithOil} with oil temperature), {C.nDays} days. Temperatures are logged / app-calculated.
''')

# 3 lag KPI label
rep('''        <Kpi label="coolant–oil lag to 70 °C" value={lag.median} unit="s" color="#dc2626"
             sub={`95% CI ${ci(lagB)}`} />''', '''        <Kpi label="coolant–oil lag to 70 °C (drives where both reached 70 °C)" value={lag.median} unit="s" color="#dc2626"
             sub={`95% CI ${ci(lagB)}; ${lagB.nDrives ?? "—"} drives, ${lagB.nDays ?? "—"} days`} />''')

# 4 callout
rep('''        Oil reaches 70 °C a median <MetricHighlight tone="measured">{lag.median} s</MetricHighlight>
        {" "}(~{Math.round((lag.median || 0) / 60)} min, CI {ci(lagB)}) after the coolant, and even once warm it
        runs <MetricHighlight tone="derived">{off.median} °C cooler</MetricHighlight> (IQR {off.p25}–{off.p75}).
        The coolant gauge reads "warm" while the oil is still climbing — the engine is not fully thermally
        settled until well into the trip, which is what makes short trips thermally costly. <EvidenceBadge status="measured" />''', '''        Among drives where both fluids reached 70 °C ({lagB.nDrives ?? "—"} drives, {lagB.nDays ?? "—"} days), the oil reaches 70 °C a median <MetricHighlight tone="derived">{lag.median} s</MetricHighlight>
        {" "}(~{Math.round((lag.median || 0) / 60)} min, CI {ci(lagB)}) after the coolant. While the coolant is at 80 °C or above, coolant minus oil is a
        median <MetricHighlight tone="derived">{off.median} °C</MetricHighlight> (IQR {off.p25}–{off.p75}). Drives that never reached 70 °C are not in the lag. <EvidenceBadge status="derived" />''')

# 5 curve caption + svg
rep('''WARM-UP CURVES — coolant (blue) vs oil (orange), median °C vs time from start</div>''',
    '''WARM-UP CURVES — coolant (blue) vs oil (orange), median °C vs elapsed time from start (cold start = coolant below {C.coldStartMaxC} °C); whiskers = spread (p25–p75) of per-drive medians across drives; hollow marker = fewer than 10 drives or 5 days</div>''')
rep('''        <polyline points={line(cool)} fill="none" stroke="#2563eb" strokeWidth={2} />
        <polyline points={line(oil)} fill="none" stroke="#ea580c" strokeWidth={2} />
        {cool.map((v, i) => v != null && <circle key={"c" + i} cx={xB(i)} cy={yT(v)} r={2.4} fill="#2563eb" />)}
        {oil.map((v, i) => v != null && <circle key={"o" + i} cx={xB(i)} cy={yT(v)} r={2.4} fill="#ea580c" />)}''',
    '''        {segs(cool).map((sg, k) => <polyline key={"cl" + k} points={sg.join(" ")} fill="none" stroke="#2563eb" strokeWidth={2} />)}
        {segs(oil).map((sg, k) => <polyline key={"ol" + k} points={sg.join(" ")} fill="none" stroke="#ea580c" strokeWidth={2} />)}
        {cool.map((v, i) => v != null && cSup[i] && cP25[i] != null && cP75[i] != null && <line key={"cw" + i} x1={xB(i)} x2={xB(i)} y1={yT(cP25[i])} y2={yT(cP75[i])} stroke="#2563eb" strokeWidth={1} opacity={0.55} />)}
        {oil.map((v, i) => v != null && oSup[i] && oP25[i] != null && oP75[i] != null && <line key={"ow" + i} x1={xB(i)} x2={xB(i)} y1={yT(oP25[i])} y2={yT(oP75[i])} stroke="#ea580c" strokeWidth={1} opacity={0.55} />)}
        {cool.map((v, i) => v != null && <circle key={"c" + i} cx={xB(i)} cy={yT(v)} r={2.4} fill={cSup[i] ? "#2563eb" : "#ffffff"} stroke="#2563eb" strokeWidth={1.2} />)}
        {oil.map((v, i) => v != null && <circle key={"o" + i} cx={xB(i)} cy={yT(v)} r={2.4} fill={oSup[i] ? "#ea580c" : "#ffffff"} stroke="#ea580c" strokeWidth={1.2} />)}''')
rep('''        <text x={PL + pw + 6} y={yT(cool[cool.length - 1]) + 3} fill="#2563eb" fontSize={8} fontWeight={700}>coolant</text>
        <text x={PL + pw + 6} y={yT(oil.filter(v => v != null).slice(-1)[0]) + 3} fill="#ea580c" fontSize={8} fontWeight={700}>oil</text>''',
    '''        {cLast >= 0 && <text x={xB(cLast) + 6} y={yT(cool[cLast]) + 3} fill="#2563eb" fontSize={8} fontWeight={700}>coolant</text>}
        {oLast >= 0 && <text x={xB(oLast) + 6} y={yT(oil[oLast]) + 11} fill="#ea580c" fontSize={8} fontWeight={700}>oil</text>}''')
rep('''        The vertical gap between the curves is the coolant–oil thermal lag (time bins in seconds)''',
    '''        Vertical gap = coolant minus oil, a temperature difference (°C), median per time bin. Later bins contain only drives that ran that long, so part of the shape of the curve is bin composition, not within-drive warm-up.''')

# 6 KM panel replaces the reachers-only panel
a = s.index('          <div style={{ fontSize: 9, color: "#64748b", marginBottom: 6 }}>MEDIAN OF REACHERS ONLY')
b = s.index('        </div>', s.index('          ))}', a))
new = '''          <div style={{ fontSize: 9, color: "#64748b", marginBottom: 6 }}>KAPLAN–MEIER MEDIAN TIME TO THRESHOLD (s; independent censoring assumed; shares of cold starts reaching a threshold are in the time-to-threshold panel)</div>
          {!kmCoh ? <div style={{ fontSize: 10, color: "#64748b" }}>Kaplan-Meier median not computed for this cohort.</div>
            : ["60", "70", "80"].map(t => {
              const km = (fl) => { const m = kmCoh?.[fl]?.[t]?.median; if (!m) return "—"; if (!m.shown) return m.text || "not shown"; return `${m.point} (${m.ci95?.[0]}–${m.ci95?.[1]})`; };
              return <Row key={t} k={`${t} °C — coolant / oil`} v={`${km("coolant")} / ${km("oil")}`} />;
            })}
          {kmCoh && <div style={{ fontSize: 9, color: "#94a3b8", marginTop: 4 }}>Cold starts in the ledger: {kmCoh.coolant?.["80"]?.n ?? "—"} (coolant), {kmCoh.oil?.["80"]?.n ?? "—"} (oil); days {kmCoh.coolant?.["80"]?.days ?? "—"}.</div>}
'''
nl = '\r\n' if '\r\n' in s[a:b] else '\n'
s = s[:a] + new.replace('\n', nl) + s[b:]
n_ok += 1

# 7 lag and offset rows
rep('''          <Row k="coolant→oil lag to 70 °C (s)" v={`${lag.median} · ${lag.p25}–${lag.p75}`} c="#dc2626" />
          <Row k="steady-state offset (°C)" v={`${off.median} · ${off.p25}–${off.p75}`} c="#ea580c" />''',
    '''          <Row k="coolant→oil lag to 70 °C (s), both reached 70 °C" v={`${lag.median} · ${lag.p25}–${lag.p75}`} c="#dc2626" />
          <Row k="coolant minus oil while coolant ≥ 80 °C (°C)" v={`${off.median} · ${off.p25}–${off.p75}`} c="#ea580c" />''')

# 8 caveat
rep('''Logged ambient falls below 15 °C in the Shoulder class and in the Cold class ({M294.coldNote}). Nothing below {S.ambientTable?.rangeC?.[0]} °C is logged, so these are mild-ambient cold-starts. The cold-start fuel-rate''',
    '''Logged ambient falls below 15 °C in the Shoulder class and in the Cold class ({M294.coldNote}); the logged start-ambient range is {S.ambientTable?.rangeC?.[0]} to {S.ambientTable?.rangeC?.[1]} °C. The cold-start fuel-rate''')

# 9 Compare: pass the series key to get()
rep('''      const vals=series.map(s=>({s,v:m.get(data[s.key])}));''', '''      const vals=series.map(s=>({s,v:m.get(data[s.key],s.key)}));''')
rep('''      const allV=hasAll?m.get(data["all"]):null; const H=23;''', '''      const allV=hasAll?m.get(data["all"],"all"):null; const H=23;''')

# 10 Compare spec for ThermalWarmupLag
a = s.index('  ThermalWarmupLag:{kind:"kpi",title:"Coolant / oil warm-up & thermal lag",metrics:[')
b = s.index('  ThermalFuelPenalty:{kind:"kpi"', a)
nl = '\r\n' if '\r\n' in s[a:b] else '\n'
new = ('  ThermalWarmupLag:{kind:"kpi",title:"Coolant / oil warm-up & thermal lag",metrics:[' + nl +
       '    {label:"Coolant \\u2192 80\\u00b0C, Kaplan\\u2013Meier median",unit:"s",digits:0,get:(d,k)=>{const m=S.thermalSupportLedger?.timeToThreshold?.cohorts?.[k]?.coolant?.["80"]?.median; return (m&&m.shown&&typeof m.point==="number")?m.point:null;}},' + nl +
       '    {label:"Oil \\u2192 80\\u00b0C, Kaplan\\u2013Meier median",unit:"s",digits:0,get:(d,k)=>{const m=S.thermalSupportLedger?.timeToThreshold?.cohorts?.[k]?.oil?.["80"]?.median; return (m&&m.shown&&typeof m.point==="number")?m.point:null;}},' + nl +
       '    {label:"Coolant\\u2013oil lag @70\\u00b0C (both reached 70\\u00b0C)",unit:"s",digits:0,get:d=>cmpDig(d,["coolantOilLag70S","median"])}],' + nl +
       '    note:"Kaplan\\u2013Meier medians come from the support ledger (cohorts all, warm, shoulder); a cohort without a ledger entry (Cold) shows no value: not computed. The lag is conditioned on drives where both fluids reached 70 \\u00b0C. Cohorts are not matched and no contrast is drawn."},' + nl)
s = s[:a] + new + s[b:]
n_ok += 1
open(p, 'w', encoding='utf-8', newline='').write(s)
print("ok edits", n_ok)
