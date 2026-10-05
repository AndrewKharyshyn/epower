"""Wording of the masterRefitProvenance block (M382, audit F01): the block is HISTORICAL (rebuild from the former lower-precision re-exports,
before the M366 raw replacement). Single source for tools/build_refit_provenance.py and tools/m382_splice.py."""
BASIS_STATUS = ("historical: rebuild from the former lower-precision re-exports in raw/ (before the M366 replacement by the sha256-verified "
                "originals); it does not describe the current raw/")
INTERPRETATION = ("Historical block (M310/M311, before the M366 raw replacement): the rebuild used the former re-exports in raw/. Drift was "
                  "confined to drives whose re-export did not match its recorded hash; new drives and hash-verified drives reproduced (same "
                  "code path). The later originals evidence (analyses/F03_originals, M366) is consistent with those re-exports being "
                  "lower-precision copies of the originals. Kept as history, not as a statement about the current raw/.")
LIMIT_0 = ("Historical: when this rebuild ran no original bytes were available; the originals were recovered afterwards (owner decisions "
           "2026-10-02/04, M366) and raw/ now holds them")
PROVENANCE_OLD = "on the raw archive held in this repository)"
PROVENANCE_NEW = "on the raw archive held in this repository at that time: the former re-exports, before M366)"
