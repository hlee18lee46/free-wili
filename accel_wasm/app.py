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
from typing import Optional
import cv2
from pathlib import Path
_MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "media")).resolve()
_MEDIA_DIR.mkdir(parents=True, exist_ok=True)


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

def _open_camera() -> Optional[cv2.VideoCapture]:
    # Use AVFoundation only on the main thread (macOS quirk)
    if threading.current_thread().name == "MainThread":
        cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
        if cap is not None and cap.isOpened():
            return cap
        if cap: cap.release()

    # Fallback: generic backend (works well in background threads)
    cap = cv2.VideoCapture(0)
    if cap is not None and cap.isOpened():
        return cap
    if cap: cap.release()
    return None


def _capture_photo_async(event_id: str, user_id: Optional[str]) -> None:
    """
    Background task: open camera, grab one frame, write JPEG,
    and update the event doc with photo metadata.
    """
    filename = None
    try:
        cap = _open_camera()
        if not cap:
            raise RuntimeError("Camera not available")

        # Warm-up frames (some cameras need a moment to adjust)
        for _ in range(3):
            cap.read()

        ok, frame = cap.read()
        cap.release()

        if not ok or frame is None:
            raise RuntimeError("Failed to read frame")

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{event_id}.jpg"
        filepath = _MEDIA_DIR / filename

        # Write JPEG
        ok = cv2.imwrite(str(filepath), frame)
        if not ok:
            raise RuntimeError("Failed to write JPEG")

        # Update Mongo event with photo info
        try:
            coll = _mongo_events()
            coll.update_one(
                {"_id": event_id},
                {
                    "$set": {
                        "photo_filename": filename,
                        "photo_path": str(filepath),
                        "photo_url": f"/media/{filename}",
                        "photo_saved_at": datetime.now(timezone.utc),
                    }
                },
            )
        except Exception as e:
            print("Mongo update after photo capture failed:", repr(e))
    except Exception as e:
        print("Camera/photo error:", repr(e))
        # Best-effort: annotate event as failed to capture (if event exists)
        try:
            coll = _mongo_events()
            coll.update_one(
                {"_id": event_id},
                {"$set": {"photo_error": str(e)}}
            )
        except Exception:
            pass


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
    
    @app.route("/media/<path:fname>")
    def serve_media(fname):
        # prevent path traversal
        safe = os.path.basename(fname)
        full = _MEDIA_DIR / safe
        if not full.exists():
            abort(404)
        return send_from_directory(str(_MEDIA_DIR), safe)
    
    return app


@app.route("/speak-motion")
def speak_motion():
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing ELEVENLABS_API_KEY in .env"}), 500

    text = request.args.get("text", "Motion detected. Theft Alert! Theft Alert!")
    voice_id = request.args.get("voice_id", "JBFqnCBsd6RMkjVDRZzb")
    model_id = request.args.get("model_id", "eleven_multilingual_v2")
    output_format = request.args.get("fmt", "mp3_44100_128")

    # Determine user scope (if any) for the event
    user_id = _derive_user_id_from_request()
    event_id = str(uuid.uuid4())

    # Pre-insert an event doc so we can attach photo later
    try:
        coll = _mongo_events()
        pre_doc = {
            "_id": event_id,
            "user_id": user_id,
            "source": "speak-motion",
            "text": text,
            "voice_id": voice_id,
            "model_id": model_id,
            "output_format": output_format,
            "success": None,          # unknown yet
            "error": None,
            "ip": request.headers.get("x-forwarded-for", request.remote_addr),
            "user_agent": request.headers.get("user-agent"),
            "created_at": datetime.now(timezone.utc),
        }
        coll.insert_one(pre_doc)
    except Exception as e:
        print("Event pre-insert error:", repr(e))

    # Kick off photo capture in the background
    try:
        threading.Thread(
            target=_capture_photo_async,
            args=(event_id, user_id),
            daemon=True
        ).start()
    except Exception as e:
        print("Failed to start photo thread:", repr(e))
        try:
            _mongo_events().update_one({"_id": event_id}, {"$set": {"photo_error": str(e)}})
        except Exception:
            pass

    # TTS response (cache-aware)
    try:
        now = time.time()
        with _TTS_LOCK:
            hit = _TTS_CACHE.get((text, voice_id, model_id, output_format))
            if hit and hit[1] > now:
                # Mark event success and return cached audio
                try:
                    _mongo_events().update_one({"_id": event_id}, {"$set": {"success": True, "error": None}})
                except Exception:
                    pass
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

        try:
            _mongo_events().update_one({"_id": event_id}, {"$set": {"success": True, "error": None}})
        except Exception:
            pass

        return Response(audio_bytes, mimetype="audio/mpeg")
    except Exception as e:
        print("ElevenLabs TTS error:", repr(e))
        try:
            _mongo_events().update_one({"_id": event_id}, {"$set": {"success": False, "error": str(e)}})
        except Exception:
            pass
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

@app.route("/events/latest")
def events_latest():
    try:
        coll = _mongo_events()
        doc = coll.find().sort("created_at", -1).limit(1).next()
    except Exception:
        return jsonify({"ok": False, "error": "No events yet"}), 404

    # make it JSON-friendly
    doc["_id"] = str(doc["_id"])
    for k in ("created_at", "photo_saved_at"):
        if doc.get(k):
            doc[k] = doc[k].isoformat()
    return jsonify({"ok": True, "event": doc})

if __name__ == "__main__":
    main()
