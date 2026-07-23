# viatom-ble

Cross-platform Python tool and library to read sensor values over BLE from Viatom / Wellue wearable pulse-oximeter rings. Runs as a standalone CLI, a background service, or embedded in another Python application. Optionally publishes readings to an MQTT broker.

## Compatibility

**Devices** — tested with a Viatom PO3 (Wellue KidsO2). Should work with all Viatom ring oximeters including PO1, PO2 (Wellue O2Ring), PO3, PO4, PO1B, and Checkme O2.

**Platforms** — Linux (Raspberry Pi is the primary target), macOS, and Windows 10+. Powered by [Bleak](https://github.com/hbldh/bleak).

**Python** — 3.9 or newer.

## Install

```bash
git clone https://github.com/ecostech/viatom-ble.git
cd viatom-ble
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

The `viatom-ble` console script is placed on the venv's `PATH` by pip. With the venv activated you can run `viatom-ble …` from any directory; when it isn't activated, invoke it directly as `/path/to/viatom-ble/.venv/bin/viatom-ble …`.

The venv step is what most modern distributions (Raspberry Pi OS Bookworm, Debian 12, recent Homebrew) require — a bare `pip install .` will fail with `error: externally-managed-environment` (PEP 668). If you know your environment allows system-wide pip installs, you can skip `python3 -m venv .venv` and the `source` line, or add `--break-system-packages` / `--user` to the `pip install` invocation — but the venv is the recommended path for both standalone use and embedding.

For development (editable install with test dependencies):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

### Embedding as a library

If you're calling `viatom_ble` from your own Python application, use the same pattern: create a venv for **your** app and `pip install /path/to/viatom-ble` (or a git URL) inside it. Do not try to install into the system Python.

```bash
cd my-app
python3 -m venv .venv
source .venv/bin/activate
pip install /path/to/viatom-ble
# or: pip install git+https://github.com/ecostech/viatom-ble.git
```

### Raspberry Pi one-time setup

On Raspberry Pi OS (Bullseye / Bookworm) add your user to the `bluetooth` group so BLE calls no longer need `sudo`:

```bash
sudo usermod -aG bluetooth $USER
# log out and back in for the group change to apply
```

Older setups without D-Bus permissions may still need `sudo` for scanning.

### macOS

On first run, macOS will prompt for Bluetooth permission for whichever terminal you launched from (e.g. Terminal, iTerm2, VS Code). Grant it in *System Settings → Privacy & Security → Bluetooth*.

Note that Apple hides the true MAC of BLE peripherals and instead surfaces a per-host CoreBluetooth UUID. Use `viatom-ble --scan-interactive` to discover the right identifier; it is what you pass to `--address`.

### Windows

Requires Windows 10 (1709+) for WinRT support. No admin required.

## Finding your device

Wear the ring, make sure it is not paired with the phone app, and run:

```bash
viatom-ble --scan-interactive
```

You will see something like:

```
Scanning for Viatom-family devices (10s)...
  [1] Checkme O2               AA:BB:CC:11:22:33   RSSI=-52 dBm
  [2] O2Ring                   11:22:33:44:55:66   RSSI=-71 dBm

Select a device: number to connect, 'a' to show all, 'r' to rescan, 'q' to quit: 1
```

Pick the number matching your ring and the tool connects immediately. If your device isn't listed (e.g. the name is customized), press `a` to disable the name filter and rescan.

For a one-shot list without the interactive prompt:

```bash
viatom-ble --scan            # only devices matching known Viatom names
viatom-ble --scan --scan-all # every BLE device seen during the scan window
```

## Running

Log readings to the console:

```bash
viatom-ble --address AA:BB:CC:11:22:33 --verbose
```

Publish to MQTT (initialization is skipped entirely without `--mqtt-address`):

```bash
viatom-ble --address AA:BB:CC:11:22:33 \
           --mqtt-address broker.local \
           --mqtt-username homeauto --mqtt-password secret \
           --mqtt-topic sensors/oximeter
```

Custom poll interval and long-form file logging:

```bash
viatom-ble --address AA:BB:CC:11:22:33 --read-period 5 --logfile /var/log/viatom-ble.log
```

Every reading published to MQTT is a single JSON object:

```json
{"spo2":97,"hr":72,"pi":6,"movement":3,"battery":85,"worn":true,"calibrating":false}
```

An online/offline status flag is also published to `<topic>/status` (retained, with an LWT for unexpected disconnects).

### CSV sample log

Add `--csv-file PATH` to append every reading to a CSV file in the exact format Viatom's PC software exports, so tools that already ingest those CSVs accept this file unchanged:

```bash
viatom-ble --address AA:BB:CC:11:22:33 --csv-file /var/lib/viatom/samples.csv
```

The file starts with a header line and then one row per reading:

```
Time,SpO2(%),Pulse Rate(bpm),Motion,SpO2 Reminder,PR Reminder,
"10:33:40PM Jan 31, 2026",97,72,3,0,0,
"10:33:42PM Jan 31, 2026",255,65535,0,0,0,
```

When the ring is off the finger, SpO2 is written as `255` and Pulse as `65535` — matching Viatom's own convention so downstream tools that already void those values keep working. Worn-but-calibrating rows keep their real `0,0` (they are not the no-finger sentinel).

**Rotating the log while the app runs**: copy the file elsewhere and then truncate or delete it. The running app detects the change on the next reading and re-adds the header automatically.

```bash
cp /var/lib/viatom/samples.csv /var/lib/viatom/rotated-$(date +%s).csv
: > /var/lib/viatom/samples.csv    # truncate; header reappears on next reading
```

## Full CLI reference

```
$ viatom-ble --help
usage: viatom-ble [-h] [--version] [-a ADDRESS] [-s] [-i] [--scan-all]
                  [--scan-duration SECONDS] [--read-period SECONDS]
                  [--reconnect-delay SECONDS] [--inactivity-timeout SECONDS]
                  [--inactivity-delay SECONDS] [--connect-timeout SECONDS]
                  [--mqtt-address MQTT_ADDRESS] [--mqtt-port MQTT_PORT]
                  [--mqtt-username MQTT_USERNAME] [--mqtt-password MQTT_PASSWORD]
                  [--mqtt-topic MQTT_TOPIC] [--mqtt-client-id MQTT_CLIENT_ID]
                  [--logfile LOGFILE] [-c] [-v] [--csv-file PATH]
```

Run `viatom-ble --help` locally for the full option descriptions.

## Embedding in your own app

### Synchronous

```python
from viatom_ble import ViatomClient, Reading

def on_reading(reading: Reading) -> None:
    if reading.worn and not reading.calibrating:
        print(reading.spo2, reading.heart_rate, reading.battery)

ViatomClient(
    address="AA:BB:CC:11:22:33",
    on_reading=on_reading,
).run_forever_sync()
```

### Async

```python
import asyncio
from viatom_ble import ViatomClient, Reading

async def main() -> None:
    async def on_reading(reading: Reading) -> None:
        print(reading.spo2, reading.heart_rate)

    client = ViatomClient(address="AA:BB:CC:11:22:33", on_reading=on_reading)
    try:
        await client.run_forever()
    except KeyboardInterrupt:
        await client.stop()

asyncio.run(main())
```

Callback functions may be either sync or async — `ViatomClient` inspects and awaits appropriately.

Other public exports: `scan_devices`, `interactive_pick`, `MqttPublisher`, `parse_notification`, and `Reading`.

## Running as a systemd service (Linux)

Edit `viatom-ble.service` and set `ExecStart` to point at the console script installed by pip (typically `/usr/local/bin/viatom-ble`) with your device address. The included unit file is a template.

```bash
sudo cp viatom-ble.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start viatom-ble
sudo systemctl enable viatom-ble    # start on boot
sudo journalctl -u viatom-ble -f    # follow logs
```

## Protocol notes

The tool speaks the Viatom BLE protocol observed on the PO3:

- Service UUID: `14839ac4-7d7e-415c-9a42-167340cf2339`
- Write characteristic UUID prefix: `8b00ace7…` — the client writes `\xaa\x17\xe8\x00\x00\x00\x00\x1b` here to request a reading.
- The same characteristic supports notifications; readings are delivered as ≥19-byte packets.

Byte layout of each notification packet:

| Index | Meaning |
|-------|---------|
| 7     | SpO2 % |
| 8     | Heart rate (bpm) |
| 14    | Battery % |
| 16    | Movement |
| 17    | Perfusion Index (PI) |
| 18    | Worn flag (0 = not on finger) |

The client's `--inactivity-timeout` / `--inactivity-delay` pair keeps the ring's battery from draining while it sits unworn: after a run of off-finger or calibrating notifications, the client force-disconnects and waits `--inactivity-delay` seconds before reconnecting.

## License

MIT — see [LICENSE](LICENSE).
