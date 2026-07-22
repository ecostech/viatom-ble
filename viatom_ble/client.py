"""Cross-platform BLE client for Viatom / Wellue pulse-oximeter rings.

Built on Bleak so it runs on Linux (BlueZ), macOS (CoreBluetooth), and
Windows (WinRT). Provides both async (``run_forever``) and sync
(``run_forever_sync``) entry points for embedding.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import signal
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from .protocol import (
    REQUEST_BYTES,
    SERVICE_UUID,
    WRITE_CHAR_UUID_PREFIX,
    Reading,
    parse_notification,
)

ReadingCallback = Callable[[Reading], None | Awaitable[None]]
StateCallback = Callable[[str], None | Awaitable[None]]

# State strings surfaced via ``on_state_change``.
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_DISCONNECTED = "disconnected"
STATE_IDLE = "idle"

_MAX_BACKOFF_SECONDS = 60.0


class ViatomClient:
    """Embeddable BLE reader.

    Parameters
    ----------
    address:
        BLE MAC (Linux/Windows) or CoreBluetooth device UUID (macOS).
    read_period:
        Seconds between poll requests to the ring.
    reconnect_delay:
        Base delay between reconnect attempts. Exponential backoff is
        applied on repeated failures, capped at 60s.
    inactivity_timeout:
        If no valid reading arrives for this many seconds, force-disconnect
        to conserve the ring's battery.
    inactivity_delay:
        Seconds to wait after an inactivity disconnect before reconnecting.
    connect_timeout:
        Seconds to wait for the initial BLE connect to succeed.
    on_reading:
        Called for every notification (worn, off-finger, or calibrating).
        May be a regular function or an async coroutine.
    on_state_change:
        Called with a state string when the connection state changes.
        May be a regular function or an async coroutine.
    logger:
        Optional logger; defaults to ``logging.getLogger(__name__)``.
    """

    def __init__(
        self,
        address: str,
        *,
        read_period: float = 2.0,
        reconnect_delay: float = 1.0,
        inactivity_timeout: float = 300.0,
        inactivity_delay: float = 130.0,
        connect_timeout: float = 10.0,
        on_reading: ReadingCallback | None = None,
        on_state_change: StateCallback | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if read_period <= 0:
            raise ValueError("read_period must be > 0")

        self.address = address
        self.read_period = read_period
        self.reconnect_delay = reconnect_delay
        self.inactivity_timeout = inactivity_timeout
        self.inactivity_delay = inactivity_delay
        self.connect_timeout = connect_timeout
        self.on_reading = on_reading
        self.on_state_change = on_state_change
        self._log = logger or logging.getLogger(__name__)

        self._stop_event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_notification_at: float | None = None

    async def stop(self) -> None:
        """Request that ``run_forever`` exit at the next opportunity."""
        self._stop_event.set()

    async def run_forever(self) -> None:
        """Loop forever, reconnecting on error with exponential backoff."""
        self._stop_event.clear()
        self._loop = asyncio.get_running_loop()
        consecutive_failures = 0
        next_delay = self.reconnect_delay

        while not self._stop_event.is_set():
            try:
                await self._run_session()
                consecutive_failures = 0
                next_delay = self.reconnect_delay
            except asyncio.CancelledError:
                raise
            except Exception as e:
                consecutive_failures += 1
                # Exponential backoff, capped, then reset by a successful reading.
                backoff = min(
                    self.reconnect_delay * (2 ** (consecutive_failures - 1)),
                    _MAX_BACKOFF_SECONDS,
                )
                next_delay = max(next_delay, backoff)
                self._log.warning(f"BLE: session ended ({type(e).__name__}: {e})")

            if self._stop_event.is_set():
                break

            self._log.info(f"BLE: waiting {next_delay:.1f}s before reconnect")
            await self._notify_state(STATE_IDLE)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=next_delay)
            except asyncio.TimeoutError:
                pass
            else:
                break  # stop requested during wait
            next_delay = self.reconnect_delay

    def run_forever_sync(self) -> None:
        """Blocking convenience wrapper. Installs SIGINT/SIGTERM handlers."""
        # asyncio.run() surfaces SIGINT as KeyboardInterrupt on Windows.
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(self._run_forever_with_signals())

    async def _run_forever_with_signals(self) -> None:
        loop = asyncio.get_running_loop()

        def _handle_signal() -> None:
            self._log.info("Stop signal received, shutting down...")
            self._stop_event.set()

        # add_signal_handler is not implemented on Windows for these signals.
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                with contextlib.suppress(NotImplementedError):
                    loop.add_signal_handler(sig, _handle_signal)

        await self.run_forever()

    async def _run_session(self) -> None:
        """One connect + subscribe + poll cycle. Raises on any error."""
        self._log.info(f"BLE: connecting to {self.address}")
        await self._notify_state(STATE_CONNECTING)

        inactivity_flag = {"triggered": False}
        stall_timeout = max(self.read_period * 3, 5.0)

        def _on_disconnected(_: BleakClient) -> None:
            self._log.info("BLE: peripheral disconnected")

        client = BleakClient(
            self.address,
            disconnected_callback=_on_disconnected,
            timeout=self.connect_timeout,
        )

        try:
            await asyncio.wait_for(client.connect(), timeout=self.connect_timeout)
        except (asyncio.TimeoutError, Exception) as e:
            self._log.warning(f"BLE: connect failed: {e}")
            raise

        try:
            self._log.info(f"BLE: connected to {self.address}")
            await self._notify_state(STATE_CONNECTED)

            write_char, notify_char = self._find_characteristics(client)

            # Choose the write mode from the characteristic's declared properties.
            # Some peripherals (observed on macOS/CoreBluetooth against the Wellue KidsO2)
            # only accept write-without-response even though bluepy's `withResponse=True`
            # worked on Linux -- BlueZ and CoreBluetooth enforce permissions differently.
            write_with_response = "write" in write_char.properties
            if not write_with_response and "write-without-response" not in write_char.properties:
                write_with_response = True  # shouldn't happen, but stay defensive
            fallback_tried = False

            fail_count = 0
            fail_limit = max(1, int(self.inactivity_timeout / self.read_period))
            self._last_notification_at = self._loop_time()

            def _on_notify(_char: BleakGATTCharacteristic, data: bytearray) -> None:
                self._last_notification_at = self._loop_time()
                reading = parse_notification(bytes(data), received_at=datetime.now())
                if reading is None:
                    return
                nonlocal fail_count
                if not reading.worn or reading.calibrating:
                    fail_count += 1
                else:
                    fail_count = 0
                self._dispatch_reading(reading)

            await client.start_notify(notify_char, _on_notify)
            try:
                while not self._stop_event.is_set():
                    try:
                        await client.write_gatt_char(
                            write_char, REQUEST_BYTES, response=write_with_response
                        )
                    except Exception as e:
                        if not fallback_tried:
                            fallback_tried = True
                            other = not write_with_response
                            self._log.warning(
                                f"BLE: write (response={write_with_response}) failed: {e}. "
                                f"Retrying with response={other}."
                            )
                            try:
                                await client.write_gatt_char(
                                    write_char, REQUEST_BYTES, response=other
                                )
                                write_with_response = other  # stick with what works
                            except Exception as e2:
                                self._log.warning(f"BLE: write failed: {e2}")
                                break
                        else:
                            self._log.warning(f"BLE: write failed: {e}")
                            break

                    # Wait one read_period, but honor stop.
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=self.read_period)
                        break
                    except asyncio.TimeoutError:
                        pass

                    # Stall watchdog: if we've been quiet for too long, break the session.
                    since = self._loop_time() - (self._last_notification_at or 0)
                    if since > stall_timeout:
                        self._log.warning(
                            f"BLE: no notifications for {since:.1f}s (>{stall_timeout:.1f}s), reconnecting"
                        )
                        break

                    if fail_count >= fail_limit:
                        self._log.info(
                            "BLE: inactivity timeout reached, disconnecting to save battery"
                        )
                        inactivity_flag["triggered"] = True
                        break
            finally:
                with contextlib.suppress(Exception):
                    await client.stop_notify(notify_char)
        finally:
            with contextlib.suppress(Exception):
                await client.disconnect()
            await self._notify_state(STATE_DISCONNECTED)

        if inactivity_flag["triggered"]:
            # Sleep the extended inactivity delay before the outer loop reconnects.
            self._log.info(f"BLE: idle for {self.inactivity_delay:.0f}s")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.inactivity_delay)

    def _find_characteristics(
        self, client: BleakClient
    ) -> tuple[BleakGATTCharacteristic, BleakGATTCharacteristic]:
        """Locate write and notify characteristics within the Viatom service."""
        services = client.services
        service = services.get_service(SERVICE_UUID)
        if service is None:
            raise RuntimeError(f"BLE service {SERVICE_UUID} not found on device")

        # Log the full characteristic table at DEBUG so `-v` gives us everything
        # needed to diagnose device-specific quirks without another round-trip.
        for char in service.characteristics:
            self._log.debug(
                f"BLE: discovered characteristic {char.uuid} properties={list(char.properties)}"
            )

        write_char: BleakGATTCharacteristic | None = None
        notify_char: BleakGATTCharacteristic | None = None
        for char in service.characteristics:
            uuid = char.uuid.lower()
            props = set(char.properties)
            if uuid.startswith(WRITE_CHAR_UUID_PREFIX) and ("write" in props or "write-without-response" in props):
                write_char = char
            # Prefer the same characteristic as the write one if possible.
            notify_capable = "notify" in props or "indicate" in props
            if notify_capable and (
                notify_char is None or (write_char is not None and char is write_char)
            ):
                notify_char = char

        if write_char is None:
            # Fall back to any writable characteristic in the service.
            for char in service.characteristics:
                props = set(char.properties)
                if "write" in props or "write-without-response" in props:
                    write_char = char
                    break

        if write_char is None or notify_char is None:
            raise RuntimeError(
                "Could not locate both write and notify characteristics on the Viatom service"
            )
        self._log.info(
            f"BLE: using write char {write_char.uuid} ({list(write_char.properties)}), "
            f"notify char {notify_char.uuid} ({list(notify_char.properties)})"
        )
        return write_char, notify_char

    def _dispatch_reading(self, reading: Reading) -> None:
        if self.on_reading is None:
            return
        try:
            result = self.on_reading(reading)
        except Exception:
            self._log.exception("on_reading callback raised")
            return
        if inspect.isawaitable(result) and self._loop is not None:
            self._loop.create_task(self._await_and_log(result, "on_reading"))

    async def _notify_state(self, state: str) -> None:
        if self.on_state_change is None:
            return
        try:
            result = self.on_state_change(state)
            if inspect.isawaitable(result):
                await result
        except Exception:
            self._log.exception("on_state_change callback raised")

    async def _await_and_log(self, coro: Awaitable[Any], name: str) -> None:
        try:
            await coro
        except Exception:
            self._log.exception(f"{name} coroutine raised")

    @staticmethod
    def _loop_time() -> float:
        return asyncio.get_running_loop().time()
