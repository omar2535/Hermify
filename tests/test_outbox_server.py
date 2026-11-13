"""The outbox server must serve files under the outbox, with the key, and nothing else."""

import os
import tempfile
import unittest
from pathlib import Path

from helpers import FILES, load, raw, request, serve

KEY = "agent-api-server-key"


class OutboxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        outbox = root / "outbox"
        (outbox / "sub").mkdir(parents=True)
        (outbox / "names.csv").write_text("name\nAda\n")
        (outbox / "sub" / "my file.txt").write_text("x")
        (outbox / "big.bin").write_bytes(b"0" * 2048)
        (root / "secret.env").write_text("SECRET=1")
        (outbox / "evil.txt").symlink_to(root / "secret.env")
        (outbox / "evil-dir").symlink_to(root)
        (root / "outbox-sibling").mkdir()
        (root / "outbox-sibling" / "x.txt").write_text("sibling")
        mod = load(FILES / "outbox-server.py", "outbox_server", {
            "OUTBOX_DIR": str(outbox), "API_SERVER_KEY": KEY, "OUTBOX_MAX_BYTES": "1024"})
        mod.Handler.log_message = lambda *a: None
        cls.srv = serve(mod.Handler)
        cls.port = cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()
        cls.tmp.cleanup()

    def get(self, path, key=KEY):
        h = {"Authorization": f"Bearer {key}"} if key is not None else {}
        status, data, resp = request(self.port, "GET", path, h)
        return status, data, resp

    def test_serves_outbox_files(self):
        status, data, resp = self.get("/files/names.csv")
        self.assertEqual((status, data), (200, b"name\nAda\n"))
        self.assertEqual(resp.getheader("Content-Type"), "text/csv")
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(self.get("/files/sub/my%20file.txt")[:2], (200, b"x"))

    def test_health_needs_no_key(self):
        self.assertEqual(self.get("/healthz", key=None)[0], 200)

    def test_keys(self):
        self.assertEqual(self.get("/files/names.csv", key=None)[0], 401)
        self.assertEqual(self.get("/files/names.csv", key="wrong")[0], 401)
        self.assertEqual(self.get("/files/names.csv", key="")[0], 401)

    def test_nothing_outside_the_outbox(self):
        for path in ["/files/../secret.env", "/files/%2e%2e/secret.env", "/files/..%2fsecret.env",
                     "/files/sub/../../secret.env", "/files/evil.txt", "/files/evil-dir/secret.env",
                     "/files/../outbox-sibling/x.txt", "/files/%2e%2e/outbox-sibling/x.txt",
                     "/files//etc/passwd", "/files/%2fetc%2fpasswd", "/secret.env", "/"]:
            self.assertEqual(self.get(path)[0], 404, path)
        status = raw(self.port, f"GET /files/../secret.env HTTP/1.1\r\nHost: h\r\n"
                                f"Authorization: Bearer {KEY}\r\nConnection: close\r\n\r\n")
        self.assertEqual(status, 404)

    def test_directories_and_missing(self):
        self.assertEqual(self.get("/files/sub")[0], 404)
        self.assertEqual(self.get("/files/")[0], 404)
        self.assertEqual(self.get("/files/nope.csv")[0], 404)

    def test_size_limit(self):
        self.assertEqual(self.get("/files/big.bin")[0], 413)

    def test_read_only(self):
        for method in ("POST", "PUT", "DELETE"):
            status, _, _ = request(self.port, method, "/files/names.csv",
                                   {"Authorization": f"Bearer {KEY}"}, b"x")
            self.assertNotEqual(status, 200, method)


if __name__ == "__main__":
    unittest.main()
