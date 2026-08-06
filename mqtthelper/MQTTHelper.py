"""Poll a couple of GPIO input pins directly and republish their raw
electrical state to MQTT, independent of any single challenge's own
protocol-level publishing - a hardware-level health signal for the
dashboard rather than a decoded application value.

Previously shelled out to the WiringPi `gpio readall` CLI and pattern-
matched pin numbers in its text output - that tool prints BCM, wPi, and
Physical columns side by side, and the old code never specified which one
it meant, so "pin 18" was genuinely ambiguous between three different
physical pins. Reading pins directly via RPi.GPIO removes that ambiguity
structurally instead of guessing at a column, and drops the WiringPi
dependency entirely (WiringPi has no official support past Pi 3, which
was an open question for this repo - see docs/AUDIT.md).
"""
import os
import signal
import time

import paho.mqtt.client as mqtt

try:
    import RPi.GPIO as GPIO
except (ImportError, RuntimeError) as exc:
    # Same fallback as mitm-modbus/slave/slave.py - RPi.GPIO raises
    # RuntimeError (not just ImportError) off real Pi hardware.
    print(f"RPi.GPIO unavailable ({exc}), using no-op GPIO mock")

    class _MockGPIO:
        BCM = "BCM"
        IN = "IN"
        PUD_DOWN = "PUD_DOWN"

        def setmode(self, mode):
            print(f"[mock GPIO] setmode({mode})")

        def setup(self, pin, mode, pull_up_down=None):
            print(f"[mock GPIO] setup(pin={pin}, mode={mode}, pull_up_down={pull_up_down})")

        def input(self, pin):
            return 0

    GPIO = _MockGPIO()

# Two independent spare pins - see docs/PINOUT_MAP.md, which reserves
# physical pin 33 (BCM13) and physical pin 35 (BCM19) for this module
# specifically because they don't collide with any pin already claimed by
# bh-intellirupter, dnpchallenge, or mitm-modbus. Override via env var if
# you wire this up to something specific.
MONITORED_PINS = {
    int(os.environ.get("MQTTHELPER_PIN_1", "13")): os.environ.get("MQTTHELPER_ZONE_1", "zone3"),
    int(os.environ.get("MQTTHELPER_PIN_2", "19")): os.environ.get("MQTTHELPER_ZONE_2", "zone4"),
}

# The three actual challenges (as opposed to mqtthelper's own generic
# pins) - see server.js's ZONES list. "Complete" means each one is
# publishing 0 (Down/green - turbine stopped, per the unified polarity in
# docs/PINOUT_MAP.md), not 1 (Normal/red - still running).
CHALLENGE_ZONES = os.environ.get("CHALLENGE_ZONES", "zone1,zone2,zone5").split(",")

# viz's Mosquitto broker lives in a separate compose project and is
# reached via its host-published port, same pattern used everywhere else
# in this repo (bh-intellirupter, dnpchallenge, mitm-modbus).
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "host.docker.internal")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))

# viz's Mosquitto doesn't set `require_certificate true` (see
# viz/mosquitto.conf), so it never asks connecting clients for a client
# certificate - only the CA used to verify viz's own server certificate is
# needed here. See mqtt-certs/CERTS.md.
CA_CERT = os.path.join(os.path.dirname(__file__), "mqtt-certs", "ca.pem")

POLL_INTERVAL_SECONDS = 1

_running = True


def _signal_handler(sig, frame):
    global _running
    print("Exiting...")
    _running = False


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# Latest known value per challenge zone, updated by _on_message() as
# viz's broker echoes them back. None until a message has actually been
# seen for that zone - deliberately distinct from 0, so "never heard from
# this challenge" doesn't get mistaken for "this challenge is done."
_challenge_state = {zone: None for zone in CHALLENGE_ZONES}


def _on_message(client, userdata, msg):
    if msg.topic in _challenge_state:
        try:
            _challenge_state[msg.topic] = int(msg.payload.decode())
        except ValueError:
            pass  # unexpected payload - ignore rather than crash the poll loop


def _all_challenges_complete():
    # Only true once every tracked zone has actually reported in AND all
    # of them read 0 (Down/green, i.e. stopped) - see CHALLENGE_ZONES.
    return all(v == 0 for v in _challenge_state.values())


def send_to_mqtt():
    GPIO.setmode(GPIO.BCM)
    for pin in MONITORED_PINS:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.tls_set(ca_certs=CA_CERT)
    client.tls_insecure_set(True)  # skip hostname check; CA validation still applies
    client.on_message = _on_message
    client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, 60)
    for zone in CHALLENGE_ZONES:
        client.subscribe(zone)
    client.loop_start()

    try:
        while _running:
            complete = _all_challenges_complete()
            for pin, zone in MONITORED_PINS.items():
                if complete:
                    # All three challenges done - zone3/zone4 go
                    # offline/green regardless of what's actually wired
                    # to these pins.
                    client.publish(zone, 0)
                else:
                    # Otherwise, publish the pin's raw electrical level
                    # (1=HIGH, 0=LOW) as before - not a judgment about
                    # whether that's "good" or "bad," just a live reading.
                    client.publish(zone, GPIO.input(pin))
            time.sleep(POLL_INTERVAL_SECONDS)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    send_to_mqtt()
