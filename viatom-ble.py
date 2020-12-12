import time
import os
import sys
import getopt
import logging
import bluepy.btle as btle
import paho.mqtt.client as mqtt
from datetime import datetime
from datetime import timedelta


def sleep(period):
    msperiod = period * 1000
    dt = datetime.now() - start_time
    ms = (dt.days * 24 * 60 * 60 + dt.seconds) * 1000 + dt.microseconds / 1000.0
    sleep = msperiod - (ms % msperiod)
    time.sleep(sleep/1000)
    dt = datetime.now() - start_time
    ms = (dt.days * 24 * 60 * 60 + dt.seconds) * 1000 + dt.microseconds / 1000.0


def on_mqtt_connect(client, userdata, flags, rc):
    client.disconnect_flag=False
    if rc == 0:
        client.connected_flag=True
        logger.info("MQTT: Connected to broker " + mqtt_address)
    else:
        client.connected_flag=False
        logger.warning("MQTT: Connection failed (code=" + rc + ")")


def on_mqtt_disconnect(client, userdata, rc):
    client.connected_flag=False
    client.disconnect_flag=True
    logger.warning("MQTT: Unexpected disconnection (code=" + rc + ")")


class ReadDelegate(btle.DefaultDelegate):
    def __init__(self):
        btle.DefaultDelegate.__init__(self)

    def handleNotification(self, handle, data):
        global ble_fail_count
        global ble_next_reconnect_delay
        try:
            if len(data) > 1:
                #logger.debug("Received Notification: " + ":".join("{:02x}".format(ord(c)) for c in data))
                #logger.debug("7=" + str(ord(data[7])) + "\t8=" + str(ord(data[8])) + "\t14=" + str(ord(data[14])) + "\t16=" + str(ord(data[16])) + "\t17=" + str(ord(data[17])) + "\t18=" + str(ord(data[18])) )
                if ord(data[18]) == 0:
                    ble_fail_count += 1
                    if verbose:
                        logger.debug("Device is not being worn!\tBattery: " + str(ord(data[14])) + "%")
                    if client.connected_flag:
                        client.publish(mqtt_topic, '{"Battery":' + str(ord(data[14])) + '}')
                elif ord(data[7]) == 0 and ord(data[8]) == 0:
                    ble_fail_count += 1
                    if verbose:
                        logger.debug("Device is calibrating...\tBattery: " + str(ord(data[14])) + "%")
                    if client.connected_flag:
                        client.publish(mqtt_topic, '{"Battery":' + str(ord(data[14])) + '}')
                else:
                    ble_fail_count = 0
                    if verbose:
                        logger.debug("SpO2: " + str(ord(data[7])) + "%\tHR: " + str(ord(data[8])) + " bpm\tPI: " + str(ord(data[17])) + "\tMovement: " + str(ord(data[16])) + "\tBattery: " + str(ord(data[14])) + "%")
                    if client.connected_flag:
                        client.publish('sensors', '{"SpO2":' + str(ord(data[7])) + ',"HR":' + str(ord(data[8])) + ',"PI":' + str(ord(data[17])) + ',"Movement":' + str(ord(data[16])) + ',"Battery":' + str(ord(data[14])) + '}')
                if ble_fail_count >= (ble_inactivity_timeout / ble_read_period):
                    # disconnect from device to conserve power
                    logger.warning("BLE: Inactivity timeout, disconnecting...")
                    ble_fail_count = 0
                    ble_next_reconnect_delay = ble_inactivity_delay
                    peripheral.disconnect()

        except:
            e = sys.exc_info()[0]
            logger.error("Data Handler Exception: " + str(e))


class ScanDelegate(btle.DefaultDelegate):
    def __init__(self):
        btle.DefaultDelegate.__init__(self)

    def handleDiscovery(self, dev, isNewDev, isNewData):
        if isNewDev:
            print "Discovered device", dev.addr
        elif isNewData:
            print "Received new data from", dev.addr


def ble_scan():
    scanner = btle.Scanner().withDelegate(ScanDelegate())
    devices = scanner.scan(10.0)

    for dev in devices:
        print "Device %s (%s), RSSI=%d dB" % (dev.addr, dev.addrType, dev.rssi)
        for (adtype, desc, value) in dev.getScanData():
            print "  %s = %s" % (desc, value)


if __name__ == "__main__":

    # ble config params
    # ble address of device
    ble_address = "f3:ce:82:50:0c:a5"
    ble_type = btle.ADDR_TYPE_RANDOM
    # seconds to wait between reads
    ble_read_period = 2
    # seconds to wait between btle reconnection attempts
    ble_reconnect_delay = 1
    # seconds of btle inactivity (not worn/calibrating) before force-disconnect
    ble_inactivity_timeout = 300
    # seconds to wait after inactivity timeout before reconnecting resumes
    ble_inactivity_delay = 130

    # mqtt config params
    mqtt_address=""
    mqtt_username=""
    mqtt_password=""
    mqtt_topic="viatom-ble"

    # other params
    ble_next_reconnect_delay = ble_reconnect_delay
    ble_fail_count = 0
    logfile = "/var/log/viatom-ble.log"
    console = False;
    verbose = False

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hvcsa:m:", ["address=","mqtt="])
    except getopt.GetoptError:
        print 'viatom-ble.py -v -a <ble_address>'
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print 'viatom-ble.py -v -a <ble_address>'
            sys.exit()
        elif opt == '-v':
            verbose = True
        elif opt == '-c':
            console = True
        elif opt == '-s':
            if os.geteuid() != 0:
                print 'Must be root to perform scan'
                sys.exit(3)
            ble_scan();
            sys.exit()
        elif opt in ("-a", "--address"):
            ble_address = arg

    # initialize logger
    if not console or logfile == "":
        print 'Logging to ' + logfile
        logging.basicConfig(format='%(asctime)s.%(msecs)03d [%(process)d] %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S', filename=logfile, level=logging.DEBUG)
    else:
        print 'Logging to console'
        logging.basicConfig(format='%(asctime)s.%(msecs)03d [%(process)d] %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S', level=logging.DEBUG)
    logger = logging.getLogger()

    logger.info("Starting...")

    # Connect to MQTT broker
    # (will automatically reconnect in background on connection drop)
    mqtt.Client.connected_flag=False
    mqtt.Client.disconnect_flag=False
    client = mqtt.Client("viatom-ble")
    client.on_connect=on_mqtt_connect
    client.on_disconnect=on_mqtt_disconnect
    client.loop_start()
    logger.info("MQTT: Connecting to broker " + mqtt_address + "...")
    client.username_pw_set(username=mqtt_username, password=mqtt_password)
    try:
        client.connect(mqtt_address)
    except:
        logger.error("MQTT: Failed to connect to broker " + mqtt_address)

    # Connect to BLE device and write/read infinitely
    peripheral = btle.Peripheral()
    while True:
        try:
            last_time = datetime.now()
            start_time = datetime.now()
            ble_fail_count = 0
            logger.info("BLE: Connecting to device " + ble_address + "...")
            # Connect to the peripheral
            #peripheral = btle.Peripheral(ble_address, ble_type)
            peripheral.connect(ble_address, ble_type)
            logger.info("BLE: Connected to device " + ble_address)
            # Set the notification delegate
            peripheral.setDelegate(ReadDelegate())
            write_handle = None
            subscribe_handle = None
            # magic stuff for the Viatom GATT service
            ble_uuid = "14839ac4-7d7e-415c-9a42-167340cf2339"
            ble_write_uuid_prefix = "8b00ace7"
            write_bytes = b'\xaa\x17\xe8\x00\x00\x00\x00\x1b'

            # this is general magic GATT stuff
            # notify handles will have a UUID that begins with this
            ble_notify_uuid_prefix = "00002902"
            # these are the byte values that we need to write to subscribe/unsubscribe for notifications
            subscribe_bytes = b'\x01\x00'
            # unsubscribe_bytes = b'\x00\x00'

            # find the desired service
            service = peripheral.getServiceByUUID(ble_uuid)
            if service is not None:
                logger.debug("Found service: " + str(service))
                #chars = service.getCharacteristics()
                #for char in chars:
                    #logger.debug("  char: " + str(char) + ", handle: " + str(char.handle) + ", props: " + str(char.properties))
                descs = service.getDescriptors()
                # this is the important part-
                # find the handles that we will write to and subscribe for notifications
                for desc in descs:
                    #logger.debug("  desc: " + str(desc))
                    str_uuid = str(desc.uuid).lower()
                    if str_uuid.startswith(ble_write_uuid_prefix):
                        write_handle = desc.handle
                        logger.debug("*** Found write handle: " + str(write_handle))
                    elif str_uuid.startswith(ble_notify_uuid_prefix):
                        subscribe_handle = desc.handle
                        logger.debug("*** Found subscribe handle: " + str(subscribe_handle))

            if write_handle is not None and subscribe_handle is not None:
                # we found the handles that we need
                logger.debug("Found both required handles")

                # this call performs the subscribe for notifications
                #response = peripheral.writeCharacteristic(subscribe_handle, subscribe_bytes, withResponse=True)

                # now that we're subscribed for notifications, waiting for TX/RX...
                logger.info("Reading from device...")
                while True:
                    # this call performs the subscribe for notifications
                    response = peripheral.writeCharacteristic(subscribe_handle, subscribe_bytes, withResponse=True)

                    # this call performs the request for data
                    response = peripheral.writeCharacteristic(write_handle, write_bytes, withResponse=True)

                    peripheral.waitForNotifications(1.0)
                    sleep(ble_read_period);

        except btle.BTLEException as e:
            logger.warning("BTLEException: " + str(e))

        except IOError as e:
            logger.error("IOError: " + str(e))

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt, exiting")
            sys.exit()

        except:
            e = sys.exc_info()[0]
            logger.error("Exception: " + str(e))

        try:
            logger.info("BLE: Waiting " + str(ble_next_reconnect_delay) + " seconds to reconnect...")
            time.sleep(ble_next_reconnect_delay);
            ble_next_reconnect_delay = ble_reconnect_delay
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt, exiting")
            sys.exit()
        except:
            e = sys.exc_info()[0]
            logger.error("Exception: " + str(e))


    logger.info("Exiting...")
    client.loop_stop()
    client.disconnect()

