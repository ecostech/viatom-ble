from viatom_ble.protocol import parse_notification


def _make_packet(spo2: int, hr: int, battery: int, movement: int, pi: int, worn: int) -> bytes:
    # Layout matches the byte indices used by parse_notification.
    buf = bytearray(20)
    buf[7] = spo2
    buf[8] = hr
    buf[14] = battery
    buf[16] = movement
    buf[17] = pi
    buf[18] = worn
    return bytes(buf)


def test_worn_reading_parses_all_fields():
    pkt = _make_packet(spo2=97, hr=72, battery=85, movement=3, pi=6, worn=1)
    reading = parse_notification(pkt)
    assert reading is not None
    assert reading.spo2 == 97
    assert reading.heart_rate == 72
    assert reading.battery == 85
    assert reading.movement == 3
    assert reading.perfusion_index == 6
    assert reading.worn is True
    assert reading.calibrating is False


def test_off_finger_reading_flags_not_worn():
    pkt = _make_packet(spo2=0, hr=0, battery=90, movement=0, pi=0, worn=0)
    reading = parse_notification(pkt)
    assert reading is not None
    assert reading.worn is False
    # calibrating only makes sense when worn; ensure off-finger doesn't mask as calibrating
    assert reading.calibrating is False
    assert reading.battery == 90


def test_calibrating_reading_when_worn_but_no_values():
    pkt = _make_packet(spo2=0, hr=0, battery=88, movement=1, pi=0, worn=1)
    reading = parse_notification(pkt)
    assert reading is not None
    assert reading.worn is True
    assert reading.calibrating is True
    assert reading.battery == 88


def test_short_packet_returns_none():
    assert parse_notification(b"\x00\x01\x02") is None
    assert parse_notification(b"") is None
    assert parse_notification(None) is None


def test_reading_is_immutable():
    pkt = _make_packet(spo2=97, hr=72, battery=85, movement=3, pi=6, worn=1)
    reading = parse_notification(pkt)
    assert reading is not None
    try:
        reading.spo2 = 50  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Reading dataclass should be frozen")
