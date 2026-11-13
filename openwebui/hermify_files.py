"""
title: Hermify files
author: Hermify
description: Lets Hermes agents send files (Excel, PDF, anything) into Open WebUI chats. The agent saves the file in its outbox; this filter fetches it from the agent's outbox server, stores it in Open WebUI for the person chatting, and swaps the path for a download link.
version: 0.1.0
license: MIT
requirements:
"""

# Install: Admin Panel -> Functions -> New Function, paste this file, save, then switch it
# on and make it Global (it only acts on Hermify agents, see `agent_host_pattern`).
#
# How it works:
# - inlet: for chats with a Hermify agent, adds a short system note telling the agent to
#   save files for the user under /opt/data/outbox/ and to mention that path in its reply.
# - outlet: finds /opt/data/outbox/... paths (with or without a MEDIA: prefix) in the
#   finished reply, downloads each from the agent pod's outbox server (port 8643) with
#   the same key Open WebUI already uses for that agent, uploads it to Open WebUI as the
#   person chatting (so only they, and admins, can open it), and replaces the path with a
#   link to /api/v1/files/<id>/content.
#
# Tested with Open WebUI v0.13.3.

import io
import logging
import os
import re
import urllib.parse
from typing import Any, Optional

import aiohttp
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

NOTE = (
    "File delivery in this chat: to give the user a file of any type (spreadsheet, document, "
    "image, archive...), save it under {outbox}/ and put the full path, for example "
    "MEDIA:{outbox}/report.xlsx, on its own line in your reply. The chat turns that line into "
    "a download link. Use simple file names without spaces. Only files under {outbox}/ can be "
    "delivered."
)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="Filter order (lower runs first).")
        agent_host_pattern: str = Field(
            default=r"^hermes-[a-z0-9-]+(\.|$)",
            description="Only connections whose host matches this regex are treated as Hermify agents.",
        )
        outbox_port: int = Field(default=8643, description="Port of the agent pod's outbox server.")
        outbox_dir: str = Field(default="/opt/data/outbox", description="The outbox path inside the agent pod.")
        max_bytes: int = Field(default=100 * 1024 * 1024, description="Skip files larger than this.")
        max_files: int = Field(default=10, description="Most files attached per reply.")
        add_instructions: bool = Field(default=True, description="Tell the agent how to deliver files (inlet).")

    def __init__(self):
        self.valves = self.Valves()

    # -- helpers ---------------------------------------------------------------------

    async def _agent_connection(self, model: Optional[dict], request) -> Optional[tuple[str, str]]:
        """(base_url, key) of the Hermify agent behind this model, or None."""
        if not model:
            return None
        if "urlIdx" not in model:
            # A workspace model built on top of an agent model.
            base_id = ((model.get("info") or {}).get("base_model_id")) or ""
            models = getattr(request.app.state, "MODELS", {}) if request else {}
            model = models.get(base_id) if base_id else None
            if not model or "urlIdx" not in model:
                return None
        try:
            from open_webui.routers.openai import get_openai_connection

            url, key, _ = await get_openai_connection(model["urlIdx"])
        except Exception:
            log.debug("hermify files: no OpenAI connection for model", exc_info=True)
            return None
        host = urllib.parse.urlsplit(url).hostname or ""
        if not re.search(self.valves.agent_host_pattern, host):
            return None
        return url, key

    def _path_re(self) -> re.Pattern:
        # Either a path in backticks (may contain spaces), or a bare path, optionally the
        # target of a markdown link. Both may carry a MEDIA: prefix. Trailing punctuation is
        # split off in _split.
        outbox = re.escape(self.valves.outbox_dir.rstrip("/"))
        return re.compile(
            rf"`(?:MEDIA:\s*)?(?P<tpath>{outbox}/[^`\n]+)`"
            rf"|(?P<md>\]\()?(?:MEDIA:\s*)?(?P<path>{outbox}/[^\s`'\"<>()\[\]{{}}|*]+)"
        )

    @staticmethod
    def _raw(m: re.Match) -> str:
        return m.group("tpath") or m.group("path")

    @staticmethod
    def _split(path: str) -> tuple[str, str]:
        """('/x/report.xlsx', '.') for '/x/report.xlsx.' : the path and trailing punctuation."""
        clean = path.rstrip(".,;:!?")
        return clean, path[len(clean):]

    async def _fetch(self, session, base_url: str, key: str, path: str) -> tuple[bytes, str]:
        rel = path[len(self.valves.outbox_dir.rstrip("/")) + 1 :]
        parts = urllib.parse.urlsplit(base_url)
        url = f"{parts.scheme}://{parts.hostname}:{self.valves.outbox_port}/files/{urllib.parse.quote(rel)}"
        async with session.get(url, headers={"Authorization": f"Bearer {key}"}) as resp:
            if resp.status == 404:
                raise ValueError("not found in the agent's outbox")
            if resp.status == 413:
                raise ValueError("too large")
            if resp.status != 200:
                raise ValueError(f"outbox server answered {resp.status}")
            size = int(resp.headers.get("Content-Length") or 0)
            if size > self.valves.max_bytes:
                raise ValueError("too large")
            buf = io.BytesIO()
            async for chunk in resp.content.iter_chunked(1 << 16):
                buf.write(chunk)
                if buf.tell() > self.valves.max_bytes:
                    raise ValueError("too large")
            ctype = (resp.headers.get("Content-Type") or "application/octet-stream").split(";")[0]
            return buf.getvalue(), ctype

    async def _store(self, request, user_id: str, name: str, data: bytes, ctype: str) -> str:
        from fastapi import UploadFile
        from starlette.datastructures import Headers

        from open_webui.models.users import Users
        from open_webui.routers.files import upload_file_handler

        user = await Users.get_user_by_id(user_id)
        if not user:
            raise ValueError("user not found")
        upload = UploadFile(
            file=io.BytesIO(data),
            filename=name,
            size=len(data),
            headers=Headers({"content-type": ctype}),
        )
        result = await upload_file_handler(
            request,
            file=upload,
            metadata={"source": "hermify-outbox"},
            process=False,
            process_in_background=False,
            user=user,
        )
        file_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
        if not file_id:
            raise ValueError("upload failed")
        return file_id

    @staticmethod
    def _replace_strings(value: Any, repl) -> Any:
        if isinstance(value, str):
            return repl(value)
        if isinstance(value, list):
            return [Filter._replace_strings(v, repl) for v in value]
        if isinstance(value, dict):
            return {k: Filter._replace_strings(v, repl) for k, v in value.items()}
        return value

    # -- filter hooks ----------------------------------------------------------------

    async def inlet(self, body: dict, __model__: Optional[dict] = None, __request__=None) -> dict:
        if not self.valves.add_instructions:
            return body
        if not await self._agent_connection(__model__, __request__):
            return body
        note = NOTE.format(outbox=self.valves.outbox_dir.rstrip("/"))
        messages = body.get("messages") or []
        if messages and messages[0].get("role") == "system" and isinstance(messages[0].get("content"), str):
            if note not in messages[0]["content"]:
                messages[0]["content"] = messages[0]["content"].rstrip() + "\n\n" + note
        else:
            messages.insert(0, {"role": "system", "content": note})
        body["messages"] = messages
        return body

    async def outlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __model__: Optional[dict] = None,
        __request__=None,
    ) -> dict:
        messages = body.get("messages") or []
        target = next((m for m in messages if body.get("id") and m.get("id") == body["id"]), None)
        if target is None:
            target = next((m for m in reversed(messages) if m.get("role") == "assistant"), None)
        if not target or target.get("role") != "assistant" or not __user__ or __request__ is None:
            return body

        pattern = self._path_re()
        text = target.get("content") or ""
        found = []
        for m in pattern.finditer(text):
            p, _ = self._split(self._raw(m))
            if p not in found:
                found.append(p)
        if not found:
            return body

        conn = await self._agent_connection(__model__, __request__)
        if not conn:
            return body
        base_url, key = conn

        urls: dict[str, str] = {}
        errors: dict[str, str] = {}
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            for path in found[: self.valves.max_files]:
                try:
                    data, ctype = await self._fetch(session, base_url, key, path)
                    file_id = await self._store(__request__, __user__["id"], os.path.basename(path), data, ctype)
                    urls[path] = f"/api/v1/files/{file_id}/content"
                except Exception as e:
                    log.warning("hermify files: %s: %s", path, e)
                    errors[path] = str(e)

        def one(m: re.Match) -> str:
            path, trail = self._split(self._raw(m))
            if path in urls:
                if m.group("md"):
                    # Already a markdown link: [text](/opt/data/outbox/x) -> [text](url)
                    return "](" + urls[path] + trail
                return f"📎 [{os.path.basename(path)}]({urls[path]}){trail}"
            if path in errors:
                note = f" (couldn't attach: {errors[path]})"
                if m.group("tpath"):
                    return m.group(0) + note
                lead = m.group(0)[: m.start("path") - m.start(0)]
                return f"{lead}{path}{note}{trail}"
            return m.group(0)

        def repl(s: str) -> str:
            return pattern.sub(one, s)

        target["content"] = repl(text)
        if target.get("output"):
            target["output"] = self._replace_strings(target["output"], repl)
        return body
