#!/usr/bin/env python3
"""PreToolUse hook: block Edit/Write on integrity-anchored files (raw drive CSVs, drive_master.csv, raw_manifest.json; M726: the frozen winter predictions and their frozen input copies).
Reads the hook JSON from stdin. Exit 2 = block (message on stderr). Pipeline scripts write these files via Bash, not via Edit."""
import json, re, sys

PROTECTED = [
    r"(^|/)raw/[^/]+\.csv$",
    r"(^|/)(20\d{6}[ _]\d{6}|20\d\d-\d\d-\d\d[ _]\d\d-\d\d-\d\d)\.csv$",
    r"(^|/)e4ORCE_[^/]+\.csv$",
    r"(^|/)drive_master\.csv$",
    r"(^|/)raw_manifest\.json$",
    r"(^|/)analyses/M717_frozen_sources/",              # M726 (G1): the frozen inputs of the winter freeze
    r"(^|/)analyses/M717_winter_predictions\.json$",    # M726 (G1): the frozen winter predictions
    r"(^|/)analyses/M726_extractor_registry\.json$",     # M727: the extractor registry of the winter freeze
    r"(^|/)tools/winter_extractors\.py$",                # M727: the frozen extractors
    r"(^|/)analyses/M728_extractor_registry\.json$",     # M728: the extractor registry (version 2)
    r"(^|/)tools/winter_extractors_b\.py$",              # M728: the frozen P4 extractor
    r"(^|/)analyses/M731_extractor_registry\.json$",     # M731: the extractor registry (version 3)
    r"(^|/)analyses/M731_frozen_engine/",                # M731: the vendored replay engine and its frozen inputs
    r"(^|/)analyses/M731_(consistency|engine)_check\.json$",   # M731: the frozen-basis checks (the P6 tolerance is read from the first)
    r"(^|/)tools/(winter_p6|winter_p2_band|winter_p2_band_run)\.py$",   # M731: the frozen P6 extractor and the realised-band tool and runner
    r"(^|/)analyses/M736_extractor_registry\.json$",     # M736: the extractor registry (version 4)
    r"(^|/)tools/winter_p2_v4\.py$",                     # M736: the frozen P2 v4 handling (path-carry bound, offset-adjusted sensitivity)
]

def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    path = (payload.get("tool_input") or {}).get("file_path", "") or ""
    for pat in PROTECTED:
        if re.search(pat, path):
            sys.stderr.write(
                f"BLOCKED: {path} is integrity-anchored (raw data / drive_master.csv / raw_manifest.json / frozen winter freeze files). "
                "Only pipeline scripts may write it; edit scripts, not data.\n")
            return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
