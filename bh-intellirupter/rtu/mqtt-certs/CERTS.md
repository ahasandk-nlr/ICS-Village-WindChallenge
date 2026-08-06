# Why this directory only has `ca.pem`

Same situation as `dnpchallenge/mqtt-certs/CERTS.md`,
`mitm-modbus/slave/mqtt-certs/CERTS.md`, and
`mqtthelper/mqtt-certs/CERTS.md` — `rtu-speaker.py` is a client of the
**viz dashboard's** Mosquitto broker, not of a broker local to this
module. `viz/mosquitto.conf` doesn't set `require_certificate true`, so
Mosquitto never asks connecting clients for a client certificate — only
the CA used to verify *viz's* server certificate is needed here.

`ca.pem` here is a **copy** of `viz/mqtt-certs/ca.pem`. If you regenerate
viz's certs (via `viz/createcerts.sh`), re-copy `viz/mqtt-certs/ca.pem`
here too, or `rtu-speaker.py`'s zone-publishing will start failing with a
TLS verification error.
