# app.py — static-only Flask server for WASM build (no serial access)
import argparse
import os
import mimetypes
from flask import Flask, send_from_directory, abort, jsonify
from serial.tools import list_ports
from flask import Response, jsonify, request
import httpx
import threading
from elevenlabs.client import ElevenLabs
from elevenlabs.play import play  # <-- import the function from the module
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient
from pymongo.errors import PyMongoError
import jwt
from jwt import InvalidTokenError, InvalidAudienceError, InvalidIssuerError

# Simple in-memory cache (text -> (bytes, expiry))
_TTS_CACHE = {}
_TTS_LOCK = threading.Lock()
_TTS_TTL_SEC = 60  # cache identical phrases for 60s

# Ensure correct MIME type for .wasm
mimetypes.add_type("application/wasm", ".wasm")

app = Flask(__name__, static_folder=None)

# --- Mongo / JWT config ---
_MONGO_URI = os.getenv("MONGO_URI")
_DB_NAME = os.getenv("MONGO_DB", "agentdb")
_EVENTS_COLL = os.getenv("EVENTS_COLLECTION", "motion_events")

_JWT_SECRET = os.getenv("LOGIN_JWT_SECRET")
_JWT_ISS = os.getenv("LOGIN_JWT_ISS", "agent-auth")
_JWT_AUD = os.getenv("LOGIN_JWT_AUD", "agent-tools")

_mongo_client = None
_events = None


def _mongo_events():
    """Lazy-init and return the events collection with indexes."""
    global _mongo_client, _events
    if _events is not None:
        return _events
    if not _MONGO_URI:
        raise RuntimeError("MONGO_URI is not set in .env (required for motion logging)")
    _mongo_client = MongoClient(_MONGO_URI)
    db = _mongo_client[_DB_NAME]
    _events = db[_EVENTS_COLL]
    # Idempotent indexes
    _events.create_index("created_at")
    _events.create_index([("user_id", 1), ("created_at", -1)], name="user_time")
    return _events


def _derive_user_id_from_request() -> Optional[str]:
    """
    Optional: derive user_id from Authorization: Bearer <JWT> header or ?jwt= query.
    Returns user_id str or None if not provided/invalid.
    """
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1].strip()
    if not token:
        token = request.args.get("jwt")

    if not token:
        return None

    if not _JWT_SECRET:
        # JWT present but we can't validate without secret; treat as anonymous
        return None

    try:
        payload = jwt.decode(
            token,
            _JWT_SECRET,
            algorithms=["HS256"],
            issuer=_JWT_ISS,
            audience=_JWT_AUD,
        )
        return payload.get("sub")
    except (InvalidTokenError, InvalidAudienceError, InvalidIssuerError):
        # Invalid tokens are ignored; we still log the event without a user_id
        return None


def _log_motion_event(text: str, voice_id: str, model_id: str, output_format: str, ok: bool, err: Optional[str]):
    try:
        coll = _mongo_events()
        doc = {
            "_id": str(uuid.uuid4()),
            "user_id": _derive_user_id_from_request(),  # may be None
            "source": "speak-motion",
            "text": text,
            "voice_id": voice_id,
            "model_id": model_id,
            "output_format": output_format,
            "success": bool(ok),
            "error": err,
            "ip": request.headers.get("x-forwarded-for", request.remote_addr),
            "user_agent": request.headers.get("user-agent"),
            "created_at": datetime.now(timezone.utc),
        }
        coll.insert_one(doc)
    except Exception as e:
        # Don't break TTS responses because logging failed.
        print("Motion log error:", repr(e))


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


@app.route("/speak-motion")
def speak_motion():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing ELEVENLABS_API_KEY in .env"}), 500

    text = request.args.get("text", "Motion detected. Theft Alert! Theft Alert!")
    voice_id = request.args.get("voice_id", "JBFqnCBsd6RMkjVDRZzb")  # sample voice
    model_id = request.args.get("model_id", "eleven_multilingual_v2")
    output_format = request.args.get("fmt", "mp3_44100_128")

    # Try to generate audio first; log result either way.
    try:
        # Cache hit?
        now = time.time()
        with _TTS_LOCK:
            hit = _TTS_CACHE.get((text, voice_id, model_id, output_format))
            if hit and hit[1] > now:
                _log_motion_event(text, voice_id, model_id, output_format, ok=True, err=None)
                return Response(hit[0], mimetype="audio/mpeg")

        client = ElevenLabs(api_key=api_key)
        stream = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format,
        )
        audio_bytes = b"".join(stream)

        with _TTS_LOCK:
            _TTS_CACHE[(text, voice_id, model_id, output_format)] = (audio_bytes, now + _TTS_TTL_SEC)

        _log_motion_event(text, voice_id, model_id, output_format, ok=True, err=None)
        return Response(audio_bytes, mimetype="audio/mpeg")
    except Exception as e:
        print("ElevenLabs TTS error:", repr(e))
        _log_motion_event(text, voice_id, model_id, output_format, ok=False, err=str(e))
        return jsonify({"error": "TTS failed"}), 500


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
