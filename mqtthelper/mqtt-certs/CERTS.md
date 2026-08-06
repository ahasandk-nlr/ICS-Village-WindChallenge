# Why this directory only has `ca.pem`

Same situation as `dnpchallenge/mqtt-certs/CERTS.md` and
`mitm-modbus/slave/mqtt-certs/CERTS.md` — `MQTTHelper.py` is a client of
the **viz dashboard's** Mosquitto broker, not of a broker local to this
module. `viz/mosquitto.conf` doesn't set `require_certificate true`, so
Mosquitto never asks connecting clients for a client certificate — only
the CA used to verify *viz's* server certificate is needed here.

This directory previously shipped a self-signed CA/server/client bundle
byte-identical to `dnpchallenge/mqtt-certs/` and
`mitm-modbus/slave/mqtt-certs/`'s pre-fix bundles — a different CA than
the one that actually signed viz's server certificate, which would have
failed every TLS handshake against the real broker regardless of any
other bug.

`ca.pem` here is a **copy** of `viz/mqtt-certs/ca.pem`. If you regenerate
viz's certs (via `viz/createcerts.sh`), re-copy `viz/mqtt-certs/ca.pem`
here too.
