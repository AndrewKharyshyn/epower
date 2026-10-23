"""M488 known-answer test of tools/highway_session_gtc.py (audit Update 7 A02): (1) a synthetic Ah ledger where the first day of a session must be INCLUDED (the end-point subtraction of a rounded cumulative ledger drops it);
(2) a declared date without a ledger entry is reported, not zero-filled; (3) the live block is reproduced independently (per-file loop, no groupby) from ah_throughput.csv and agrees with the payload; the payload block splices only
/highwaySessionGtc and its stamp and is idempotent."""
import copy, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import highway_session_gtc as H

CAP = H.CAP_AH_RATED
# (1) synthetic: 3 days, session = d2..d3 inclusive; two drives on d2
ah = pd.DataFrame(dict(file=list("abcd"), date=["2026-01-01", "2026-01-02", "2026-01-02", "2026-01-03"], gross_throughput_ah=[10.0, 20.0, 5.0, 30.0]))
sess = [dict(id="s", label="s", dates=["2026-01-02", "2026-01-03"])]
b = H.build(ah, sess)
assert abs(b["totalGtc"] - (20.0 + 5.0 + 30.0) / CAP) < 1e-6, b["totalGtc"]
assert abs(b["corpusGtc"] - 65.0 / CAP) < 1e-6 and abs(b["sharePct"] - 55 / 65 * 100) < 1e-3
# the end-point subtraction (cum at d3 minus cum at d2) would have given only the d3 day:
cum = {"2026-01-01": 10.0, "2026-01-02": 35.0, "2026-01-03": 65.0}
assert abs((cum["2026-01-03"] - cum["2026-01-02"]) / CAP - 30.0 / CAP) < 1e-9 and b["totalGtc"] > 30.0 / CAP
# a missing Ah entry is not counted and a missing date is listed
ah2 = ah.copy(); ah2.loc[3, "gross_throughput_ah"] = float("nan")
b2 = H.build(ah2, sess)
assert b2["missingDates"] == ["2026-01-03"] and abs(b2["totalGtc"] - 25.0 / CAP) < 1e-6
# two sessions may not share a date
try:
    H.build(ah, [dict(id="a", label="a", dates=["2026-01-01"]), dict(id="b", label="b", dates=["2026-01-01"])]); raise SystemExit("duplicate date accepted")
except AssertionError:
    pass

# (2/3) live block vs an independent per-file loop
live = pd.read_csv("ah_throughput.csv", low_memory=False)
tot = {}
for _, r in live.iterrows():
    if pd.notna(r["ah_throughput"]):
        tot[str(r["date"])] = tot.get(str(r["date"]), 0.0) + float(r["ah_throughput"]) / CAP
A = json.load(open("summary_arrays.json", encoding="utf-8"))
blk = A["highwaySessionGtc"]
want = sum(tot[d] for s in H.SESSIONS for d in s["dates"])
assert abs(blk["totalGtc"] - want) < 1e-5, (blk["totalGtc"], want)
assert abs(blk["corpusGtc"] - sum(tot.values())) < 1e-5 and not blk["missingDates"]
assert abs(blk["sharePct"] - want / sum(tot.values()) * 100) < 1e-3
assert blk["nDeclaredDates"] == sum(len(s["dates"]) for s in H.SESSIONS) == len(blk["declaredDates"])
assert abs(sum(s["gtc"] for s in blk["sessions"]) - blk["totalGtc"]) < 1e-5
dm = pd.read_csv("drive_master.csv", low_memory=False)
assert H.build(H.EF.exposure_frame(dm, H.EF.RATED)) == blk, "payload block differs from a rebuild"
md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
new, ch, bad = H.splice(A, blk, md5)
assert not bad and ch == [] or all(c.startswith("/highwaySessionGtc") or c.startswith("/_artifactStamps/highwaySessionGtc") for c in ch), ch
print("test_highway_session_gtc OK")
