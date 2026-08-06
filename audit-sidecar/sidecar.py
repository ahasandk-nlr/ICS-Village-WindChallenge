"""audit-sidecar: a single service attached to every challenge's own Docker
network, so participants have one place to watch traffic across all of them
and to read/write the protocol points that matter for each challenge -
without needing raw NIC access to networks that never reach a physical
wire (see docs/AUDIT.md Part 3 for why that matters here).

Each challenge network stays independent from the others; this container
is simply a member of all of them at once, the same way a shared span/tap
point would be on real hardware.
"""
import html
import os
import socket
import struct
import threading
import time
from collections import deque

import requests
from flask import Flask, jsonify, render_template_string, request
from pymodbus.client import ModbusTcpClient
from scapy.all import IP, TCP, Raw, sniff

from challenges import CHALLENGES, find_challenge, find_element

app = Flask(__name__)

EVENTS = deque(maxlen=int(os.environ.get("EVENTS_MAXLEN", "500")))
EVENTS_LOCK = threading.Lock()

# Prefix-matched against this container's own IP on each interface to label
# which challenge network a given interface belongs to. Must match the
# subnets assigned in each challenge's docker-compose.yml network block.
NETWORK_LABELS = {
    "172.30.0.": "bh-intellirupter",
    "172.31.0.": "dnpchallenge",
    "172.20.": "mitm-modbus",
    "172.32.0.": "mqtthelper",
    "172.33.0.": "viz",
}


def label_for_ip(ip):
    for prefix, label in NETWORK_LABELS.items():
        if ip.startswith(prefix):
            return label
    return f"unknown ({ip})"


def local_interfaces():
    """Yield (iface, ip) for every non-loopback IPv4-addressed interface."""
    import psutil

    for iface, addrs in psutil.net_if_addrs().items():
        if iface == "lo":
            continue
        for addr in addrs:
            if addr.family == socket.AF_INET:
                yield iface, addr.address


def decode_modbus(payload):
    if len(payload) < 8:
        return None
    try:
        _txid, _protoid, length, unit_id, func_code = struct.unpack(">HHHBB", payload[:8])
    except struct.error:
        return None
    is_exception = bool(func_code & 0x80)
    return f"Modbus unit={unit_id} func={'EXC:' if is_exception else ''}0x{func_code & 0x7F:02x} len={length}"


def decode_payload(payload, sport, dport):
    if 502 in (sport, dport):
        decoded = decode_modbus(payload)
        if decoded:
            return decoded
    if 23 in (sport, dport):
        try:
            text = payload.decode("utf-8", errors="replace").strip()
            if text:
                return "telnet: " + text
        except Exception:
            pass
    if 20000 in (sport, dport):
        return f"dnp3 (raw, {len(payload)}B): {payload[:24].hex()}"
    return f"raw ({len(payload)}B): {payload[:24].hex()}"


def handle_packet(label, iface, pkt):
    if IP not in pkt:
        return
    sport = pkt[TCP].sport if TCP in pkt else None
    dport = pkt[TCP].dport if TCP in pkt else None
    summary = decode_payload(bytes(pkt[Raw].load), sport, dport) if Raw in pkt else ""
    event = {
        "ts": time.time(),
        "network": label,
        "iface": iface,
        "src": pkt[IP].src,
        "dst": pkt[IP].dst,
        "sport": sport,
        "dport": dport,
        "summary": summary,
    }
    with EVENTS_LOCK:
        EVENTS.appendleft(event)


def sniff_iface(iface, label):
    while True:
        try:
            sniff(iface=iface, prn=lambda p: handle_packet(label, iface, p), store=False)
        except Exception as exc:
            print(f"[sniff:{iface}] error, retrying in 5s: {exc}", flush=True)
            time.sleep(5)


def start_sniffers():
    started = set()
    for iface, ip in local_interfaces():
        if iface in started:
            continue
        started.add(iface)
        label = label_for_ip(ip)
        threading.Thread(target=sniff_iface, args=(iface, label), daemon=True).start()
        print(f"[sidecar] sniffing {iface} ({ip}) as '{label}'", flush=True)


# ---- Challenge element read/write ------------------------------------

def read_modbus_element(challenge, element):
    client = ModbusTcpClient(challenge["host"], port=challenge["port"])
    try:
        if not client.connect():
            return None, "connection failed"
        unit = challenge.get("unit", 1)
        kind, addr = element["kind"], element["address"]
        if kind == "coil":
            rr = client.read_coils(addr, count=1, slave=unit)
        elif kind == "discrete_input":
            rr = client.read_discrete_inputs(addr, count=1, slave=unit)
        elif kind == "holding_register":
            rr = client.read_holding_registers(addr, count=1, slave=unit)
        else:
            return None, f"unsupported kind {kind}"
        if rr.isError():
            return None, str(rr)
        value = rr.bits[0] if hasattr(rr, "bits") else rr.registers[0]
        return value, None
    except Exception as exc:
        return None, str(exc)
    finally:
        client.close()


def write_modbus_element(challenge, element, value):
    client = ModbusTcpClient(challenge["host"], port=challenge["port"])
    try:
        if not client.connect():
            return "connection failed"
        unit = challenge.get("unit", 1)
        kind, addr = element["kind"], element["address"]
        if kind == "coil":
            rr = client.write_coil(addr, bool(int(float(value))), slave=unit)
        elif kind == "holding_register":
            rr = client.write_register(addr, int(float(value)), slave=unit)
        else:
            return f"cannot write to a {kind}"
        return str(rr) if rr.isError() else None
    except Exception as exc:
        return str(exc)
    finally:
        client.close()


def read_otsim_element(challenge, element):
    url = f"http://{challenge['host']}:{challenge['port']}/api/v1/query/{element['tag']}"
    try:
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        return resp.json().get("value"), None
    except Exception as exc:
        return None, str(exc)


def write_otsim_element(challenge, element, value):
    url = f"http://{challenge['host']}:{challenge['port']}/api/v1/write/{element['tag']}/{value}"
    try:
        resp = requests.post(url, timeout=3)
        resp.raise_for_status()
        return None
    except Exception as exc:
        return str(exc)


def read_element(challenge, element):
    if challenge["protocol"] == "modbus":
        return read_modbus_element(challenge, element)
    return read_otsim_element(challenge, element)


def write_element(challenge, element, value):
    if challenge["protocol"] == "modbus":
        return write_modbus_element(challenge, element, value)
    return write_otsim_element(challenge, element, value)


# ---- Web UI ------------------------------------------------------------

PAGE = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>audit-sidecar</title>
<style>
  body { font-family: -apple-system, Segoe UI, sans-serif; margin: 0; padding: 1rem;
         background: #111; color: #ddd; }
  h1 { font-size: 1.1rem; margin: 0 0 0.75rem; }
  h2 { font-size: 0.95rem; margin: 1.5rem 0 0.5rem; }
  .tabs { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
  .tab { padding: 0.25rem 0.6rem; border: 1px solid #444; border-radius: 4px;
         cursor: pointer; font-size: 0.85rem; }
  .tab.active { background: #2d6cdf; border-color: #2d6cdf; color: white; }
  table { border-collapse: collapse; width: 100%; font-size: 0.82rem; }
  th, td { border-bottom: 1px solid #333; padding: 0.3rem 0.5rem; text-align: left;
           font-family: ui-monospace, monospace; }
  th { color: #999; font-weight: normal; }
  .net-badge { padding: 0.05rem 0.4rem; border-radius: 3px; background: #333;
               font-size: 0.75rem; }
  .challenge { border: 1px solid #333; border-radius: 6px; padding: 0.75rem;
               margin-bottom: 0.75rem; }
  .challenge .note { color: #999; font-size: 0.78rem; margin: 0.25rem 0 0.6rem; }
  .elem-row { display: flex; align-items: center; gap: 0.5rem; margin: 0.3rem 0;
              font-size: 0.85rem; }
  .elem-name { flex: 1; }
  .elem-value { min-width: 3.5rem; font-family: ui-monospace, monospace; }
  button { background: #2d6cdf; border: none; color: white; padding: 0.2rem 0.5rem;
           border-radius: 4px; cursor: pointer; font-size: 0.78rem; }
  button.secondary { background: #444; }
  input[type=text] { width: 4rem; background: #222; border: 1px solid #444;
                      color: #ddd; padding: 0.15rem 0.3rem; border-radius: 3px; }
  .ro-tag { color: #777; font-size: 0.72rem; }
  #traffic { max-height: 45vh; overflow-y: auto; border: 1px solid #333; border-radius: 6px; }
</style>
</head>
<body>
<h1>audit-sidecar - shared traffic + challenge state view</h1>

<h2>Live traffic (all challenge networks)</h2>
<div class="tabs" id="netTabs"><div class="tab active" id="allTab">all</div></div>
<div id="traffic">
  <table>
    <thead><tr><th>time</th><th>network</th><th>src</th><th>dst</th><th>ports</th><th>summary</th></tr></thead>
    <tbody id="trafficBody"></tbody>
  </table>
</div>

<h2>Challenge state</h2>
<div id="challenges"></div>

<script>
const CHALLENGES = {challenges_json};
const NETWORKS = {networks_json};
let currentNet = "";

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

async function refreshTraffic() {
  const url = currentNet ? `/api/events?network=${encodeURIComponent(currentNet)}` : "/api/events";
  const resp = await fetch(url);
  const events = await resp.json();
  const body = document.getElementById("trafficBody");
  body.innerHTML = events.map(e => `
    <tr>
      <td>${fmtTime(e.ts)}</td>
      <td><span class="net-badge">${e.network}</span></td>
      <td>${e.src}</td>
      <td>${e.dst}</td>
      <td>${e.sport ?? ""}&rarr;${e.dport ?? ""}</td>
      <td>${e.summary}</td>
    </tr>`).join("");
}

function buildTabs() {
  const tabsEl = document.getElementById("netTabs");
  for (const net of NETWORKS) {
    const tab = document.createElement("div");
    tab.className = "tab";
    tab.textContent = net;
    tab.onclick = () => selectTab(net, tab);
    tabsEl.appendChild(tab);
  }
}

function selectTab(net, el) {
  currentNet = net;
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  el.classList.add("active");
  refreshTraffic();
}

function renderChallenges() {
  const root = document.getElementById("challenges");
  root.innerHTML = CHALLENGES.map(c => `
    <div class="challenge">
      <strong>${c.label}</strong> <span class="net-badge">${c.protocol}</span>
      ${c.note ? `<div class="note">${c.note}</div>` : ""}
      ${c.elements.map(el => `
        <div class="elem-row" data-challenge="${c.id}" data-element="${el.name}">
          <span class="elem-name">${el.name}</span>
          <span class="elem-value" id="val-${c.id}-${cssSafe(el.name)}">-</span>
          <button class="secondary" onclick="doRead('${c.id}', '${escapeJs(el.name)}')">read</button>
          ${el.access === "rw" ? `
            <input type="text" id="in-${c.id}-${cssSafe(el.name)}" placeholder="value">
            <button onclick="doWrite('${c.id}', '${escapeJs(el.name)}')">write</button>
          ` : '<span class="ro-tag">read-only</span>'}
        </div>
      `).join("")}
    </div>
  `).join("");
}

function cssSafe(s) { return s.replace(/[^a-zA-Z0-9]/g, "_"); }
function escapeJs(s) { return s.replace(/'/g, "\\\\'"); }

async function doRead(challengeId, elementName) {
  const valEl = document.getElementById(`val-${challengeId}-${cssSafe(elementName)}`);
  valEl.textContent = "...";
  const resp = await fetch(`/api/read/${encodeURIComponent(challengeId)}/${encodeURIComponent(elementName)}`);
  const data = await resp.json();
  valEl.textContent = resp.ok ? data.value : `err: ${data.error}`;
}

async function doWrite(challengeId, elementName) {
  const inputEl = document.getElementById(`in-${challengeId}-${cssSafe(elementName)}`);
  const value = inputEl.value;
  const resp = await fetch(`/api/write/${encodeURIComponent(challengeId)}/${encodeURIComponent(elementName)}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({value}),
  });
  const data = await resp.json();
  if (!resp.ok) {
    alert(`write failed: ${data.error}`);
  } else {
    doRead(challengeId, elementName);
  }
}

document.getElementById("allTab").onclick = (e) => selectTab("", e.target);
buildTabs();
renderChallenges();
refreshTraffic();
setInterval(refreshTraffic, 2000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    import json

    challenges_for_js = [
        {
            "id": c["id"],
            "label": html.escape(c["label"]),
            "protocol": c["protocol"],
            "note": html.escape(c.get("note", "")) if c.get("note") else "",
            "elements": [
                {"name": e["name"], "access": e["access"]} for e in c["elements"]
            ],
        }
        for c in CHALLENGES
    ]
    page = PAGE.replace("{challenges_json}", json.dumps(challenges_for_js))
    page = page.replace(
        "{networks_json}", json.dumps(sorted(set(NETWORK_LABELS.values())))
    )
    return render_template_string(page)


@app.route("/api/events")
def api_events():
    network = request.args.get("network")
    with EVENTS_LOCK:
        events = list(EVENTS)
    if network:
        events = [e for e in events if e["network"] == network]
    return jsonify(events[:200])


@app.route("/api/read/<challenge_id>/<element_name>")
def api_read(challenge_id, element_name):
    challenge = find_challenge(challenge_id)
    if not challenge:
        return jsonify({"error": "unknown challenge"}), 404
    element = find_element(challenge, element_name)
    if not element:
        return jsonify({"error": "unknown element"}), 404
    value, err = read_element(challenge, element)
    if err:
        return jsonify({"error": err}), 502
    return jsonify({"value": value})


@app.route("/api/write/<challenge_id>/<element_name>", methods=["POST"])
def api_write(challenge_id, element_name):
    challenge = find_challenge(challenge_id)
    if not challenge:
        return jsonify({"error": "unknown challenge"}), 404
    element = find_element(challenge, element_name)
    if not element:
        return jsonify({"error": "unknown element"}), 404
    if element.get("access") != "rw":
        return jsonify({"error": "read-only element"}), 403
    payload = request.get_json(silent=True) or {}
    value = payload.get("value")
    if value is None or value == "":
        return jsonify({"error": "missing value"}), 400
    err = write_element(challenge, element, value)
    if err:
        return jsonify({"error": err}), 502
    return jsonify({"ok": True})


if __name__ == "__main__":
    start_sniffers()
    app.run(host="0.0.0.0", port=8000, threaded=True)
