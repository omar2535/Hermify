"""Hermify outbox: serves files the agent saved for its person, read-only.

Runs as a sidecar in each agent pod. Open WebUI's "Hermify files" filter fetches
GET /files/<path> with the agent's API_SERVER_KEY and stores the file in Open WebUI
for the person chatting. Only files under OUTBOX_DIR are served; symlinks that lead
out of it are refused. Standard library only.
"""

import hmac
import mimetypes
import os
import shutil
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.realpath(os.environ.get("OUTBOX_DIR", "/opt/data/outbox"))
PORT = int(os.environ.get("OUTBOX_PORT", "8643"))
MAX_BYTES = int(os.environ.get("OUTBOX_MAX_BYTES", str(100 * 1024 * 1024)))
EXPECTED = ("Bearer " + os.environ["API_SERVER_KEY"]).encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "hermify-outbox"
    sys_version = ""

    def _empty(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/healthz":
            return self._empty(200)

        auth = (self.headers.get("Authorization") or "").encode()
        if not hmac.compare_digest(auth, EXPECTED):
            return self._empty(401)

        if not url.path.startswith("/files/"):
            return self._empty(404)
        rel = urllib.parse.unquote(url.path[len("/files/"):])
        path = os.path.realpath(os.path.join(ROOT, rel))
        if not path.startswith(ROOT + os.sep) or not os.path.isfile(path):
            return self._empty(404)

        size = os.path.getsize(path)
        if size > MAX_BYTES:
            return self._empty(413)

        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        try:
            with open(path, "rb") as f:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                shutil.copyfileobj(f, self.wfile)
        except OSError:
            # Gone or unreadable between the checks and the read.
            if not self.wfile.closed:
                self.close_connection = True

    def log_message(self, fmt, *args):
        # Path and status only; never headers (they carry the key).
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    print(f"outbox: serving {ROOT} on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
