#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HEART = """
  ██   ██
██████████
 ████████
   ████
    ██
""".strip("\n")


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok", "component": "mcu-simulator"})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/bridge/call":
            self.send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "invalid JSON"})
            return

        method = request.get("method")
        args = request.get("args", [])
        if method != "keyword_detected":
            self.send_json(404, {"error": f"unknown Bridge method: {method}"})
            return

        label = args[0] if args else "unknown"
        print(f"[MCU] keyword_detected({label!r})", flush=True)
        print("[MCU] wake_up()", flush=True)
        print(f"[LED]\n{HEART}", flush=True)
        self.send_json(200, {
            "ok": True,
            "animation": "HeartAnim",
            "label": label,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def log_message(self, fmt, *args):
        print(f"[HTTP] {fmt % args}", flush=True)


if __name__ == "__main__":
    print("[MCU] Bridge simulator listening on :9000", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()

