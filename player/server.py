"""HTTP control server for the radio.

Endpoints:
    GET  /                — control UI (HTML)
    GET  /style.css       — UI styles
    GET  /app.js          — UI script
    GET  /state           — current channel + volume + channel list (JSON)
    POST /switch?ch=<id>  — switch to channel
    POST /volume?v=<0-100>— set volume

Designed for local-network use (the Pi inside a boombox). No auth, no TLS.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "control"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".ico":  "image/x-icon",
}


class _Handler(BaseHTTPRequestHandler):
    player = None

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        path = url.path
        if path == "/" or path == "/index.html":
            self._serve_file(STATIC_DIR / "index.html")
        elif path == "/state":
            self._json(200, self.player.get_state())
        elif path.lstrip("/") in {"style.css", "app.js", "favicon.ico"}:
            self._serve_file(STATIC_DIR / path.lstrip("/"))
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if url.path == "/switch":
            ch = (qs.get("ch") or [None])[0]
            if not ch:
                self._json(400, {"error": "missing ch"})
                return
            # Run in a thread — switch_to takes several seconds.
            threading.Thread(
                target=self.player.switch_to, args=(ch,), daemon=True
            ).start()
            self._json(200, {"ok": True, "switching_to": ch})
        elif url.path == "/volume":
            raw = (qs.get("v") or [None])[0]
            try:
                vol = int(raw)
            except (TypeError, ValueError):
                self._json(400, {"error": "missing/invalid v"})
                return
            self.player.set_volume(vol)
            self._json(200, {"ok": True, "volume": self.player.target_volume})
        else:
            self.send_error(404)

    def log_message(self, fmt: str, *args) -> None:
        return  # quiet


def serve(player, port: int = 8080) -> ThreadingHTTPServer:
    _Handler.player = player
    srv = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    print(f"control UI → http://0.0.0.0:{port}")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv
