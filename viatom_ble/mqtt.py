"""Optional MQTT publisher.

Only imported by callers that pass an MQTT broker address. Nothing here
initializes a connection until :meth:`MqttPublisher.start` is called.
"""

from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from .protocol import Reading

_STATUS_ONLINE = json.dumps({"online": True})
_STATUS_OFFLINE = json.dumps({"online": False})


class MqttPublisher:
    """Thin wrapper around paho-mqtt that publishes Reading objects as JSON.

    Publishes each Reading to ``topic`` and maintains an online/offline
    status via a Last Will and Testament posted to ``<topic>/status``.
    """

    def __init__(
        self,
        address: str,
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        topic: str = "viatom-ble",
        client_id: str = "viatom-ble",
        logger: logging.Logger | None = None,
    ) -> None:
        self.address = address
        self.port = port
        self.topic = topic
        self.status_topic = f"{topic}/status"
        self._log = logger or logging.getLogger(__name__)
        self._connected = False

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        if username:
            self._client.username_pw_set(username=username, password=password)
        self._client.will_set(self.status_topic, _STATUS_OFFLINE, qos=1, retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        """Kick off the paho network loop and initiate a connection."""
        self._log.info(f"MQTT: connecting to broker {self.address}:{self.port}")
        try:
            self._client.connect_async(self.address, self.port)
        except OSError as e:
            self._log.error(f"MQTT: failed to resolve broker {self.address}: {e}")
        self._client.loop_start()

    def stop(self) -> None:
        try:
            if self._connected:
                self._client.publish(self.status_topic, _STATUS_OFFLINE, qos=1, retain=True)
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    def publish(self, reading: Reading) -> None:
        if not self._connected:
            return
        payload = json.dumps(
            {
                "spo2": reading.spo2,
                "hr": reading.heart_rate,
                "pi": reading.perfusion_index,
                "movement": reading.movement,
                "battery": reading.battery,
                "worn": reading.worn,
                "calibrating": reading.calibrating,
            }
        )
        self._client.publish(self.topic, payload)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code == 0 or getattr(reason_code, "is_failure", False) is False:
            self._connected = True
            self._log.info(f"MQTT: connected to broker {self.address}")
            client.publish(self.status_topic, _STATUS_ONLINE, qos=1, retain=True)
        else:
            self._connected = False
            self._log.warning(f"MQTT: connection failed (code={reason_code})")

    def _on_disconnect(
        self, client, userdata, disconnect_flags=None, reason_code=None, properties=None
    ) -> None:
        self._connected = False
        if reason_code is not None and reason_code != 0:
            self._log.warning(f"MQTT: disconnected (code={reason_code})")
        else:
            self._log.info("MQTT: disconnected")
