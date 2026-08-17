const fs = require('fs');
const path = require('path');
const express = require('express');
const helmet = require('helmet');
const https = require('https');
const { Server } = require('socket.io');
const mqtt = require('mqtt');

// ---------------------------------------------------------------------
// SSL certificates for HTTPS (Node.js server-side TLS).
// ---------------------------------------------------------------------
const serverKey = fs.readFileSync(path.join(__dirname, 'mqtt-certs', 'server.key'));
const serverCert = fs.readFileSync(path.join(__dirname, 'mqtt-certs', 'server.pem'));
const caPath = path.join(__dirname, 'mqtt-certs', 'ca.pem'); 

// Create an Express app
const app = express();

// Use Helmet for default security headers, including basic CSP
app.use(
  helmet({
    contentSecurityPolicy: {
      directives: {
        defaultSrc: ["'self'"],
        scriptSrc: ["'self'"] // Scripts must come from same origin
      }
    },
  })
);

// ---------------------------------------------------------------------
// Which venue map to show (public/map.png = Las Vegas, public/denMap.png
// = Denver). Previously hardcoded as a literal filename in
// public/index.html's <img src>, which meant switching venues meant
// editing and redeploying frontend source. Now a one-line env var change
// - see docker-compose.yml's MAP_IMAGE and docs/ADMIN.md.
// ---------------------------------------------------------------------
const MAP_IMAGE = process.env.MAP_IMAGE || 'denMap.png';
app.get('/map-config.js', (req, res) => {
  res.type('application/javascript').send(`window.MAP_IMAGE = ${JSON.stringify(MAP_IMAGE)};`);
});

// ---------------------------------------------------------------------
// Which zones actually exist, where they sit on the map, and which
// challenge each one belongs to. Single source of truth for the MQTT
// subscription list below, the canvas overlay, and the side panel - all
// three used to independently hardcode zones 1..16 in a fixed 4x4 grid
// covering the whole map, most of which nothing ever published to.
//
// Positions are hand-placed to cluster over each map's downtown/city-core
// area rather than tile the whole canvas - sizes and placement are
// deliberately uneven, not a grid. The three shipped maps (map.png /
// denMap.png / ftcMap.png) don't have their downtown areas at identical
// pixel coordinates, so this is a reasonable shared compromise across all
// three, not a pixel-perfect match to any one of them - re-tune per-map
// if that precision ever matters.
// ---------------------------------------------------------------------
const ZONES = [
  { num: 1, x: 770, y: 640, w: 220, h: 170, label: 'mitm-modbus' },
  { num: 2, x: 1010, y: 640, w: 220, h: 170, label: 'dnpchallenge' },
  { num: 3, x: 730, y: 830, w: 140, h: 110, label: 'mqtthelper (pin 33)' },
  { num: 4, x: 1150, y: 830, w: 140, h: 110, label: 'mqtthelper (pin 35)' },
  { num: 5, x: 890, y: 830, w: 240, h: 180, label: 'bh-intellirupter' },
];
app.get('/zone-config.js', (req, res) => {
  res.type('application/javascript').send(`window.ZONES = ${JSON.stringify(ZONES)};`);
});

// Serve static files (index.html, main.js, images, etc.) from the "public" folder
app.use(express.static(path.join(__dirname, 'public')));

// Create an HTTPS server
const server = https.createServer(
  {
    key: serverKey,
    cert: serverCert,
    // If using self-signed, you may need: ca: fs.readFileSync(caPath)
  },
  app
);

// Attach Socket.IO to the HTTPS server
const io = new Server(server);

// ---------------------------------------------------------------------
// MQTT Client Setup - connect to broker at 'mqtt' for TLS on port 1883
// ---------------------------------------------------------------------
const mqttClient = mqtt.connect({
  host: 'mqtt',
  port: 1883,         // If Mosquitto is configured for TLS on 1883
  protocol: 'mqtts',  // 'mqtts' indicates secure MQTT
  ca: fs.readFileSync(caPath),
  // If self-signed, you might do rejectUnauthorized: false
});

mqttClient.on('connect', () => {
  console.log('Node.js -> MQTT broker connected');
  
  // Subscribe only to zones something actually publishes to (see ZONES
  // above) - previously subscribed to zone1..zone16 unconditionally, 11
  // of which nothing has ever published to.
  for (const zone of ZONES) {
    const topic = `zone${zone.num}`;
    mqttClient.subscribe(topic, (err) => {
      if (err) {
        console.error(`Error subscribing to ${topic}:`, err.message);
      } else {
        console.log(`Subscribed to ${topic}`);
      }
    });
  }
});

mqttClient.on('message', (topic, message) => {
  console.log(`MQTT message on ${topic}: ${message.toString()}`);
  // Forward MQTT data to all Socket.IO clients
  io.emit('mqttMessage', { topic, message: message.toString() });
});

mqttClient.on('error', (err) => {
  console.error('MQTT Error:', err.message);
});

// ---------------------------------------------------------------------
// Socket.IO: Handle client connections
// ---------------------------------------------------------------------
io.on('connection', (socket) => {
  console.log('New Socket.IO client:', socket.id);

  // Example custom event
  socket.on('my event', (data) => {
    console.log('Client says:', data);
    socket.emit('my response', { msg: 'Hello from the server!' });
  });
});

// Start the server on port 3000
server.listen(3000, () => {
  console.log('HTTPS server running on https://localhost:3000');
});
