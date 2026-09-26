#!/usr/bin/env python3
"""PreToolUse hook: block Edit/Write on integrity-anchored files (raw drive CSVs, drive_master.csv, raw_manifest.json).
Reads the hook JSON from stdin. Exit 2 = block (message on stderr). Pipeline scripts write these files via Bash, not via Edit."""
import json, re, sys

PROTECTED = [
    r"(^|/)raw/[^/]+\.csv$",
    r"(^|/)(20\d{6}[ _]\d{6}|20\d\d-\d\d-\d\d[ _]\d\d-\d\d-\d\d)\.csv$",
    r"(^|/)e4ORCE_[^/]+\.csv$",
    r"(^|/)drive_master\.csv$",
    r"(^|/)raw_manifest\.json$",
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
                f"BLOCKED: {path} is integrity-anchored (raw data / drive_master.csv / raw_manifest.json). "
                "Only pipeline scripts may write it; edit scripts, not data.\n")
            return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
