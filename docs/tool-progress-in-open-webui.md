# Tool progress in Open WebUI

On Telegram the gateway shows each tool an agent runs. Open WebUI shows nothing until the reply's first words arrive, so a turn that reads a few web pages and searches memory looks stuck for a minute.

The agents do stream their tool calls: each one is an extra frame on the chat stream (`event: hermes.tool.progress`). Open WebUI drops those frames, because they aren't chat chunks. The filter [`openwebui/hermify_tool_progress.py`](../openwebui/hermify_tool_progress.py) catches them first and turns each tool call into a status line above the reply (`📄 web_extract: https://example.com`), then adds "Used N tools" when the reply ends. Click the status line to see the whole list; it stays in the chat.

To install it:

1. Admin Panel → Functions → New Function.
2. Paste the file and save.
3. Switch it on and make it Global.

The line shows the tool that started last, so it keeps shimmering while the model thinks after that tool finishes. Memory recalls the agent makes on its own before each turn aren't tool calls and don't show up. Tested with Open WebUI v0.13.3.
