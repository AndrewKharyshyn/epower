#!/usr/bin/env python3
"""language_gate.py (M326): robust forbidden-wording matcher used by semantic_gate.py check A2 (spec analyses/M326_spec.md rev 2).

Matching rules (Director, M326 rev 2): NFKC normalisation; case-insensitive; arrows, hyphens, slashes, punctuation and runs of spaces collapse to ONE
space; word-bounded with an optional s/es suffix on every word (plural-safe: 're-serialization' and 're-serializations'); a whitespace-STRIPPED form is
also searched for phrases of >= 12 characters (the jsdom tab dumps concatenate words); context rules (term near other terms within N tokens, with a
negation allowance 'not/never/no/nor/cannot' in the 3 tokens before the term). Payload checks use STRING VALUES only, never key names. jsx: strings and
JSX text FAIL, comments WARN. Known-answer fixtures: tests/synthetic/test_language_gate.py."""
import re, unicodedata

NEG = {"not", "never", "no", "nor", "cannot", "without"}


def norm(t):
    t = unicodedata.normalize("NFKC", str(t)).lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _words(phrase):
    return norm(phrase).split()


def _phrase_rx(phrase):
    w = _words(phrase)
    return re.compile(r"\b" + r"\s+".join(re.escape(x) + r"(?:s|es)?" for x in w) + r"\b")


def hit_phrase(phrase, text):
    """True if `phrase` occurs in `text` under the matching rules (spaced form, or stripped form for phrases >= 12 characters)."""
    n = norm(text)
    if _phrase_rx(phrase).search(n):
        return True
    p = "".join(_words(phrase))
    return len(p) >= 12 and p in n.replace(" ", "")


def hit_ctx(term, near, text, window=4, allow_negated=True):
    """term within `window` tokens of any word in `near`; a term preceded (3 tokens) by a negation is allowed when allow_negated."""
    tw = _words(term)
    toks = norm(text).split()
    nr = {norm(x) for x in near}
    for i in range(len(toks) - len(tw) + 1):
        if toks[i:i + len(tw)] != tw:
            continue
        if allow_negated and NEG & set(toks[max(0, i - 3):i]):
            continue
        lo, hi = max(0, i - window), min(len(toks), i + len(tw) + window)
        if nr & (set(toks[lo:i]) | set(toks[i + len(tw):hi])):
            return True
    return False


class Rule:
    def __init__(self, rid, kind, why, phrase=None, rx=None, term=None, near=(), window=4):
        self.rid, self.kind, self.why, self.phrase, self.term, self.near, self.window = rid, kind, why, phrase, term, tuple(near), window
        self.rx = re.compile(rx) if rx else None

    def hits(self, text):
        if self.kind == "phrase":
            return hit_phrase(self.phrase, text)
        if self.kind == "regex":
            return bool(self.rx.search(norm(text)))
        if self.kind == "ctx":
            return hit_ctx(self.term, self.near, text, self.window)
        raise ValueError(self.kind)


# W0 rules (ledger ids in the reason). Later waves append here, each with the removed wording and its ledger id.
RULES = [
    Rule("W0-fuelpid", "phrase", "F2.22/D-S7: fuel rate IS logged (app-calculated) on a subset of drives", phrase="no fuel-rate PID"),
    Rule("W0-fuelflow", "regex", "F2.22/F34.r3: 'no fuel-flow data/channel' is false", rx=r"\bno fuel flow (?:data|channel)s?\b"),
    Rule("W0-greatmajority", "ctx", "F2.22: 'great majority' + fuel/PID claim is false (fuel rate present on a subset)", term="great majority", near=("fuel", "pid", "maf"), window=12),
    Rule("W0-amplitude", "phrase", "p14.11: the rainflow floor is a cycle RANGE (rainflow.extract_cycles c[0]), not an amplitude", phrase="amplitude floor"),
    Rule("W0-zerogtc", "regex", "p4.3: non-integrable logs carry no GTC value (missing), they are not 'contributing 0.0 / 0 / zero GTC'", rx=r"\bcontribut\w* (?:0 0|0|zero) gtc\b"),
    Rule("W0-fuelflow-avail", "regex", "F34.r3/F2.22: 'fuel-flow/injector data not available', 'requires fuel-flow data the logger does not provide', 'carries no fuel-flow channel' are false (fuel rate is logged, app-calculated, on a subset)",
         rx=r"\bfuel flow (?:\w+ ){0,3}(?:data|channel)s?\b(?: \w+){0,6} (?:not available|not provide|does not provide)|\bcarries no fuel flow\b"),
    Rule("M325-410", "phrase", "F01.r3/D-1: 410/410 byte-identical is contradicted (333/489 fail)", phrase="410/410"),
    Rule("M325-reserialize", "regex", "F01.r3/Cs-76: transfer re-serialization is not the established cause", rx=r"\bre ?serializ\w*"),
    Rule("M325-originals", "regex", "E-N1: originals were recovered (M323)", rx=r"\boriginals (?:are )?unavailable\b"),
]


def scan_text(text, rules=RULES):
    return [r.rid for r in rules if r.hits(text)]


def payload_strings(o):
    """String VALUES only (never keys)."""
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from payload_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from payload_strings(v)


def scan_payload(obj, rules=RULES):
    out = {}
    for s in payload_strings(obj):
        for rid in scan_text(s, rules):
            out.setdefault(rid, []).append(s[:80])
    return out


def split_jsx(src):
    """(code_text, comment_text): crude but conservative; // comments only when preceded by whitespace/line start, /* */ blocks removed."""
    comments = re.findall(r"/\*.*?\*/", src, flags=re.S)
    code = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    cm, lines = [], []
    for ln in code.split("\n"):
        m = re.search(r"(^|\s)//(.*)$", ln)
        if m and "://" not in ln[max(0, m.start() - 6):m.start() + 3]:
            cm.append(m.group(2))
            ln = ln[:m.start()]
        lines.append(ln)
    return "\n".join(lines), "\n".join(comments + cm)


def scan_jsx(src, rules=RULES):
    code, comm = split_jsx(src)
    return scan_text(code, rules), scan_text(comm, rules)
