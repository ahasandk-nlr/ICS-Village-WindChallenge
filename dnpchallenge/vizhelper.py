import os
import signal
import time

import requests
import paho.mqtt.client as mqtt

# rtu/ied are ot-sim containers in this same docker-compose project, so
# they're reachable by service name on the default compose network.
RTU_HOST = os.environ.get('RTU_HOST', 'rtu')
RTU_API_PORT = os.environ.get('RTU_API_PORT', '9101')
IED_HOST = os.environ.get('IED_HOST', 'ied')
IED_API_PORT = os.environ.get('IED_API_PORT', '9102')

# The MQTT broker is viz's Mosquitto instance, which lives in a *separate*
# docker-compose project (viz/docker-compose.yml). It's reached via
# Docker's host-gateway hostname and viz's host-published port, the same
# pattern used for bh-intellirupter's rtu -> hmi.py connection.
MQTT_BROKER_HOST = os.environ.get('MQTT_BROKER_HOST', 'host.docker.internal')
MQTT_BROKER_PORT = int(os.environ.get('MQTT_BROKER_PORT', '1883'))

# Mosquitto's viz/mosquitto.conf does not set `require_certificate true`,
# so it never requests a client certificate - only the CA used to verify
# viz's server certificate is needed here. See mqtt-certs/CERTS.md.
CA_CERT = os.path.join(os.path.dirname(__file__), 'mqtt-certs', 'ca.pem')

POLL_INTERVAL_SECONDS = 1

_running = True


def _signal_handler(sig, frame):
    global _running
    print('Exiting...')
    _running = False


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def turbine_is_stopped():
    """True once the IED reports an active e-stop and the RTU's status
    LED has cleared (i.e. the stop has been acknowledged/latched), per the
    logic programs in iedconfig.xml / rtuconfig.xml.
    """
    rtu_resp = requests.get(f'http://{RTU_HOST}:{RTU_API_PORT}/api/v1/query/led', timeout=5)
    rtu_resp.raise_for_status()
    rtudata = rtu_resp.json()

    ied_resp = requests.get(f'http://{IED_HOST}:{IED_API_PORT}/api/v1/query/estop', timeout=5)
    ied_resp.raise_for_status()
    ieddata = ied_resp.json()

    stopped = ieddata['value'] == 1 and rtudata['value'] == 0
    if stopped:
        print('turbine stopped')
    return stopped


def send_to_mqtt():
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.tls_set(ca_certs=CA_CERT)
    client.tls_insecure_set(True)  # skip hostname check; CA validation still applies

    client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
    client.loop_start()

    try:
        while _running:
            try:
                stopped = turbine_is_stopped()
            except requests.RequestException as exc:
                # rtu/ied may still be booting, or briefly unreachable - don't
                # crash the whole helper over a transient poll failure.
                print(f'Poll failed, will retry: {exc}')
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # zone2 is this challenge's assigned dashboard zone (zone1 is
            # mitm-modbus - see viz/public/index.html's zone numbering).
            # Published value semantics match viz's frontend: 1 = good/
            # normal, 0 = fault/alarm - so "stopped" (the win condition
            # from a player's perspective) shows as the alarm state on the
            # operator dashboard, same as a real HMI would show it.
            client.publish('zone2', 0 if stopped else 1)
            time.sleep(POLL_INTERVAL_SECONDS)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    send_to_mqtt()
