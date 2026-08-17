# GPIO Pinout Map — Turbine Relay Bank + Sensor

**A visual schematic version of this document** — Pi header → relay board
→ turbine, drawn out — **is published as [Turbine Relay Wiring
diagram](https://claude.ai/code/artifact/65629792-abd0-401d-9efd-2917cae65147).**
Use it alongside this text reference; regenerate/update it if the pin
assignments below change.

This is the authoritative physical wiring reference for connecting the
Raspberry Pi's GPIO header to the 6-channel relay board that switches
power to the turbine/load, plus the single 5V+GND pair that powers both
the relay board's logic rail and the physical sensor.

**Assumption stated up front:** this map treats the turbine + relay bank +
sensor as **one shared physical rig** that different challenge software
stacks (`bh-intellirupter`, `dnpchallenge`, `mitm-modbus`) can each drive,
rather than five independent physical turbines. That matches the original
framing of this exhibit (one Pi, one turbine, one relay, one power bus) and
the fact that most challenges' own config files never pin down a physical
GPIO pin at all — they're written to share one. **If that assumption is
wrong** (e.g. each challenge actually gets its own separate Pi + turbine
station), most of this still applies per-station, but the "only one
challenge stack should be driving the shared pins at a time" note below
becomes moot and each station can just reuse the same channel numbering
independently. Confirm with whoever owns the physical build before wiring.

All pin numbers below are **physical header pin numbers** (the position on
the 40-pin header, 1–40), not BCM numbers — matching how `dnpchallenge`'s
`ot-sim` configs already reference pins (`mode="board"`). A BCM
cross-reference is included for the modules that use `RPi.GPIO`/BCM
numbering instead (`mitm-modbus`), since mixing the two without a
translation table is exactly how wiring mistakes happen.

## 1. Power wiring (relay board + sensor)

One 5V/GND pair from the Pi feeds **both** the relay board's logic rail
and the sensor, as requested — do not run a second, separate 5V tap for
the sensor.

| Signal | Pi physical pin | Notes |
|---|---|---|
| 5V | Pin 2 (or Pin 4) | To relay board `VCC` **and** sensor `VCC`, in parallel |
| GND | Pin 6 (or any other GND pin) | Common ground: relay board `GND`, sensor `GND`, and (implicitly, since they share the Pi) every GPIO signal pin below |

**Before wiring:**
- Confirm the relay board's logic rail actually wants 5V (most common
  hobbyist "SRD-05VDC-SL-C"-style 6-relay boards do) and draws low enough
  current that the Pi's 5V rail can supply it alongside whatever else is
  on that rail — check the board's datasheet for logic-side current draw
  (typically tens of mA per relay coil when energized; a 6-relay board with
  all six coils on simultaneously can approach ~360–480mA, which is within
  a Pi's 5V budget but worth confirming against your specific PSU).
- **The relay board's logic-side 5V (from the Pi) is a completely separate
  concern from whatever voltage/current the turbine's power bus itself
  runs at on the COM/NO/NC switched side.** Never connect the turbine
  motor's power bus wiring to the Pi's 5V pin — it only ever touches the
  relay's switched contacts (see §3). If the turbine's power bus is mains
  voltage or anything above extra-low-voltage DC, that's a separate
  electrical safety domain — verify the relay board's contact voltage/
  current rating exceeds what the turbine draws, and follow standard mains
  isolation practice; this document only covers the Pi-side logic wiring.
- Many of these relay boards have a **JD-VCC jumper** separating the
  opto-isolator's LED-side supply from the relay coil supply, for running
  the coil side off a separate, isolated power source. For this exhibit
  (low-current DC "turbine" load, not switching mains), leaving the jumper
  in place (single shared 5V supply) is fine. Remove it and feed relay
  coil power separately only if you end up switching something higher-power
  or noise-sensitive.
- Check whether your specific relay board is **active-low** (most
  SRD-05VDC-SL-C clones are: `GPIO.output(pin, GPIO.LOW)` energizes the
  relay, `HIGH` de-energizes it) or active-high. This inverts every
  "ON"/"OFF" assumption in the challenge code below if you get it backwards
  — verify with a multimeter against your actual board before wiring
  anything permanent.

## 2. Relay channel assignments (6-channel board)

| Ch | Pi physical pin | BCM (if relevant) | Signal | Owning challenge | Status |
|---|---|---|---|---|---|
| CH1 | 18 | GPIO24 | Turbine / load relay (primary win-condition target) | `dnpchallenge` (`ied`, `iedconfig.xml` `rpi-gpio` output pin 18, tag `turbine`) | **Already hardcoded in `main`** — wire to match, don't change without also updating `iedconfig.xml`. |
| CH2 | 11 | GPIO17 | Turbine output (`%QX10` in `fixedfinal.st`) | `bh-intellirupter` (OpenPLC) | **Proposed, not yet set anywhere in the repo.** OpenPLC doesn't hardcode physical pins in source — assign this in the web UI under Settings → Hardware Layer once the hardware layer is set to Raspberry Pi (see `docs/ADMIN.md`), matching this table. |
| CH3 | 32 | GPIO12 | Turbine/load relay (`changeON()`) | `mitm-modbus` (`slave/slave.py`) | **Fixed.** `slave.py` now uses a single `RELAY_PIN` constant (default BCM12 / physical 32, env-overridable) for both `GPIO.setup()` and `GPIO.output()` — the previous setup(17)/output(12) mismatch is resolved. |
| CH4 | 15 | GPIO22 | Status LED (`rtu`) | `dnpchallenge` (`rtuconfig.xml` `rpi-gpio` output pin 15, tag `led`) | **Already hardcoded in `main`.** Low-current LED — driving it through a relay channel is optional; a direct GPIO + current-limiting resistor works too and doesn't consume a relay channel. Included here in case you'd rather route every output through the same board for consistency. |
| CH5 | — | — | Spare | Unassigned | Reserved for expansion (e.g. a dedicated fault/alarm indicator relay, separate from CH4's LED). |
| CH6 | — | — | Spare | Unassigned | Reserved for expansion. |

**Only one challenge's software stack should be actively driving the
shared channels (CH1–CH3) at a time.** GPIO pins can only be exported/
claimed by one process at once, and — per the shared-rig assumption above —
CH1–CH3 each represent a *different attack path to the same physical
turbine relay concept*, not three independent turbines. Running more than
one challenge stack against live GPIO simultaneously will produce
contention errors or, worse, two programs disagreeing about relay state.

## 3. Relay switched side (COM/NO/NC → turbine power bus)

**Confirmed requirement:** the turbine runs (spins, draws power) during
normal operation, and stops as the result of a successful attack. On the
`viz` dashboard, this is: **red = "Normal" (power flowing, fan on)**,
**green = "Down" (zone offline)** — implemented in the dashboard that's
actually served, `viz/public/index.html` + `viz/public/main.js`'s
`drawZone()`/`updateBoard()` (verified directly: `val === 1` → red +
"Normal", else → green + "Down"; no changes needed there). *(Correction:
an earlier pass verified this against `viz/index.html` at the repo root —
that file and `viz/index-http.html` next to it are **not actually served**;
`server.js` only serves the `public/` directory, so `public/index.html` is
the real one. Same semantics either way, but cite the right file — see
`docs/AUDIT.md`.)*

**All three turbine-relay channels now agree on GPIO polarity: HIGH =
running normally, LOW = stopped (successful attack).**
`dnpchallenge/iedconfig.xml`'s logic previously computed the opposite
(`turbine = not(control==1 and estop==0)`, settling to LOW during normal
operation) — a real, confirmed bug, since it also meant the DNP3-exposed
`turbine.status` point told a connecting master the opposite of the
turbine's actual state. Fixed to `turbine = (control==1 and estop==0)`,
now matching `bh-intellirupter` (`Turbine := NOT(Trip) AND VoltageChk`,
TRUE when no fault and sensor in-range) and `mitm-modbus`
(`changeON(1)`/`changeON(0)` mirroring the keep-alive coil, confirmed live
end-to-end including the attack and self-correction). See `docs/AUDIT.md`
for the fix details.

**Because all three now agree, one wiring rule applies to every channel:**

- **COM** → one leg of the turbine motor's power bus.
- Confirm your relay board's active-high vs. active-low behavior with a
  multimeter first (§1) — that determines which of the two rows below
  applies, and it's specific to your physical board, not something this
  document can determine for you.
- **Active-high board** (GPIO HIGH energizes the relay): wire the turbine
  to **NO**. Energized (HIGH = normal = running) closes the circuit;
  de-energized (LOW = attacked = stopped) opens it.
- **Active-low board** (GPIO LOW energizes the relay): wire the turbine to
  **NC**. De-energized (HIGH = normal = running) leaves it closed;
  energized (LOW = attacked = stopped) opens it.

This applies identically to CH1 (`dnpchallenge`), CH2
(`bh-intellirupter`), and CH3 (`mitm-modbus`) — the same physical
COM/NO-or-NC choice is correct across all three now, which wasn't true
before the polarity fix above.

## 4. Non-relay direct GPIO connections

Not every signal needs to go through the relay board — inputs (buttons/
switches) and low-current indicators don't switch power, so they connect
directly to the header instead.

| Signal | Pi physical pin | BCM | Owning challenge | Notes |
|---|---|---|---|---|
| Switch / e-stop input | 16 | GPIO23 | `dnpchallenge` (`rtu`, `rtuconfig.xml` input pin 16, tag `switch`) | Wire as a simple momentary switch to GND with the Pi's internal pull-up enabled (or an external pull-up resistor), active-low. Already hardcoded — don't reassign without updating `rtuconfig.xml`. |
| Voltage sensor / `Sensor` input | *(unassigned — propose Pin 29 / GPIO5)* | GPIO5 | `bh-intellirupter` (`%IX0.1` in `fixedfinal.st`) | Not hardcoded anywhere in the repo; assign via OpenPLC's hardware layer UI once set to Raspberry Pi. If this is an analog sensor rather than a digital threshold switch, note the Pi's GPIO pins are digital-only — an analog sensor needs an ADC (e.g. MCP3008 over SPI) in between, which isn't currently part of this repo's hardware design at all. Flagging as an open question, not solving it here. |
| `VoltageChk` input | *(unassigned — propose Pin 31 / GPIO6)* | GPIO6 | `bh-intellirupter` (`%IX0.0` in `fixedfinal.st`) | Same caveats as above. |
| Monitored input 1 | 33 | GPIO13 | `mqtthelper` (`MQTTHELPER_PIN_1`, publishes to `zone3`) | Free/spare pin, chosen specifically to avoid colliding with anything else in this table — see §5. Nothing is wired to it yet; it reads LOW (via internal pull-down) until something is. |
| Monitored input 2 | 35 | GPIO19 | `mqtthelper` (`MQTTHELPER_PIN_2`, publishes to `zone4`) | Same as above. |

## 5. Resolved: `mqtthelper`'s monitored pins

`mqtthelper/MQTTHelper.py` previously read pins `[18, 8]` by shelling out
to `gpio readall` (a WiringPi CLI tool) and pattern-matching literal
numbers in its text output. `gpio readall` prints **multiple numbering
columns side by side** (BCM, wPi, and Physical), and the code's match
(`f"| {pin_number} "`) didn't specify which column it meant — so "18"
could have meant physical pin 18 (this table's CH1 / turbine relay,
BCM24), BCM GPIO18 (a completely different physical pin, header position
12), or the WiringPi "wPi" index 18 (different again) — genuinely
ambiguous, and worth noting that "18" could easily have collided with
CH1's turbine relay if it had meant physical pin 18.

**Fixed:** `MQTTHelper.py` now reads GPIO directly via `RPi.GPIO` (same
mock-fallback pattern as `mitm-modbus/slave.py`) instead of shelling out
to WiringPi at all, on two explicitly assigned, previously-unclaimed pins
(physical 33/BCM13 and physical 35/BCM19, both env-var overridable) —
removing the ambiguity structurally instead
of just picking one column and hoping.

## 6. Full 40-pin reference (for context)

Standard Raspberry Pi 40-pin header, physical pin → BCM GPIO. Pins already
spoken for by this map are marked; the rest (including the I2C/SPI/UART
reserved pins) should be left alone unless a future challenge specifically
needs them.

| Physical | BCM | Used by | Physical | BCM | Used by |
|---|---|---|---|---|---|
| 1 (3.3V) | — | | 2 (5V) | — | **Relay board + sensor VCC (§1)** |
| 3 | GPIO2 (SDA1) | reserved (I2C) | 4 (5V) | — | spare 5V |
| 5 | GPIO3 (SCL1) | reserved (I2C) | 6 (GND) | — | **Relay board + sensor GND (§1)** |
| 7 | GPIO4 | spare | 8 | GPIO14 (TXD) | reserved (UART) |
| 9 (GND) | — | spare GND | 10 | GPIO15 (RXD) | reserved (UART) |
| 11 | GPIO17 | **CH2 — bh-intellirupter turbine (§2)** | 12 | GPIO18 | spare |
| 13 | GPIO27 | spare | 14 (GND) | — | spare GND |
| 15 | GPIO22 | **CH4 / rtu LED (§2)** | 16 | GPIO23 | **rtu switch input (§4)** |
| 17 (3.3V) | — | | 18 | GPIO24 | **CH1 — turbine relay (§2)** |
| 19 | GPIO10 (MOSI) | reserved (SPI) | 20 (GND) | — | spare GND |
| 21 | GPIO9 (MISO) | reserved (SPI) | 22 | GPIO25 | spare |
| 23 | GPIO11 (SCLK) | reserved (SPI) | 24 | GPIO8 (CE0) | reserved (SPI) |
| 25 (GND) | — | spare GND | 26 | GPIO7 (CE1) | reserved (SPI) |
| 27 | ID_SD | reserved (HAT EEPROM) | 28 | ID_SC | reserved (HAT EEPROM) |
| 29 | GPIO5 | **proposed — bh-intellirupter `Sensor` input (§4)** | 30 (GND) | — | spare GND |
| 31 | GPIO6 | **proposed — bh-intellirupter `VoltageChk` input (§4)** | 32 | GPIO12 | **CH3 — mitm-modbus relay (§2)** |
| 33 | GPIO13 | **mqtthelper monitored input 1 -- zone3 (§4)** | 34 (GND) | — | spare GND |
| 35 | GPIO19 | **mqtthelper monitored input 2 -- zone4 (§4)** | 36 | GPIO16 | spare |
| 37 | GPIO26 | spare | 38 | GPIO20 | spare |
| 39 (GND) | — | spare GND | 40 | GPIO21 | spare |
