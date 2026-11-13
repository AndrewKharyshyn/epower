"""M630 (W1-06): torque chart wording and clipping. Caption from TQ_MIN/TQ_MAX, the plateau line bound to torqueBySpeed[*].regenMin, a clipped mark with its value for regen minima below the axis, 'commanded (target) torque'."""


def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        ok = False
        for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
            if s.count(oo) == 1:
                s = s.replace(oo, nn)
                ok = True
                break
        assert ok, (p, o[:90], s.count(o))
    open(p, 'w', encoding='utf-8', newline='').write(s)


edit('xtrail_summary.jsx', [
    # plateau from the payload: the regen minimum shared by at least two adjacent speed zones (most zones wins)
    ('''  const zero = yTq(0);

  // Area paths (P90/P10 envelope)''',
     '''  const zero = yTq(0);
  // M630 (W1-06): the regen-minimum plateau is read from the payload (the regenMin value shared by the most speed zones, at least two), not typed
  const _rmZones = {}; D.forEach(d => { if (d.regenMin != null) (_rmZones[d.regenMin] = _rmZones[d.regenMin] || []).push(d.speed); });
  const _plat = Object.entries(_rmZones).filter(([, z]) => z.length >= 2).sort((a, b) => b[1].length - a[1].length)[0];

  // Area paths (P90/P10 envelope)'''),
    ('Motor torque (N·m) · chart clipped at ±160 N·m — peaks above shown as ticks</text>',
     'Commanded (target) motor torque (N·m) · axis {TQ_MIN} to {TQ_MAX} N·m — values beyond it are drawn at the edge with their value</text>'),
    ('''        <line x1={PL} y1={yTq(-163)} x2={PL+pw} y2={yTq(-163)} stroke="#60a5fa" strokeWidth={1.5} strokeDasharray="5 3" opacity={0.7}/>
        <text x={PL+pw-3} y={yTq(-163)-4} textAnchor="end" fill="#60a5fa" fontSize={7.5} opacity={0.9}>regen plateau −163 N·m (20-100 km/h)</text>''',
     '''        {_plat && <g>
          <line x1={PL} y1={yTq(Number(_plat[0]))} x2={PL+pw} y2={yTq(Number(_plat[0]))} stroke="#60a5fa" strokeWidth={1.5} strokeDasharray="5 3" opacity={0.7}/>
          <text x={PL+pw-3} y={yTq(Number(_plat[0]))-4} textAnchor="end" fill="#60a5fa" fontSize={7.5} opacity={0.9}>regen minimum {_plat[0]} N·m in the zones {_plat[1].join(", ")} km/h</text></g>}'''),
    ('''              {/* Regen min tick */}
              <line x1={x-6} y1={yTq(d.regenMin)} x2={x+6} y2={yTq(d.regenMin)} stroke="#60a5fa" strokeWidth={2} opacity={0.7}/>''',
     '''              {/* Regen min tick; a value below the axis is drawn at the edge with its value (M630) */}
              <line x1={x-6} y1={yTq(d.regenMin)} x2={x+6} y2={yTq(d.regenMin)} stroke="#60a5fa" strokeWidth={2} opacity={0.7}/>
              {d.regenMin < TQ_MIN && <text x={x} y={BP_T+BP_H-4} textAnchor="middle" fill="#60a5fa" fontSize={6.5} opacity={0.9}>{d.regenMin}</text>}'''),
    ('transform={`rotate(-90,12,${BP_T+BP_H/2})`}>Torque (N·m)</text>',
     'transform={`rotate(-90,12,${BP_T+BP_H/2})`}>Commanded torque (N·m)</text>'),
])

edit('language_gate.py', [(
    '    Rule("M500-emulation-attribution"',
    '''    Rule("M630-torque-chart-caption", "regex", "M630/self-audit W1-06: the torque chart axis runs from -180 to 160 N.m, so 'clipped at +-160 N.m' was wrong; the regen plateau is read from torqueBySpeed regenMin (-163 N.m in the 20-80 km/h zones, -149 in 80-100, -245 in 0-20, not 20-100 km/h); the signal is the commanded (target) torque",
         rx=r"chart clipped at 160 n m|regen plateau 163 n m 20 100 km h"),
    Rule("M500-emulation-attribution"''')])

edit('semantic_gate.py', [(
    'ok("A2 REQUIRED selector label reads \'Thermal cohort\'", any("Thermal cohort" in t for t in T.values()))',
    'ok("A2 REQUIRED selector label reads \'Thermal cohort\'", any("Thermal cohort" in t for t in T.values()))\n'
    '_tq = A["torqueBySpeed"]; _zc = {}                                                                     # M630 (W1-06): the torque-chart plateau label equals the regenMin plateau of the payload\n'
    'for _d in _tq:\n'
    '    _zc.setdefault(_d["regenMin"], []).append(_d["speed"])\n'
    '_pl = sorted([(v, z) for v, z in _zc.items() if len(z) >= 2], key=lambda x: -len(x[1]))[0]\n'
    'ok("A2 REQUIRED M630 torque chart: caption states the axis, the plateau label equals the payload regenMin plateau, the clipped regen minimum is labelled",\n'
    '   all(("regen minimum %s N·m in the zones %s km/h" % (_pl[0], ", ".join(_pl[1]))) in T.get("distribution__" + m, "") and "axis -180 to 160" in T.get("distribution__" + m, "") for m in ("all",))\n'
    '   and all(str(_d["regenMin"]) in T.get("distribution__all", "") for _d in _tq if _d["regenMin"] < -180))')])
print('ok')
