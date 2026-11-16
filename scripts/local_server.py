"""Local dev server: real LINE via ngrok, NO AWS. In-memory store, session logic runs synchronously.

    make local            # then: ngrok http 8000
    # LINE Developers > Messaging API > Webhook URL = https://<ngrok-id>.ngrok-free.app/callback
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from adapters.line import verify_signature
from config import load_settings
from wiring import build_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("local")

settings = load_settings()
if settings.line_provider != "real":
    settings = settings.model_copy(update={"line_provider": "real"})
engine = build_engine(settings)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # health check
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"pai-nhai-dee-wa local ok")

    def do_POST(self) -> None:
        if self.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not verify_signature(settings.line_channel_secret, body, self.headers.get("x-line-signature")):
            log.warning("bad signature -> 401")
            self.send_response(401)
            self.end_headers()
            return
        for ev in json.loads(body).get("events", []):
            log.info("event type=%s", ev.get("type"))  # never log text
            try:
                asyncio.run(engine.handle(ev))
            except Exception:
                log.exception("event failed")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args: object) -> None:  # silence default access log
        pass


def main() -> None:
    for problem in settings.problems():
        log.warning("config: %s", problem)
    port = int(os.environ.get("PORT", "8000"))
    log.info("listening on http://localhost:%d/callback (llm=%s places=%s)",
             port, settings.llm_provider, settings.places_provider)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
