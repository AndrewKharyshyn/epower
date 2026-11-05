# M379 Rev 4 addendum (2026-11-05, M578): regime threshold 1.05 s -> 1.10 s; guard zone [1.06, 1.135) s

Owner decision (Andrii, chat 2026-11-05, verbatim): "I suggest to still classify those drives since they are valid drives. Let's review the classification method. Suggest to classify as slow over 1.1s while fast - less than 1.1 s. You analyze this and review the classification methodology"
Director ruling: `analyses/M578_cadence_threshold_director_ruling.json` (supersedes the "unclassified" part of `analyses/M578_cadence_gap_director_ruling.json`).

## Rule
fast if `I_sample_period_s` < 1.10 s; slow if >= 1.10 s; null if missing. A drive with 1.06 <= period < 1.135 s STOPs for Director review (the guard zone; empty on the 632-drive corpus).

## Record
- Chosen POST HOC, after seeing the 11 periods of the 2026-11-03..05 drives (0.919, 0.991, 1.055, 1.001, 1.003, 0.972, 0.940, 0.968, 0.952, 0.953, 1.004). 1.10 s is the upper edge of the gap pre-declared as (1.0, 1.1) s in Rev 2.
- Neutral for history: 0 of the 621 older drives change regime (fast max 0.984 s, slow min 1.137 s); verified by rebuilding the sidecar on the committed master. Four new drives (1.055, 1.001, 1.003, 1.004 s) are fast; at 1.05 s the 1.055 s drive would have been slow.
- No outcome estimate was seen with these drives before the choice (the M577 slow term was computed on the 590-drive frame that ends 2026-11-03 and does not contain them).
- "Fast" now pools two PID-set configurations (from 2026-11-03 the PID set varies drive to drive, 76-87 raw columns); the period is a proxy for the polling epoch, not a physical regime. No cadence effect is claimed.
- Inline 1.05 s consumers are NOT changed in M578 (checkpoint and ML16 risk): `cadence_monitor` text only is updated. The one drive classified differently there is `2026-11-04_08-01-15` (1.055 s): sidecar fast, inline 1.05 slow.
- Follow-up milestone (spec, blind audit, Director): a PID-set/epoch covariate taken from the raw header column set, and one central regime reader replacing every inline threshold; `compute_drive_summary_v6.POWERFADE_FAST_S` changes in a planned full checkpoint rebuild. Revisit the binary rule if post-change periods reach 1.06 s.
