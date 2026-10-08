#!/usr/bin/env python3
"""Tiny stand-in for the Home Assistant Core API, for local testing of ha-safe-write / ha-reload.

POST /api/config/core/check_config -> {"result":"valid"}, or "invalid" while the file
                                      /homeassistant/.mock-fail exists (touch it to test rollback)
POST /api/services/<domain>/<svc>  -> 200 []
"""
import http.server, json, os

FAIL_FLAG = os.environ.get("MOCK_FAIL_FLAG", "/homeassistant/.mock-fail")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.endswith("/config/core/check_config"):
            if os.path.exists(FAIL_FLAG):
                body = {"result": "invalid", "errors": "Mock error: remove %s to make the check pass" % FAIL_FLAG}
            else:
                body = {"result": "valid", "errors": None}
        else:
            body = []
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        print("[mock-ha]", self.command, self.path, flush=True)


http.server.HTTPServer(("127.0.0.1", 8123), Handler).serve_forever()
