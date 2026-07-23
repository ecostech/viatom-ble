"""viatom-ble: cross-platform BLE reader for Viatom / Wellue pulse-ox rings."""

from .client import (
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_DISCONNECTED,
    STATE_IDLE,
    ViatomClient,
)
from .csv_writer import CsvWriter
from .mqtt import MqttPublisher
from .protocol import (
    REQUEST_BYTES,
    SERVICE_UUID,
    WRITE_CHAR_UUID_PREFIX,
    Reading,
    parse_notification,
)
from .scanner import interactive_pick, scan_devices

__version__ = "0.2.0"

__all__ = [
    "CsvWriter",
    "MqttPublisher",
    "REQUEST_BYTES",
    "Reading",
    "SERVICE_UUID",
    "STATE_CONNECTED",
    "STATE_CONNECTING",
    "STATE_DISCONNECTED",
    "STATE_IDLE",
    "ViatomClient",
    "WRITE_CHAR_UUID_PREFIX",
    "interactive_pick",
    "parse_notification",
    "scan_devices",
    "__version__",
]
