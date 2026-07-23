"""Command-line entry point for viatom-ble."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import __version__
from .client import ViatomClient
from .csv_writer import CsvWriter
from .mqtt import MqttPublisher
from .protocol import Reading
from .scanner import interactive_pick, scan_devices

_LOG = logging.getLogger("viatom_ble")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="viatom-ble",
        description=(
            "Read sensor values over BLE from Viatom / Wellue pulse-oximeter rings. "
            "Optionally publish readings to an MQTT broker."
        ),
    )
    parser.add_argument("--version", action="version", version=f"viatom-ble {__version__}")

    ble = parser.add_argument_group("BLE")
    ble.add_argument(
        "-a", "--address",
        help="BLE device address to connect to (MAC on Linux/Windows, UUID on macOS).",
    )
    ble.add_argument(
        "-s", "--scan", action="store_true",
        help="Scan for nearby BLE devices, print them, and exit.",
    )
    ble.add_argument(
        "-i", "--scan-interactive", action="store_true",
        help="Scan for nearby devices, prompt to pick one by number, then connect.",
    )
    ble.add_argument(
        "--scan-all", action="store_true",
        help="Do not filter scan results by known Viatom family name prefixes.",
    )
    ble.add_argument(
        "--scan-duration", type=float, default=10.0, metavar="SECONDS",
        help="How long each scan runs (default: 10).",
    )
    ble.add_argument(
        "--read-period", type=float, default=2.0, metavar="SECONDS",
        help="Seconds between poll requests to the ring (default: 2).",
    )
    ble.add_argument(
        "--reconnect-delay", type=float, default=1.0, metavar="SECONDS",
        help="Base delay between reconnect attempts (default: 1).",
    )
    ble.add_argument(
        "--inactivity-timeout", type=float, default=300.0, metavar="SECONDS",
        help="Force-disconnect after this many seconds without a valid reading (default: 300).",
    )
    ble.add_argument(
        "--inactivity-delay", type=float, default=130.0, metavar="SECONDS",
        help="Delay before reconnecting after an inactivity disconnect (default: 130).",
    )
    ble.add_argument(
        "--connect-timeout", type=float, default=10.0, metavar="SECONDS",
        help="Seconds to wait for the initial BLE connect to succeed (default: 10).",
    )

    mq = parser.add_argument_group("MQTT (all optional; nothing is initialized without --mqtt-address)")
    mq.add_argument("--mqtt-address", help="MQTT broker hostname or IP.")
    mq.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port (default: 1883).")
    mq.add_argument("--mqtt-username", help="MQTT username.")
    mq.add_argument("--mqtt-password", help="MQTT password.")
    mq.add_argument(
        "--mqtt-topic", default="viatom-ble",
        help="Topic to publish readings to (default: viatom-ble).",
    )
    mq.add_argument(
        "--mqtt-client-id", default="viatom-ble",
        help="MQTT client ID (default: viatom-ble).",
    )

    log = parser.add_argument_group("Logging")
    log.add_argument("--logfile", help="Path to log file. If omitted, logs go to stderr.")
    log.add_argument(
        "-c", "--console", action="store_true",
        help="Force logging to the console even if --logfile is set.",
    )
    log.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging.")
    log.add_argument(
        "--csv-file", metavar="PATH",
        help=(
            "Write each reading to a Viatom-format CSV sample log at PATH. "
            "The file is created if missing, appended to if present. "
            "Truncating or deleting the file externally causes the header to be re-added "
            "automatically on the next reading."
        ),
    )

    return parser


def _setup_logging(args: argparse.Namespace) -> None:
    level = logging.DEBUG if args.verbose else logging.INFO
    handlers: list[logging.Handler] = []

    if args.logfile and not args.console:
        try:
            handlers.append(logging.FileHandler(args.logfile))
        except OSError as e:
            print(f"Could not open logfile {args.logfile}: {e}", file=sys.stderr)
            handlers.append(logging.StreamHandler(sys.stderr))
    else:
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d [%(process)d] %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def _print_scan_results(entries) -> None:
    if not entries:
        print("No devices found.")
        return
    print(f"{'Name':<24} {'Address':<40} RSSI")
    for device, adv in entries:
        name = adv.local_name or device.name or "<unnamed>"
        rssi = adv.rssi if adv.rssi is not None else 0
        print(f"{name:<24} {device.address:<40} {rssi} dBm")


def _log_reading(reading: Reading, verbose: bool) -> None:
    if not reading.worn:
        if verbose:
            _LOG.debug(f"Device not worn. Battery: {reading.battery}%")
        return
    if reading.calibrating:
        if verbose:
            _LOG.debug(f"Device calibrating. Battery: {reading.battery}%")
        return
    _LOG.info(
        f"SpO2: {reading.spo2}%  HR: {reading.heart_rate} bpm  "
        f"PI: {reading.perfusion_index}  Movement: {reading.movement}  "
        f"Battery: {reading.battery}%"
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _setup_logging(args)
    _LOG.info(f"viatom-ble {__version__} starting")

    # Scan-only mode: print and exit.
    if args.scan:
        entries = asyncio.run(
            scan_devices(duration=args.scan_duration, name_filter=not args.scan_all)
        )
        _print_scan_results(entries)
        return 0

    # Interactive scan: user picks a device to connect to.
    if args.scan_interactive:
        try:
            selected = asyncio.run(
                interactive_pick(duration=args.scan_duration, name_filter=not args.scan_all)
            )
        except KeyboardInterrupt:
            return 130
        if not selected:
            print("No device selected.")
            return 0
        args.address = selected

    if not args.address:
        parser.error("--address is required (or use --scan-interactive to pick one)")

    # MQTT gate: only initialize a publisher if the user supplied a broker.
    publisher: MqttPublisher | None = None
    if args.mqtt_address:
        publisher = MqttPublisher(
            address=args.mqtt_address,
            port=args.mqtt_port,
            username=args.mqtt_username,
            password=args.mqtt_password,
            topic=args.mqtt_topic,
            client_id=args.mqtt_client_id,
            logger=logging.getLogger("viatom_ble.mqtt"),
        )
        publisher.start()

    # CSV gate: only initialize a writer if the user supplied a path.
    csv_writer: CsvWriter | None = None
    if args.csv_file:
        csv_writer = CsvWriter(args.csv_file, logger=logging.getLogger("viatom_ble.csv"))

    def on_reading(reading: Reading) -> None:
        _log_reading(reading, args.verbose)
        if publisher is not None:
            publisher.publish(reading)
        if csv_writer is not None:
            try:
                csv_writer.write(reading)
            except OSError as e:
                _LOG.error(f"CSV: write failed: {e}")

    client = ViatomClient(
        address=args.address,
        read_period=args.read_period,
        reconnect_delay=args.reconnect_delay,
        inactivity_timeout=args.inactivity_timeout,
        inactivity_delay=args.inactivity_delay,
        connect_timeout=args.connect_timeout,
        on_reading=on_reading,
        logger=logging.getLogger("viatom_ble.client"),
    )

    try:
        client.run_forever_sync()
    finally:
        if csv_writer is not None:
            csv_writer.close()
        if publisher is not None:
            publisher.stop()
        _LOG.info("viatom-ble exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
