# Admin Guide — ICS Village Wind Turbine Challenge

Audience: exhibit organizers/admins setting up, running, and functionally
testing this exhibit — either in simulation (laptop/VM, no Pi) or on the
real Raspberry Pi + relay + turbine hardware.

Read [`AUDIT.md`](AUDIT.md) first if you haven't — it lists every known
bug and gap referenced below by file/line. This guide assumes those issues
get fixed as you bring each module up; it tells you how to set up and
verify each one, and calls out which known bugs will block you from doing
so until patched.

**Environment reminder:** unless explicitly noted, everything below is
written for the **simulation environment** (Docker on a normal x86/amd64
or non-Pi ARM host, no relay attached). Steps that require the actual
Raspberry Pi and physical wiring are marked **[PI ONLY]**.

---

## 0. Before you start anything

- Docker + Docker Compose installed on the admin/test host.
- `openssl` available if you need to regenerate any TLS certs
  (`viz/createcerts.sh` is the only cert-generation script in the repo —
  every other module ships pre-baked certs under its own `mqtt-certs/`
  directory; treat those as demo-only and rotate them before any public
  event).
- Pull the relevant git branches before assuming a module is "missing
  code" — see the branch table below. Several modules' real source lives
  on unmerged branches, not on `main`.

| If you're setting up... | Also check branch |
|---|---|
| `bh-intellirupter` (OpenPLC) | No longer needed — `bh-intellirupter/OpenPLC_v3/` is now vendored directly on `main` (see `OpenPLC_v3/VENDORED.md`). The old `sri` branch is stale and no longer the source of truth for this. |
| DNP3 docs/config | `jg-dnp3-doc` — name suggests DNP3-specific documentation that may already exist there |
| Viz dashboard | `VIZ`, `mines_students_challenge` — variants of the dashboard |
| Modbus MITM | `mitm-modbus` (branch of the same name) |

To pull a branch for inspection without touching `main`:
```bash
git fetch origin
git switch -c sri-review origin/sri
```

---

## 1. `viz/` — Dashboard (start this first)

**Purpose:** central dashboard. An HTTPS Node/Express server subscribes to
MQTT topics `zone1`..`zone16` over TLS and pushes updates to a browser via
Socket.IO. Every other challenge module publishes its state here, so bring
this up before testing anything else.

**Setup:**
```bash
cd viz
docker compose up --build
```
This starts two services: `https` (the dashboard, port 3000) and `mqtt`
(Mosquitto, ports 1883/8443) using the certs already in `mqtt-certs/` and
`mosquitto.conf`. If you need fresh certs, run `./createcerts.sh` first —
it regenerates a full CA/server/client chain into `mqtt-certs/` and prints
each file it created.

**Functional test:**
1. Open `https://<host>:3000` in a browser (accept the self-signed cert
   warning). You should see the zone grid from `public/index.html`.
2. Publish a test message and confirm it reaches the browser live:
   ```bash
   docker exec -it <mqtt_container> mosquitto_pub \
     --cafile /mosquitto/config/ca.pem -h localhost -p 1883 \
     -t zone1 -m 1
   ```
   The corresponding zone tile in the browser should flip state within
   ~1s. If it doesn't, check the Node container logs for `MQTT Error:` —
   TLS cert mismatches are the most common cause.
3. Confirm all 16 zone subscriptions succeeded: `docker logs <https
   container>` should print `Subscribed to zone1` through `zone16` with no
   `Error subscribing` lines.

**Known issues:** none blocking. `viz/Dockerfilehttps` is an unused
duplicate file — safe to ignore or delete, don't confuse it with the real
`Dockerfile`. Also worth knowing: `viz/index.html` and
`viz/index-http.html` at the repo root (not inside `public/`) are dead
files nothing ever serves — the real frontend is `viz/public/index.html` +
`viz/public/main.js`. Don't edit the root-level ones expecting it to
change what's live.

**Switching the served map between venues:** the dashboard's background
map is controlled by the `MAP_IMAGE` environment variable on the `https`
service in `viz/docker-compose.yml` — `map.png` (Las Vegas), `denMap.png`
(Denver), or `ftcMap.png` (Fort Collins), all three shipping in
`viz/public/` at identical pixel dimensions (2232×1684). To switch:
```yaml
# viz/docker-compose.yml
services:
  https:
    environment:
      MAP_IMAGE: ftcMap.png   # was denMap.png
```
then `docker compose up -d --build https`. This used to be a hardcoded
filename in `public/index.html`'s `<img src>` — fixed so venue changes are
a one-line config edit instead of a frontend source edit. If you add
another venue's map image, match the exact 2232×1684 canvas size — if your
source screenshot has a different aspect ratio (Fort Collins' did, at
1339×867 vs. the canvas's 1684:2232 ratio), center-crop it to 1.325:1
*before* scaling to 2232×1684, or it'll come out visibly stretched
compared to the other maps. A one-off Python/Pillow snippet did this for
`ftcMap.png`; there's no repo tooling for it since it's a rare, one-time
operation per new venue.

**Zone positions on the dashboard are hand-placed, not a grid — and only
active zones exist at all.** `server.js`'s `ZONES` array (served to the
frontend via `/zone-config.js`) is the single source of truth for which
zones exist, where each one sits on the canvas, and what `server.js`
subscribes to on the MQTT side — previously these three things were three
independently-hardcoded "1 through 16" loops, 11/16 of which corresponded
to zones nothing has ever published to. To add a challenge's zone (or
move/resize an existing one), edit the `ZONES` array in `server.js` only —
`public/main.js` and the side panel rebuild themselves from it
automatically. Current positions cluster around the map's downtown/
city-core area, sized and placed individually rather than tiling the
canvas — but since the three shipped maps' downtown areas aren't at
identical pixel coordinates, this is a shared compromise across all three,
not independently tuned per map. If you need pixel-accurate placement for
a specific map, that means adding a `MAP_IMAGE`-keyed zone layout rather
than one shared `ZONES` array — not done here, since it wasn't asked for
and adds real complexity for a cosmetic concern.

---

## 2. `dnpchallenge/` — DNP3 RTU/IED pair

**Dashboard zone:** `zone2`. **Access/interact:** connect a DNP3 master to
`ied`'s outstation (published port `20000`) and read/write
`turbine.status`/`turbine.control`; `rtu`'s telnet console (port `2323`)
and logic-module API (port `9101`) are also directly reachable.

**Purpose:** two `ot-sim` nodes talk DNP3. **`rtu`** reads a physical
switch/e-stop (GPIO input pin 16) and drives a status LED (GPIO output pin
15), and exposes a telnet console (port 2323) and its logic-module API on
port 9101. **`ied`** is the DNP3 outstation that owns the turbine relay
(GPIO output pin 18) and exposes its API on port 9102. *(If you've read an
older copy of this doc or `AUDIT.md`, note the rtu/ied roles were
originally documented backwards — this has been corrected and verified
directly against `rtuconfig.xml`/`iedconfig.xml`.)* This is the challenge
with the most direct, real GPIO integration in the repo, and the fixes
below have already been applied on `main`.

**Setup:**
```bash
cd dnpchallenge
docker compose up --build
```
Exposes: RTU telnet on `2323`, IED DNP3 outstation on `20000`. The
`vizhelper` service builds and runs automatically now (it previously
didn't run at all — see `AUDIT.md`) and connects out to `viz`'s dashboard,
so bring `viz/` up first (see section 1) if you want to see this
challenge's state reflected there.

**Note on the `ot-sim` image:** `rtu`/`ied` pull
`ghcr.io/patsec/ot-sim/ot-sim:main` from GitHub Container Registry.
Confirm your build host (ideally the Pi itself) can actually reach
`ghcr.io` before an event — some venue/guest networks block or rate-limit
GHCR, which would otherwise look like a mysterious hang on first
`docker compose up`. Pull it ahead of time if you're not sure about
day-of connectivity: `docker pull ghcr.io/patsec/ot-sim/ot-sim:main`.

**Already fixed on `main`** (previously blocking, kept here so you know
what changed): `vizhelper.py`'s missing `return` and missing `()` on
`response.json` are fixed; it now addresses `rtu`/`ied` by Docker Compose
service name instead of `127.0.0.1` (which never worked once it was
actually containerized); and it now authenticates to `viz`'s real
Mosquitto broker using a copy of viz's actual CA certificate instead of a
mismatched local one (see `mqtt-certs/CERTS.md`) — previously even a
bug-free version of this script would have failed every TLS handshake
against the real dashboard. The `vizhelper` service itself now has a
`Dockerfile`/`requirements.txt` and actually builds and runs.

**Functional test (simulation, no physical switch/relay):**
1. Telnet into the RTU's exposed console to confirm the message bus and
   logic module are alive:
   ```bash
   telnet localhost 2323
   ```
   You should see the banner defined in `rtuconfig.xml`'s `<telnet>`
   block.
2. Confirm DNP3 is up: point any DNP3 master tool (e.g. `pydnp3`,
   `dnp3-cli`, or a scanner) at `localhost:20000` (the `ied` outstation)
   and read binary input `Group1Var1` at address 0 (`turbine.status`). It
   should read `1` (turbine running) by default, since `estop` starts at
   `0`.
3. Simulate an e-stop by writing to the RTU's `switch` variable via its
   logic module API (`http://localhost:9101/api/v1/...`), or by driving
   GPIO pin 16 high if you're already on hardware. Confirm `turbine.control`
   (address 10 on the DNP3 link) flips to `0` and stays there for the
   ~60-cycle debounce window defined in the RTU's logic program before
   releasing.
4. Confirm the dashboard tie-in: with `viz/` and `dnpchallenge/` both up,
   watch `docker logs` on the `vizhelper` container for `turbine stopped`
   once you trigger the e-stop above, and confirm `zone2` on the viz
   dashboard (`https://<host>:3000`) flips to the alarm/red state within
   ~1s. If it doesn't, check `vizhelper`'s logs for TLS or connection
   errors first — see `mqtt-certs/CERTS.md` if it's a cert issue.
5. **[PI ONLY]** With the relay wired to IED output pin 18: confirm the
   relay physically opens within your required stop time when the e-stop
   path above is triggered, and that it fails safe (stays open) if you
   kill the `ied` container mid-test. This is also the first real-hardware
   test of the `rpi-gpio` module end-to-end — nothing above proves the
   physical pins actually toggle, only that the DNP3/logic/MQTT plumbing
   around them is correct.

**Known issues:** the DNP3-focused README (`README.md`) is a one-line
placeholder — check the `jg-dnp3-doc` branch before writing a new one from
scratch, per the table above.

---

## 3. `mitm-modbus/` — Modbus MITM (Ettercap) exercise

**Dashboard zone:** `zone1`. **Access/interact:** `master`/`slave`'s
Modbus traffic isn't reachable from the exhibit network directly — use the
`attacker` box's web terminal (port `7681`, no login) to run Ettercap
against them from inside their network segment.

**Purpose:** a master/slave Modbus TCP pair on a dedicated bridge network
(`my_network`, 172.20.0.0/16); an `attacker` box on the same network runs
Ettercap with the provided filter (`etter.filter.modbus`) to intercept and
alter traffic between them. The slave also drives a GPIO pin and publishes
to MQTT.

**Setup — fixed and verified end-to-end in this pass**, including a real,
live ARP-poisoning + filter-substitution run (not just "the containers
start"). No patching needed before use:

```bash
cd mitm-modbus
docker compose up --build
```

This starts `master`, `slave`, and `attacker`. Everything below was
previously broken and is now fixed (see `AUDIT.md` for the full list):
`slave.py`'s `RPi.GPIO` import (now falls back to a mock off-Pi), the
pin-17-vs-12 mismatch (now a single `RELAY_PIN` env var, default BCM12 —
`docs/PINOUT_MAP.md` CH3), the `shutdown_coil()` type error and its
never-actually-running coil-monitoring loop (was called without `await`),
`master.py`'s dead code and hardcoded slave IP, both Dockerfiles' stdout
buffering (fixed with `PYTHONUNBUFFERED=1` — without it, `docker logs`
on either container could look empty even while everything was working),
and the MQTT/CA mismatch (now tied into the real `viz` dashboard the same
way `dnpchallenge` was).

**Functional test:**
1. Bring the stack up and confirm `master` and `slave` are actually
   talking: `docker logs <master>` should show repeating
   `WriteCoilResponse(1) => True` / `restarting` lines, and `docker logs
   <slave>` should show `monitoring the coil` and Modbus debug frames
   (`Factory Request[WriteSingleCoilRequest'...`). If `master`'s log looks
   empty, that's the stdout-buffering issue above — confirm the image was
   rebuilt after the fix, not just restarted.
2. Confirm the dashboard tie-in: with `viz/` also up, `slave`'s logs
   should show no `couldn't reach MQTT broker` warnings, and the `zone1`
   tile on the viz dashboard should reflect state.
3. **Run the actual MITM attack** via the `attacker` box's web terminal at
   `http://<host>:7681` (no login — see `attacker/README.md` for the full
   walkthrough):
   ```bash
   nmap -sn 172.20.0.0/24
   ettercap -T -q -i eth0 -F etter.filter.modbuscomp -M arp:remote /172.20.0.2// /172.20.0.3//
   ```
   Confirm Ettercap resolves both hosts' real MAC addresses, reports ARP
   poisoning established, and — with the filter loaded — prints
   `Correctly substituted and logged` as it catches and alters a live
   Modbus write-coil packet. This exact sequence was confirmed working
   end-to-end while building this challenge.
4. **Confirm the actual win condition, not just the packet substitution:**
   watch `slave`'s logs (`docker logs -f <slave>`) while the attack in
   step 3 runs. Before the attack, `coil 1 (keep-alive) reads: True`
   should repeat steadily (one transient `False` reading right at boot is
   expected and self-corrects — see `AUDIT.md`). During the attack, it
   should flip to `coil 1 (keep-alive) reads: False` for the attack's
   entire duration, with `[mock GPIO] output(pin=12, value=0)` (or the
   real `GPIO.output` call on hardware) alongside it — that's the
   "turbine stopped" state. Stop the attack and confirm it self-corrects
   back to `True`/`value=1` within one 5s cycle. If you only ever see
   `True`, something regressed — this exact chain (concurrency, the
   correct Modbus function code, and bidirectional relay mirroring) is
   what makes the win condition detectable at all; see `AUDIT.md` for the
   three specific bugs that used to make this impossible.
5. If you edit `etter.filter.modbus`, recompile it before loading —
   Ettercap loads `etter.filter.modbuscomp`, not the source filter
   directly: `etterfilter etter.filter.modbus -o etter.filter.modbuscomp`.
6. **[PI ONLY]** Confirm `changeON()`'s GPIO pin (BCM12 / physical pin 32)
   toggles the physical relay as expected, wired per
   `docs/PINOUT_MAP.md` §3 (HIGH = normal/running, LOW = attacked/stopped
   — the same rule now applies to every turbine-relay channel in the
   repo, including this one, after the `dnpchallenge` polarity fix — see
   `docs/AUDIT.md`).

**Note on `attacker`'s privilege level:** it runs `privileged: true`, not
just `NET_ADMIN`/`NET_RAW` — Ettercap writes to
`/proc/sys/net/ipv6/conf/all/forwarding` as part of its own startup safety
routine, and `/proc/sys` stays read-only under Docker's default profile
regardless of added capabilities (confirmed directly: it fails with
`Read-only file system` on that path without `privileged: true`). Same
unauthenticated-by-design trust model as `audit-sidecar`'s write panel —
don't expose port 7681 beyond the exhibit network.

---

## 4. `mqtthelper/` — GPIO-to-MQTT bridge

**Dashboard zones:** `zone3`, `zone4`. **Access/interact:** not a player
attack surface on its own — it mirrors two spare GPIO pins' raw state.
Nothing to connect to; if either zone matters for a given instance of this
exhibit, that's whatever gets physically wired to physical pins 33/35.
**New:** these two zones also go offline (green/"Down") automatically once
all three actual challenges (`zone1`/`zone2`/`zone5`, configurable via
`CHALLENGE_ZONES`) report stopped — see the functional test below.

**Purpose:** poll GPIO pin state directly and republish per-zone status to
MQTT so the dashboard reflects raw hardware state, independent of any
specific challenge's own protocol-level publishing.

**Setup — fixed and verified end-to-end in this pass**, including a live
connection to `viz`'s real broker confirmed by subscribing directly to its
output. No patching needed:

```bash
cd mqtthelper
docker compose up --build
```

Everything below was previously broken and is now fixed (see `AUDIT.md`
for the full list): the Dockerfile's `node`-vs-`python3` `CMD` mismatch,
the self-linking compose file (renamed the service from `mqtt` to
`mqtthelper`, now `build: .`), the WiringPi CLI dependency (replaced with
direct `RPi.GPIO` reads on two explicit, non-conflicting pins — physical
33/BCM13 and physical 35/BCM19, see `docs/PINOUT_MAP.md`), the
`str`+`int` crash (and a related High/Low topic-name mismatch bug found
alongside it), and the CA/broker-address mismatch (now tied into the real
`viz` dashboard the same way `dnpchallenge` and `mitm-modbus` were).

**Important — found while testing this module, but it affects every
module that uses these certs:** the checked-in TLS certs had actually
**expired** (`viz/mqtt-certs/` was valid 2025-02-05 through 2026-02-05).
This was regenerated via `viz/createcerts.sh` and the new CA redistributed
to `dnpchallenge`, `mitm-modbus/slave`, and `mqtthelper` as part of this
pass (new expiry: 2026-08-06). **This will expire again in a year** — put
a reminder somewhere real (calendar, ticket, whatever this team actually
uses), not just this checklist, or you'll be back here re-diagnosing the
exact same `certificate has expired` error.

**Functional test:**
1. Bring up `viz/` first (`docker compose up -d mqtt` is enough if you
   don't need the dashboard UI itself running), then `mqtthelper`.
   `docker logs <mqtthelper>` should show no traceback — if you see
   `certificate has expired` or `certificate verify failed`, regenerate
   certs per the note above before anything else.
2. Confirm publishes actually land, directly against the broker:
   ```bash
   docker exec -it <viz_mqtt_container> mosquitto_sub \
     --cafile /mosquitto/config/ca.pem -h localhost -p 1883 \
     -t zone3 -t zone4 -v
   ```
   You should see `zone3 0` / `zone4 0` once a second (both pins read LOW
   via internal pull-down until something is actually wired to them —
   this is expected, it proves the publish path works end-to-end even
   before any physical sensor is connected).
3. **[PI ONLY]** Wire something to physical pins 33/35 and confirm the
   published value flips between 0/1 as expected, and that the
   corresponding dashboard zone tiles update.
4. Confirm the "all challenges complete" override: with `mqtthelper`
   running, manually publish fake challenge state and watch `zone3`/
   `zone4` react:
   ```bash
   # not complete yet - zone3/zone4 should keep publishing pin state
   docker exec -it <viz_mqtt_container> mosquitto_pub \
     --cafile /mosquitto/config/ca.pem -h localhost -p 1883 -t zone1 -m 1
   # ...repeat for zone2 and zone5 with -m 1...

   # now mark all three stopped - zone3/zone4 should both flip to 0
   docker exec -it <viz_mqtt_container> mosquitto_pub \
     --cafile /mosquitto/config/ca.pem -h localhost -p 1883 -t zone1 -m 0
   # ...repeat for zone2 and zone5 with -m 0...
   ```
   Watch `zone3`/`zone4` via `mosquitto_sub` (as in step 2) while you do
   this — they should only flip to `0` once *all three* of `zone1`/
   `zone2`/`zone5` have reported `0`; publishing just one or two shouldn't
   be enough. `mqtthelper` also needs to have seen a real value for each
   challenge zone at least once before it will call anything "complete" —
   if you've just started all the containers, give it a moment.

---

## 5. `bh-intellirupter/` — OpenPLC turbine PLC + RTU

**Dashboard zone:** `zone5` (new in this pass — this challenge previously
had no tie-in to the shared dashboard at all, unlike the other three).
**Access/interact:** the PLC's Modbus port is published (default `5000`)
— connect any Modbus client and work with the coils driving
`fixedfinal.st`'s trip/reset/turbine logic. The OpenPLC web UI (`9000`) is
also reachable.

**Purpose:** an OpenPLC "PLC" runs the ladder logic in `fixedfinal.st`
(voltage-sensor-driven trip logic with a 3-strike fault counter and 15s
fault-light timer); a separate `rtu` container polls it over Modbus,
injects simulated sensor data, and forwards readings to `hmi.py` for live
plotting.

**Setup — fixed, but must be built on the Raspberry Pi itself.**
`bh-intellirupter/OpenPLC_v3/` is now a vendored copy of upstream OpenPLC_v3
with wiringPi baked in and the `rpi` hardware layer set as the default
build target (see `OpenPLC_v3/VENDORED.md`). `startup.sh` and the IP
addressing in `hmi.py`/`rtu-speaker.py` have also been fixed — you no
longer need to patch anything here before a first attempt.

**Important:** because wiringPi packages are architecture-specific
(armhf/arm64), **`docker compose build` for the `plc` service must run on
the Raspberry Pi**, not on an x86 dev laptop. If you try it on x86 you'll
get through dependency install and the from-source compiles of
matiec/OpenDNP3/libmodbus/snap7 (those are architecture-neutral), then fail
at the wiringPi install step — that failure is expected off-Pi and isn't a
sign anything else is broken. There is currently no simulation-only path to
fully exercise this module end-to-end; see `AUDIT.md` Part 2.

**Setup (on the Pi):**
```bash
cd bh-intellirupter
docker compose up --build
```
Exposes: OpenPLC Modbus on `5000`, OpenPLC web UI on `9000`. `hmi.py` runs
on the host itself, started by `startup.sh` (`python3 hmi.py &`), and binds
`0.0.0.0:8888`/`8889` — use `startup.sh` rather than `docker compose up`
alone if you want the HMI plot running too.

**Functional test:**
1. Log into the OpenPLC web UI at `http://<host>:9000` (default OpenPLC
   credentials unless changed — rotate them before any public event) and
   confirm `fixedfinal.st`'s compiled program (or equivalent) is loaded and
   running.
2. **[PI ONLY]** Confirm the hardware layer took: Settings → Hardware
   Layer should already show Raspberry Pi selected (the Dockerfile sets
   this as the default now, so you shouldn't need to change it manually —
   if it's still on Blank/Linux, the `change_hardware_layer.sh rpi` step in
   the Dockerfile didn't take, which points at a build-time failure worth
   investigating). Confirm the `%QX10`/`%QW15` addresses in the ladder
   logic map to the physical pins in `docs/PINOUT_MAP.md` (CH2, physical
   pin 11 / BCM17 for `Turbine`) — OpenPLC's hardware-layer UI is where you
   actually assign physical pin numbers to those addresses; this hasn't
   been verified against a real build yet (see `docs/AUDIT.md`).
3. Start the RTU (`docker compose up -d rtu`, or via `startup.sh`): confirm
   it connects to the PLC's Modbus port (check `rtu` container logs for
   connection errors — it now targets `PLC_HOST=plc`/`PLC_PORT=502` and
   `HMI_HOST=host.docker.internal` by default; override those env vars in
   `docker-compose.yml` if your setup needs something different) and that
   `hmi.py`'s live plot window updates with simulated voltage values.
4. Force a fault: with the RTU running, watch for the plot to cross the
   `lower_bound`/`upper_bound` lines (1.2/1.8 in `hmi.py`, note these are
   in different units than the `*1000` scaling applied to the plotted
   data — double check this matches the ladder logic's own expectations
   before trusting the visual). Confirm `Trip`/`Fault` coils flip in the
   OpenPLC UI and the turbine output de-energizes.
5. **[PI ONLY]** Confirm the physical relay opens when `Turbine` (%QX10)
   goes false, and that the 15s fault-light timer (`TOF0`) and 3-strike
   counter (`CTU0`) behave as expected against real timing, not just the
   20ms software task interval defined in the `CONFIGURATION` block.
6. Confirm the dashboard tie-in (new in this pass — `rtu-speaker.py` now
   publishes to `zone5`, which this challenge previously had none of):
   with `viz/` also up, `docker logs <rtu>` should show no `couldn't reach
   MQTT broker`/`couldn't read turbine coil` warnings once the PLC is
   running, and the `zone5` tile on the dashboard should track the
   `Turbine` coil's state live. The coil address it reads
   (`TURBINE_COIL_ADDR`, default `10`) is a best-effort guess at `%QX10`'s
   Modbus mapping — cross-check it against Settings → Modbus Server in the
   OpenPLC web UI and override the env var in `docker-compose.yml` if it
   doesn't match.

---

## 6. `audit-sidecar/` — shared traffic + challenge-state view

**Purpose:** every challenge above keeps its own independent Docker
network — that's deliberate, not a bug — which means none of their
internal traffic reaches a physical wire a participant could plug into
(see `docs/AUDIT.md` Part 3). Instead of bridging all the networks
together, this single service joins each of them as an extra member (like
a shared span/tap port would on a real switch) and serves one web page
where participants can watch live traffic across all five networks and
read/write the specific protocol points each challenge cares about.

**Setup — must start last.** Every other challenge's `docker-compose.yml`
must already be up before this one, since it attaches to their networks
by name (`external: true`) and Docker errors out if that network doesn't
exist yet:

```bash
# bring up viz, dnpchallenge, mitm-modbus, mqtthelper, bh-intellirupter first
cd audit-sidecar
docker compose up --build
```

Open `http://<host>:8000`. If a network is missing, the error names
exactly which challenge to start first.

**Functional test:**
1. With at least one challenge running, confirm its traffic shows up in
   the live feed (e.g. `viz`'s HTTPS/MQTT traffic, or `dnpchallenge`'s
   telnet banner if you connect to port 2323 while watching).
2. Click a network tab and confirm it filters to just that challenge's
   traffic.
3. Pick a read-only element (e.g. `dnpchallenge-ied`'s `status`) and
   confirm "read" returns a real value — this proves the sidecar can
   actually reach that challenge's service by Docker DNS.
4. Pick a read-write element (e.g. `dnpchallenge-rtu`'s `switch`), write a
   value, then read it back and confirm it changed. For `mitm-modbus` or
   `bh-intellirupter`'s Modbus elements, cross-check the written value
   against that challenge's own state (dashboard zone, OpenPLC UI, etc.)
   to confirm the write actually landed, not just that the HTTP call
   succeeded.

**Known limitations** (see `audit-sidecar/README.md` for the full list):
the write panel has no authentication; DNP3 packets show as raw hex in the
traffic view (reading/writing `dnpchallenge`'s tags still works, just not
via decoded packet inspection); and this does **not** restore
`mitm-modbus`'s original Ettercap/ARP-spoofing gameplay — that challenge's
design still needs a conscious rethink around "manipulate the point
directly via the sidecar" instead, which hasn't been done here.

---

## 7. General pre-event checklist

- [ ] All five modules build and start cleanly (`docker compose up
      --build` with no crash-looping containers) in the simulation
      environment.
- [ ] All GPIO-touching code paths have been exercised at least once on
      the actual Raspberry Pi hardware, not just in simulation — several
      of these bugs (pin mismatches, `RPi.GPIO` Pi-detection) are
      invisible until you're on real hardware.
- [x] One document exists mapping every physical GPIO pin in use across
      all modules that will run concurrently on the same Pi, with no
      collisions — see [`docs/PINOUT_MAP.md`](PINOUT_MAP.md).
- [ ] **Check TLS cert expiry before every event, not just once.** The
      certs shipped in this repo had already expired
      (`viz/mqtt-certs/` was valid 2025-02-05 through 2026-02-05) and
      were regenerated as part of this audit (new expiry: 2026-08-06).
      Check with `openssl x509 -in viz/mqtt-certs/ca.pem -noout -enddate`
      before relying on them, and re-run `viz/createcerts.sh` (then
      re-copy `viz/mqtt-certs/ca.pem` into `dnpchallenge/mqtt-certs/`,
      `mitm-modbus/slave/mqtt-certs/`, and `mqtthelper/mqtt-certs/`) if
      they're expired or close to it. Separately: rotate away from the
      checked-in certs entirely before any public event — they're
      committed to the repo in plaintext, which is fine for a lab/CTF box
      but not for anything reachable beyond the exhibit network.
- [ ] Default credentials (OpenPLC web UI, any other admin panel) have
      been changed from defaults.
- [ ] A rollback/reset procedure exists to restore each challenge to its
      starting state between player attempts (this repo doesn't currently
      define one — worth adding a `reset.sh` per module once the above
      bugs are fixed).
- [ ] Confirmed the venue network lets the Pi/build host reach `ghcr.io`
      (needed to pull the `ot-sim` image for `dnpchallenge`) — pull it
      ahead of time if there's any doubt, since some guest/venue networks
      block or heavily rate-limit GHCR.
