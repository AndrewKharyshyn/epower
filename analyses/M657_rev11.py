"""Apply the Director review (verdict revise) to analyses/M657_spec.md -> Rev 1.1. ASCII only."""


def rep(t, o, n):
    assert t.count(o) == 1, (o[:80], t.count(o))
    return t.replace(o, n)


p = 'analyses/M657_spec.md'
t = open(p, encoding='utf-8').read()
t = rep(t, '# M657 spec (Rev 1, DRAFT for Director review)', '# M657 spec (Rev 1.1, Director review applied; owner decisions O1 and O2 below pending)')
t = rep(t, 'Status: PRE-REGISTERED DRAFT, written before any result of this analysis exists. Date 2026-11-14.',
        'Status: PRE-REGISTERED, written before any result of this analysis exists. Date 2026-11-14. Rev 1.1 applies the Director review (verdict revise; changes R1-R11 in section 9). '
        'Already seen before pre-registration (disclosed): the M627 block (input time at or above 63.70 kW is 70 to 91 % by era, the output limit is not constant, utilisation maximum 1.171); '
        '3 of the 432 drives with the channel are not analysed in M627 (unusable I x V pairing), the same exclusion applies here.')
t = rep(t, 'how much logged time and how many independent days support each cell, and how often does the reported value sit at the ceiling that may be a saturated byte?',
        'how much logged time and how many independent days support each cell, and how often does the reported value sit at the logged maximum (63.70 kW or above) that may be a saturated byte? '
        'The channel is logged by the Car Scanner ELM OBD2 app (logged / app-calculated).')
t = rep(t, 'the power that the BMS reports as possible (input = charge acceptance, output = discharge capability)', 'the power that the BMS reports as possible (input possible power and output possible power channels)')
t = rep(t, 'Sample rule: a possible-power sample is used at its own timestamp (no hold across gaps longer than 15 s; the time weight of a sample is min(gap to the next sample of the channel, 15 s));',
        'Sample rule: a possible-power sample is used at its own timestamp (no hold across gaps longer than 15 s; the time weight of a sample is min(gap to the next sample of the channel, 15 s); '
        'the last sample of a drive carries the median gap of that drive, at most 15 s);')
t = rep(t, 'Cells: pack temperature bins of 5 C from the observed minimum to the maximum (open ends merged only when below the support floor);',
        'Cells: pack temperature bins of 5 C with edges at multiples of 5 C anchored at 0 C (fixed, they never move between ingestions; an end bin below the support floor is listed as not shown, not merged);')
t = rep(t, 'the **ceiling share** (time share of samples at or above the ceiling flag 63.70 kW for input, per-era output ceiling from the M627 block for output), and the **below-ceiling** median and 5th percentile (labelled conditional on the reported limit being below the ceiling; descriptive, no censoring correction).',
        'the **logged-maximum share** (time share of samples at or above 63.70 kW, the same byte-maximum flag for both directions; deviation from Rev 1, which assumed an output ceiling: the output limit is not constant, '
        'kW era 41.5 to 63.75 kW, so for output the flag is a logged-maximum marker, not a ceiling), and the **below-maximum** median and 5th percentile (conditional on the reported value being below the logged maximum; '
        'descriptive, selected on the outcome, so composition can drive a trend; no censoring correction). Where the median or the 95th percentile of a cell is at or above 63.70 kW it is printed as '
        '"at the logged maximum (>=63.70 kW)", not as a number, and a zero-width interval is flagged degenerate, not precise.')
t = rep(t, 'A cell is **supported** with at least 10 drives on at least 5 days and 600 s; **exploratory** below 10 effective days (no reading class); otherwise **not shown** (reason printed).',
        'Support ladder (ordered): **not shown** below 10 drives on 5 days and 600 s (reason printed); **exploratory** when those floors are met and the effective days are below 10 (point and interval only, no reading class); '
        '**supported** with effective days >= 10. Only supported cells feed the reading ladder, the monotone rule and the winter rule.')
t = rep(t, 'Intervals: day-clustered percentile bootstrap on calendar day, seed 42, 4000 draws, for the median and the ceiling share of supported cells;',
        'Intervals: day-clustered percentile bootstrap on calendar day, seed 42, 4000 draws, resampling the cell\'s OWN days (a thin cell cannot be emptied by days that are not in it), for the median, the 5th and 95th percentile '
        'and the logged-maximum share of every shown cell; the median-of-medians sensitivity uses the same day resampling with the per-drive medians re-taken in each draw;')
t = rep(t, 'A monotone-in-temperature statement is allowed only if it holds in every pair of neighbouring supported bins of the row and the day-clustered intervals of the end bins do not overlap; otherwise "no ordered relation is established".',
        'A monotone-in-temperature statement applies to the below-maximum median and to the logged-maximum share (named quantities), within ONE era only, and is allowed only if the supported bins are contiguous (no unsupported gap), '
        'the order holds in every pair of neighbouring bins (a tie counts as not ordered) and the day-clustered intervals of the end bins do not overlap; otherwise "no ordered relation is established". '
        'No cross-era temperature contrast is drawn: the hp era is May to September and the kW era September onward, so era and season are confounded and any cold bin exists only in the kW era.')
i = t.index('## 4. Saturation check (D-04)')
j = t.index('## 5. Winter evidence rule')
sat = ('## 4. Saturation check (D-04), descriptive only\n'
       'Is 63.75 kW = 255 x 0.25 a saturated byte? A temperature-independent design cap at the same value would give the same pattern, so the pattern alone cannot identify saturation. '
       'Script-written descriptions: the share of input samples exactly on the era maximum, the number of distinct values within 1 kW below the maximum, the maximum run length of the constant maximum, and the classes '
       '"maximum reached in every supported bin" / "maximum absent in some supported bin" / "undetermined" (a zero share in a high-SoC bin is also expected under a saturated byte). '
       'The one check that can separate a censored value from a limit that is actually imposed: the time share of samples where the logged I x V charge power exceeds the reported input limit while that limit is at the logged maximum '
       'versus below it (the M627 utilisation maximum is 1.171, i.e. the logged power exceeded the reported limit). The check is reported as a descriptive pair of shares with day-clustered intervals; '
       'it never converts the value into a physical statement.\n\n')
t = t[:i] + sat + t[j:]
t = rep(t, 'a winter statement about regenerative acceptance is allowed only for bins that reach "supported"',
        'a winter statement about the logged input possible power (which covers generator charging as well as regeneration; the channel does not separate them) is allowed only for bins that reach "supported"')
t = rep(t, 'A cell where they differ by more than the larger of their interval half-widths is flagged "estimator-dependent".',
        'A cell where they differ by more than the larger of their interval half-widths and one logged grid step (0.1 kW in the hp era, 0.05 kW in the kW era) is flagged "estimator-dependent". '
        'A cadence-regime sensitivity (tools/regime_reader.py strata) is reported beside the primary; samples dropped for a missing pack temperature or SoC are counted by era and logger regime (the missingness may not be random).')
t = rep(t, 'the supported cells cover less than 10 % of the channel time;', 'the supported cells cover less than 25 % of the channel time of the analysed drives (raised from 10 % at the Director\'s review);')
sec9 = ('## 9. Director review (2026-11-14, verdict revise) and how each change was applied\n'
        'R1 output ceiling undefined: one logged-maximum flag (63.70 kW) for both directions, stated as a deviation (owner decision O1 asks to confirm the output direction stays in scope). '
        'R2 ceiling dominance: values at the logged maximum print as such, zero-width intervals flagged degenerate. R3 bootstrap: own-day resampling, median-of-medians interval defined. '
        'R4 estimator-dependence flag includes one grid step. R5 support ladder ordered, only supported cells feed the ladders. R6 saturation rule re-labelled as descriptions plus the I x V check (owner decision O2 asks to approve it). '
        'R7 monotone rule: named quantities, ties not ordered, contiguous bins, one era. R8 bin edges fixed at multiples of 5 C. R9 last-sample weight defined, cadence-regime sensitivity added. '
        'R10 pre-seen M627 facts and the 3 excluded drives disclosed. R11 wording: no capacity, charge-acceptance or regenerative-acceptance language; logged / app-calculated.\n'
        'Risks recorded: era is confounded with season; below-maximum descriptives are selected on the outcome; a winter limit drop could be over-read as "the buffer is constrained" '
        '(the channel also covers generator charging); missing temperature or SoC may not be random.\n\n'
        'Owner decisions pending: O1 the output direction is in scope with the logged-maximum flag instead of a ceiling (recommended: yes). '
        'O2 the logged-power-above-limit check is the saturation evidence (recommended: yes).\n\n')
t = rep(t, '## 8. Acceptance', sec9 + '## 8. Acceptance')
open(p, 'w', encoding='utf-8').write(t)
print('ok')
