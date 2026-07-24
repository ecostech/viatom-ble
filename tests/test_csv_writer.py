from datetime import datetime

from viatom_ble.csv_writer import CsvWriter, format_viatom_time
from viatom_ble.protocol import Reading

FIXED_TIME = datetime(2026, 1, 31, 22, 33, 40)
EXPECTED_STAMP = "10:33:40PM Jan 31, 2026"


def _reading(*, spo2: int, hr: int, worn: bool, calibrating: bool = False,
             battery: int = 85, movement: int = 3, pi: int = 6,
             when: datetime = FIXED_TIME) -> Reading:
    return Reading(
        spo2=spo2,
        heart_rate=hr,
        battery=battery,
        movement=movement,
        perfusion_index=pi,
        worn=worn,
        calibrating=calibrating,
        raw=b"\x00" * 20,
        received_at=when,
    )


def test_format_viatom_time_matches_sample():
    assert format_viatom_time(FIXED_TIME) == EXPECTED_STAMP


def test_format_viatom_time_padded_hour_unpadded_day():
    dt = datetime(2026, 1, 5, 13, 5, 7)
    assert format_viatom_time(dt) == "01:05:07PM Jan 5, 2026"


def test_format_viatom_time_midnight_and_noon():
    assert format_viatom_time(datetime(2026, 6, 1, 0, 0, 0)) == "12:00:00AM Jun 1, 2026"
    assert format_viatom_time(datetime(2026, 6, 1, 12, 0, 0)) == "12:00:00PM Jun 1, 2026"


def test_header_written_on_new_file(tmp_path):
    path = tmp_path / "samples.csv"
    writer = CsvWriter(path)
    writer.close()
    content = path.read_text(encoding="utf-8")
    # csv.writer defaults to '\r\n' line terminators; check the header line only.
    first_line = content.splitlines()[0]
    assert first_line == "Time,SpO2(%),Pulse Rate(bpm),Motion,SpO2 Reminder,PR Reminder,"


def test_worn_reading_writes_actual_values(tmp_path):
    path = tmp_path / "samples.csv"
    writer = CsvWriter(path)
    writer.write(_reading(spo2=97, hr=72, worn=True))
    writer.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[1] == f'"{EXPECTED_STAMP}",97,72,3,0,0,'


def test_not_worn_reading_uses_sentinel(tmp_path):
    path = tmp_path / "samples.csv"
    writer = CsvWriter(path)
    writer.write(_reading(spo2=0, hr=0, worn=False))
    writer.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[1] == f'"{EXPECTED_STAMP}",255,65535,3,0,0,'


def test_calibrating_reading_keeps_zero_values(tmp_path):
    """Worn + spo2=0/hr=0 (calibrating) should write real 0,0 -- not the sentinel."""
    path = tmp_path / "samples.csv"
    writer = CsvWriter(path)
    writer.write(_reading(spo2=0, hr=0, worn=True, calibrating=True))
    writer.close()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[1] == f'"{EXPECTED_STAMP}",0,0,3,0,0,'


def test_reopening_existing_file_does_not_duplicate_header(tmp_path):
    path = tmp_path / "samples.csv"
    w1 = CsvWriter(path)
    w1.write(_reading(spo2=97, hr=72, worn=True))
    w1.close()

    w2 = CsvWriter(path)
    w2.write(_reading(spo2=95, hr=70, worn=True))
    w2.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    # One header + two data rows.
    assert len(lines) == 3
    assert lines[0].startswith("Time,SpO2(%)")
    # No second header anywhere.
    assert sum(1 for ln in lines if ln.startswith("Time,SpO2(%)")) == 1


def test_external_truncation_triggers_reheader(tmp_path):
    path = tmp_path / "samples.csv"
    writer = CsvWriter(path)
    writer.write(_reading(spo2=97, hr=72, worn=True))

    # Simulate an external cp + truncate.
    path.write_text("", encoding="utf-8")

    writer.write(_reading(spo2=95, hr=70, worn=True))
    writer.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # re-added header + one row
    assert lines[0].startswith("Time,SpO2(%)")
    assert lines[1].endswith(",95,70,3,0,0,")


def test_external_deletion_triggers_reheader(tmp_path):
    path = tmp_path / "samples.csv"
    writer = CsvWriter(path)
    writer.write(_reading(spo2=97, hr=72, worn=True))
    path.unlink()

    writer.write(_reading(spo2=95, hr=70, worn=True))
    writer.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("Time,SpO2(%)")
    assert lines[1].endswith(",95,70,3,0,0,")


def test_context_manager_closes(tmp_path):
    path = tmp_path / "samples.csv"
    with CsvWriter(path) as writer:
        writer.write(_reading(spo2=97, hr=72, worn=True))
    # File should be readable and complete after exit.
    content = path.read_text(encoding="utf-8")
    assert content.count(EXPECTED_STAMP) == 1
