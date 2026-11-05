"""Line-ending shim (M310). The repo's canonical bytes are LF (the drive_master.csv MD5 anchor is taken over them), but Python text-mode
writes on Windows emit CRLF. With this directory on PYTHONPATH (tools/run_ingest.py sets it for every stage), text-mode WRITES
default to newline="\\n" (open/io.open, hence json.dump/Path.write_text) and pandas' default line terminator becomes "\\n"
(os.linesep). Reads are untouched; an explicit newline= argument always wins; binary modes are untouched.
Interactive use: export PYTHONPATH="$PWD/tools/eol_shim"."""
import builtins, io, os, time as _time

os.linesep = "\n"                      # pandas to_csv default lineterminator (read at call time)
_orig_open = builtins.open


def _open(file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
    if newline is None and isinstance(mode, str) and "b" not in mode and any(c in mode for c in "wax") and "+" not in mode:
        newline = "\n"
    if isinstance(mode, str) and any(c in mode for c in "wax"):
        # M575: a write-mode open can fail transiently on Windows (OSError 22 / PermissionError while a scanner or indexer holds the file): the M575 ingestion lost a 2-hour run to one such error. Retry a few times.
        for attempt in range(8):
            try:
                return _orig_open(file, mode, buffering, encoding, errors, newline, closefd, opener)
            except OSError as e:
                if attempt == 7 or e.errno not in (22, 13, 5, 32):
                    raise
                _time.sleep(0.5 * (attempt + 1))
    return _orig_open(file, mode, buffering, encoding, errors, newline, closefd, opener)


builtins.open = _open
io.open = _open
