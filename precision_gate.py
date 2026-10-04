"""precision_gate.py (M368, gate A3): rendered numbers must not carry unjustified precision.

Input: per-leaf records written by dump_tabs.js (tabtext/_precision_leaves.json: {tab, mode, text} for every leaf element whose OWN
text holds a number with >= 5 decimals, or a raw 'p=0.000...' string). A leaf FAILS if it holds a number with more than 4 decimals AND
more than 3 significant figures (so small rates shown to 3 significant figures pass), or any raw p-value string (use fmtP), unless an
allow-list entry matches it exactly. Allow-list (analyses/M368_precision_allowlist.json): entries keyed by tab + exact leaf text, each
with class, reason and milestone; no wildcards; an entry that matches nothing is an orphan and also fails (the list cannot grow
silently). Adding an entry after M368 needs a Director ruling noted in the CHANGELOG (Director, 2026-10-04)."""
import re

NUM = re.compile(r"(?<![\w.])-?\d[\d,]*\.(\d{5,})(?!\d)")
RAWP = re.compile(r"\bp=0\.0{3}")


def sig_figs(token):
    digits = re.sub(r"[^\d]", "", token.split(".")[0] + "." + token.split(".")[1]).lstrip("0")
    return len(digits)


def leaf_violations(text):
    out = []
    for m in NUM.finditer(text):
        tok = m.group(0).lstrip("-").replace(",", "")
        if sig_figs(tok) > 3:
            out.append(m.group(0))
    if RAWP.search(text):
        out.append("raw p string")
    return out


def check(leaves, allow):
    """-> (violations [(tab, mode, text, tokens)], orphans [entry])"""
    key = lambda tab, text: (tab, " ".join(text.split()))
    allowed = {key(e["tab"], e["text"]): e for e in allow}
    used, viol = set(), []
    for lf in leaves:
        toks = leaf_violations(lf["text"])
        if not toks:
            continue
        k = key(lf["tab"], lf["text"])
        if k in allowed:
            used.add(k)
        else:
            viol.append((lf["tab"], lf["mode"], lf["text"][:120], toks))
    orphans = [e for k, e in allowed.items() if k not in used]
    return viol, orphans
