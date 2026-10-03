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
    Rule("W6-equilibrium", "ctx", "Cs-52: a finite maximum over a bounded window does not establish thermal equilibrium (negated forms such as 'not a demonstrated thermal equilibrium' pass)",
         term="thermal equilibrium", near=("reaches", "reaching", "accumulator", "signature", "holds"), window=6),
    Rule("W6-accumulator", "phrase", "Cs-52: 'thermal accumulator reaching equilibrium' is an unestablished mechanism claim", phrase="thermal accumulator"),
    Rule("W6-nearequilibrium", "regex", "Cs-52: warm starts 'are already near equilibrium' is an unestablished claim; say they begin close to their peak", rx=r"\b(?:already )?near equilibrium\b"),
    Rule("W6-literal38", "regex", "Cs-15/E-8: unbound literal 'calc engine load ... averages ~38%' removed from the SoC-pattern section", rx=r"\bcalc(?:ulated)? engine load during these discharge seconds averages 38\b", scope=("jsx",)),   # the same M41 literal in 3 builder/payload strings needs a computed key: W6b
    # W1a (M332): GTR / fuel / generator language (Director constraints: no share direction, no closure words, buffer thesis not resting on the GTR split)
    Rule("W1-buffercorroborated", "regex", "F11.6/D-4: f_gen is a sensitivity index; 'the battery is a buffer, corroborated through the fuel channel' is not supported (F04 open)", rx=r"\bbuffer corroborated through the fuel channel\b"),
    Rule("W1-twothirds", "regex", "F11.9: 'two-thirds of fuel energy lost as heat' follows from an assumed BSFC surface, not a measurement", rx=r"\btwo thirds of fuel energy\b"),
    Rule("W1-nearneutral", "regex", "p18.17: the battery remainder is an unclosed, prior-dependent model residual, not 'near-neutral'", rx=r"\bnear neutral net of\b"),
    Rule("W1-grounded", "regex", "D-6/p18.1: the BSFC surface is an assumed prior; only RPM occupancy is observed", rx=r"\bbsfc anchor is grounded in this corpus\b"),
    Rule("W1-independentpaths", "regex", "F10.3/p24.12: Path A and Path B share priors; their correlation is an association, not independent agreement", rx=r"\btwo independent paths agree\b"),
    Rule("W1-robust", "regex", "p19.11: the f_gen sensitivity range straddles 0.5; the buffer conclusion cannot rest on it", rx=r"\bbuffer conclusion does not (?:depend|hinge) on\b"),
    Rule("W1-bufferthesis", "regex", "Director/W1 constraint: the buffer thesis must not rest on the GTR split ('buffer thesis in miniature', 'core of the buffer argument', 'bidirectional signature of a power buffer', 'buffer does the heavy lifting', 'buffer is real and bidirectional', 'buffer covers the gap', 'buffer relative role recedes')",
         rx=r"\bbuffer thesis in miniature\b|\bcore of the buffer argument\b|\bbidirectional signature of a power buffer\b|\bbuffer does the heavy lifting\b|\bbuffer is real and bidirectional\b|\bbuffer covers the gap\b|\bbuffer s relative role recedes\b|\bfixed point generator takes over\b"),
    Rule("W1-tank", "regex", "F11.9/F17: etas are model-derived indices implied by the assumed BSFC surface, not 'tank-to-traction/bus efficiency'", rx=r"\btank (?:to )?(?:traction|bus|wheel)\b"),
    Rule("W1-fuelchemmeasured", "regex", "C10.11/F2.22: fuel is logged volume x assumed E10 LHV (app-calculated rate), not 'measured'", rx=r"\bfuel chem measured\b|\bmeasured fuel flow\b|\bonly fuel chem is measured\b"),
    Rule("W1-repays", "regex", "D-18: generator and regen are not separately metered; say net pack-energy recovery", rx=r"\bgenerator repays\b"),
    Rule("W1-whygen", "regex", "Cs-24: say observed engine-start contexts, not 'why the generator fires'", rx=r"\bwhy the generator fires\b"),
    Rule("W1-transient", "regex", "F28/D-17: baseline-relative start-impulse index, not 'measured transient buffering' or a capacity multiple", rx=r"\bmeasured transient buffering\b"),
    Rule("W1-roundtrip", "regex", "p17.11: the FCE/EFC gap is a charge-discharge imbalance, not a 'round-trip loss' gap/asymmetry", rx=r"\bround trip loss (?:gap|asymmetry)\b|\basymmetry round trip loss\b"),
    Rule("W1-enrichment", "regex", "p18.2: the HIGH regime note is 'assumed high-load (boost proxy)'; enrichment is untested", rx=r"^enrichment$", scope=("payload",)),
    Rule("M337-fuelmeter", "regex", "M337 Director: the logger counter and rate are logged/app-calculated by Car Scanner; never a fuel meter", rx=r"\bfuel meter\b"),
    Rule("M337-validatedfuel", "regex", "M337 Director: agreement of two app-calculated series is not validation or accuracy of fuel", rx=r"\b(?:accurate|validated|verified) fuel (?:counter|rate|volume|data|consumption)\b"),
    Rule("M337-equivalent", "regex", "M337 Director: the +/-1% review margin is not a justified equivalence bound; no statistical-equivalence claim", rx=r"\bstatistically equivalent\b|\bequivalent to the counter\b"),
    Rule("M337-loggerbias", "regex", "M337 Director: the rate-integral minus counter difference is a consistency check dependent on the dt cap, not a logger bias", rx=r"\blogger bias\b|\bcounter bias\b"),
    Rule("M337-startupfuel", "regex", "M337 Director/audit: a short-trip rate is not fuel wasted at startup", rx=r"\bfuel wasted at start ?up\b"),
    Rule("M337-seasonal", "regex", "M337 Director: the 14-day windows show trip-mix change, not a seasonal trend or an increase in consumption", rx=r"\bseasonal (?:consumption )?trend\b|\bconsumption increased\b|\bconsumption rose\b"),
    Rule("M338-lhv89", "regex", "M338/C05: the SoC-balanced scenario uses the single assumed E10 basis from model_constants; the old literal LHV 8.9 kWh/L basis is retired", rx=r"\blhv 8 9 kwh l\b|\bgasoline lhv 32 mj l\b"),
    Rule("M339-idlewaste", "regex", "M339 Director: stationary fuel is a temporal state of the logged rate, never waste or an idle penalty", rx=r"\bidle waste\b|\bwasted fuel\b|\bfuel wasted\b|\bidle penalty\b"),
    Rule("M339-warmuppenalty", "regex", "M339 Director: warm-up curves are associations by initial coolant; no warm-up, cold-start or startup penalty/fuel claim", rx=r"\bwarm up penalty\b"),
    Rule("M339-measuredstationary", "regex", "M339 Director: logged/app-calculated, never 'measured' stationary fuel or speed-integral quantities", rx=r"\bmeasured stationary fuel\b"),
    Rule("M339-chargingfuel", "regex", "M339 Director: net-pack-charging fuel is a temporal state of the logged rate, not fuel allocated to the battery", rx=r"\bfuel used to charge the battery\b"),
    Rule("M340-hs-sustained", "regex", "M340/F06: the cumulative 130+ km/h exposure is not a sustained or continuous run; the contiguous-run row says contiguous run, the exposure row says cumulative exposure", rx=r"\blongest sustained 130 km h discharge\b|\blongest continuous stretch of net discharge\b"),
    Rule("M340-intake-max", "regex", "M340/F07: the intake-air maximum is a native-sample maximum, not the hottest cabin-sourced air or a bound on the achievable pack minimum", rx=r"\bhottest cabin sourced cooling air\b|\bbounds the achievable pack minimum\b"),
    Rule("M343-coldstartband", "regex", "M343 Director: coolant bands at the onset sample are start context only; no 'cold start' or 'warm restart' label for them", rx=r"\bcold start (?:onsets|bands?)\b|\bwarm restart (?:onsets|bands?)\b"),
    Rule("M343-fuelonstart", "regex", "M343 Director: RPM onsets are not fuel-on starts", rx=r"\bfuel on starts? (?:rate|count)\b|\bmeasured engine start rate\b"),
    Rule("M357-recovery-ratio", "regex", "M357: the approach / launch figure is the per-cycle ratio approach regen / launch discharge (derived), not a 'recovery ratio'", rx=r"\bapproach recovery ratio\b|\brecovery ratio above pools\b"),
    Rule("M357-not-braking", "regex", "M357: no mechanism or signature claim about braking vs engine refill in the Crawl & Stop-Go callout", rx=r"\bnot by braking\b|\brefilled by the engine\b|\bbuffer not braking signature\b"),
    Rule("M357-recovers", "phrase", "M357: reconstructed energies are not 'recovered'", phrase="recovers a median"),
    Rule("M357-closed-gen", "phrase", "M357: no closure claim ('closed by the generator')", phrase="closed by the generator"),
    Rule("M357-returns-nothing", "phrase", "M357: no 'buffer returns almost nothing' claim", phrase="returns almost nothing"),
    Rule("M357-forces-refills", "phrase", "M357: no causal 'forces engine refills' claim", phrase="forces engine refills"),
    Rule("M358-measured-current", "phrase", "M358: peak current is logged (BMS-reported via OBD), not a 'measured quantity' here", phrase="the current in A is the measured quantity"),
    Rule("M358-not-measured-power", "phrase", "M358: kW is derived as logged HV current x logged HV voltage; use that wording, not 'not a measured power'", phrase="not a measured power"),
    Rule("M359-buffer-moves-first", "phrase", "M359: withdrawn wording (marginal medians are not one realised sequence; spec analyses/M359_spec.md Rev 2)", phrase="The buffer moves first"),
    Rule("M359-peaks-before", "phrase", "M359: withdrawn wording (marginal medians are not one realised sequence; spec analyses/M359_spec.md Rev 2)", phrase="peaks ~0.8 s before"),
    Rule("M359-covers-transient", "phrase", "M359: withdrawn wording (marginal medians are not one realised sequence; spec analyses/M359_spec.md Rev 2)", phrase="The buffer covers the transient"),
    Rule("M359-engine-follows", "phrase", "M359: withdrawn wording (marginal medians are not one realised sequence; spec analyses/M359_spec.md Rev 2)", phrase="engine follows and relieves"),
    Rule("M359-power-buffer-handoff", "phrase", "M359: withdrawn wording (marginal medians are not one realised sequence; spec analyses/M359_spec.md Rev 2)", phrase="power-buffer handoff, start to finish"),
    Rule("M359-handed-load", "phrase", "M359: withdrawn wording (marginal medians are not one realised sequence; spec analyses/M359_spec.md Rev 2)", phrase="are handed the load"),
    Rule("M359-full-ordering", "phrase", "M359: withdrawn wording (marginal medians are not one realised sequence; spec analyses/M359_spec.md Rev 2)", phrase="full multi-signal ordering"),
    Rule("M361-cabin-sourced", "phrase", "M361: intake-air channel wording (routing to the pack is not verified; scope is drives with a value; unavailable since the last valid date; spec analyses/M361_spec.md Rev 2)", phrase="Coldest cabin-sourced cooling air"),
    Rule("M361-pack-inlet", "phrase", "M361: intake-air channel wording (routing to the pack is not verified; scope is drives with a value; unavailable since the last valid date; spec analyses/M361_spec.md Rev 2)", phrase="presented to the pack inlet"),
    Rule("M361-inlet-rise", "phrase", "M361: intake-air channel wording (routing to the pack is not verified; scope is drives with a value; unavailable since the last valid date; spec analyses/M361_spec.md Rev 2)", phrase="intake-air inlet to cell temperature"),
    Rule("M361-avg-40min", "phrase", "M361: intake-air channel wording (routing to the pack is not verified; scope is drives with a value; unavailable since the last valid date; spec analyses/M361_spec.md Rev 2)", phrase="averaged across every drive longer than 40 minutes"),
    Rule("M361-coldest-mornings", "phrase", "M361: intake-air channel wording (routing to the pack is not verified; scope is drives with a value; unavailable since the last valid date; spec analyses/M361_spec.md Rev 2)", phrase="coldest mornings"),
    Rule("M362-cold-starts-axis", "phrase", "M362: engine-start counts are detector-defined RPM onsets (not cold starts, not measured, not a per-drive range bar); no unsupported mechanism (spec analyses/M362_spec.md Rev 2)", phrase="Engine cold-starts per 100 km"),
    Rule("M362-how-often-cold", "phrase", "M362: engine-start counts are detector-defined RPM onsets (not cold starts, not measured, not a per-drive range bar); no unsupported mechanism (spec analyses/M362_spec.md Rev 2)", phrase="how often the engine cold-starts"),
    Rule("M362-per-drive-range", "phrase", "M362: engine-start counts are detector-defined RPM onsets (not cold starts, not measured, not a per-drive range bar); no unsupported mechanism (spec analyses/M362_spec.md Rev 2)", phrase="bar = per-drive range"),
    Rule("M362-real-counts", "phrase", "M362: engine-start counts are detector-defined RPM onsets (not cold starts, not measured, not a per-drive range bar); no unsupported mechanism (spec analyses/M362_spec.md Rev 2)", phrase="real detector counts"),
    Rule("M362-measured-starts", "phrase", "M362: engine-start counts are detector-defined RPM onsets (not cold starts, not measured, not a per-drive range bar); no unsupported mechanism (spec analyses/M362_spec.md Rev 2)", phrase="measured starts"),
    Rule("M362-mostly-because", "phrase", "M362: engine-start counts are detector-defined RPM onsets (not cold starts, not measured, not a per-drive range bar); no unsupported mechanism (spec analyses/M362_spec.md Rev 2)", phrase="mostly because short/urban trips never allow the engine"),
    Rule("M360-show-sketch", "phrase", "M360: the allocation sketch is shown by default (owner decision 2026-10-03); no reveal-button wording", phrase="Show allocation sketch"),
    Rule("M360-hide-sketch", "phrase", "M360: no reveal-button wording", phrase="Hide allocation sketch"),
    Rule("M360-sketch-hidden", "phrase", "M360: the sketch is no longer hidden behind a reveal", phrase="hidden by default behind an explicit reveal"),
    Rule("M360-node-closed", "regex", "M360: the generator node/branches are represented with an explicit residual, never 'closed' or 'repaired' (negations such as 'not closed' stay allowed)", rx=r"\bgenerator (node|branches) (is|are|was|were) (now )?(closed|repaired)\b"),
    Rule("M360-gtr-repaired", "regex", "M360: the GTR reconstruction is not 'repaired' or 'closed'", rx=r"\bGTR (reconstruction )?(is |was |has been )?(now )?(repaired|closed)\b"),
    Rule("M360-f04-repaired", "regex", "M360: F04 is not 'repaired', 'closed' or 'resolved'", rx=r"\bF04 (is |was |has been )?(now )?(repaired|closed|resolved)\b"),
    Rule("M359-resolves-sequence", "phrase", "M359: withdrawn wording (marginal medians are not one realised sequence; spec analyses/M359_spec.md Rev 2)", phrase="resolves the sequence of that handoff"),
    Rule("M359-median-timeline", "phrase", "M359: withdrawn wording (marginal medians are not one realised sequence; spec analyses/M359_spec.md Rev 2)", phrase="MEDIAN HANDOFF TIMELINE"),
    Rule("M356-phase-additive", "phrase", "M356 Cs-21: the launch, creep, approach and cycle windows are not additive (they can share one sample)", phrase="windows sum to the cycle"),
    Rule("M355-odo-logging", "regex", "M355 Cs-1: the odometer is a dash reading with a date; logging does not run 'through' the odometer reading", rx=r"\blogging through [\d ]+ km on the odometer\b"),
    Rule("M355-odo-true", "phrase", "M355 Cs-1: the odometer is the instrument-cluster total km from new (dash reading as of a date), not a 'true total'", phrase="true total km from new"),
    Rule("M355-paired-energy", "regex", "M355 Cs-1: the family is named 'Current-integral energy metrics' in S.eligibility", rx=r"\bpaired energy (?:metrics|drives|eligible|count)\b"),
    Rule("M354-cold-zero", "regex", "M354 F08.r1: the Cold class has 2 observed drives (below the cohort minimum); never 'Cold cohort n=0 / has 0 drives'", rx=r"\bcold (?:cohort |class )?(?:currently )?(?:has|n) 0\b"),
    Rule("M353-offset-per-drive", "phrase", "M353 p15.4: the BMS current offset is one corpus-wide constant re-solved per corpus build, not fitted per drive", phrase="fitted per drive"),
    Rule("M353-offset-label", "phrase", "M353 p15.4: registry label is 'one corpus-wide constant', not 'per drive'", phrase="BMS current offset (per drive)"),
    Rule("M353-derived-per-drive", "phrase", "M353 p15.4: the offset class is 'Derived, corpus constant'", phrase="Derived per drive"),
    Rule("M353-signcheck", "phrase", "M353 p15.4: the offset is not sign-checked per drive (single corpus constant)", phrase="Sign-checked per drive"),
    Rule("M353-measured-offset", "phrase", "M353 p15.4: the offset is estimated by a SoC-anchored solve, not measured", phrase="measured offset"),
    Rule("M352-ambient-mean", "regex", "M352 p21.5/p21.6: the table mean is a trapezoidal / start-end-pair / single-reading ambient mean over readings at equal intervals (times not recorded), never a time-weighted or continuous ambient mean", rx=r"\btime weighted mean ambient\b|\bcontinuous(?:ly)? (?:time weighted )?ambient mean\b|\btimed readings\b|\bambient at peak\b"),
    Rule("M352-measured-ambient", "regex", "M352 F13.3: ambient is a driver-recorded dashboard readout, not a measured ambient", rx=r"\bmeasured ambient\b|\bsensor measured outside temperature\b"),
    Rule("M351-noise-null", "regex", "M351 F31.r1: the resistance-record simulation is an IID residual-model reference distribution, not a noise test or a null", rx=r"\bnoise alone (?:produces|yields)\b|\bwithin what noise alone\b|\bpercentile \d+ of that null\b|\babove the null range\b|\bnot a property of the pack\b"),
    Rule("M351-pzero", "regex", "M351 p23.16: a rounded-to-zero p-value is shown as p<0.001, never p=0", rx=r"\bp 0 0+(?= |$)"),
    Rule("M349-glossary-fgen", "regex", "M349: the glossary f_gen / battery-buffer share are bound to the corpus headline (0.466 / 0.534), not the typed literals 0.477 / 0.523", rx=r"f gen 0 477|battery buffer share 0 523"),
    Rule("M348-warmup-title", "regex", "M348 Director: the Compare warm-up pooled line is an n-weighted mean of per-class medians, never an unlabelled warm-up curve", rx=r"coolant warm up curve (?:c |deg c )?vs distance km(?! n weighted mean)"),
    Rule("M348-pooledmedian", "regex", "M348 Director: the Compare warm-up pooled line is a weighted summary of class medians, not a pooled-sample median or a median warm-up curve", rx=r"(?:pooled median warm up|median warm up curve)"),
    Rule("M345-signature", "regex", "M345/M77: run-length invariance across drive type is consistent with, not the signature of, a buffer-limited architecture; it does not separate an energy limit from a controller SoC policy", rx=r"\bsignature of a buffer limited architecture\b"),
    Rule("M336-nodeclosed", "regex", "M336 Director: the generator node is consistent within the dual bracket, not closed under the pre-registered +/-5% rule; no 'node closed/balanced/closure achieved' wording", rx=r"\bgenerator node (?:is )?(?:closed|balanced)\b|\bnode closure (?:achieved|reached)\b"),
    Rule("M336-fullcorpusfgen", "regex", "M336 Director: the closure f_gen covers the fuel-PID subset only, never the full corpus", rx=r"\bfull corpus f gen\b"),
    Rule("W1-independentcorrob", "regex", "p19.13/F10.3: Path A and Path B share priors; not an independent corroboration of M265", rx=r"\bindependent corroboration of m265\b", scope=("payload",)),
    # M333: GTR accounting gate
    Rule("W7-conserved", "regex", "M333/D-5/F04: the generator branches do not close; the revealed sketch is an allocation sketch, not a 'conserved cascade/split' or a 'separate Sankey' per cohort",
         rx=r"\bconserved cascade\b|\btraction supply split conserved\b|\beach cohort is a separate sankey\b"),
    Rule("W7-sensitivityindex", "regex", "M333/W1a: f_gen is an allocation index, not a 'sensitivity index'", rx=r"\bf gen is a sensitivity index\b"),
    # M334: Fuel tab wording (association, scenario, logged/app-calculated; no cost, no cause)
    Rule("W8-penalty", "regex", "F2.18/FUEL-02.A4/D-14/Cs-39: a stratified observational contrast is an adjusted fuel-rate association, not a 'penalty' or a 'cost in fuel'",
         rx=r"\bthermal fuel penalty\b|\bcombustion penalty\b|\bcost in fuel\b|\bfuel cost question\b|\b(?:naive )?trip level penalty\b|\bnaive trip penalty\b|\bnot a winter penalty\b"),
    Rule("W8-literals", "regex", "F1.17: hand-typed fuel literals ('under 0.1 L of fuel-equivalent', 'p95 up to ~2.5', '~3% small') contradict CAP 2.1 kWh / 8.9 kWh/L; values are bound to the payload",
         rx=r"\bunder 0 1 l of fuel equivalent\b|\bp95 up to 2 5 for short\b|\b3 small\b"),
    Rule("W8-fixedfuel", "regex", "FUEL-01.A3: the regression intercept is an unattributed per-trip intercept, not 'per-trip fixed fuel (cold-start/idle)'", rx=r"\bper trip fixed fuel\b"),
    Rule("W8-ecufuel", "regex", "Director M334: the fuel flow is logged/app-calculated (Car Scanner), not an 'ECU fuel-flow PID' measurement", rx=r"\becu fuel flow pid\b|\bfuel flow measured\b"),
    Rule("W8-4b", "regex", "F2.24: use named section references (Fuel tab), not '4b' / '§4b'", rx=r"\b4b generator traction\b|\bsection 4b\b"),
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
