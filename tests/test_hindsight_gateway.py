"""The Hindsight gateway must let each key use its own bank and nothing else.

A fake Hindsight records every request that reaches it, so the tests also check that
refused requests never get through, not just that the gateway answered 403.
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler

from helpers import FILES, load, raw, request, serve

KEY_A, KEY_B = "key-alice-0123456789", "key-bob-9876543210"
A, B = "/v1/default/banks/hermes-alice", "/v1/default/banks/hermes-bob"


class FakeHindsight(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen: list = []
    lock = threading.Lock()

    def _any(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        with self.lock:
            FakeHindsight.seen.append({"method": self.command, "path": self.path,
                                       "auth": self.headers.get("Authorization"), "body": body})
        if "stream=1" in self.path:
            # No Content-Length: the gateway has to stream it through re-chunked.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"data: one\n\ndata: two\n\n")
            self.close_connection = True
            return
        out = json.dumps({"ok": True, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _any

    def log_message(self, *a):
        pass


class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = serve(FakeHindsight)
        mod = load(FILES / "hindsight-gateway.py", "hindsight_gateway", {
            "UPSTREAM": f"http://127.0.0.1:{cls.upstream.server_port}",
            "HERMIFY_KEY_0": KEY_A, "HERMIFY_BANK_0": "hermes-alice",
            "HERMIFY_KEY_1": KEY_B, "HERMIFY_BANK_1": "hermes-bob",
            "HERMIFY_BANK_2": "hermes-nokey",  # Secret without the key: locked out
        })
        mod.Handler.log_message = lambda *a: None
        cls.gw = serve(mod.Handler)
        cls.port = cls.gw.server_port

    @classmethod
    def tearDownClass(cls):
        cls.gw.shutdown(); cls.gw.server_close()
        cls.upstream.shutdown(); cls.upstream.server_close()

    def setUp(self):
        FakeHindsight.seen.clear()

    def call(self, method, path, key=KEY_A, body=None):
        h = {"Authorization": f"Bearer {key}"} if key else {}
        if body is not None:
            body = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        return request(self.port, method, path, h, body)[0]

    def assertForwarded(self, method, path, key=KEY_A, body=None):
        self.assertEqual(self.call(method, path, key, body), 200, f"{method} {path}")
        self.assertEqual(FakeHindsight.seen[-1]["path"], path)

    def assertRefused(self, method, path, key=KEY_A, want=403, body=None):
        before = len(FakeHindsight.seen)
        self.assertEqual(self.call(method, path, key, body), want, f"{method} {path}")
        self.assertEqual(FakeHindsight.seen[before:], [], f"{method} {path} reached Hindsight")

    # --- what a key may do

    def test_own_bank_works(self):
        self.assertForwarded("PUT", A, body={})
        self.assertForwarded("PATCH", A, body={})
        self.assertForwarded("POST", A + "/memories", body={"items": []})
        self.assertForwarded("POST", A + "/memories/recall", body={"query": "q"})
        self.assertForwarded("POST", A + "/reflect", body={"query": "q"})
        self.assertForwarded("GET", A + "/operations/abc")
        self.assertForwarded("GET", A + "/stats")
        self.assertForwarded("GET", A + "/config")
        self.assertForwarded("POST", A + "/import", body={})
        self.assertForwarded("GET", A + "/documents/doc%20one")
        self.assertForwarded("GET", A + "/memories/list?limit=5&q=x")

    def test_each_key_maps_to_its_own_bank(self):
        self.assertForwarded("GET", B + "/stats", key=KEY_B)
        self.assertRefused("GET", A + "/stats", key=KEY_B)

    def test_harmless_globals(self):
        self.assertForwarded("GET", "/version")
        self.assertForwarded("GET", "/v1/version")
        self.assertForwarded("GET", "/v1/bank-template-schema")
        self.assertEqual(self.call("GET", "/health", key=None), 200)  # probes, no key

    def test_authorization_is_not_forwarded(self):
        self.call("GET", A + "/stats")
        self.assertIsNone(FakeHindsight.seen[-1]["auth"])

    def test_body_and_query_pass_through(self):
        self.call("POST", A + "/memories/recall?budget=low", body={"query": "hello"})
        last = FakeHindsight.seen[-1]
        self.assertEqual(last["path"], A + "/memories/recall?budget=low")
        self.assertEqual(json.loads(last["body"]), {"query": "hello"})

    def test_chunked_request_body(self):
        body = b'{"query": "chunked"}'
        status = raw(self.port, f"POST {A}/memories/recall HTTP/1.1\r\nHost: h\r\n"
                                f"Authorization: Bearer {KEY_A}\r\nTransfer-Encoding: chunked\r\n"
                                f"Connection: close\r\n\r\n{len(body):x}\r\n{body.decode()}\r\n0\r\n\r\n")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(FakeHindsight.seen[-1]["body"]), {"query": "chunked"})

    # --- other banks, however it's spelled

    def test_other_bank_refused(self):
        for m, sub in [("GET", "/stats"), ("POST", "/memories/recall"), ("POST", "/memories"),
                       ("DELETE", ""), ("PUT", "")]:
            self.assertRefused(m, B + sub, body={} if m in ("POST", "PUT") else None)

    def test_path_tricks_refused(self):
        for path in [
            A + "/%2e%2e/hermes-bob/stats",
            A + "/%2E%2E/hermes-bob/stats",
            "/v1/default/banks/hermes-alice%2F..%2Fhermes-bob/stats",
            "/v1/default/banks/hermes-alice%2fx/stats",
            "/v1/default/banks//hermes-bob/stats",
            "/v1/default/banks/HERMES-BOB/stats",
            "/v1/default/banks/hermes-alice%20/stats",
            "/v1/other/banks/hermes-bob/stats",
            "/v1/default/banks/hermes-alice/memories/%2e%2e/%2e%2e/hermes-bob/stats",
            A + "/./stats",
            A + "//stats",
            A + "/",
        ]:
            self.assertRefused("GET", path)
        for line in [f"GET {A}/../hermes-bob/stats", f"GET http://127.0.0.1{B}/stats",
                     f"GET {A}\\..\\hermes-bob/stats", "GET /v1/default/banks/hermes-bob\t/stats",
                     f"GET {A}/stats/../../hermes-bob/stats"]:
            status = raw(self.port, f"{line} HTTP/1.1\r\nHost: h\r\nAuthorization: Bearer {KEY_A}\r\n"
                                    "Connection: close\r\n\r\n")
            self.assertIn(status, (400, 403), line)
        self.assertEqual(FakeHindsight.seen, [])

    # --- things that cross banks or leave the bank

    def test_cross_bank_and_global_endpoints_refused(self):
        for m, path in [
            ("GET", "/v1/default/banks"),
            ("POST", A + "/aliases"), ("GET", A + "/aliases"), ("PATCH", A + "/aliases/x"),
            ("POST", A + "/clone?target_bank_id=hermes-bob"),
            ("POST", A + "/transfer/export"), ("POST", A + "/transfer/import?target_bank_id=hermes-bob"),
            ("POST", A + "/document-transfer"), ("POST", A + "/document-transfer/export"),
            ("POST", A + "/webhooks"), ("GET", A + "/webhooks"),
            ("PATCH", A + "/config"), ("DELETE", A + "/config"),
            ("GET", A + "/something-new-in-a-future-hindsight"),
            ("GET", "/v1/default/chunks/abc"), ("GET", "/v1/default/files/download/abc"),
            ("GET", "/metrics"), ("GET", "/openapi.json"), ("GET", "/docs"),
            ("POST", "/mcp"), ("GET", "/mcp/"),
        ]:
            self.assertRefused(m, path, body={} if m in ("POST", "PATCH") else None)

    # --- keys

    def test_bad_keys(self):
        self.assertRefused("GET", A + "/stats", key=None, want=401)
        self.assertRefused("GET", A + "/stats", key="wrong", want=401)
        self.assertRefused("GET", A + "/stats", key="", want=401)
        self.assertRefused("GET", "/version", key=None, want=401)
        status = raw(self.port, f"GET {A}/stats HTTP/1.1\r\nHost: h\r\nAuthorization: Basic {KEY_A}\r\n"
                                "Connection: close\r\n\r\n")
        self.assertEqual(status, 401)
        self.assertEqual(FakeHindsight.seen, [])

    def test_bank_without_key_is_locked_out(self):
        # hermes-nokey has no key, so nothing opens it; the same holds for a key that's
        # blank in the environment.
        self.assertRefused("GET", "/v1/default/banks/hermes-nokey/stats", key="", want=401)

    # --- responses

    def test_streamed_response_passes_through(self):
        # Upstream answers without Content-Length (like server-sent events): the gateway
        # re-chunks it, and the client gets every event.
        status, data, resp = request(self.port, "POST", A + "/reflect?stream=1",
                                     {"Authorization": f"Bearer {KEY_A}"}, b"{}")
        self.assertEqual(status, 200)
        self.assertEqual(data, b"data: one\n\ndata: two\n\n")
        self.assertEqual(resp.getheader("Transfer-Encoding"), "chunked")

    def test_keep_alive_serves_several_requests(self):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        for _ in range(3):
            c.request("GET", A + "/stats", headers={"Authorization": f"Bearer {KEY_A}"})
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 200)
        c.close()

    def test_upstream_down_is_a_502(self):
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
        s.close()  # nothing listens there now
        mod = load(FILES / "hindsight-gateway.py", "hindsight_gateway_down", {
            "UPSTREAM": f"http://127.0.0.1:{dead}", "GATEWAY_UPSTREAM_TIMEOUT": "3",
            "HERMIFY_KEY_0": KEY_A, "HERMIFY_BANK_0": "hermes-alice"})
        mod.Handler.log_message = lambda *a: None
        gw = serve(mod.Handler)
        try:
            status, _, _ = request(gw.server_port, "GET", A + "/stats", {"Authorization": f"Bearer {KEY_A}"})
            self.assertEqual(status, 502)
        finally:
            gw.shutdown(); gw.server_close()


if __name__ == "__main__":
    unittest.main()
