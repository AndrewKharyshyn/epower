#!/usr/bin/env python3
"""Prepend a CHANGELOG entry by CONCATENATION (never a boundary-spanning str_replace). The entry is inserted before the
first existing '## M...' heading; the preamble (if any) stays above.
Usage: python tools/changelog_draft.py --id M300 --title "..." --rationale "..." [--files a b] [--date YYYY-MM-DD] [--dry-run]
Gates are filled from the latest runs/*/status.json; corpus state from state.json; flags from delta_report.json."""
import argparse, datetime as dt, glob, json, os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P = lambda *a: os.path.join(ROOT, *a)


def jload(p):
    return json.load(open(p)) if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True); ap.add_argument("--title", required=True); ap.add_argument("--rationale", required=True)
    ap.add_argument("--files", nargs="*", default=[]); ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    runs = sorted(glob.glob(P("runs", "*", "status.json")))
    st = jload(runs[-1]) if runs else None
    state = jload(P("state.json")) or {}
    delta = jload(P("delta_report.json")) or {}
    dmi = state.get("drive_master") or {}
    lines = [f"## {a.id} ({a.date}): {a.title}", "",
             f"**Rationale.** {a.rationale}", "",
             f"**State.** `drive_master.csv` {dmi.get('rows')} rows, MD5 `{dmi.get('md5')}`.", ""]
    if st:
        lines.append("**Gates (runs/%s).** " % st["run"] + "; ".join(f"{s['id']}={s['status']}" for s in st["stages"]) + f" -> {st['result']}.")
        lines.append("")
    if delta:
        lines.append("**Delta flags.** " + ("; ".join(delta.get("flags", [])) or "none") + ".")
        lines.append("")
    if a.files:
        lines.append("**Files.** " + ", ".join(f"`{f}`" for f in a.files) + ".")
        lines.append("")
    entry = "\n".join(lines) + "\n"
    old = open(P("CHANGELOG.md"), encoding="utf-8").read()
    m = re.search(r"(?m)^## M\d", old)
    pos = m.start() if m else 0
    new = old[:pos] + entry + "\n" + old[pos:]
    if a.dry_run:
        print(entry); return
    open(P("CHANGELOG.md"), "w", encoding="utf-8").write(new)
    print(f"prepended {a.id} ({len(entry)} chars); CHANGELOG now {len(new)} chars")


if __name__ == "__main__":
    main()
