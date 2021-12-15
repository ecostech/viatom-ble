# viatom-ble
Python script to read sensor values over BLE from Viatom wearable ring oxygen (SpO2) monitors.

Reads values once every 2 second and logs to console or log file. Also publishes values to an MQTT broker if so configured.

## Compatability
Tested against a Viatom model PO3 (Wellue KidsO2) during development.

Should be compatible with all Viatom ring oxygen monitors inluding models PO1, PO2 (Wellue O2Ring), PO3, PO4 and PO1B.

## Setup
Install BluePy for BLE and Paho for MQTT client

```
sudo pip install bluepy
sudo pip install paho-mqtt
```

Scan while wearing the device to determine it's BLE address.

*Note: Ensure the device is not connected to any other monitor (ie the mobile app) before scanning.*

```
sudo python viatom-ble.py -s
```

Look for a device with `Complete Local Name` that is associated with the ring monitor device and note its `Device` address (six colon-delimited octets, eg aa:bb:cc:11:22:33)

Edit the python script `viatom-ble.py` and enter the BLE address where the `ble_address` variable is initialized.

Optionally also configure the MQTT client by enering values for the `mqtt_*` variables where they are initialized.

Test BLE connectivity while wearing the device.

*Note: Warnings and exceptions from the MQTT client can be ignored if it has not been configured.*

```
python viatom-ble.py -v -c
```

## Installation
Edit the service definition file `viatom-ble.service` and update the command in `ExecStart` to reflect the correct path to the python script.

Install the service definition file:

```
sudo cp viatom-ble.service /lib/systemd/system/.
sudo systemctl daemon-reload
```

To start the service:

```
sudo systemctl start viatom-ble
```

To automatically start the service on boot:

```
sudo systemctl enable viatom-ble
```

## TODO
Make the python script compatible with including as a module in other scripts.

