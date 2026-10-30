#!/usr/bin/env python3
"""M539 wave 1 (analyses/M539_spec.md Rev 2): the ONE engine-on rule of the project (owner delegation 2026-10-30, option A of analyses/M536_decision_pack.md): engine-on = logged rpm > 400 on the 1 Hz grid
(strict boundary); engine-off = rpm <= 400 or missing is NOT assumed: a missing second is neither on nor in the band. The 300-400 rpm band is reported separately and is CLOSED [300, 400], the exact complement of
'rpm > 400' inside the former 'rpm >= 300' on-time. Wave 1 adds this module, the site registry (analyses/M539_site_registry.json, tools/engine_on_sites.py) and the tests; NO existing producer is changed.
Separate names that never use this rule: generator-active (reconstructed Pgen > 0), the RPM onset detector (> 300 rpm, run >= 2 s), the engine-start trigger (> 800 after <= 100), event classifiers, the regeneration
engine-off proxy (<= 300, owner decision 2026-10-14 (g))."""
import numpy as np

THRESHOLD_RPM = 400.0
BOUNDARY = "gt"                 # engine-on iff rpm > THRESHOLD_RPM
BAND_LO_RPM = 300.0             # low-rpm rotation band, closed [BAND_LO_RPM, THRESHOLD_RPM]
NAN_POLICY = "a missing second is neither engine-on nor in the band; counts of missing seconds are reported separately"


def engine_on(rpm):
    """boolean array: rpm > 400 (NaN -> False)"""
    r = np.asarray(rpm, dtype=float)
    return np.where(np.isnan(r), False, r > THRESHOLD_RPM)


def low_rpm_band(rpm):
    """boolean array: 300 <= rpm <= 400 (NaN -> False); complement of engine_on inside rpm >= 300"""
    r = np.asarray(rpm, dtype=float)
    return np.where(np.isnan(r), False, (r >= BAND_LO_RPM) & (r <= THRESHOLD_RPM))


def legacy_ge300(rpm):
    """the former B1 convention (rpm >= 300, NaN -> False): ge300 == engine_on | low_rpm_band"""
    r = np.asarray(rpm, dtype=float)
    return np.where(np.isnan(r), False, r >= 300.0)
