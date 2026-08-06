# audit-sidecar

One shared service, attached to every challenge's own Docker network at
once, so there's a single place participants can go to:

1. **Watch live traffic** across all five challenge networks (best-effort
   protocol decode: Modbus function codes, cleartext telnet, raw hex for
   everything else including DNP3, which isn't decoded in depth here).
2. **Read and, where applicable, write** the specific protocol points that
   matter for finishing each challenge (Modbus coils/registers via
   `pymodbus`, `dnpchallenge`'s ot-sim tags via its own HTTP API), instead
   of needing to hand-roll a Modbus/DNP3 client just to poke at a value
   they've already identified from the traffic view.

See `docs/AUDIT.md` Part 3 for *why* this exists: none of these
challenges' internal traffic reaches a physical wire on its own (private
Docker bridge networks per challenge), so without something like this,
there's no way for a participant to observe or interact with most of it at
all.

## Setup

**Bring up every challenge stack first** (`bh-intellirupter`,
`dnpchallenge`, `mitm-modbus`, `mqtthelper`, `viz`) so their Docker
networks exist, *then* bring this up:

```bash
cd audit-sidecar
docker compose up --build
```

`docker-compose.yml` references each challenge's network as
`external: true` by its exact Compose-generated name (e.g.
`dnpchallenge_default`, `mitm-modbus_my_network`, or the explicitly named
`proxiable` for `bh-intellirupter`). If a challenge hasn't been started
yet, Docker will fail to start this service with a "network not found"
error naming exactly which one — bring that challenge up and retry.

Open `http://<host>:8000`.

## How interface-to-challenge labeling works

Each challenge's `docker-compose.yml` was given an explicit subnet
(172.30.0.0/24 for `bh-intellirupter`, 172.31.0.0/24 for `dnpchallenge`,
172.20.0.0/16 for `mitm-modbus` (pre-existing), 172.32.0.0/24 for
`mqtthelper`, 172.33.0.0/24 for `viz`) specifically so this container could
be given a deterministic static IP on each one. `sidecar.py`'s
`NETWORK_LABELS` matches its own IP prefix on each interface against that
table to know which challenge a given interface's traffic belongs to. If
you change any challenge's subnet, update `NETWORK_LABELS` in
`sidecar.py` (and this container's static IPs in `docker-compose.yml`) to
match, or interface labeling will silently show `unknown (<ip>)` instead
of the challenge name.

## What this does *not* do

- **It does not make `mitm-modbus`'s Ettercap/ARP-spoofing mechanic work
  as originally designed.** That challenge's premise is a participant
  actively poisoning ARP on the wire between `master` and `slave`; a
  passive observer sitting on the same Docker network doesn't reproduce
  that (there's nothing stopping the real conversation, and a participant
  still has no way to run Ettercap against it without a NIC on that
  network segment, which they still don't have). This sidecar gives
  visibility into that traffic and a way to read/write the coil it
  controls directly — it doesn't restore the "intercept and alter live
  traffic yourself" experience. That challenge's design intent may need a
  conscious update to match what's actually deliverable here (e.g.
  "observe and manipulate the point directly" rather than "MITM it").
- **DNP3 traffic is not deeply decoded** — the live traffic view shows raw
  frame bytes for `dnpchallenge`'s DNP3 traffic (port 20000), not decoded
  function codes/points. Reading and writing `dnpchallenge`'s actual tags
  works fine (via ot-sim's own HTTP API, not by decoding DNP3 on the
  wire), so the challenge is still fully usable through this tool — it's
  specifically the *raw DNP3 packet view* that's shallow right now.
- **`bh-intellirupter`'s Modbus addresses in `challenges.py` are
  best-effort**, read directly off `fixedfinal.st`'s `%QX`/`%IX`
  declarations, not verified against OpenPLC's actual compiled Modbus
  address list. Cross-check against Settings → Modbus Server in the
  OpenPLC web UI before relying on them for anything beyond exploration.

## Security note

The write panel can change live challenge state (trip a coil, clear a
fault, flip an e-stop tag) from a single shared web page with no
authentication. That's intentional for an exhibit built around
participants manipulating these systems — but it also means **anyone who
can reach port 8000 can reset or interfere with another participant's
in-progress attempt**. If that's not acceptable for your event, put this
behind whatever access control your exhibit network already uses, or
restrict the write endpoints (`POST /api/write/...`) separately from the
read-only traffic view.
