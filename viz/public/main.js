/***************************************************************
 * 1) LAYOUT SETUP AND ZONE TRACKING
 ***************************************************************/
function resize() {
    const body = document.getElementById("body");
    const canvas = document.getElementById("canvas");
    const side = document.getElementById("side");
    side.style.width = (body.clientWidth - canvas.clientWidth) - 1 + "px";
  }

  window.onresize = resize;

  const canvas = document.getElementById("canvas");
  const ctx = canvas.getContext("2d");
  const image = document.getElementById("map");

  // window.ZONES comes from /zone-config.js (server.js) - one entry per
  // zone that actually exists, with its own position/size on the canvas.
  // Previously this was a fixed 4x4 grid covering the whole canvas for
  // zones 1..16 regardless of whether anything published to most of
  // them. Keyed by zone number (not a dense 0-15 array) since the active
  // zone numbers aren't necessarily contiguous.
  const ZONES = window.ZONES || [];
  const zoneState = new Map(ZONES.map((z) => [z.num, 1])); // 1 = Normal, 0 = Down

  function shapeFor(zone) {
    const { x, y, w, h } = zone;
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]];
  }

  /***************************************************************
   * 2) DRAWING AND UPDATING ON CANVAS
   ***************************************************************/

  /**
   * Draw a single zone on the canvas
   * @param {CanvasRenderingContext2D} ctx
   * @param {object} zone - entry from ZONES
   * @param {boolean} isNormal - true=Normal, false=Down
   */
  function drawZone(ctx, zone, isNormal) {
    const shape = shapeFor(zone);
    ctx.beginPath();

    // Color: Normal=red, Down=green
    ctx.fillStyle = isNormal ? "red" : "green";
    ctx.globalAlpha = 0.4;

    ctx.moveTo(shape[0][0], shape[0][1]);
    shape.forEach((pt) => ctx.lineTo(pt[0], pt[1]));
    ctx.fill();

    // Label the zone number in the center, sized to fit the zone's own
    // box (zones vary in size now, unlike the old uniform grid).
    ctx.globalAlpha = 0.6;
    ctx.textAlign = "center";
    ctx.font = `${Math.max(18, Math.min(zone.w, zone.h) * 0.35)}px Arial`;
    ctx.fillText(zone.num.toString(), zone.x + zone.w / 2, zone.y + zone.h / 2);
    ctx.globalAlpha = 1;
  }

  function drawAllZones() {
    ctx.drawImage(image, 0, 0);
    for (const zone of ZONES) {
      drawZone(ctx, zone, zoneState.get(zone.num) === 1);
    }
  }

  /**
   * Build the side panel rows once, from ZONES, and update their
   * text/color whenever state changes.
   */
  function buildSidePanel() {
    const list = document.getElementById("zoneList");
    list.innerHTML = ZONES.map((zone) => `
      <div style="display: flex; justify-content: space-around; align-items: center; margin: 2px 0;">
        <p style="margin: 0;" title="${zone.label}">Zone ${zone.num} <span style="opacity:0.7; font-size:0.8em;">— ${zone.label}</span></p>
        <div id="zone${zone.num}Div"
             style="background-color: red; width: 80px; height: 20px;
                    display: flex; align-items: center; justify-content: center;">
          <p id="zone${zone.num}Text" style="margin: 0; font-size: 0.8em;">Normal</p>
        </div>
      </div>
    `).join("");
  }

  function updateBoard() {
    for (const zone of ZONES) {
      const textElem = document.getElementById(`zone${zone.num}Text`);
      const divElem = document.getElementById(`zone${zone.num}Div`);
      if (!textElem || !divElem) continue;

      if (zoneState.get(zone.num) === 1) {
        textElem.innerText = "Normal";
        divElem.style.backgroundColor = "red";
      } else {
        textElem.innerText = "Down";
        divElem.style.backgroundColor = "green";
      }
    }
  }

  /**
   * Called whenever a single zone's status changes
   * @param {number} zoneNumber
   * @param {boolean} isNormal
   */
  function updateZone(zoneNumber, isNormal) {
    if (!zoneState.has(zoneNumber)) return; // not a zone we track

    zoneState.set(zoneNumber, isNormal ? 1 : 0);
    updateBoard();
    drawAllZones();
  }

  /***************************************************************
   * 3) INITIAL SETUP AND EVENT HANDLERS
   ***************************************************************/

  resize();
  buildSidePanel();

  // Draw once image is loaded
  image.addEventListener("load", drawAllZones);

  // window.MAP_IMAGE comes from /map-config.js (server.js, driven by the
  // MAP_IMAGE env var) - setting src here (rather than hardcoding it in
  // index.html) is what makes switching venues a one-line env var change.
  image.src = window.MAP_IMAGE || "denMap.png";

  // ---------------------------------------------------------------
  // SOCKET.IO: connect to the server, handle events
  // ---------------------------------------------------------------
  const socket = io();

  // Example: send an event
  socket.emit('my event', { msg: 'Hello from the client!' });

  // Handle server response
  socket.on('my response', (data) => {
    console.log('Server responded:', data);
    drawAllZones();
  });

  // Listen for MQTT messages forwarded by the server
  socket.on('mqttMessage', (data) => {
    console.log("mqttMessage:", data);

    const prefix = "zone";

    // Extract everything after "zone"
    const zoneStr = data.topic.slice(prefix.length); // e.g. "10"
    const zoneNum = parseInt(zoneStr, 10);
    if (isNaN(zoneNum)) return;

    // -- Possibly parse data.message as JSON --
    let value = data.message;
    if (typeof value === 'string') {
      try {
        const parsed = JSON.parse(value);
        value = parsed;
      } catch (err) {
        // leave as string if parse fails
      }
    }

    // If it's an array, pick subValue = value[zoneNum % 4], else process value directly
    if (Array.isArray(value)) {
      const subValue = value[zoneNum % 4];
      processValue(zoneNum, subValue);
    } else {
      processValue(zoneNum, value);
    }
  });

  /**
   * Convert subValue to a boolean, then updateZone(zoneNum, thatBoolean)
   */
  function processValue(zoneNum, val) {
    if (typeof val === 'boolean') {
      updateZone(zoneNum, val);
    } else if (typeof val === 'string') {
      const lower = val.toLowerCase();
      if (lower === 'true') {
        updateZone(zoneNum, true);
      } else if (lower === 'false') {
        updateZone(zoneNum, false);
      } else if (lower === '0') {
        updateZone(zoneNum, false);
      } else if (lower === '1') {
        updateZone(zoneNum, true);
      } else {
        console.log('String not recognized as boolean/0/1:', val);
      }
    } else if (typeof val === 'number') {
      if (val === 0) {
        updateZone(zoneNum, false);
      } else if (val === 1) {
        updateZone(zoneNum, true);
      } else {
        console.log('Number not recognized (only 0/1) -> boolean:', val);
      }
    } else {
      console.log('Unsupported type for data.message:', val);
    }
  }

  socket.on('disconnect', () => {
    console.log('Socket.IO disconnected');
  });
