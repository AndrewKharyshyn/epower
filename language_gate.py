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
    def __init__(self, rid, kind, why, phrase=None, rx=None, term=None, near=(), window=4, scope=("dom", "payload", "config", "jsx")):
        self.rid, self.kind, self.why, self.phrase, self.term, self.near, self.window = rid, kind, why, phrase, term, tuple(near), window
        self.scope = tuple(scope)     # where the rule is enforced; a narrower scope is a documented, temporary exemption (see the wave addendum)
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
    Rule("W2-nocold", "regex", "F13.8/D-3/F24: 'no Cold' is false (2 observed drives on 1 date, below support); say 'Cold: N observed, below support'",
         rx=r"\bno cold\b(?! (?:pack|soak|start|season|ambient|cohort|temperature|content))"),
    Rule("W2-sub15", "regex", "D-2/F24/p21.10: 'no sub-15 C data' contradicted (pack probes reach the 'Battery temp min' record; Cold ambient 5 C observed)", rx=r"\bno sub 15"),
    Rule("W2-seasonlabel", "regex", "C11.2/p20.2: the cohort filter is a thermal (ambient) cohort, not a calendar season", rx=r"\bseason filter\b"),
    Rule("W2-warmseason-corpus", "regex", "p21.10: the logged corpus is not 'warm-season only' (Warm + Shoulder, Cold observed on 2 drives)",
         rx=r"\bwhole corpus is warm season\b|\bwarm season data only\b", scope=("dom", "payload", "jsx")),   # config: only the dated drivingMixNote (L1344) is allow-listed -> W2b
    Rule("W3-measuredfade", "regex", "Cs-74: the V-regression resistance is a load-excited proxy; power fade is not 'measured'", rx=r"\bmeasured power fade\b|\bpower fade is measured\b|\bpower fade(?: \w+){0,5} is measured\b"),
    Rule("W3-nodetectable", "regex", "D-15/R11: 'no detectable cell-spread trend' -> trend not resolved, equivalence not established, provenance-sensitive", rx=r"\bno detectable cell spread trend\b"),
    Rule("W3-nofade", "regex", "D-15: the axis zero is 'zero trend', not 'no fade'", rx=r"\bzero no fade\b"),
    Rule("W3-mde", "regex", "F22/D-16/p23.9: mdeRisePctPerYr is a bootstrap CI half-width, not a detection-power / minimum-detectable-effect calculation",
         rx=r"\bmde\b|\bminimum detectable\b|\bdetection (?:limit|floor|power)\b|\b(?:not yet )?resolvable now\b|\bwould need a \d+ month window\b"),
    Rule("W3-wikner", "regex", "R5: the Wikner ladder is a cross-check, not a transferable 'protective/elevated' classification", rx=r"\b(?:protective|elevated) per wikner\b"),
    Rule("W3-sharedcoolant", "regex", "D-12/F27.r1/R2: coolant-loop topology is unestablished", rx=r"\bshared (?:liquid )?coolant loop\b"),
    Rule("W4-measuredcapture", "regex", "F29: KE recovery is an apparent proxy (assumed mass, classifier), not a measured capture efficiency", rx=r"\bmeasured capture (?:efficiency|by pack)\b"),
    Rule("W4-fulldod", "regex", "p15.10/p24.3: the k=2 sum is an uncalibrated depth-squared weighted cycle sum, not 'cumulative damage' / 'full-DoD-equivalents'", rx=r"\bfull dod equivalents?\b|\bcumulative damage\b"),
    Rule("W4-10x", "regex", "p15.10/p24.4: the ~10x depth 'mitigation' is a scenario, not a measured effect", rx=r"\b10(?:x| x)? (?:depth )?mitigation\b|\broughly a 10(?:x| x)? (?:depth )?(?:mitigation|longer)\b"),   # '10×' normalises to '10'
    Rule("W4-ambientbin", "regex", "F12.r3/B-RegenByTempMeasured: the bins are PACK temperature (mean T1-T4 at the decel sample), not ambient", rx=r"\brecovery proxy by ambient bin\b"),
    Rule("W4-pureregenkpi", "regex", "p17.9: engine-off braking regen-at-pack is classifier-conditional (the enum 'Pure regen' stays internal)",
         rx=r"\b(?:peak charging ceiling|high soc ceiling|high soc reduction) pure regen\b"),
    Rule("W4-startproxy", "regex", "B-StartsPer100km/F10.r1: n_sign_crossings counts pack-current direction reversals, not engine starts", rx=r"\bengine start proxy\b"),
    Rule("W5-preinstr", "regex", "F09.r2: the gap is drives without a value on that axis, not 'pre-instrumentation-era files with no pack-temperature channel'",
         rx=r"\bpre instrumentation era files\b|\bno pack temperature channel at all\b"),
    Rule("W5-novel", "regex", "p26.11: no 'first-ever' / 'novel method' claims without a systematic search (regression guard)",
         rx=r"\bfirst ever\b|\bnovel (?:method|approach)\b|\bunprecedented\b"),
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
