#!/usr/bin/env bash
# apply_m284_post.sh - idempotent post-step, run AFTER compute_summary_arrays.py / refresh_gtr_headline.py
# (which regenerate summary_arrays.json and drop these patches). Order matters. Works from a flat project
# checkout or from the work/{track3,track4}/ tree. Run from the directory holding summary_arrays.json.
set -euo pipefail
S() { for d in track3 track4 claude .; do [ -f "$d/$1" ] && { echo "$d/$1"; return; }; done; echo "$1"; }
python3 "$(S patch_m284_data.py)"        # assumptionsRegistry, determinism scope, derived GTR limitations
python3 "$(S refresh_seasonal_kpis.py)"  # EnergyIntensity/CohortExposure @ current corpus + day-cluster CI
python3 "$(S records_resistance.py)"     # excitation-gated pack-resistance-proxy record
python3 "$(S records_rainflow.py)"       # rainflow exposure records
python3 "$(S cohort_distributions.py)"   # per-drive cohort distributions for ECDF small multiples
python3 "$(S records_disclosure.py)"     # M291/B8 disclosure contract; must follow records_* (they rebuild record entries)
python3 "$(S fuel_contract_flag.py)"       # M334: Fuel-tab disclosure block (from fuel_contract.json built by tools/fuel_contract.py); before the F03 flag
python3 "$(S f03_provenance_flag.py)"       # M307/F03: provenance-sensitivity notice (from f03_provenance.json); must be last
