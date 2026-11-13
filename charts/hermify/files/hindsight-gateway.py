"""Hermify Hindsight gateway: each agent may only touch its own memory bank.

Hindsight's API has no per-bank auth, so this small proxy sits in front of it (a
sidecar in the Hindsight pod; the NetworkPolicy only lets agents reach this port). Each
agent sends its own HINDSIGHT_API_KEY as a Bearer token; the key decides the one bank it
may use. Anything not explicitly allowed is refused: other banks, the bank list, aliases,
clones, cross-bank transfers, webhooks, global chunk/file lookups, MCP.

Config (env): GATEWAY_PORT, UPSTREAM (http://127.0.0.1:8888), and for each tenant
HERMIFY_KEY_<n> / HERMIFY_BANK_<n>. Standard library only.
"""

import hashlib
import http.client
import json
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("GATEWAY_PORT", "8889"))
UPSTREAM = urllib.parse.urlsplit(os.environ.get("UPSTREAM", "http://127.0.0.1:8888"))
MAX_BODY = int(os.environ.get("GATEWAY_MAX_BODY", str(64 * 1024 * 1024)))
TIMEOUT = float(os.environ.get("GATEWAY_UPSTREAM_TIMEOUT", "600"))

# sha256(key) -> bank id
BANKS: dict[str, str] = {}
for name, value in os.environ.items():
    m = re.fullmatch(r"HERMIFY_KEY_(\d+)", name)
    if m and value:
        bank = os.environ.get(f"HERMIFY_BANK_{m.group(1)}", "")
        if bank:
            BANKS[hashlib.sha256(value.encode()).hexdigest()] = bank

# No bank needed: harmless, read-only.
GLOBAL_GET = {"/version", "/v1/version", "/health", "/health/live", "/health/ready", "/v1/bank-template-schema"}

# What an agent may do inside its own bank: the first path segment after the bank id.
# Left out on purpose: aliases, clone, transfer, document-transfer (they link or copy to
# other banks) and webhooks (Hindsight would call out to any URL). New Hindsight
# endpoints stay blocked until they're added here.
BANK_SUBRESOURCES = {
    "memories", "reflect", "documents", "entities", "graph", "mental-models", "directives",
    "operations", "observations", "stats", "tags", "profile", "config", "files",
    "attachments", "consolidate", "consolidation", "consolidation-strategies", "background",
    "knowledge-base", "pages", "health", "audit-logs", "llm-requests", "import", "export",
    "prompts",
}
READ_ONLY_SUBRESOURCES = {"config"}  # bank tuning stays with the admin (Hindsight UI)

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
              "trailer", "transfer-encoding", "upgrade", "host", "authorization", "content-length",
              "expect"}
SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._~%:@!$&'()*+,;=-]+")


def allowed(method: str, path: str, bank: str) -> bool:
    if method in ("GET", "HEAD") and path in GLOBAL_GET:
        return True
    parts = path.split("/")
    # "", "v1", "default", "banks", <bank>, [sub, ...]
    if len(parts) < 5 or parts[:4] != ["", "v1", "default", "banks"]:
        return False
    for seg in parts[1:]:
        if not seg or not SAFE_SEGMENT.fullmatch(seg):
            return False
        dec = urllib.parse.unquote(seg)
        if dec in (".", "..") or "/" in dec or "\\" in dec:
            return False
    if parts[4] != bank:  # compared raw: bank ids never need encoding
        return False
    if len(parts) == 5:
        return method in ("GET", "PUT", "PATCH", "DELETE")
    sub = parts[5]
    if sub not in BANK_SUBRESOURCES:
        return False
    if sub in READ_ONLY_SUBRESOURCES and method not in ("GET", "HEAD"):
        return False
    return True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 900  # idle keep-alive connections don't hold a thread forever
    server_version = "hermify-hindsight-gateway"
    sys_version = ""

    def _reply(self, code: int, detail: str):
        body = json.dumps({"detail": detail}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes | None:
        if (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            out = bytearray()
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                        pass
                    return bytes(out)
                out += self.rfile.read(size)
                self.rfile.readline()
                if len(out) > MAX_BODY:
                    return None
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return None
        return self.rfile.read(length) if length else b""

    def _handle(self):
        path, _, query = self.path.partition("?")
        if path in ("/health", "/health/live", "/health/ready") and self.command == "GET" \
                and not self.headers.get("Authorization"):
            # Probes (kubelet) and plain health checks, no key needed.
            bank = "-"
        else:
            auth = self.headers.get("Authorization") or ""
            key = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
            bank = BANKS.get(hashlib.sha256(key.encode()).hexdigest()) if key else None
            if not bank:
                self.close_connection = True
                return self._reply(401, "Hindsight gateway: missing or unknown API key")
            if not allowed(self.command, path, bank):
                self.log_message('denied %s %s (bank %s)', self.command, path, bank)
                self.close_connection = True
                return self._reply(403, "Hindsight gateway: not allowed for this key")

        body = self._read_body()
        if body is None:
            self.close_connection = True
            return self._reply(413, "Hindsight gateway: request body too large")

        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        headers["Host"] = UPSTREAM.netloc
        if body or self.command in ("POST", "PUT", "PATCH"):
            headers["Content-Length"] = str(len(body))
        conn = http.client.HTTPConnection(UPSTREAM.hostname, UPSTREAM.port or 80, timeout=TIMEOUT)
        try:
            conn.request(self.command, self.path, body=body or None, headers=headers)
            resp = conn.getresponse()
            self.send_response(resp.status, resp.reason)
            length = resp.getheader("Content-Length")
            for k, v in resp.getheaders():
                if k.lower() not in HOP_BY_HOP:
                    self.send_header(k, v)
            no_body = self.command == "HEAD" or resp.status in (204, 304) or 100 <= resp.status < 200
            if no_body:
                self.send_header("Content-Length", length or "0")
                self.end_headers()
                return
            if length is not None:
                self.send_header("Content-Length", length)
                self.end_headers()
                while chunk := resp.read(65536):
                    self.wfile.write(chunk)
            else:
                # Stream through (e.g. server-sent events) re-chunked.
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while chunk := resp.read1(65536):
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
        except (OSError, http.client.HTTPException) as e:
            self.close_connection = True
            try:
                self._reply(502, f"Hindsight gateway: upstream error ({type(e).__name__})")
            except OSError:
                pass
        finally:
            conn.close()

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _handle

    def do_OPTIONS(self):
        self._reply(405, "Hindsight gateway: method not allowed")

    def log_message(self, fmt, *args):
        # Method, path (no query string: it can hold memory text) and status; never headers.
        msg = fmt % args
        msg = re.sub(r'"(\w+) ([^ ?"]*)\?[^ "]*', r'"\1 \2?…', msg)
        sys.stderr.write(f"{self.address_string()} {msg}\n")


if __name__ == "__main__":
    if not BANKS:
        print("hindsight-gateway: no HERMIFY_KEY_n/HERMIFY_BANK_n configured; every request will be refused",
              file=sys.stderr, flush=True)
    configured = {os.environ[k] for k in os.environ if re.fullmatch(r"HERMIFY_BANK_\d+", k)}
    for bank in sorted(configured - set(BANKS.values())):
        print(f"hindsight-gateway: no key for bank {bank} (HINDSIGHT_API_KEY missing from its Secret); "
              "that agent can't use memory", file=sys.stderr, flush=True)
    print(f"hindsight-gateway: {len(BANKS)} key(s), :{PORT} -> {UPSTREAM.geturl()}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
