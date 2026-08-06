from pymodbus.client import ModbusTcpClient
import time
import numpy as np
import signal
import socket
import struct
import os
import paho.mqtt.client as mqtt

# bh-intellirupter previously had no tie-in to the shared viz dashboard at
# all, unlike dnpchallenge/mitm-modbus/mqtthelper - this is the "vizhelper"
# equivalent for this challenge, folded into the existing polling loop
# rather than a separate service, since this script already holds the
# Modbus connection to the PLC it needs.
#
# ADDRESS CAVEAT: this reads Modbus coil TURBINE_COIL_ADDR as a best-effort
# stand-in for the ladder logic's %QX10 "Turbine" output - matiec's exact
# byte.bit -> Modbus coil address mapping for a bare (no ".bit" suffix)
# %QX10 declaration hasn't been verified against OpenPLC's own compiled
# Modbus address list. Verify under Settings -> Modbus Server in the
# OpenPLC web UI and override via env var if it doesn't match.
TURBINE_COIL_ADDR = int(os.environ.get('TURBINE_COIL_ADDR', '10'))
ZONE = os.environ.get('ZONE', 'zone5')

# Same pattern as dnpchallenge/vizhelper.py, mitm-modbus/slave.py, and
# mqtthelper/MQTTHelper.py: viz's Mosquitto broker lives in a separate
# compose project and is reached via its host-published port, using a
# copy of viz's real CA (see rtu/mqtt-certs/CERTS.md) since viz's
# mosquitto.conf doesn't require client certificates.
MQTT_BROKER_HOST = os.environ.get('MQTT_BROKER_HOST', 'host.docker.internal')
MQTT_BROKER_PORT = int(os.environ.get('MQTT_BROKER_PORT', '1883'))
CA_CERT = os.path.join(os.path.dirname(__file__), 'mqtt-certs', 'ca.pem')

mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
try:
    mqtt_client.tls_set(ca_certs=CA_CERT)
    mqtt_client.tls_insecure_set(True)  # skip hostname check; CA validation still applies
    mqtt_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
    mqtt_client.loop_start()
except OSError as exc:
    # Dashboard being down shouldn't take the actual challenge down with
    # it - same reasoning as mitm-modbus/slave.py's changeON() fix.
    print(f"couldn't reach MQTT broker at {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}: {exc}")


def publish_turbine_zone():
    try:
        rr = plc_client.read_coils(TURBINE_COIL_ADDR, count=1, slave=1)
        if rr.isError():
            print(f"couldn't read turbine coil: {rr}")
            return
        # 1 = Normal/red (turbine running), 0 = Down/green - matching the
        # now-unified polarity across all three turbine-relay challenges,
        # see docs/PINOUT_MAP.md.
        mqtt_client.publish(ZONE, 1 if rr.bits[0] else 0)
    except OSError as exc:
        print(f"couldn't publish to MQTT: {exc}")


# Properly defining a safe exit
def safe_exit():
    print('Exiting...')
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    plc_client.close()
    client_socket.close()
    exit(0)

# Add mechanism to gracefully exit on interupt
def signal_handler(sig, frame):
    safe_exit()

signal.signal(signal.SIGINT, signal_handler)

# The PLC lives on the same docker-compose network as this container, so
# reach it via the compose service name and its *internal* Modbus port
# (502) - not the host-published port (5000 in docker-compose.yml, which
# is only for access from outside the compose network).
PLC_HOST = os.environ.get('PLC_HOST', 'plc')
PLC_PORT = int(os.environ.get('PLC_PORT', '502'))

# hmi.py runs directly on the host (started by startup.sh), not inside
# docker-compose, so it isn't reachable by service name. HMI_HOST defaults
# to Docker's special host-gateway hostname (wired up via extra_hosts in
# docker-compose.yml) so this keeps working regardless of what IP the host
# actually has. Override HMI_HOST if you need to point at a different box.
HMI_HOST = os.environ.get('HMI_HOST', 'host.docker.internal')
HMI_PORT = int(os.environ.get('HMI_PORT', '8888'))
HMI_SPEAKER_PORT = int(os.environ.get('HMI_SPEAKER_PORT', '8889'))

# Create a TCP socket
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.connect((HMI_HOST, HMI_PORT))
listener_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener_socket.connect((HMI_HOST, HMI_SPEAKER_PORT))

# Set up modbus client
plc_client = ModbusTcpClient(host=PLC_HOST, port=PLC_PORT, auto_open=True)
plc_client.connect()

# Global params
mu = 0.5                            # Average for normal distribution
sd = 0.09                           # Standard deviation for normal distribution
sleep_time = 1 / 1000 * 500         # How long to sleep (ms) in loop
reset_addr = 3                      # Address of control for turbine
input_addr = 3                      # Address that holds the voltage value

# Call the reset coil on PLC
# plc_client.write_coil(reset_addr, True, slave=1)

while(True):
    # Get voltage from PLC (and add random noise)
    result = plc_client.read_discrete_inputs(input_addr, 8, slave=1)
    # print(result.bits)
    check = result.bits[0]
    if (not check):
        voltage_value = 1 + np.random.normal(mu, sd, 1)
    else:
        voltage_value = 1.5
    print('Got voltage: ' + str(voltage_value))

    # # Send voltage to HMI
    data_to_send = struct.pack('!f', voltage_value)
    client_socket.sendall(data_to_send)

    # Listener logic
    while True:
        received_bytes = listener_socket.recv(1024)
        if received_bytes:
            break
    # print('\n' + str(received_bytes) + '\n')
    received_data = received_bytes.decode().strip()
    # print('\n' + str(received_data) + '\n')
    if received_data == 'fault':
        print('ERROR: recieved fault')
        plc_client.write_coil(1, True, slave=1)
        time.sleep(0.2)
        plc_client.write_coil(1, False, slave=1)

    publish_turbine_zone()

    time.sleep(sleep_time)

