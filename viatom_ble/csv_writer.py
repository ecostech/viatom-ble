"""CSV sample log in Viatom's native format.

Writes one row per BLE notification to a CSV file whose header and formatting
match the output of Viatom's own PC software, so tools that already ingest
those CSVs (e.g. to void ``SpO2=255``/``Pulse=65535`` no-finger samples) accept
this file unchanged.

External processes can rotate the log by copying and truncating (or deleting)
the file; ``CsvWriter`` detects that on the next write and re-adds the header
automatically. No signals are involved.
"""

from __future__ import annotations

import contextlib
import csv
import logging
import os
from datetime import datetime
from pathlib import Path

from .protocol import Reading

# Exact header row Viatom's PC export produces. The empty seventh field
# is intentional -- it yields the trailing comma the format requires.
HEADER: tuple[str, ...] = (
    "Time",
    "SpO2(%)",
    "Pulse Rate(bpm)",
    "Motion",
    "SpO2 Reminder",
    "PR Reminder",
    "",
)

# Sentinel values Viatom uses for "device is not on a finger".
NO_FINGER_SPO2 = 255
NO_FINGER_PULSE = 65535


def format_viatom_time(dt: datetime) -> str:
    """Format a datetime as e.g. ``10:33:40PM Jan 31, 2026``.

    Built manually because ``strftime`` cannot produce non-zero-padded hour
    and day portably across Linux / macOS / Windows.
    """
    hour_12 = dt.hour % 12 or 12
    ampm = "PM" if dt.hour >= 12 else "AM"
    return f"{hour_12}:{dt.minute:02d}:{dt.second:02d}{ampm} {dt:%b} {dt.day}, {dt.year}"


class CsvWriter:
    """Append-only writer that produces a Viatom-format CSV sample log."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        logger: logging.Logger | None = None,
    ) -> None:
        self.path = Path(path)
        self._log = logger or logging.getLogger(__name__)
        self._file = None
        self._writer: csv.writer | None = None  # type: ignore[assignment]
        self._open()

    def _open(self) -> None:
        needs_header = not self.path.exists() or self.path.stat().st_size == 0
        # This file is held open for the lifetime of the CsvWriter and closed
        # in .close() / __exit__; a `with` block would defeat that.
        self._file = open(self.path, "a", newline="", encoding="utf-8")  # noqa: SIM115
        self._writer = csv.writer(self._file)
        if needs_header:
            self._writer.writerow(HEADER)
            self._file.flush()
            self._log.info(f"CSV: initialized {self.path}")
        else:
            self._log.info(f"CSV: appending to existing {self.path}")

    def _reopen_if_truncated(self) -> None:
        """If an external process emptied or deleted the file, reopen it."""
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            self._log.info(f"CSV: {self.path} was removed, re-creating")
            self._close_file()
            self._open()
            return
        if size == 0:
            self._log.info(f"CSV: {self.path} was truncated externally, re-adding header")
            self._close_file()
            self._open()

    def write(self, reading: Reading) -> None:
        self._reopen_if_truncated()
        assert self._writer is not None and self._file is not None
        if reading.worn:
            spo2 = reading.spo2
            pulse = reading.heart_rate
        else:
            spo2 = NO_FINGER_SPO2
            pulse = NO_FINGER_PULSE
        row = (
            format_viatom_time(reading.received_at),
            spo2,
            pulse,
            reading.movement,
            0,
            0,
            "",
        )
        self._writer.writerow(row)
        self._file.flush()

    def close(self) -> None:
        self._close_file()

    def _close_file(self) -> None:
        if self._file is not None:
            with contextlib.suppress(OSError):
                self._file.close()
        self._file = None
        self._writer = None

    def __enter__(self) -> CsvWriter:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
