"""M640 (W1-15): the M119-v2 pack-temperature hazard chart shows its fit domain: the x axis extends to the current observed minimum, the region below the fit floor is shaded and named, and the not-in-fit drive count comes from the monitor keys."""
def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        ok = False
        for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
            if s.count(oo) == 1:
                s = s.replace(oo, nn); ok = True; break
        assert ok, (p, o[:90], s.count(o))
    open(p, 'w', encoding='utf-8', newline='').write(s)

edit('xtrail_summary.jsx', [
 ('    const xmin = B.tpackMinC, xmax = B.tpackMaxC;\n    const ymax = Math.max(...P.hi, 1e-6);',
  '    // M640 (self-audit W1-15): the fit domain is [tpackMinC, tpackMaxC]; the axis also covers the lowest pack temperature observed in the current corpus (monitor key observedRangeC) so the part outside the fit is visible\n'
  '    const fitMin = B.tpackMinC, xmax = B.tpackMaxC;\n'
  '    const obsLo = MON && MON.sides && MON.sides[tag] && MON.sides[tag].observedRangeC ? MON.sides[tag].observedRangeC[0] : null;\n'
  '    const xmin = (obsLo !== null && obsLo < fitMin) ? Math.floor(obsLo) : fitMin;\n'
  '    const ymax = Math.max(...P.hi, 1e-6);'),
 ('          {tailLo > xmin ? <rect x={sx(xmin)} y={mg.t} width={sx(tailLo) - sx(xmin)} height={Hh - mg.t - mg.b} fill="#fef3c7" opacity="0.7" /> : null}',
  '          {xmin < fitMin ? <g><rect x={sx(xmin)} y={mg.t} width={sx(fitMin) - sx(xmin)} height={Hh - mg.t - mg.b} fill="#e2e8f0" opacity="0.9"><title>{`Observed in the current corpus (down to ${obsLo}\u00b0C) but below the fit floor of ${fitMin}\u00b0C: no fitted hazard here`}</title></rect><text x={(sx(xmin) + sx(fitMin)) / 2} y={mg.t + 9} fontSize="6.5" fill="#475569" textAnchor="middle">not in fit</text></g> : null}\n'
  '          {tailLo > fitMin ? <rect x={sx(fitMin)} y={mg.t} width={sx(tailLo) - sx(fitMin)} height={Hh - mg.t - mg.b} fill="#fef3c7" opacity="0.7" /> : null}'),
 ('          <text x={W - mg.r} y={Hh - 3} fontSize="7" fill="#94a3b8" textAnchor="end">{xmax.toFixed(0)}°C</text>\n        </svg>\n      </div>\n    );\n  };\n  const ladderPanel',
  '          <text x={W - mg.r} y={Hh - 3} fontSize="7" fill="#94a3b8" textAnchor="end">{xmax.toFixed(0)}°C</text>\n        </svg>\n'
  '        {MON ? <div style={{ fontSize: 8.5, color: "#64748b", lineHeight: 1.4, marginTop: 2 }}>Fit domain {fitMin}\u2013{xmax}°C{xmin < fitMin ? `; grey: ${obsLo}\u2013${fitMin}°C observed in the current corpus but outside the fit (no fitted hazard)` : ""}. {MON.newDrivesSinceBasis} of {MON.currentNDrives} drives are not in the fit (basis {MON.basisNDrives}).</div> : null}\n      </div>\n    );\n  };\n  const ladderPanel'),
])
print('ok')
