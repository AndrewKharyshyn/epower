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


def prepare(text):
    """Normalise ONE text for all rules: (norm, whitespace-stripped norm, tokens)."""
    n = norm(text)
    return n, n.replace(" ", ""), n.split()


class Rule:
    def __init__(self, rid, kind, why, phrase=None, rx=None, term=None, near=(), window=4, scope=("dom", "payload", "config", "jsx")):
        self.rid, self.kind, self.why, self.phrase, self.term, self.near, self.window = rid, kind, why, phrase, term, tuple(near), window
        self.scope = tuple(scope)     # where the rule is enforced; a narrower scope is a documented, temporary exemption (see the wave addendum)
        self.rx = re.compile(rx) if rx else None
        # M470 (audit speed): everything that depends only on the rule is computed once, not per scanned string
        if kind == "phrase":
            self._prx, self._pstrip = _phrase_rx(phrase), "".join(_words(phrase))
        elif kind == "ctx":
            self._tw, self._nr = _words(term), {norm(x) for x in self.near}

    def hits(self, text):
        return self.hits_prepared(*prepare(text))

    def hits_prepared(self, n, stripped, toks):
        """Same decision as the former per-call implementation, on a text that was normalised ONCE (n = norm(text), stripped = n without spaces, toks = n.split())."""
        if self.kind == "phrase":
            if self._prx.search(n):
                return True
            return len(self._pstrip) >= 12 and self._pstrip in stripped
        if self.kind == "regex":
            return bool(self.rx.search(n))
        if self.kind == "ctx":
            tw, nr, window, ltw = self._tw, self._nr, self.window, len(self._tw)
            for i in range(len(toks) - ltw + 1):
                if toks[i:i + ltw] != tw:
                    continue
                if NEG & set(toks[max(0, i - 3):i]):
                    continue
                lo, hi = max(0, i - window), min(len(toks), i + ltw + window)
                if nr & (set(toks[lo:i]) | set(toks[i + ltw:hi])):
                    return True
            return False
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
    Rule("W2-nocold", "regex", "F13.8/D-3/F24: 'no Cold' is false (Cold drives are observed); say 'Cold: N observed on D dates' with the cohortSupport concentration fields (M487: do not state 'below support' unconditionally)",
         rx=r"\bno cold\b(?! (?:pack|soak|start|season|ambient|cohort|temperature|content))"),
    Rule("W2-sub15", "regex", "D-2/F24/p21.10: 'no sub-15 C data' contradicted (pack probes reach the 'Battery temp min' record; Cold ambient 5 C observed)", rx=r"\bno sub 15"),
    Rule("W2-seasonlabel", "regex", "C11.2/p20.2: the cohort filter is a thermal (ambient) cohort, not a calendar season", rx=r"\bseason filter\b"),
    Rule("W2-warmseason-corpus", "regex", "p21.10: the logged corpus is not 'warm-season only' (Warm + Shoulder, Cold observed on 2 drives)",
         rx=r"\bwhole corpus is warm season\b|\bwarm season data only\b", scope=("dom", "payload", "jsx")),   # config: only the dated drivingMixNote (L1344) is allow-listed -> W2b
    Rule("M395-cadencecontrolled", "regex", "M393/M395: HV-current density enters the powerFade slope as two covariates and the adjustment is only partial (the slope's size and sign depend on how cadence is handled, powerFade.cadenceSensitivity): 'cadence controlled', 'sampling cadence is controlled' and 'held constant in the trend' overstate",
         rx=r"\bcadence controlled\b|\bsampling cadence is controlled\b|\bheld constant in the trend\b|\bcadence and temperature controlled\b"),
    Rule("M395-notpackaging", "regex", "M393/M395: logging density raises the proxy but how much of the uncontrolled slope it explains is not established: 'logging-density artifact, not pack aging' / 'tracks ... not the pack' overstate",
         rx=r"\blogging density artifact,? not pack aging\b|\btracks the mid corpus hv current logging density change,? not the pack\b"),
    Rule("W3-measuredfade", "regex", "Cs-74: the V-regression resistance is a load-excited proxy; power fade is not 'measured'", rx=r"\bmeasured power fade\b|\bpower fade is measured\b|\bpower fade(?: \w+){0,5} is measured\b"),
    Rule("W3-nodetectable", "regex", "D-15/R11: 'no detectable cell-spread trend' -> trend not resolved, equivalence not established, provenance-sensitive", rx=r"\bno detectable cell spread trend\b"),
    Rule("W3-nofade", "regex", "D-15: the axis zero is 'zero trend', not 'no fade'", rx=r"\bzero no fade\b"),
    Rule("W3-mde", "regex", "F22/D-16/p23.9: mdeRisePctPerYr is a bootstrap CI half-width, not a detection-power / minimum-detectable-effect calculation",
         rx=r"\bmde\b|\bminimum detectable\b|\bdetection (?:limit|floor|power)\b|\b(?:not yet )?resolvable now\b|\bwould need a \d+ month window\b"),
    Rule("M408-powerfade-wording", "regex", "M408: the V-regression power-fade trend is an estimated proxy trend that is not resolved in this window; not 'measured', not 'statistically detectable/indistinguishable', not 'detectable'",
         rx=r"\bno statistically detectable power fade\b|\bmeasured trend is statistically indistinguishable\b|\bis the measured trend\b|\bno degradation trend is detectable\b|\bthe measured interval (?:straddles|excludes)\b"),
    Rule("M410-serialdep-readings", "regex", "M410/Director: serial-dependence results are not evidence of absence; HAC/block/GLS rows are partial remedies, not corrections or a primary interval",
         rx=r"\bno serial dependence\b|\bserial dependence is absent\b|\bdays are independent\b|\bcr1 (?:is )?adequate\b|\bdependence robust\b|\b(?:hac|gls|block) (?:slope |interval )?(?:is |are )?(?:the )?(?:corrected|primary)\b"),
    Rule("M415-exposure", "regex", "M415/Director: the rated 5 Ah reference is documentary (not a measurement, not a confirmation of the fitted SoC scale, no derived rated kWh); the legacy 2.1 kWh reference is a different reference, not an error or a correction; a higher count on the rated basis is a reference effect, not more wear",
         rx=r"\b(?<!no )rated kwh\b|\bconfirms? (?:the )?(?:rated|5 ah)\b|\b(?:rated|5 ah) (?:capacity )?(?:is |was )?confirmed\b|\b2 1 kwh (?:is|was) (?:an? )?(?:error|wrong|mistake)\b|\b(?:the )?2 1 kwh (?:figure |value |constant )?(?:was |is )?corrected\b|\b(?:higher|more|increased) (?:wear|degradation|ageing|aging) (?:on|under|with) the rated\b"),
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
    Rule("M366-inside-cis-claim", "phrase", "M366: the replacement is described plainly (FUEL-12 moved outside its previous CI; estimates not claimed to be unchanged; no corrected / inflated wording); Director ruling analyses/M366_spec.md Rev 2", phrase="published estimates remain inside their CIs"),
    Rule("M366-inflated", "phrase", "M366: the replacement is described plainly (FUEL-12 moved outside its previous CI; estimates not claimed to be unchanged; no corrected / inflated wording); Director ruling analyses/M366_spec.md Rev 2", phrase="re-exports inflated"),
    Rule("M366-corrected", "phrase", "M366: the replacement is described plainly (FUEL-12 moved outside its previous CI; estimates not claimed to be unchanged; no corrected / inflated wording); Director ruling analyses/M366_spec.md Rev 2", phrase="after the correction"),
    Rule("M366-prov-sens-label", "phrase", "M366: raw/ now holds the sha256-verified originals (the 333 re-exports were replaced); the old provenance-sensitive / hash-failing wording is withdrawn; spec analyses/M366_spec.md", phrase="provenance-sensitive (F03)"),
    Rule("M366-hash-failing-raw", "phrase", "M366: raw/ now holds the sha256-verified originals (the 333 re-exports were replaced); the old provenance-sensitive / hash-failing wording is withdrawn; spec analyses/M366_spec.md", phrase="hash-failing raw"),
    Rule("M366-hash-passing-raw", "phrase", "M366: raw/ now holds the sha256-verified originals (the 333 re-exports were replaced); the old provenance-sensitive / hash-failing wording is withdrawn; spec analyses/M366_spec.md", phrase="Hash-passing / hash-failing"),
    Rule("M366-archived-copies-fail", "phrase", "M366: raw/ now holds the sha256-verified originals (the 333 re-exports were replaced); the old provenance-sensitive / hash-failing wording is withdrawn; spec analyses/M366_spec.md", phrase="fail both fingerprints"),
    Rule("M366-re-anchoring-undecided", "phrase", "M366: raw/ now holds the sha256-verified originals (the 333 re-exports were replaced); the old provenance-sensitive / hash-failing wording is withdrawn; spec analyses/M366_spec.md", phrase="re-anchoring undecided"),
    Rule("M370-stale-blocks-collective", "phrase", "M370: the five carried-forward GTR blocks are not all on the former re-exports basis (sensitivity, simultaneity, speedSplit sit on older drive sets; crossval on an 82-drive recovered file); each block states its own basis; spec analyses/M370_spec.md Rev 2", phrase="written once by one-off tools and carried forward"),
    Rule("M372-closure-former-reexports", "phrase", "M372: gtrClosure was refreshed on the sha256-verified originals (same 257-drive set); the former-re-exports label no longer describes it; spec analyses/M372_spec.md Rev 2", phrase="computed on the former raw/ re-exports (pre-M366); not refreshed on the originals"),
    Rule("M373-dominant-mode", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="in urban and mixed driving it is the dominant engine-on mode"),
    Rule("M373-clean-monotonic", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="a clean monotonic trend through mixed and mixed-highway"),
    Rule("M373-controller-shaped", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="the high-speed draw is a controller-shaped demand/generation gap"),
    Rule("M373-controller-deliberate", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="the discharge is the controller deliberately under-generating to steer SoC toward its"),
    Rule("M373-gen-arm-flat", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="while the generator arm stays comparatively flat"),
    Rule("M373-fgen-rises-sharply", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="f_gen rises sharply above 60"),
    Rule("M373-same-monotonic-story", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="the same monotonic story as the drive-type view"),
    Rule("M373-binning-artefact", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="is a binning artefact rather than a physical plateau"),
    Rule("M373-near-parity", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="the near-parity of the two lowest bins"),
    Rule("M373-byte-exact-all", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="after validating byte-exact against fuel_recon_master.csv"),
    Rule("M373-speedsplit-earlier-basis", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="is carried at an earlier basis and is not refreshed by ingestion"),
    Rule("M373-aux-better-constrained", "phrase", "M373: the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; interpretive and direction-of-trend wording that the values did not support (or that no test supports) is withdrawn; spec analyses/M373_spec.md Rev 2", phrase="is, if anything, better-constrained than these bounds imply"),
    Rule("M373-pack-absorbing-surplus", "phrase", "M373 (Director string review): the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; wording that the values or a test do not support is withdrawn; spec analyses/M373_spec.md Rev 3", phrase="The pack absorbing surplus at low demand and supplying the gap at high demand"),
    Rule("M373-sens-invariant-title", "phrase", "M373 (Director string review): the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; wording that the values or a test do not support is withdrawn; spec analyses/M373_spec.md Rev 3", phrase="Sensitivity — which conclusions are invariant"),
    Rule("M373-fgen-stays-inside", "phrase", "M373 (Director string review): the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; wording that the values or a test do not support is withdrawn; spec analyses/M373_spec.md Rev 3", phrase="f_gen stays inside"),
    Rule("M373-measured-standstill", "phrase", "M373 (Director string review): the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; wording that the values or a test do not support is withdrawn; spec analyses/M373_spec.md Rev 3", phrase="note the measured key-on standstill draw"),
    Rule("M373-threshold-robustness", "phrase", "M373 (Director string review): the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; wording that the values or a test do not support is withdrawn; spec analyses/M373_spec.md Rev 3", phrase="and by threshold-robustness of the four-state split"),
    Rule("M373-predominantly-charging", "phrase", "M373 (Director string review): the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; wording that the values or a test do not support is withdrawn; spec analyses/M373_spec.md Rev 3", phrase="urban engine-on time is predominantly battery-CHARGING, not battery-assisting"),
    Rule("M373-xval-current-not-stale", "phrase", "M373 (Director string review): the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; wording that the values or a test do not support is withdrawn; spec analyses/M373_spec.md Rev 3", phrase="so its figures are current, not stale"),
    Rule("M373-speedsplit-m255-current", "phrase", "M373 (Director string review): the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; wording that the values or a test do not support is withdrawn; spec analyses/M373_spec.md Rev 3", phrase="and the speed-binned traction split (M255) are current"),
    Rule("M373-sens-m279-recomputed", "phrase", "M373 (Director string review): the refreshed simultaneity / speedSplit / sensitivity blocks are descriptive point values with no interval; wording that the values or a test do not support is withdrawn; spec analyses/M373_spec.md Rev 3", phrase="The sensitivity table was recomputed to the current corpus at the corrected sign (M279)"),
    Rule("M373-sens-recomputed-m279-b", "phrase", "M373 (Director string review): the refreshed blocks are descriptive point values with no interval; stale M279/M280 'recomputed / verified' wording is withdrawn; spec analyses/M373_spec.md Rev 3", phrase="Sensitivity was recomputed to the current corpus at the corrected sign, M279"),
    Rule("M373-already-verified", "phrase", "M373 (Director string review): the speed-split provenance text no longer carries M255-era counts or 'trusted / already-verified / validated to reproduce' wording; spec analyses/M373_spec.md Rev 3", phrase="already-verified per-drive reconstruction machinery"),
    Rule("M373-trusted-formula", "phrase", "M373 (Director string review): the speed-split provenance text no longer carries M255-era counts or 'trusted / already-verified / validated to reproduce' wording; spec analyses/M373_spec.md Rev 3", phrase="a byte-identical copy of the trusted aggregate formula"),
    Rule("M373-validated-to-reproduce", "phrase", "M373 (Director string review): the speed-split provenance text no longer carries M255-era counts or 'trusted / already-verified / validated to reproduce' wording; spec analyses/M373_spec.md Rev 3", phrase="validated to reproduce fuel_recon_master.csv"),
    Rule("M373-all-145", "phrase", "M373 (Director string review): the speed-split provenance text no longer carries M255-era counts or 'trusted / already-verified / validated to reproduce' wording; spec analyses/M373_spec.md Rev 3", phrase="on all 145 fuel-instrumented drives"),
    Rule("M373-standstill-measurement", "phrase", "M373 (Director string review): the speed-split provenance text no longer carries M255-era counts or 'trusted / already-verified / validated to reproduce' wording; spec analyses/M373_spec.md Rev 3", phrase="it is a standstill measurement"),
    Rule("M375-headline-definition-label", "phrase", "M375: the GTR family uses the canonical-clean eligibility (ens_outlier_v2) since M375; the f_gen-not-NaN headline definition, its 'not canonical-clean' labels and the open-item clause are withdrawn; spec analyses/M375_spec.md Rev 3", phrase="drive set = headline definition (f_gen not NaN"),
    Rule("M375-all-261-label", "phrase", "M375: the GTR family uses the canonical-clean eligibility (ens_outlier_v2) since M375; the f_gen-not-NaN headline definition, its 'not canonical-clean' labels and the open-item clause are withdrawn; spec analyses/M375_spec.md Rev 3", phrase="includes drives with NaN f_gen and canonical outliers"),
    Rule("M375-closure-not-canonical-rule", "phrase", "M375: the GTR family uses the canonical-clean eligibility (ens_outlier_v2) since M375; the f_gen-not-NaN headline definition, its 'not canonical-clean' labels and the open-item clause are withdrawn; spec analyses/M375_spec.md Rev 3", phrase="clean = f_gen not NaN, not the canonical rule"),
    Rule("M375-open-item-clause", "phrase", "M375: the GTR family uses the canonical-clean eligibility (ens_outlier_v2) since M375; the f_gen-not-NaN headline definition, its 'not canonical-clean' labels and the open-item clause are withdrawn; spec analyses/M375_spec.md Rev 3", phrase="the headline's departure from the canonical-clean rule is an open item"),
    Rule("M375-old-statistical-unit", "phrase", "M375: the GTR family uses the canonical-clean eligibility (ens_outlier_v2) since M375; the f_gen-not-NaN headline definition, its 'not canonical-clean' labels and the open-item clause are withdrawn; spec analyses/M375_spec.md Rev 3", phrase="share of gross traction demand; clean = f_gen not NaN."),
    Rule("M364-sharpest-test", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="sharpest test of the power-buffer thesis"),
    Rule("M364-clean-signature", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="clean power-buffer signature"),
    Rule("M364-defining-cycle", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="the defining power-buffer cycle"),
    Rule("M364-defining-series", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="the defining series-hybrid signature"),
    Rule("M364-both-faces", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="both faces of power-buffer"),
    Rule("M364-buffer-energy-title", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="Buffer Energy per Cycle"),
    Rule("M364-measured-at-shunt", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="every number under it is measured at the pack shunt"),
    Rule("M364-is-buffer-cycle", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="IS the buffer"),
    Rule("M364-spread-detectable", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="No cell-voltage-spread trend is detectable"),
    Rule("M364-trend-detectable", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="No cell-spread or resistance trend is detectable"),
    Rule("M364-fundamentally", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="fundamentally a power buffer"),
    Rule("M364-not-reservoir-signature", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="buffer-not-reservoir signature"),
    Rule("M364-measured-title", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="Measured pack-terminal energy accounting"),
    Rule("M364-tracks-demand", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="tracks buffering demand"),
    Rule("M364-sourcing-sinking", "phrase", "M364: thesis wording is a qualified description (consistent with / described as), not a test, signature or proof; spec analyses/M364_spec.md Rev 2", phrase="buffer sourcing and sinking exactly"),
    Rule("M363-sign-crossings-prose", "phrase", "M363: the direction-reversal metric is not an engine-start count or proxy; no purpose, wear or controller inference in the engine-cycling text (spec analyses/M363_spec.md Rev 2)", phrase="pack-current sign crossings"),
    Rule("M363-engine-start-proxy", "phrase", "M363: the direction-reversal metric is not an engine-start count or proxy; no purpose, wear or controller inference in the engine-cycling text (spec analyses/M363_spec.md Rev 2)", phrase="Engine-start proxy"),
    Rule("M363-wear-signal", "phrase", "M363: the direction-reversal metric is not an engine-start count or proxy; no purpose, wear or controller inference in the engine-cycling text (spec analyses/M363_spec.md Rev 2)", phrase="mechanical-wear signal"),
    Rule("M363-confirms-speed", "phrase", "M363: the direction-reversal metric is not an engine-start count or proxy; no purpose, wear or controller inference in the engine-cycling text (spec analyses/M363_spec.md Rev 2)", phrase="confirms engine-on is primarily a function of speed"),
    Rule("M363-gen-feeding", "phrase", "M363: the direction-reversal metric is not an engine-start count or proxy; no purpose, wear or controller inference in the engine-cycling text (spec analyses/M363_spec.md Rev 2)", phrase="generator feeding motor"),
    Rule("M363-top-up", "phrase", "M363: the direction-reversal metric is not an engine-start count or proxy; no purpose, wear or controller inference in the engine-cycling text (spec analyses/M363_spec.md Rev 2)", phrase="top up SoC"),
    Rule("M363-setpoint", "phrase", "M363: the direction-reversal metric is not an engine-start count or proxy; no purpose, wear or controller inference in the engine-cycling text (spec analyses/M363_spec.md Rev 2)", phrase="steer SoC back to its setpoint"),
    Rule("M363-start-proxy", "phrase", "M363: the direction-reversal metric is not an engine-start count or proxy; no purpose, wear or controller inference in the engine-cycling text (spec analyses/M363_spec.md Rev 2)", phrase="start PROXY"),
    Rule("M363-proxy-count", "phrase", "M363: the direction-reversal metric is not an engine-start count or proxy; no purpose, wear or controller inference in the engine-cycling text (spec analyses/M363_spec.md Rev 2)", phrase="proxy count"),
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
    Rule("M379-cadence-claim", "ctx", "M379b Director: the emulation is a sampling sensitivity, never a cadence effect that is proven / measured / confirmed / corrected", term="cadence effect", near=("proven", "measured", "confirmed", "corrected", "established", "demonstrated"), window=6),
    Rule("M379-cadence-corrected", "phrase", "M379b Director: no published figure is corrected for cadence", phrase="corrected for cadence"),
    Rule("M379-cadence-bias", "phrase", "M379b Director: cadence bias presents the emulated sampling sensitivity as a bias of the published figures", phrase="cadence bias"),
    # M382 (audit 2026-10-05): wording removed from the dashboard/payload, one rule per replaced statement (old wording + ledger id)
    Rule("M382-F01-nooriginals", "regex", "audit F01: originals exist (recovered, registered, raw/ replaced in M366); 'no original bytes are available' is false", rx=r"\bno original bytes (?:are )?available\b"),
    Rule("M382-F01-archivediffers", "regex", "audit F01: raw/ holds the sha256-verified originals; 'the raw archive held in this repository differs from the originals' describes the pre-M366 state", rx=r"\braw archive held in this repository differs from the originals\b"),
    Rule("M382-F02-identical", "regex", "audit F02: the historical full refit exclusion sets are NOT file-identical (masterRefitAudit.exclusionSets); only the seeded re-run is", rx=r"\bexclusion sets (?:\w+ ){0,5}with identical file identities\b"),
    Rule("M382-F02-purefunction", "regex", "audit F02: a fresh refit does not reproduce the published exclusion set, so 'pure function of current inputs' is unsupported", rx=r"\bpure function of current inputs\b"),
    Rule("M382-F03-zeroenergy", "regex", "audit F03: the two drives carry non-zero released energy (master); 'contribute literal 0.0 kWh' is false", rx=r"\bcontribute literal 0 0 kwh\b"),
    Rule("M382-F08-rpm22", "regex", "audit F08: RPM missingness is a computed per-drive coverage (eligibility.dataCoverage), not a fixed ~22%", rx=r"\brpm has 22 missing samples\b"),
    Rule("M382-F08-1hz", "regex", "audit F08: channels are logged at their own native intervals; no universal 1 Hz / uniform grid statement", rx=r"\b1 hz resampled to a uniform 1 second grid\b"),
    Rule("M382-F09-onepass", "regex", "audit F09: the master is published additively (new files only), not reprocessed in one pass", rx=r"\breprocessed from raw logs in one pass\b"),
    Rule("M382-F09-everyfile", "regex", "audit F09: sign_check is ok on 503 drives, not_testable on 9, missing on 12; 'verified on every file' overstates it", rx=r"\bcharge positive sign convention verified via torque co check on every file\b"),
    # M399 (analyses/M399_wording_spec.md; audits of 2026-10-11): truthful-output wording wave
    Rule("M399-N09-gross2x", "regex", "N09: 'gross runs ~2x net' contradicts the data (gross 1568.9 kWh vs signed net about -49.6 kWh); net I x V is not net SoC change", rx=r"\bgross runs \d+ net\b"),
    Rule("M399-N09-auditfooter", "regex", "N09: the 'audit could not verify raw-stream results' footer is historical; raw/ holds the sha256-verified originals (M366)", rx=r"\baudit could not verify raw stream results\b"),
    Rule("M399-D3-hz", "regex", "D3: the logged PIDs update about every 1.28 s (median interval, ~0.78 Hz), not at '~1.3 Hz' / '~1.26 Hz'; state the interval in seconds first", rx=r"\b1 (?:3|26) hz\b"),
    Rule("M399-F16-linear", "regex", "F16: GTC/FCE (throughput / reference) and C-rate (current / reference charge capacity) scale INVERSELY with the selected reference capacity, not linearly",
         rx=r"\bscales? linearly with (?:the |this |that )?(?:assumed |unverified )*(?:2 1 kwh )?(?:pack )?(?:capacity|constant|value|it|cap kwh)\b"),
    Rule("M399-F16-uniquealt", "regex", "F16/F17: 2.1 and 1.8 kWh are two reference scenarios; 'exactly one credible alternative reference point' is an unsupported uniqueness claim", rx=r"\bexactly one credible alternative\b"),
    Rule("M399-F16-nooem", "regex", "F16/S1: Nissan Australia (13 Oct 2022) publishes 2.1 kWh for the X-Trail e-POWER e-4ORCE without defining gross or usable energy; 'not a published OEM spec / nameplate figure' is a blanket statement that is false; say the basis is undefined and FWD applicability unverified",
         rx=r"\bnot (?:a |an )?(?:published )?oem (?:spec|specification|nameplate)\b|\bdo not publish a cell pack energy capacity spec\b"),
    Rule("M401-N06-hardlevel", "regex", "N06: overlapping windows give a rank RESOLUTION (about 1/(n_eff+1)), not an 'effective hard level' / calibrated false-alarm rate; a non-flag is 'no shift detected', not stable calibration", rx=r"\beffective hard level\b"),
    Rule("M404-percell", "regex", "M404: the Article-10 disclosure (X-Trail e-POWER T33) says 'Rated capacity 5 Ah' (Ah = Wh / nominal battery voltage); it does not say per cell and does not name the drivetrain", rx=r"\b5 0 ah per cell\b|\bah per cell figure\b|\boem disclosed 5 0 ah\b"),
    Rule("W3-power80", "regex", "M406 Director: a minimum effect at the observed standard error is a design-conditional quantity; never 'observed power', 'post hoc power', 'powered to detect' or 'rules out slopes' (W3-mde stays unchanged)", rx=r"\bobserved power (?:of|calculation|analysis|computed|was|is)\b|\bpost hoc power\b|\bpowered to detect\b|\brules? out slopes\b"),
    Rule("M418-thermal-censoring", "regex", "M418/Director: a drive whose observation ended (key-off) before the threshold is right-censored, not a drive that failed to warm up; the reachers-only median is not a typical or cohort warm-up time; risk-set counts are not a survival estimate; no winter warm-up statement from the suppressed cold cohort; fuel is logged/app-calculated",
         rx=r"\b(?:failed|fails|fail|failure) to warm up\b|\bdid not warm up\b|\bnever warmed up\b|\bengine warms up in\b|\btypical warm up time\b|\bmedian warm up time\b(?!.{0,120}\breachers?\b)|\bsurvival (?:curve|estimate|function|probability|analysis)\b|\bwinter warm up\b|\bmeasured fuel\b"),
    Rule("M435-thermal-tte", "regex", "M435/Director (amends M418-thermal-censoring; declared deviation from the M418 ruling): 'Kaplan-Meier' only as 'Kaplan-Meier (product-limit) estimate'; survival wording stays forbidden; the estimate is never a 'cumulative incidence', 'unbiased' or a 'true' time; the worst-case bounds are identification bounds, not confidence intervals; independent censoring is an assumption ('assumes'), informative stopping is not 'shown/proven/confirmed'; the estimate is no probability that the car warms and no typical-trip or fleet statement; the reachers-only median is a comparison, never a cohort median",
         rx=r"\bkaplan meier\b(?! product limit estimate)|\bsurvival (?:rate|time)\b|\bsurvivor function\b|\bcumulative incidence\b.{0,80}\bkaplan meier\b|\bkaplan meier\b.{0,80}\bcumulative incidence\b|\b(?:unbiased|bias corrected|corrects the bias)\b(?=.{0,80}\b(?:warm up|threshold|censor))|\btrue (?:warm up time|time to threshold)\b|\bcensoring (?:is|was|are) (?:non informative|independent|uninformative)\b|\bprobability (?:that )?the (?:engine|car) warms\b|\b(?:robust|insensitive) to (?:the )?censoring\b|\binformative (?:stopping|censoring)\b.{0,40}\b(?:shown|proven|confirmed|demonstrated)\b|\b(?:shows|proves|confirms|demonstrates) (?:that )?(?:informative|non independent)\b|\bis the cohort median\b|\bmeasured time to threshold\b|\btime to threshold s median\b"),
    Rule("M435-thermal-tte-ctx", "ctx", "M435/Director: 'confidence' is not applied to the worst-case (Manski) identification bounds, and warm-up / threshold results carry no typical-trip, fleet or population reading (negations such as 'not confidence intervals' stay allowed)", term="confidence", near=("manski",), window=6),
    Rule("M435-thermal-tte-scope", "ctx", "M435/Director: no typical-trip, fleet or population reading next to the warm-up / threshold results", term="typical trip", near=("warm", "threshold", "censoring"), window=8),
    Rule("M437-fill-sensitivity", "regex", "M437/Director: the forward-fill sensitivity is a range over declared conventions (S0 stays the record, no setting is chosen); the old wording 'the headline classes are unchanged' is replaced by the script-written statement; the range is never 'robust', 'insensitive', 'stable', a 'bound' or 'does not depend on the fill'",
         rx=r"\bheadline classes are unchanged\b|\b(?:robust|insensitive|stable) (?:to|against) the (?:forward )?fill\b|\bdoes not depend on the (?:forward )?fill\b|\bfill (?:limit )?(?:range )?is a bound\b|\bfill\b.{0,40}\b(?:negligible|unchanged|confirmed)\b|\b(?:negligible|unchanged|confirmed)\b.{0,40}\bfill\b"),
    Rule("M438-start-strata", "regex", "M438/Director: the start-temperature strata describe, they do not identify an effect of the start temperature (entangled with season, trip length and the decision to stop); the standardized value is standardized to the observed start-temperature mix, not an adjustment; contrasts are descriptive; nothing 'survives' conditioning",
         rx=r"\bexplained by (?:the )?start temperature\b|\baccounts? for (?:the )?start temperature\b|\b(?:adjusted|controlled|corrected) for (?:the )?(?:start temperature|season)\b|\bcontrols? for (?:the )?(?:start temperature|season)\b|\bsurvives (?:conditioning|stratif)\b|\bremoves the censoring assumption\b|(?<!identify an )\beffect of (?:the )?start temperature\b|\bstart temperature (?:effect|causes)\b|\bcensoring (?:is|are) (?:harmless|ignorable|negligible)\b|\bdose response\b"),
    Rule("M438-start-strata-ctx", "ctx", "M438/Director: no gradient or trend across the start-temperature terciles is claimed (negations such as no gradient is claimed stay allowed)", term="gradient", near=("tercile", "terciles", "start", "temperature"), window=8),
    Rule("M439-regen-wording", "regex", "M439/Director: the regeneration ratio is an apparent, assumed-mass kinetic-energy recovery ratio (charge-direction energy at the battery terminals over the KE loss): not 'measured capture', not 'one series, all measured', not 'real data, not a model', no unidentified cause (drag, rolling, back-EMF, friction-brake blending) and no upper/lower-bound claim; cohort captions are bound to the active cohort",
         rx=r"\bmeasured capture vs speed\b|\bone series all measured\b|\bmeasured capture is a much flatter\b|\bmeasured plateau\b|\bevery measured efficiency figure\b|\breal data not a model\b|\bthe energy actually returned to the battery\b|\bactually recovered into the battery\b|\bupper bounded proxy\b|\brather than a measured conversion efficiency\b|\bcapture sits on a flat plateau\b|\bmotor speed is too low for meaningful back emf\b|\bremainder lost to aero drag\b|\broughly two thirds of braking energy\b|\bdrag rolling dominate\b|\bnot physically different in kind\b|\bengine runs almost continuously there leaving little engine off coasting\b|\btoo brief for sustained braking events\b|\bregen share rises with trip length up to the mixed distance band\b|\bcapture rate is comparable\b|\bof captured energy\b|\bengine off regen captured energy\b|\ba capture proxy\b|\bpower efficiency vs braking speed\b|\bleans on the friction brakes\b|\bshifts more deceleration to friction brakes\b",
         scope=("dom", "jsx", "config")),
    Rule("M440-regen-sensitivity", "regex", "M440/Director: the legacy apparent KE recovery is a declared extraction convention with known weaknesses; its sensitivity is a range over declared conventions, not a correction, an error, a bias, a true value or a defect-free extraction; the low-speed bin is not summarised as one number",
         rx=r"\bdefect free\b|\bcorrected (?:apparent )?(?:ke )?recovery\b|\btrue (?:apparent )?(?:ke )?recovery\b|\b(?:error|bias) of the legacy\b|\blegacy (?:bars|values|estimator) (?:is|are) (?:wrong|biased)\b|\bbin 5 is 1 6\b|\bthe low speed collapse is an artefact\b"),
    Rule("M441-regen-v2", "regex", "M441/Director: the v2 cells are OBSERVED apparent KE recovery ratios with assumed masses (temperature and SOC are confounded in the logged data); no true/real recovery, no cadence-invariance claim, no temperature or SOC effect shown, no BMS limit identified, no SOC standardization claimed for the observed view",
         rx=r"\b(?:true|real|actual) (?:apparent )?(?:ke |kinetic energy )?recovery\b|\bcadence (?:invariant|independent|free)\b|\bindependent of (?:the )?(?:polling|sampling) (?:rate|cadence)\b|\b(?:soc|temperature) (?:effect|dependence) (?:is|was|has been) (?:shown|established|demonstrated|proven|confirmed)\b|\bbms (?:charge )?limit (?:is|was|has been) (?:shown|identified|found|confirmed)\b|(?<!\bnot )\b(?:standardi[sz]ed|adjusted|corrected|controlled) for soc\b|\bcold (?:weather |temperatures? )?(?:reduces|lowers) (?:the )?(?:regen|recovery)\b"),
    Rule("M442-gates", "regex", "M442/Director: the cadence gate G2 was NOT TESTABLE (not passed); the harmonized level is resolution-conditional (3 s grid, assumed mass), cadence is not controlled or removed, and a resolved contrast is descriptive, not an effect",
         rx=r"\bg2 (?:passed|passes|is passed|was passed)\b|\bcadence (?:is |was )?(?:controlled|corrected|neutrali[sz]ed|removed)\b|\bresolution (?:effect |bias )?(?:is |was )?(?:removed|eliminated|corrected)\b|\bresolved (?:effect|difference) (?:is|was) real\b|\b(?:3 s|common) (?:grid|resolution) (?:level|estimate) is (?:the )?(?:true|real|actual)\b"),
    Rule("M444-soc-standardized", "regex", "M444/Director: the SOC-standardized bars adjust for the SOC composition of the groups only (not speed, demand, season, day or cadence); never an effect of temperature, an efficiency, controlled for or independent of SOC, or confirmed by a holdout",
         rx=r"\b(?:controls?|controlled) for (?:the )?soc\b|\bindependent of (?:the )?soc\b|\bconfirmed by (?:the )?hold ?outs?\b|\bhold ?outs? (?:confirm|confirms|confirmed|validate|validates|validated)\b|\bsoc standardi[sz]ed (?:effect|efficiency)\b|\b(?:true|real|causal) effect of (?:the )?(?:pack )?temperature\b|\bremoves? (?:the )?(?:effect of )?soc\b|\bsoc (?:explains?|accounts? for|explained|accounted for) (?:the )?(?:rise|increase|difference)\b|\bdemand adjusted\b|\bno temperature dependence\b|\b(?:the )?(?:bars?|levels?|temperature bins?) (?:are |is )?equivalent\b"),
    Rule("M420-integration-scenarios", "regex", "M420/Director: integration-choice scenarios are single-choice recomputations (deterministic on this corpus), never a total, combined or overall uncertainty, an error budget, a worst case, a bound, the integration error/bias or the accuracy of the throughput; the Monte Carlo interval is conditional and is not drawn around the nominal as accuracy; the midpoint deviation is a rule difference, not an integrator error",
         rx=r"\bshift\b.{0,40}\bexact\b|\binterval around the nominal\b|\bcode correctness cross check\b.{0,30}\bdeviation\b|\b(?<!understate )(?:total|combined|overall|full) uncertainty\b|\berror budget\b|\b(?:measured|true) throughput\b|\baccuracy of the (?:throughput|integration)\b|\bhold variants bracket the truth\b"),
    Rule("M446-stratified-display", "regex", "M446/Director: the stratified display shows NATIVE, resolution-conditional apparent KE recovery per polling stratum; the strata are not comparable and are not contrasted; never a true or more accurate level, an underestimate of one stratum, a cadence-corrected or cadence-adjusted level, a passed G2, a total accuracy interval, or an optimal/peak recovery temperature",
         rx=r"\b(?:true|more accurate) (?:native )?level\b|\b(?:slow|fast) polled (?:drives |stratum )?(?:under|over)estimates?\b|\bcadence (?:corrected|adjusted)\b|\btotal accuracy interval\b|\b(?:optimal|optimum) (?:pack )?temperature\b|\bpeak (?:ke )?recovery\b|\bg2 (?:was |is )?(?:passed|met)\b|\b(?:highest|lowest) recovery at\b|\bcold reduces recovery\b|\bfast vs slow\b|\bresolution corrected\b|\bwithin error\b"),
    Rule("M453-measured-regen-wording", "regex", "M453/language debt: the regeneration capture fraction and the descent-budget charge energy are derived from the logged current and voltage (integrated, assumed mass), not measured quantities",
         rx=r"\bregen capture fraction measured\b|\bpack measured charge energy\b"),
    Rule("M458-standby-wording", "regex", "M458/Director: the Car-OFF standby value is a SoC drift rate (Sen slope, assumed capacity, attribution not identified), not a measured standby power; the bootstrap share of positive draws is not a probability P(draw>0); the interval is day-clustered only for the arrival-day rule",
         rx=r"\bbms telematics sen s slope\b|\bp draw 0\b|\bmeasured standby power\b|\bvalidated standby rate\b"),
    Rule("M460-zero-fuel-wording", "regex", "M460/Director: the zero-fuel state is a ZERO LOGGED (app-calculated) FUEL RATE, not a measured fuel flow and not a physical claim about injection (the phrase fuel cut is legitimate elsewhere in the repository and is checked inside the zeroFuelVariant block by the semantic gate); the two definitions of electric are never called equal or equivalent, and the counter row is not an independent definition",
         rx=r"\binjection off\b|\bburns no fuel\b|\bzero fuel consumption\b|\bmeasured fuel rate\b|\bindependent counter\b"),
    Rule("M421-offset-claims", "regex", "M421/Director (audit F14): the two-pass offset is a model-derived residual-balance offset conditional on the SoC/capacity ledger, not a calibrated sensor zero, a real bias, a corrected or recalibrated sensor, or corroborated by the Ready-mode idle current (which carries auxiliary load); its interval is fit variability",
         rx=r"current sensor (?:offset|bias)|sensor offset residual|real sign consistent|not a fitting artefact|(?:idle hold|ready idle) (?:check|corroborat)|offset (?:is )?(?:corrected|recalibrat)|offset corrected|offset.{0,60}excludes zero|(?<!not a )calibrated (?:sensor )?zero"),
    Rule("M521-timebase-wording", "regex", "M521/Director: engine-on quantities name their time base; the speed-zone share is a share of logged samples (native cadence, not time-weighted), not an engine-on time share; rpm is logged, so 'field-logged', never 'field-measured'",
         rx=r"\bengine on time share\b|\bfield measured refinement\b"),
    Rule("M522-band-occupancy", "regex", "M522/Director: the 300-1400 rpm band share is bound to the payload (low-occupancy, descriptive, no interval); never near-empty, a rev-through, or a literal share of engine-on time; time spent inside the band is not analysed",
         rx=r"\bnear empty\b|\brev through\b|(?<!\d )\b4 of engine on time\b"),
    Rule("M523-historical-rpm-literals", "regex", "M523/Director: the M205/M218 literals (2000.30 rpm, 1500 and 1589, 45/55) are historical re-derivations at 5 rpm resolution and carry the qualifier not recomputed on the current corpus in the same passage; the motored share is bound to the payload hours (no hand-typed 2.5 %); the cross-check says logged, not raw, field telemetry",
         rx=r"\bonly\b 2 5 of the boost classified population\b|\bfrom\b raw field telemetry\b|\b(?:1500 and 1589|45 55)\b(?!.{0,420}\bnot recomputed on the current corpus\b)",
         scope=("dom", "jsx", "config")),
    Rule("M524-timebase-x-lines", "regex", "M524/Director: the engine-state occupancy chart is a share of RPM-supported 1 Hz time (off = rpm < 400), not of engine-on time; the simultaneity table is generator-active time (reconstructed generator power above zero), not rpm engine-on time",
         rx=r"\bengine rpm band occupancy of engine on time\b|\bof pooled engine time\b|\bpooled agrees with the rpm distribution\b"),
    Rule("M525-opt-band-wording", "regex", "M525/Director: the best-point band is an observed occupancy of logged engine rpm bound to rpmOptBand (with its interval); the label steady cruise / generator-charging load is not derivable from an rpm histogram; the stale one-off wording computed once on 397 of 410 drives is gone",
         rx=r"\bsteady cruise generator charging load\b|\bcomputed once on 397 of 410 drives\b", scope=("dom", "jsx", "config")),
    Rule("M526-corpus-size-text", "regex", "M526/Director: payload text must not state a corpus size as live or current when it describes an earlier milestone (446-drive, 320-drive), must not call the superseded 410-drive RPM sample current, and must not carry the hand-typed motored share of the boost-classified population (basis not traceable); applies to the payload as well (the M523 payload exemption is lifted for this pattern)",
         rx=r"\bonly 2 5 of the boost classified population\b|\brefreshed m281 are current\b|\blive 446 drive\b|\bcurrent 320 drive\b"),
    Rule("M528-dated-narrative", "regex", "M528/Director: hand-written dated notes must read as of their date (at that date, then-current); the 2026-07-14 distance-mix note is a dated snapshot that reweights, not corrects, the distance mix; the 374-drive rpmFinding entry is superseded by rpmOptBand (M525)",
         rx=r"\bcurrent dataset distance mix audit 2026 07 14\b|\bcorrects the distance mix\b|\brecomputed on the current 194 drive corpus\b|\bfreshly recomputed from the current 374 drive rpmdistribution\b"),
    Rule("M533-cadence-reference-draw", "regex", "M533/Director: the displayed emulation magnitude (1.6-1.8 mohm) is ONE slow-pool draw; the old bare statement that the thinning lowers the proxy by a-b mohm without the reference-draw qualifier and the spread across draws is forbidden; the min / max across draws is a descriptive range, never an interval, CI or uncertainty bound",
         rx=r"\bno fade rate is claimed emulated slow cadence thinning\b|\b(?:span|range|spread) (?:interval|ci|confidence interval)\b|\binterval of the (?:span|range|spread)\b|\b(?:span|spread) (?:is|as) an? (?:interval|ci)\b"),
    Rule("M535-retired-mix-note", "regex", "M535/Director: the typed 2026-07-14 distance-mix percentages (19 pure-highway, 58 mixed_highway, 77 highway-blended, 16 urban, 6 mixed) are retired from the dashboard, payload and config; they live in the spec and the CHANGELOG only; the live shares are observedMix / observedMixDetail",
         rx=r"\b19 pure highway|\b58 mixed highway|\b77 highway blended km|\b16 urban 6 mixed\b"),
    Rule("M537-cadence-union-spread", "regex", "M537/Director: the displayed spread of the emulated paired difference is the union over the M532 and M534 configurations; the M533 clause (spread over 11 draws and seeds only) is allowed only when it is followed by the sentence that the wider spread over the M534 configurations is not available; the spread is never attributed to (or explained by) the pool draw or the seeds",
         rx=r"across 11 slow pool draws and seeds reference draw included(?!.{0,600}the wider spread over the m534 configurations is not available)|driven by the (?:pool|seeds)|explained by the (?:pool|seeds)|not attributable to the (?:pool|seeds)"),
    Rule("M541-engine-on-label", "regex", "M541/Director: the engine-on rule is logged rpm > 400 (1 Hz grid, strict); shares and hours built on the stored rpm >= 300 bins are labelled as such (rpm >= 300 basis) and are never called engine-on time; the 300-400 rpm band is the low-rpm rotation band, not off-time; the old wording (engine-on time or hours with the bare rpm >= 300, 1 Hz grid basis, and the chart cuts at rpm < 300 comparison) is retired.",
         rx=r"\bengine on (?:time|hours) rpm 300 1 hz grid\b|\bchart cuts at rpm 300\b|\bevery bin except 0 engine off\b", scope=("dom", "jsx")),   # the dated payload strings of the one-off rpm_opt_band estimand keep the rpm >= 300 wording until M543
    Rule("M543-opt-band-label", "regex", "M543/Director: the OPT-band share and the peak-bin share are shares of engine-on time under the project rule (rpm > 400, 1 Hz grid); the interim wording that left them on the rpm >= 300 basis until the rule was applied (and the later step pointer) is retired; stored-bin figures keep their rpm >= 300 basis tag.",
         rx=r"\bof rpm 300 time rpm 300 basis until the engine on rule is applied to this block\b|\bthey move to the rule in a later step\b", scope=("dom", "jsx")),
    Rule("M545-engine-on-native-rows", "regex", "M545/Director: the turbo and Highway-vs-city shares are shares of engine-on NATIVE ROWS (rpm > 400, logged samples, native cadence), not of engine-on time (M521: not time-weighted); the former wording (share of engine-on time at rpm > 300, the gate baked into every band, time-at-this-rpm) is retired; the stored rpm > 300 share is quoted only as the labelled stored basis.",
         rx=r"\bof engine on time n \d+ 0 1 bar\b|\bof engine on time rpm 300 at 0 1 bar\b|\brpm 300 gate baked into every band\b|\bof time at this rpm with boost active\b|\bsecondary context on drives logging boost and rpm pids rpm 300 boost\b", scope=("dom", "jsx")),
    Rule("M545-engine-on-run-wording", "regex", "M545/Director: the run-length and per-speed blocks under the rule are a run-boundary re-definition (rpm > 400, 1 Hz grid; deterministic, same data); they are never called a correction, a true or more accurate engine-on, or a false engine-on, and a change is never presented as a finding",
         rx=r"\b(?:true|more accurate|corrected) engine on (?:run|runs|duration|segment|segments)\b|\bfalse engine on\b|\bengine on (?:run|runs|segment|segments) (?:were|are) (?:wrongly|falsely) (?:merged|counted)\b", scope=("dom", "jsx", "config")),
    Rule("M546-state-machine-off-boundary", "regex", "M546/Director: the engine state machine under the project rule has off = rpm <= 400 (a second at exactly 400 rpm is off); the definition off = rpm < 400 is the stored basis and appears only with the label stored basis (compare-mode titles, the dwell-survival block, the stored-value sentence).",
         rx=r"(?<!stored basis )\boff rpm 400\b(?! the project s engine on rule)(?! strict engine on boundary)", scope=("dom", "jsx")),
    Rule("M530-ledger-corpus-now", "regex", "M530/Director: dated session-ledger notes name their date (corpus as of <date>: N drives); a present-tense corpus now N drives reads false once the corpus has grown; the batch phrase lifts the study to N drives is dated by construction and is not flagged",
         rx=r"\bcorpus now \d+ drives\b"),
    Rule("M527-recomputed-mode-centres", "regex", "M527/Director: the rpm mode centres are RECOMPUTED on the current corpus and bound to rpmModeCentres; a historical value (2000.30 rpm) is dated history only (M205 reported ...) and never stands as the current value; the old not-recomputed qualifier no longer applies to these numbers",
         rx=r"\b2000 30\b(?<!reported 2000 30)", scope=("dom", "jsx", "config")),
    Rule("M531-motored-share-interval", "regex", "M531/Director: the motored share carries its day-clustered interval (or states exploratory, no interval where the support rule fails); the descriptive, no interval label next to the share is gone; grid-only gap-fill is a labelled post hoc sensitivity, never the headline",
         rx=r"\bboost classified engine on hours.{0,140}descriptive no interval\b", scope=("dom", "jsx", "config")),
    Rule("M399-archaeology", "regex", "reader-facing text must not carry change-log history (it belongs in CHANGELOG)",
         rx=r"\bthis paragraph previously quoted\b|\bprior hand typed\b|\bsuperseded 28 w figure\b|\brecomputed 2026 07 10\b|\brefreshed at m373\b"),
    Rule("M427-F04-ev-bound", "regex", "M427/audit F04: the +/-3 s nearest-sample alignment and the symmetric 3 s debounce can move engine-off boundaries in either direction; neither guarantees a one-sided bound; say 'estimated RPM-defined engine-off share' with a detector sensitivity range (not a confidence interval)",
         rx=r"\bbias(?:es)? engine off upward\b|\bev (?:distance|time|share)\b.{0,50}\bupper bound\b|\bevery ev distance and time figure is an upper bound\b"),
    Rule("M427-F09-mix-order", "regex", "M427/audit F09: the selected scenario blend is city 40 / mixed 10 / highway 50; '50/40/10 (city/mixed/highway)' lists the shares in the wrong order", rx=r"\b50 40 10 city mixed highway\b"),
    Rule("M427-F09-gtr-root", "regex", "M427/audit F09: the root generatorTractionRecon staleness note is derived from the per-block producers (refreshedBlocks, staleBlocks, gtrClosure); the old 'script not present / 374-drive M256 basis / does not reflect the current corpus' note is obsolete",
         rx=r"\bgenerating script for this key is not present\b|\bdoes not reflect the current 410 drive corpus\b|\b374 drive m256 corpus basis\b"),
    Rule("M427-F18-isolates", "regex", "M427/audit F18: matched coarse RPM/load or road-speed cells give a conditional contrast; they do not isolate enrichment, cold friction or strategy (coolant, oil, catalyst, route and demand stay entangled)",
         rx=r"\bisolates? enrichment cold friction\b|\bisolates? series hybrid strategy\b|\bisolates? (?:the )?(?:enrichment|friction) (?:and|or) (?:the )?cold\b"),
    Rule("M429-soak-ratio", "regex", "M429/audit F06 (+F05): the coolant and oil tau compared with the pack tau is a point-estimate ratio of fitted summaries with the interval overlap stated; it is not 'physically consistent' evidence and not a 'cross-check that the fit machinery behaves sensibly' (the pack fit has a negative predictive R2); the pooled pack tau rests on parks of an hour or longer (gap split), not on the short gaps",
         rx=r"\bphysically consistent with coolant and oil\b|\bfit machinery behaves sensibly\b|\bindependently known faster cooling\b|\bshort gap behavior it s best supported by\b"),
    Rule("M432-F04-range-reading", "regex", "M432/audit F04: the detector-sensitivity range of the engine-off distance share is a range over declared conventions (paired difference on the drives valid under both settings); it is not a confidence interval, not an 'upper/lower bound' of the share, not 'the true share' and does not make the estimate 'robust' or 'insensitive' to the detector (the RPM threshold alone moves it by about 1-2 percentage points); negations such as 'not a bound on the true share' stay allowed",
         rx=r"\b(?:upper|lower) bound (?:of|on|for) (?:the )?(?:estimated )?(?:rpm defined )?(?:engine off|ev) (?:distance )?share\b|\bthe true (?:engine off|ev) (?:distance )?share (?:is|lies|falls)\b|\b(?:engine off|ev) (?:distance )?share is (?:robust|insensitive) to\b|\bdetector (?:conventions? )?(?:is|are) (?:immaterial|irrelevant)\b"),
    Rule("M430-r2-dismissed", "regex", "M430/audit F05: the in-sample R2 of the parked-soak fits is printed with its plain meaning (the through-origin Sen line against a free-level mean of the log excess ratio); it is not 'not a meaningful diagnostic' and not omitted, and 'the first-order model does not describe the pairs' overstates (a negative R2 does not mean no decay; held-out errors are reported)",
         rx=r"\br2 is not a meaningful diagnostic\b|\bnot a meaningful diagnostic for this fit\b|\bdoes not describe (?:the|these) pairs\b|\bnot that there is no decay\b"),
    Rule("M467-F02-spread-flip", "regex", "M467/audit F02: the controlled cell-spread slope is positive on the current corpus (degradationTrends.cellSpread, cluster-robust OLS); the early-corpus 'flips to -0.39 ... summer confound confirmed' reading is superseded and may appear only as a dated historical note",
         rx=r"\bflips? to 0 39\b|\bconfirming the apparent uptrend was a summer\b|\bsummer (?:heat load )?confound confirmed\b"),
    Rule("M467-F02-nocapacity", "regex", "M467/audit F02: an apparent scale of the logged BMS SoC is estimable (capacityBasis.ahPer100); what is not identified is physical full capacity, accessible capacity and capacity fade; 'no capacity observable' is too absolute",
         rx=r"\bno capacity observable\b|\bcontains no capacity observable\b|\bpassive obd cannot produce (?:a|one)\b"),
    Rule("M469-calendar-literals", "regex", "M469/audit (hardcoded literals): the calendar-aging rate factors are bound to seasonalLife.calendarAnnualFactor / monthly[].calendarFactor and the Arrhenius Ea (0.5 eV); the typed Q10=2 parameterisation, the 0.44 driving-heat uplift with ~1.5% of hours at ~40 C, and the typed winter factor 0.145 are retired (no duty-weighted producer exists)",
         rx=r"\bq10 2\b|\brising to 0 44\b|\b1 5 of hours at 40 c\b|\bwinter quarter factor 0 145\b"),
    Rule("M471-F01-etabus-label", "regex", "M471/audit F01: corpus.etaBus is the GENERATOR-bus / chemical-fuel ratio (glossary term eta tank->bus); the net traction-bus / fuel index is flows.etaTankToTraction (a different number). The M332 label 'Net traction-bus/fuel index' on etaBus mixed the two up",
         rx=r"\bnet traction bus fuel index\b"),
    Rule("M472-cold-single-trip", "regex", "M472/Director: the cold cohort is in effect one trip (cohortSupport): its values are single-trip descriptors, never validated or robust cohort values, never a description of winter behaviour",
         rx=r"\bcold (?:cohort )?(?:is |are |values? (?:is |are )?)?(?:validated|robust)\b|\bcold (?:values?|figures?|cohort) (?:describes?|represents?|shows?) winter\b|\bwinter inference from (?:the )?cold\b"),
    Rule("M473-normal-z-label", "regex", "M473/audit: the released cluster-robust trend intervals use the cluster-t reference t(G-1) (degradationTrends.*.clusterRobustOLS.ciReference); the former label 'cluster-robust (CR1) normal (z) interval' is no longer true",
         rx=r"\bcluster robust (?:cr1 )?normal z interval\b"),
    Rule("M474-capacity-scale-readings", "regex", "M474/audit: the apparent logged-SoC scale (capacityBasis) does not identify full or accessible capacity, state of health, or which of 2.1 kWh / 1.8 kWh is gross or usable; the 5 Ah figure is documentary, not a pack test of this vehicle",
         rx=r"\b(?:confirms?|proves?|shows?|establishes?) (?:that )?(?:the )?(?:2 1 kwh|1 8 kwh)(?: is| are| was)? (?:a )?(?:the )?(?:gross|usable|accessible|full)\b|\bfitted (?:soc )?scale (?:is|equals|gives) (?:the )?(?:usable|accessible|full|physical) capacity\b"),
    Rule("M476-spread-baseline-and-resistance-labels", "regex", "M476/Director (external recheck 2026-10-22): cell_spread_mean_mv is the mean over ALL paired samples of a drive (loaded and low-current), so its median is an all-paired-sample mean spread, never a resting or unloaded spread; the resistanceVreg trend is the sensitivity without a HV-current-density term (the primary resistance estimand is powerFade), never labelled density-adjusted",
         rx=r"\bresting spread median\b|\bunloaded spread grows\b|\bv regression t hv current density adjusted(?! partial)"),
    Rule("M480-spread-proxy-wording", "regex", "M480/Director (2026-10-22): the positive conditional spread slope is an estimated within-window association (about 5 months); the tested drive-level timing and loading-mix proxies do not explain it (provisional; pair-level test M480b pending), but logger-timing confounding is not excluded; never cadence-invariant, a spread slope that is not a logging artefact, a ruled-out logger/cadence effect, controlled-for/removed logger effect, or independent controls (the loading-mix proxies share the outcome loaded pairs)",
         rx=r"\bcadence invariant\b|\b(?:spread|slope)(?: \w+){0,12} not a (?:logging|logger) artefact\b|\brules? out (?:a |the )?(?:logger|logging|cadence)\b|\b(?:controls?|controlled) for (?:the )?(?:logger|logging|cadence)\b|\bremoves? the (?:logger|logging|cadence) effect\b|\btiming (?:and loading mix )?proxies (?:are|were) independent controls\b"),
    Rule("M480b-pair-level-wording", "regex", "M480b/Director (2026-10-22): the pair-level result is consistent, imprecise (unresolved at pair level); the restricted-condition outcome is a fixed-n upper L-statistic (about q0.90), never called p95; the low-current control is not distinguished from zero but imprecise, never a flat or null control; never not-explained-by-the-tested-restrictions, or pair-level confirmed / survives / persists",
         rx=r"\bnot explained by the tested restrictions\b|\bfixed[ -]n(?: \w+){0,4} p95\b|\b(?:o3|low current|negative control)(?: \w+){0,6} (?:shows? no|is flat|flat control|null control)\b|\bpair level(?: \w+){0,3} (?:confirms?|confirmed|survives?|persists?)\b"),
    Rule("M481-resistance-serial-title", "regex", "M481/Director (2026-10-22): the serial-dependence and equivalence rows for the resistance proxy are computed on the V-regression sensitivity design S0 (no HV-current-density term); the primary resistance estimand is powerFade (S1, partial adjustment); the unqualified title Resistance (power) proxy trend followed directly by the observation count is retired; no S1 equivalence verdict exists",
         rx=r"\bresistance power proxy trend (?:\d+ )?observations\b"),
    Rule("M482-power-fade-tab-wording", "regex", "M482/Director labelling (2026-10-22): the power-fade trend is an estimated, model-derived resistance proxy (powerFade, primary, partial adjustment), never measured resistance; the accumulated turnover is integrated from logged current, an estimate, never from measured data",
         rx=r"\bpower fade measured\b|\bresistance rise (?:is )?(?:actually )?measured\b|\bday cumulative from measured data\b"),
    Rule("M483-measured-intensity-wording", "regex", "M483/Director (2026-10-22): the per-class GTC/km intensity is integrated from the logged HV current and voltage and divided by an assumed capacity constant, so it is estimated (from logged current; assumed capacity), never measured, observed or app-calculated (app-calculated applies to the logger fuel rate and counter); the observed logged mix is a logged mix; the M25 resistance null is an estimated proxy result; the evidence class is logged telemetry (thermal sensor readings and negations such as not measured are unaffected)",
         rx=r"\bmeasured mix\b|\bmeasured (?:driving )?intensities\b|\bmeasured driving type intensity\b|\bmeasured per class intensities\b|\bmeasured gtcperkm\b|\bown measured cycling intensity\b|\bmeasured telemetry\b|\bmeasured inputs are those\b|\bmeasured and modeled figures\b|\bworkload is measured\b|\bwhether the measured m25\b|\bobserved estimated gtcperkm\b|\bown observed estimated cycling intensity\b|\bapp calculated (?:per class |driving )?intensities\b|\bobserved logged app calculated (?:per class |driving )?intensities\b"),
    Rule("M484-thermal-sensor-wording", "regex", "M484/Director (2026-10-22): the pack-temperature statistics and the hot-tail inputs come from logged BMS temperature-sensor readings, so they are logged, never measured quantities of a derived model; say logged BMS sensor readings (negations such as not measured, code identifiers and payload keys like packThermalMeasured are unaffected)",
         rx=r"\bthermal exposure is measured\b|\bhot tail measured\b|\bmeasured hot tail\b|\bhot tail (?:above )?is measured\b|\bmeasured hot modeled cold tails\b|\bby the measured af\b|\blargest measured thermal rise\b|\bthis one is measured\b|\bambient measured per class rise\b|\bcool charging exposure is measured\b|\bcool exposure measured\b|\bmeasured thermics\b|\bmeasured high t cycle damage\b"),
    Rule("M485-window-caveat-wording", "regex", "M485/Director (2026-10-22): the window caveat is a descriptive set of nested cumulative refits of the released cell-spread estimator (current code, current corpus), not independent replication, a persistence or stability result, an onset date, or a reconstruction of earlier dashboard releases; the sentence closes with no claim beyond the released interval",
         rx=r"\bcell spread (?:slope )?(?:is |was )?(?:persistent|stable|unstable|robust|confirmed|validated|replicated)\b|\bwindow caveat (?:shows|proves|confirms|demonstrates)\b|\bcumulative refits? (?:replicate|replicates|confirm|confirms|validate|validates|show stability|show persistence)\b|\b(?:first|became) significant (?:at|on|in) (?:the )?(?:cutoff|october|september)\b|\bonset of (?:the )?(?:cell spread )?(?:rise|trend|slope)\b|\bearlier dashboard releases? (?:showed|reported|displayed)\b|\b(?:cutoffs?|refits?|window caveat)(?: \w+){0,10} (?:fragile|mostly null|no effect|significance rate|sensitive endpoint|degradation rate)\b"),
    Rule("M486-primary-equivalence-wording", "regex", "M486/Director (2026-10-23): once powerFadeEquivalence exists the primary design has an equivalence test, so the retired wording that none exists is forbidden in the rendered text and the payload (the JSX fallback literal for a build without the key is exempt); the test is a descriptive TOST at the locked bound over a short window and never proves or confirms the state of the pack",
         rx=r"\bno equivalence test exists for the primary design\b|\bcadence adjusted equivalence of the pack\b|\bequivalence test (?:on the primary design )?(?:proves|confirms|shows) (?:that )?(?:the )?(?:pack|battery|resistance)\b", scope=("dom", "payload", "config")),
    Rule("M507-few-cluster-wording", "regex", "ST-06/M507 (Director): the few-cluster coverage is a stylised simulation of a method property; it is never described as corrected, exact or valid, as the true coverage of a displayed interval or as an adjustment of any interval",
         rx=r"(few|small) cluster (coverage|simulation) (is )?(corrected|exact|valid|adjusted)|true coverage of (the|this|any) displayed interval|intervals? (was|were|are) (corrected|adjusted) for (few|small) clusters|(at least|more than) (20|twenty) (day )?clusters (is|are) (sufficient|reliable|adequate)|(20|twenty) (day )?clusters (is|are) (sufficient|reliable|adequate)"),
    Rule("M505-alignment-wording", "regex", "CD-05/M505 (Director): the alignment rules are a method disagreement of an estimated proxy; no pairing rule is correct, better or proper, the sensitivity is not robust or insensitive in general, nothing is lag-corrected or bias-corrected, and an excludes-zero reading under one rule is not a confirmed trend",
         rx=r"trend (is )?(confirmed|established) (by|under) \w+ (pairing|alignment)|(correct|better|proper) (current voltage )?(pairing|alignment)|lag corrected|logger lag (is )?identified|(robust|insensitive) to (the )?(pairing|alignment)|alignment corrected"),
    Rule("M504-contrast-wording", "regex", "ST-09/M504 (Director): the Warm-vs-Shoulder contrast is an unadjusted comparison of ambient-threshold classes; the same-date and common-support designs are restrictions reported as sensitivity, never adjustments, matched estimates, deconfounded or bias-corrected results or a thermal effect",
         rx=r"(contrast|cohorts?|shoulder|warm) (\w+ ){0,6}(adjusted for|controls? for|after accounting for|deconfounded|bias corrected)|matched estimate|true thermal effect|thermal effect of the contrast"),
    Rule("M503-grid-wording", "regex", "M503/Director (2026-10-24): the logged grid of the CSV copy is not a sensor resolution; a 0.1 V logged step is not a finer or more precise voltage and the coarse-grid window is not described as affected, biased or corrected",
         rx=r"finer (pack )?voltage|more precise (pack )?voltage|voltage resolution (improved|increased)|coarse grid window (affect|bias)|corrected for the coarse grid"),
    Rule("M502-null-result-wording", "regex", "M502/audit ST-10: a non-significant result is an absence of detection, never a genuine null result, and a failure to improve a model does not confirm it is adequate",
         rx=r"genuine null result|which confirms the first order model"),
    Rule("M500-emulation-attribution", "regex", "M500/audit CD-04: the M393 cadence emulation thins each logged column independently and therefore also alters the I-V co-timing; the former wording that sampling alone lowers the proxy, or that I-V co-timing is not emulated, is not supported",
         rx=r"emulated slow cadence sampling lowers the proxy|i v co timing and jitter are not emulated"),
    Rule("M499-resistance-trend-wording", "regex", "M499/Director (2026-10-24): the resistance-proxy months coefficient depends on how temperature enters the model (key-on pack temperature excludes zero, five specifications include it); no specification slope may be described as a rising resistance, an established or significant trend, or a degradation rate, and the key-on result is a noisier proxy, not a trend",
         rx=r"\bresistance is (rising|increasing)\b|\bresistance (trend|slope) is (established|significant)\b|\bsignificant (resistance|power fade) (trend|slope|increase)\b|\bkey on (pack )?temperature (slope|trend) is (a trend|significant|established)\b"),
    Rule("M487-A01-tost-wider", "regex", "M487/audit Update 7 A01: the cell-spread 90% equivalence CI lies wholly above the declared bound (equivalence rejected at that bound); it is NOT 'wider than the bound / inconclusive by design'. Each TOST reading is derived from the metric's own CI and bound (tostReading); 'wider than the bound' is correct only for an interval that straddles it (resistance)",
         rx=r"\bboth (?:slope )?(?:confidence intervals|cis) (?:are )?wider than the bound\b|\bnot because a real drift was found\b|\bslope ci is wider than the bound so neither drift nor equivalence is established\b|\binconclusive by design\b"),
    Rule("M487-A03-cold-below-support", "regex", "M487/audit Update 7 A03: 13 Cold drives are analysed as a cohort against a minimum of 10; the limitation is concentration (one drive holds about 91% of the Cold km, about 1.2 effective dates), shown from cohortSupport. 'Cold-class drives are below minimum support' as an unconditional statement is stale",
         rx=r"\bcold class drives are below (?:the )?minimum support\b|\bthe cold class is below (?:the )?minimum support\b|\banalysed as a cohort below the minimum\b"),
    Rule("M487-A04-coverage-released", "phrase", "M487/audit Update 7 A04: the coverage table column is the CR1 interval with the t(G-1) reference from the historical M410 harness, not the normal-reference 'released CR1'", phrase="Coverage: released CR1"),
    Rule("M491-A08-difference-method", "regex", "M491/audit Update 7 A08: the Warm-vs-Shoulder urban difference interval resamples the union of calendar dates jointly (dates shared by both cohorts together); the former label 'cohort-stratified calendar-day bootstrap (days resampled within each cohort)' described independent per-cohort resampling, which drops the covariance of shared dates (now the stored sensitivity ci95IndependentCohorts, not the displayed interval)",
         rx=r"cohort stratified (?:calendar )?day bootstrap|days resampled within each cohort"),
    Rule("M494-block-sensitivity-wording", "regex", "M494/Director: the week-block and moving-block intervals are a block sensitivity across neighbouring dates (an uncertainty analysis, not a change of the point estimate); the thermal cohorts are ambient-threshold classes confounded with season, date and drift. Block resampling does not 'account for dependence', 'confirm' or 'replicate' the contrast and is not 'robust'",
         rx=r"block (?:bootstrap|sensitivity) (?:confirms|replicates|accounts for)|(?:confirms|replicates) the (?:seasonal )?(?:urban )?contrast|robust(?:ly)? (?:to|across) (?:the )?(?:resampling|block)|accounts? for (?:serial )?dependence|no seasonal effect|(?:borderline|marginal(?:ly)?) significan\w* (?:difference|contrast|gap|interval|endpoint|urban|warm|shoulder)|nearly excludes zero|(?:tighter|more precise) (?:under|with) (?:the )?(?:week |block)"),
    Rule("M495-rolling-origin-wording", "regex", "M495/Director: the rolling-origin evaluation of the declared pipeline design is out-of-time for estimation only (the design was selected on the full data), never prospective; a flag at an origin is a planning-threshold flag, not a refit decision, and the result is not a validation of the model; the verdict says 'flagged' where the specification says 'detected'",
         rx=r"rolling origin (?:evaluation )?(?:is |was )?prospective|prospective rolling origin|(?:validates|validated|proves) the (?:hazard )?(?:model|pipeline)|degradation (?:was )?detected at origin"),
    Rule("M510-A02-shoulder-urbanonly", "regex", "M510/audit 2026-10-25 A02: Shoulder is not urban-only (it holds highway, mixed-highway and mixed drives, about half of its distance); the contrast is restricted to urban trips, the cohort is not; state the route mix from comparisonCube._meta.routeMixByCohort",
         rx=r"\bshoulder is urban only\b"),
    Rule("M510-A02-nohighway-fuel", "regex", "M510/audit 2026-10-25 A02: the SoC-balanced-fuel subset contains highway trips; say 'urban by trip count' and give the distance mix from socBalancedFuel.routeMix, never 'no pure-highway fuel'",
         rx=r"\bno pure highway fuel\b|\bwarm season only no seasonal cold\b"),
    Rule("M510-A02-degradation-claim", "regex", "M510/audit 2026-10-25 sec 5/12: the loaded cell-spread slope is a conditional association, not pack degradation, SOH or ageing; withheld claims",
         rx=r"\bcell spread (?:slope |trend )?(?:proves|confirms|demonstrates|establishes) (?:pack )?(?:degradation|ageing|aging|deterioration)\b|\bpack (?:degradation|ageing|aging|deterioration) is (?:established|proven|confirmed|demonstrated)\b"),
    Rule("M510-A02-capacity-proven", "regex", "M510/audit 2026-10-25 sec 7/12: the logged BMS-SoC energy scale (about 1.8 kWh per 100 points) is an apparent logged-scale estimate; the physical pack capacity is not identified and CAP_KWH stays verified:false",
         rx=r"\b(?:proves|confirms|establishes|demonstrates) (?:that )?(?:the )?(?:full |physical |usable )?(?:pack )?capacity (?:is|of) 1 8\b|\b(?:physical|full) (?:pack )?capacity is (?:proven|confirmed|established) (?:to be )?1 8\b"),
    Rule("M512-A04-engine-runtime", "regex", "M512/audit 2026-10-25 A04: engine_on_pct x duration_s is a duration-scaled (imputed) estimate, not total or measured engine runtime; the engine-on time is stated inside RPM-supported intervals (eng_rpm > 400: rotating, not necessarily fuelled) with the unsupported time beside it",
         rx=r"\btotal engine (?:generator )?runtime\b|\b(?:measured|exact) (?:total )?engine (?:on )?(?:time|runtime|hours)\b|\bengine on seconds engine on pct duration s\b"),
    Rule("M514-joint-matrix-wording", "regex", "M514/Director (2026-10-25): the joint instrumentation matrix reads 'procedure-dependent, unresolved'; the cells share the same drives and are not independent; G1/G2 are aliased with calendar time and G1 is not blind; never 'positive in every cell' alone, 'consistently positive', 'robust across the matrix', 'insensitive to' a choice, a better/preferred/best cell",
         rx=r"\bpositive in every cell\b|\bconsistently positive\b|\b(?:better|preferred|best) cell\b|\bmatrix (?:confirms|proves|establishes)\b|\brobust across (?:the )?(?:matrix|cells|specifications)\b|\binsensitive to (?:the )?(?:alignment|grid|cadence|temperature)\b"),
    Rule("M517-class-rate-wording", "regex", "M517/Director (2026-10-26): per-class engine-on rates are descriptive, not adjusted for speed or route mix, and class intervals are not a between-class test; never 'urban uses the engine more', 'significantly higher', or a ranking drawn from the class rates",
         rx=r"\burban (?:uses|runs) the engine more\b|\b(?:significantly|reliably) (?:higher|lower) (?:engine|rate)\b|\bclass rates? (?:differ|are different) (?:significantly|reliably)\b"),]

_SCAN_CACHE = {}


def scan_text(text, rules=RULES):
    """Rule ids that hit `text`, in rule order. M470: the text is normalised once for all rules and the result is cached per text for the shared RULES list; a cached result is returned as a copy."""
    if rules is not RULES:      # only the shared module list is cached (a caller's temporary list could reuse an object id)
        prep = prepare(text)
        return [r.rid for r in rules if r.hits_prepared(*prep)]
    key = (text, len(rules))
    hit = _SCAN_CACHE.get(key)
    if hit is None:
        prep = prepare(text)
        hit = tuple(r.rid for r in rules if r.hits_prepared(*prep))
        if len(_SCAN_CACHE) > 20000:
            _SCAN_CACHE.clear()
        _SCAN_CACHE[key] = hit
    return list(hit)


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


def cell_spread_trend_violations(ci95, texts):
    """M427 (audit F01): fact-aware check. `ci95` is the released cell-spread interval (degradationTrends.cellSpread.clusterRobustOLS.ci95), `texts` {name: rendered text}.
    A rendered sentence that calls the cell-spread trend null while the interval excludes zero (or a positive-slope sentence while it spans zero) is a violation.
    Returns [(name, phrase)]. The wording is derived in the dashboard (trendLabel/spreadSpans); this is the independent check."""
    spans = ci95[0] <= 0 <= ci95[1]
    null_ph = ("no directional cell-spread trend", "cell-spread trend not resolved", "no difference from the may baseline is resolved", "spread trend is indistinguishable from zero",
               "remains statistically indistinguishable from zero", "no resolved trend in the", "no directional trend is resolved")
    pos_ph = ("positive conditional cell-spread slope", "positive conditional slope")
    bad = []
    for k, t in texts.items():
        low = re.sub(r"\s+", " ", t).lower()
        for ph in (pos_ph if spans else null_ph):
            if ph in low:
                bad.append((k, ph))
    return bad
