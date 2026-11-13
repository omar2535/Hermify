"""Shared bits for the tests: load the chart's Python files and run servers in threads."""

import http.client
import importlib.util
import os
import socket
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ROOT / "charts" / "hermify" / "files"


def load(path: Path, name: str, env: dict[str, str]):
    """Import a script (hyphenated names allowed) with `env` set while it loads."""
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def serve(handler) -> ThreadingHTTPServer:
    """Start `handler` on a free localhost port in a background thread."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def request(port, method, path, headers=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data, r


def raw(port, text: str) -> int:
    """Send a hand-written request (for paths http.client would refuse); return the status."""
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(text.encode())
    buf = b""
    while b"\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    s.close()
    return int(buf.split(b"\r\n", 1)[0].split()[1])
