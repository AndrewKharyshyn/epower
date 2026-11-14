"""M652 (gate L): official-disclosure wording leftovers adjacent to M642. Byte-level exact-string edits. ASCII only (non-ASCII via chr)."""
OHM = chr(0x3a9); MU = chr(0x3bc)
def edit(p, pairs):
    b = open(p, 'rb').read()
    for o, n in pairs:
        ob = o.encode('utf-8'); assert b.count(ob) == 1, (o[:70], b.count(ob))
        b = b.replace(ob, n.encode('utf-8'))
    open(p, 'wb').write(b)

edit('xtrail_summary.jsx', [
 ('`motor ${pw.motorRatedKw} kW rated vs ${pw.officialKw} kW battery cap`', '`motor ${pw.motorRatedKw} kW rated vs ${pw.officialKw} kW disclosed battery figure (at ${pw.officialConditionSoc} % SoC)`'),
 ('rising {rz.officialIncreasePct}% to <strong>{rz.officialEolMohm} m' + chr(0x3a9) + '</strong> by {od.expectedLifeKm.toLocaleString("en-US")} km.',
  'rising by up to {rz.officialIncreasePct}% (the sheet\'s maximum) to an implied <strong>{rz.officialEolMohm} m' + chr(0x3a9) + '</strong> (derived: new value x (1 + rise), not a printed figure) by {od.expectedLifeKm.toLocaleString("en-US")} km.'),
])
edit('compute_summary_arrays.py', [("""'measured / modeled figures. Source disclosure and '""", """'logged and estimated figures. Source disclosure and '""")])
# the payload leaf: exact-string edit of the carried text (idempotent)
p = 'summary_arrays.json'
b = open(p, 'rb').read()
o = b"against this study's own measured / modeled figures."; n = b"against this study's own logged and estimated figures."
if b.count(o) == 1:
    open(p, 'wb').write(b.replace(o, n))
else:
    assert b.count(n) == 1, (b.count(o), b.count(n))
print('ok')
