#!/usr/bin/env python3
import os, threading, time, re, json
from collections import deque
from flask import Flask, send_from_directory, render_template_string
from flask_sock import Sock
import serial

# --- CONFIG ---
SERIAL_PORT = os.environ.get("FWILI_PORT", "/dev/cu.usbmodem1133201")  # Display CPU you used
BAUD        = int(os.environ.get("FWILI_BAUD", "115200"))
READ_TIMEOUT= 0.2

# --- Parsers (covers your real output) ---
RE_ACCEL_EVENT = re.compile(r"\[\*accel\s+[^\]]*?\s(\d+)g\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)", re.I)
RE_BANNER      = re.compile(r"Accel\s*\(\s*(\d+)g\)\s*:\s*x\s*(-?\d+)\s*y\s*(-?\d+)\s*z\s*(-?\d+)", re.I)

def parse_line(line: str):
    """
    Returns (ax, ay, az) in m/s^2 or None if not accel.
    Prefers event format; falls back to banner format.
    """
    m = RE_ACCEL_EVENT.search(line)
    if not m:
        m = RE_BANNER.search(line)
    if not m:
        return None
    rng_g = int(m.group(1))       # 2,4,8,16...
    sx, sy, sz = int(m.group(2)), int(m.group(3)), int(m.group(4))
    # LSB/g scaling: 2g→16384, 4g→8192, 8g→4096, 16g→2048 -> g_per_lsb = rng/32768
    g_per_lsb = float(rng_g) / 32768.0
    g2ms2 = 9.80665
    ax = sx * g_per_lsb * g2ms2
    ay = sy * g_per_lsb * g2ms2
    az = sz * g_per_lsb * g2ms2
    return (ax, ay, az)

# --- App ---
app = Flask(__name__)
sock = Sock(app)

# store live websocket connections
clients = set()
clients_lock = threading.Lock()

# simple rolling buffer (for late joiners)
history = deque(maxlen=300)  # ~30s if 10Hz

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)

@app.route("/wasm")
def wasm_index():
    # Serve accel_wasm/index.html as a template (or you can inline small HTML)
    return send_from_directory("accel_wasm", "index.html")

@app.route("/pkg/<path:path>")
def wasm_pkg(path):
    # Serve WASM build output from wasm-pack (pkg/ folder)
    return send_from_directory("accel_wasm/pkg", path)

# optional: serve Chart.js locally if needed later; for now we use CDN in template
@app.route("/healthz")
def healthz():
    return "ok", 200

@sock.route("/stream")
def stream(ws):
    # send a short history so chart isn’t empty
    with clients_lock:
        clients.add(ws)
    try:
        if history:
            ws.send(json.dumps({"type":"history","data":list(history)}))
        # keep the socket open; we don’t expect client → server messages
        while True:
            msg = ws.receive(timeout=60)
            # ignore; just keep alive
            if msg is None:
                break
    except Exception:
        pass
    finally:
        with clients_lock:
            clients.discard(ws)

def broadcast(sample):
    payload = json.dumps({"type":"sample","data":sample})
    dead = []
    with clients_lock:
        for ws in list(clients):
            try:
                ws.send(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            clients.discard(ws)

def serial_reader():
    # open serial and just read lines forever
    while True:
        try:
            with serial.Serial(SERIAL_PORT, BAUD, timeout=READ_TIMEOUT) as ser:
                # small warmup
                time.sleep(0.2)
                while True:
                    raw = ser.readline().decode("utf-8","ignore").strip()
                    if not raw:
                        continue
                    # ignore button spam
                    if raw.startswith("[*button"):
                        continue
                    parsed = parse_line(raw)
                    if parsed:
                        ax, ay, az = parsed
                        sample = {"t": time.time(), "ax": ax, "ay": ay, "az": az}
                        history.append(sample)
                        broadcast(sample)
        except Exception as e:
            # if port not present or momentarily busy, wait and retry
            time.sleep(0.5)

# start reader thread
t = threading.Thread(target=serial_reader, daemon=True)
t.start()

# ---------- Minimal HTML ----------
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>FREE-WILi Live Accel</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 20px; }
    #status { margin-bottom: 10px; }
    canvas { max-width: 100%; height: 320px; }
    .row { display: flex; gap: 16px; flex-wrap: wrap; }
    .card { padding: 12px; border: 1px solid #ddd; border-radius: 12px; }
  </style>
</head>
<body>
  <h2>FREE-WILi Live Accelerometer</h2>
  <div id="status">Connecting…</div>
  <div class="row">
    <div class="card"><canvas id="ax"></canvas></div>
    <div class="card"><canvas id="ay"></canvas></div>
    <div class="card"><canvas id="az"></canvas></div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script>
  const charts = {};
  function mkChart(canvasId, label) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
      type: 'line',
      data: { labels: [], datasets: [{ label, data: [], pointRadius: 0, borderWidth: 1 }] },
      options: {
        animation: false,
        responsive: true,
        scales: { x: { display:false }, y: { title: { display:true, text:'m/s²' } } },
        plugins: { legend: { display:true } }
      }
    });
  }
  charts.ax = mkChart('ax', 'ax');
  charts.ay = mkChart('ay', 'ay');
  charts.az = mkChart('az', 'az');

  function addSample(s) {
    const ts = new Date(s.t * 1000).toLocaleTimeString();
    for (const k of ['ax','ay','az']) {
      const c = charts[k];
      c.data.labels.push(ts);
      c.data.datasets[0].data.push(s[k]);
      if (c.data.labels.length > 300) {
        c.data.labels.shift();
        c.data.datasets[0].data.shift();
      }
      c.update('none');
    }
  }

  function addHistory(arr) {
    for (const s of arr) addSample(s);
  }

  const proto = (location.protocol === 'https:') ? 'wss' : 'ws';
  const ws = new WebSocket(proto + '://' + location.host + '/stream');
  ws.onopen = () => document.getElementById('status').textContent = 'Connected';
  ws.onclose = () => document.getElementById('status').textContent = 'Disconnected';
  ws.onerror = () => document.getElementById('status').textContent = 'Error (see console)';
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'history') addHistory(msg.data);
      if (msg.type === 'sample') addSample(msg.data);
    } catch(e) { console.error(e); }
  };
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5020"))
    print(f"Serving on http://127.0.0.1:{port}  (reading {SERIAL_PORT} @ {BAUD})")
    app.run(host="0.0.0.0", port=port)
