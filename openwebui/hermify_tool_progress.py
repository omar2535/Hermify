"""
title: Hermify tool progress
author: Hermify
description: Shows a Hermes agent's tool calls (web pages read, memory recalls, commands...) as status lines above its reply while it works, like Telegram's tool progress.
version: 0.1.0
license: MIT
requirements:
"""

# Install: Admin Panel -> Functions -> New Function, paste this file, save, then switch it
# on and make it Global.
#
# How it works: Hermes streams each tool call to Open WebUI as an extra SSE frame
# (`event: hermes.tool.progress`, data {"tool", "emoji", "label", "toolCallId", "status"}).
# Open WebUI ignores the event name and drops the frame because it has no `choices`, but
# stream filters see it first. This one turns each "running" frame into a status line, and
# when the reply finishes adds "Used N tools", so the last line stops shimmering and the
# list stays in the chat (click the status line to expand it).
#
# Tested with Open WebUI v0.13.3 and Hermes' API server.

from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, Field

# Replies with tools in flight; bounds the per-reply counters if a stream never finishes.
MAX_TRACKED = 256


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="Filter order (lower runs first).")
        max_label: int = Field(default=120, description="Longest status line, in characters.")

    def __init__(self):
        self.valves = self.Valves()
        # message id -> tool calls started in that reply. One Filter serves every chat.
        self._counts: dict[str, int] = {}

    def _line(self, event: dict) -> str:
        tool = event["tool"]
        label = str(event.get("label") or "").strip()
        text = tool if not label or label == tool else f"{tool}: {label}"
        if len(text) > self.valves.max_label:
            text = text[: self.valves.max_label - 1] + "…"
        emoji = event.get("emoji")
        return f"{emoji} {text}" if emoji else text

    async def stream(
        self,
        event: dict,
        __event_emitter__: Optional[Callable[[dict], Awaitable[Any]]] = None,
        __message_id__: Optional[str] = None,
    ) -> dict:
        if not __event_emitter__ or not __message_id__ or not isinstance(event, dict):
            return event

        if "toolCallId" in event and "tool" in event and "choices" not in event:
            if event.get("status") == "running":
                if __message_id__ not in self._counts and len(self._counts) >= MAX_TRACKED:
                    self._counts.pop(next(iter(self._counts)))
                self._counts[__message_id__] = self._counts.get(__message_id__, 0) + 1
                await __event_emitter__(
                    {"type": "status", "data": {"description": self._line(event), "done": False}}
                )
            return event

        choices = event.get("choices") or []
        if choices and choices[0].get("finish_reason") and __message_id__ in self._counts:
            n = self._counts.pop(__message_id__)
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": f"Used {n} tool{'s' if n != 1 else ''}", "done": True},
                }
            )
        return event
