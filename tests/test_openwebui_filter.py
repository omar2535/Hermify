"""The Open WebUI filter: which paths it picks up, how it rewrites replies, and that it
only touches Hermify agents. Network and storage are faked; Open WebUI isn't needed.
"""

import asyncio
import importlib.util
import sys
import types
import unittest

from helpers import ROOT


def _stub_modules():
    # Open WebUI's environment has pydantic and aiohttp; CI may not. Minimal stand-ins.
    if "pydantic" not in sys.modules:
        try:
            import pydantic  # noqa: F401
        except ImportError:
            pd = types.ModuleType("pydantic")

            class _Field:
                def __init__(self, default=None, description=""):
                    self.default = default

            class BaseModel:
                def __init__(self, **kw):
                    for k, v in vars(type(self)).items():
                        if isinstance(v, _Field):
                            setattr(self, k, kw.get(k, v.default))

            pd.BaseModel = BaseModel
            pd.Field = lambda default=None, description="": _Field(default, description)
            sys.modules["pydantic"] = pd
    if "aiohttp" not in sys.modules:
        try:
            import aiohttp  # noqa: F401
        except ImportError:
            sys.modules["aiohttp"] = types.ModuleType("aiohttp")


_stub_modules()
spec = importlib.util.spec_from_file_location("hermify_files", ROOT / "openwebui" / "hermify_files.py")
hf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hf)


class _Session:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


hf.aiohttp.ClientSession = _Session
hf.aiohttp.ClientTimeout = lambda **k: None

AGENT = ("http://hermes-alice.ns.svc.cluster.local:8642/v1", "key")


def make_filter(conn=AGENT):
    f = hf.Filter()
    fetched = []

    async def agent_connection(model, request):
        return conn

    async def fetch(session, base, key, path):
        fetched.append(path)
        if path.endswith("missing.csv"):
            raise ValueError("not found in the agent's outbox")
        return b"x", "text/csv"

    async def store(request, uid, name, data, ctype):
        return f"id-{name}"

    f._agent_connection, f._fetch, f._store = agent_connection, fetch, store
    return f, fetched


def outlet(f, text, output=None):
    msg = {"id": "a1", "role": "assistant", "content": text}
    if output is not None:
        msg["output"] = output
    body = {"id": "a1", "messages": [{"id": "u1", "role": "user", "content": "hi"}, msg]}
    out = asyncio.run(f.outlet(body, __user__={"id": "u"}, __model__={}, __request__=object()))
    return out["messages"][1]


class FilterTest(unittest.TestCase):
    def test_media_line_becomes_link(self):
        f, fetched = make_filter()
        m = outlet(f, "Done!\nMEDIA:/opt/data/outbox/report.xlsx")
        self.assertEqual(m["content"], "Done!\n📎 [report.xlsx](/api/v1/files/id-report.xlsx/content)")
        self.assertEqual(fetched, ["/opt/data/outbox/report.xlsx"])

    def test_bare_path_backticks_spaces_and_punctuation(self):
        f, _ = make_filter()
        m = outlet(f, "Saved to /opt/data/outbox/a.csv. Also `/opt/data/outbox/my file.txt`!")
        self.assertEqual(m["content"], "Saved to 📎 [a.csv](/api/v1/files/id-a.csv/content). "
                                       "Also 📎 [my file.txt](/api/v1/files/id-my file.txt/content)!")

    def test_markdown_link_keeps_its_text(self):
        f, _ = make_filter()
        m = outlet(f, "Here's [the sheet](/opt/data/outbox/a.csv).")
        self.assertEqual(m["content"], "Here's [the sheet](/api/v1/files/id-a.csv/content).")

    def test_missing_file_is_reported_not_hidden(self):
        f, _ = make_filter()
        m = outlet(f, "See /opt/data/outbox/missing.csv.")
        self.assertEqual(m["content"],
                         "See /opt/data/outbox/missing.csv (couldn't attach: not found in the agent's outbox).")

    def test_paths_outside_the_outbox_are_left_alone(self):
        f, fetched = make_filter()
        text = "Not these: /opt/data/.env, /opt/data/outbox_evil/x, /tmp/outbox/x, MEDIA:/etc/passwd"
        self.assertEqual(outlet(f, text)["content"], text)
        self.assertEqual(fetched, [])

    def test_same_file_fetched_once_and_max_files(self):
        f, fetched = make_filter()
        f.valves.max_files = 2
        outlet(f, " ".join(f"/opt/data/outbox/{n}.csv" for n in "aabcd"))
        self.assertEqual(fetched, ["/opt/data/outbox/a.csv", "/opt/data/outbox/b.csv"])

    def test_structured_output_is_rewritten_too(self):
        f, _ = make_filter()
        text = "MEDIA:/opt/data/outbox/a.csv"
        m = outlet(f, text, output=[{"type": "message", "content": [{"type": "output_text", "text": text}]}])
        self.assertEqual(m["output"][0]["content"][0]["text"], m["content"])

    def test_non_agent_models_untouched(self):
        f, fetched = make_filter(conn=None)
        text = "MEDIA:/opt/data/outbox/a.csv"
        self.assertEqual(outlet(f, text)["content"], text)
        self.assertEqual(fetched, [])
        body = {"messages": [{"role": "user", "content": "hi"}]}
        self.assertEqual(asyncio.run(f.inlet(body)), {"messages": [{"role": "user", "content": "hi"}]})

    def test_inlet_note_added_once(self):
        f, _ = make_filter()
        body = {"messages": [{"role": "system", "content": "Be nice."}, {"role": "user", "content": "hi"}]}
        body = asyncio.run(f.inlet(body))
        body = asyncio.run(f.inlet(body))
        self.assertEqual(body["messages"][0]["content"].count("File delivery"), 1)
        self.assertTrue(body["messages"][0]["content"].startswith("Be nice."))

    def test_agent_host_pattern(self):
        f = hf.Filter()
        pattern = f.valves.agent_host_pattern
        import re
        self.assertTrue(re.search(pattern, "hermes-alice.ns.svc.cluster.local"))
        self.assertTrue(re.search(pattern, "hermes-alice"))
        for host in ("litellm.example.com", "my-hermes-alice", "api.openai.com"):
            self.assertFalse(re.search(pattern, host), host)


if __name__ == "__main__":
    unittest.main()
