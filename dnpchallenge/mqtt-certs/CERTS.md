# Why this directory only has `ca.pem`

`vizhelper.py` is a client of the **viz dashboard's** Mosquitto broker
(`viz/docker-compose.yml`), not of a broker local to this module. Its only
job over TLS is to verify *that* broker's server certificate — Mosquitto's
`viz/mosquitto.conf` doesn't set `require_certificate true`, so it never
asks connecting clients for a client certificate. That means a client cert
here is dead weight, not a requirement.

This directory previously shipped its own self-signed CA/server/client
bundle (byte-identical to the one under `mqtthelper/mqtt-certs/` and
`mitm-modbus/slave/mqtt-certs/`) that had nothing to do with viz's actual
CA — pointing `vizhelper.py` at it would have made every TLS handshake
against the real dashboard fail with an unknown-CA error, bugs aside.

`ca.pem` here is a **copy** of `viz/mqtt-certs/ca.pem` — the CA that
actually signed the dashboard's server certificate — copied in rather than
mounted/shared live, consistent with how every other module in this repo
ships its own local cert files. If you regenerate viz's certs (via
`viz/createcerts.sh`), re-copy `viz/mqtt-certs/ca.pem` here too, or
`vizhelper.py`'s TLS connections will start failing.
