#!/usr/bin/env python3
"""M368: round the displayed kWh / GTC tokens in the session-ledger prose (summary_config.json sessions + sessionGroups).
Spec: analyses/M368_spec.md Rev 2 item 4. A token is rewritten ONLY if (a) the row name resolves to one calendar day and
(b) the 4-dp literal equals round(master day sum, 4). Anything else is REPORTED, never overwritten. Every token is logged
(row, token, old, new, master value) to analyses/M368_ledger_rewrite_log.tsv; the rest to analyses/M368_ledger_unrewritten.tsv.
Usage: python tools/m368_ledger_round.py [--apply]"""
import datetime as dt, json, os, re, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
from m368_fmt import fmt_energy, fmt_cycles

MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
NUM = r"[+-]?\d+\.\d{4}"
PATS = [  # (label, regex with one capture group = the 4-dp literal, master column, formatter)
    ("gross", re.compile(rf"(?<![\w.+-])({NUM})(?= kWh gross)"), "gross_throughput_kwh", lambda x: fmt_energy(x)),
    ("gtc", re.compile(rf"(?<=GTC )({NUM})(?!\d)"), "gtc", lambda x: fmt_cycles(x)),
    ("net", re.compile(rf"(?<![\w.])({NUM})(?= kWh net corr2p sum)"), "net_draw_kwh_corr2p", lambda x: fmt_energy(x, signed=True)),
]


def single_day(name, year):
    """'Sep 22' / 'Sep 07' -> date; None for ranges, '+', AM/PM or anything else."""
    s = re.sub(r"\s+", " ", re.sub(r"[‒-―−–]", "-", str(name))).strip()
    m = re.fullmatch(r"([A-Za-z]{3}) 0?(\d{1,2})", s)
    if not m or m.group(1).title() not in MON:
        return None
    return dt.date(year, MON.index(m.group(1).title()) + 1, int(m.group(2)))


def main():
    apply = "--apply" in sys.argv
    raw_text = open("summary_config.json", encoding="utf-8", newline="").read()
    cfg = json.loads(raw_text)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    dm["_d"] = pd.to_datetime(dm["date"]).dt.date
    year = dm["_d"].iloc[0].year
    sums = dm.groupby("_d")[["gross_throughput_kwh", "gtc", "net_draw_kwh_corr2p"]].sum()
    log, report = [], []
    for field in ("sessionGroups", "sessions"):
        for row in cfg[field]:
            day = single_day(row.get("name"), year)
            note = row.get("note", "")
            for label, rx, col, fm in PATS:
                def sub(m, label=label, col=col, fm=fm, field=field, row=row, day=day):
                    lit = m.group(1)
                    if day is None or day not in sums.index:
                        report.append((field, row["name"], label, lit, "row name not a single resolvable day"))
                        return lit
                    mv = float(sums.loc[day, col])
                    if round(mv, 4) != float(lit):
                        report.append((field, row["name"], label, lit, f"differs from master {mv:.4f}"))
                        return lit
                    new = fm(mv)
                    log.append((field, row["name"], label, lit, new, f"{mv:.6f}"))
                    return new
                note = rx.sub(sub, note)
            row["note"] = note if "note" in row else None
            if "note" not in row or row["note"] is None:
                row.pop("note", None)
    os.makedirs("analyses", exist_ok=True)
    with open("analyses/M368_ledger_rewrite_log.tsv", "w", encoding="utf-8", newline="\n") as f:
        f.write("ledger\trow\ttoken\told\tnew\tmaster_value\n")
        for r in log:
            f.write("\t".join(r) + "\n")
    with open("analyses/M368_ledger_unrewritten.tsv", "w", encoding="utf-8", newline="\n") as f:
        f.write("ledger\trow\ttoken\tliteral\treason\n")
        for r in report:
            f.write("\t".join(r) + "\n")
    roundtrip = json.dumps(json.loads(raw_text), ensure_ascii=False, indent=1) == raw_text
    print(json.dumps({"apply": apply, "tokens_rewritten": len(log), "tokens_reported_not_rewritten": len(report), "writer_roundtrip_byte_identical": roundtrip}))
    if apply:
        if not roundtrip:
            sys.exit("refusing to write: json writer does not reproduce the current file byte-for-byte")
        with open("summary_config.json", "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(cfg, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
