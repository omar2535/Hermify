# Files in Open WebUI

Open WebUI talks to the agents over their chat API, which is text only. Ask an agent for a spreadsheet there and you'd get back a path to a file you can't reach. The fix has two halves.

## The outbox

Each agent pod runs a tiny read-only file server (`agent.outbox`, on by default) that serves `/opt/data/outbox` and nothing else, only to Open WebUI, and only with that agent's `API_SERVER_KEY`. Symlinks pointing outside the folder are refused. In a box, the same folder is `~/agent/outbox`.

## The filter

The other half is an Open WebUI filter, [`openwebui/hermify_files.py`](../openwebui/hermify_files.py). To install it:

1. Admin Panel → Functions → New Function.
2. Paste the file and save.
3. Switch it on and make it Global.

It only touches chats with Hermify agents (connections whose host starts with `hermes-`). Before a message goes out, it adds a short note telling the agent to save files in its outbox and mention the path. When the reply comes back, it pulls each file over, stores it in Open WebUI as the person who's chatting (only they and admins can open it), and swaps the path for a download link.

To update it later, paste the new version over the old one in the same place.

Telegram doesn't need any of this; the gateway already sends files there.
