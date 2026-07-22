"""BLE scanning and interactive device selection.

Uses Bleak so it works on Linux (BlueZ), macOS (CoreBluetooth), and Windows (WinRT).
"""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

_LOG = logging.getLogger(__name__)

# Case-insensitive substrings that match Viatom / Wellue family device names.
COMPATIBLE_NAME_PREFIXES: tuple[str, ...] = (
    "o2",
    "po",
    "checkme",
    "viatom",
    "wellue",
    "sleepu",
    "oxyring",
)

# Sentinel values returned by _scan_and_prompt to signal user choices.
_RESCAN = object()
_SHOW_ALL = object()


def _is_compatible(name: str | None) -> bool:
    if not name:
        return False
    lower = name.lower()
    return any(prefix in lower for prefix in COMPATIBLE_NAME_PREFIXES)


async def scan_devices(
    duration: float = 10.0,
    name_filter: bool = True,
) -> list[tuple[BLEDevice, AdvertisementData]]:
    """Passively discover devices for ``duration`` seconds.

    Returns a list of (BLEDevice, AdvertisementData) tuples sorted by RSSI
    strongest-first. When ``name_filter`` is True, entries whose advertised
    name does not match a known Viatom family prefix are dropped.
    """
    _LOG.debug(f"Scanning for BLE devices for {duration}s (filter={name_filter})")
    discovered = await BleakScanner.discover(timeout=duration, return_adv=True)
    entries: list[tuple[BLEDevice, AdvertisementData]] = list(discovered.values())

    if name_filter:
        entries = [
            (dev, adv)
            for dev, adv in entries
            if _is_compatible(adv.local_name or dev.name)
        ]

    entries.sort(key=lambda item: item[1].rssi if item[1].rssi is not None else -999, reverse=True)
    return entries


async def _scan_and_prompt(duration: float, name_filter: bool):
    """One scan-and-select cycle. Returns an address, None (quit), or a sentinel."""
    filter_label = "Viatom-family devices" if name_filter else "all devices"
    print(f"Scanning for {filter_label} ({duration:.0f}s)...")

    seen: dict[str, tuple[BLEDevice, AdvertisementData, int]] = {}

    def on_detect(device: BLEDevice, adv: AdvertisementData) -> None:
        name = adv.local_name or device.name
        if name_filter and not _is_compatible(name):
            return
        if device.address in seen:
            idx = seen[device.address][2]
            seen[device.address] = (device, adv, idx)
            return
        idx = len(seen) + 1
        seen[device.address] = (device, adv, idx)
        rssi = adv.rssi if adv.rssi is not None else 0
        print(f"  [{idx}] {(name or '<unnamed>'):<24} {device.address}   RSSI={rssi} dBm")

    scanner = BleakScanner(detection_callback=on_detect)
    await scanner.start()
    try:
        await asyncio.sleep(duration)
    finally:
        await scanner.stop()

    if not seen:
        print("No matching devices found.")
    else:
        print()

    choice = input(
        "Select a device: number to connect, 'a' to show all, 'r' to rescan, 'q' to quit: "
    ).strip().lower()

    if choice in ("q", ""):
        return None
    if choice == "r":
        return _RESCAN
    if choice == "a":
        return _SHOW_ALL
    try:
        idx = int(choice)
    except ValueError:
        print(f"Unrecognized input '{choice}', rescanning...")
        return _RESCAN

    for device, _adv, entry_idx in seen.values():
        if entry_idx == idx:
            return device.address
    print(f"No device with number {idx}, rescanning...")
    return _RESCAN


async def interactive_pick(
    duration: float = 10.0,
    name_filter: bool = True,
) -> str | None:
    """Scan and prompt the user to pick a device by number.

    Prints devices as they are discovered. After ``duration`` elapses, prompts
    for a number (select), ``a`` (show all / disable filter), ``r`` (rescan),
    or ``q`` (quit). Returns the selected device address, or None if the user
    quits.
    """
    while True:
        result = await _scan_and_prompt(duration, name_filter)
        if result is _RESCAN:
            continue
        if result is _SHOW_ALL:
            name_filter = False
            continue
        return result  # type: ignore[return-value]  # str address or None
