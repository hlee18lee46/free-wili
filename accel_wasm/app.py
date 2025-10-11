# app.py — static-only Flask server for WASM build (no serial access)
import argparse
import os
import mimetypes
from flask import Flask, send_from_directory, abort, jsonify
from serial.tools import list_ports

# Ensure correct MIME type for .wasm
mimetypes.add_type("application/wasm", ".wasm")

app = Flask(__name__, static_folder=None)


def _safe_path(root, path):
    """Resolve path safely inside root directory."""
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(os.path.realpath(root)):
        abort(403)
    return full


def create_app(web_root: str):
    """Factory to create a Flask app bound to a specific web root."""

    @app.route("/")
    def index():
        return send_from_directory(web_root, "index.html")

    @app.route("/<path:asset_path>")
    def serve_asset(asset_path):
        full = _safe_path(web_root, asset_path)
        directory, filename = os.path.split(full)
        if not os.path.exists(full):
            abort(404)
        return send_from_directory(directory, filename)

    # Optional: List serial ports without opening them
    @app.route("/ports")
    def list_serial_ports():
        ports = []
        for p in list_ports.comports():
            ports.append({
                "device": p.device,
                "description": p.description,
                "hwid": p.hwid,
            })
        return jsonify(ports)

    return app


def main():
    parser = argparse.ArgumentParser(description="Static server for WASM (no serial).")
    parser.add_argument("--host", default="127.0.0.1", help="Host IP (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7001, help="Port number (default: 7001)")
    parser.add_argument("--web-root", default="web", help="Directory with index.html and pkg/")
    args = parser.parse_args()

    web_root = args.web_root
    if not os.path.exists(os.path.join(web_root, "index.html")):
        raise SystemExit(f"[error] index.html not found in {web_root}")

    print(f"Serving {web_root} on http://{args.host}:{args.port} (no serial access)")
    app_instance = create_app(web_root)
    app_instance.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
