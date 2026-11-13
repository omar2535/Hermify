# Changelog

Each release's section here is also its GitHub Release notes. Upgrade steps are under **Upgrading** when a release needs any.

## [Unreleased]

## [0.4.0] - 2026-11-13

- `hindsight.gateway.ingress`: a hostname for the bank gateway, so agents outside the cluster (Hermes on your laptop, say) can use Hindsight. Only the gateway is exposed, never Hindsight's API, so every request still needs a key and opens one bank. Off by default.
- Tests for the Hindsight gateway, the outbox server and the Open WebUI filter, run in CI on every PR.
- `SECURITY.md` and this changelog.

## [0.3.0] - 2026-11-12

Memory banks are private now.

- Hindsight's API has no per-bank auth, so until now any agent could read any other person's bank. A small gateway now runs as a sidecar in the Hindsight pod (`hindsight.gateway`, on by default). Each agent sends its own `HINDSIGHT_API_KEY` and can only use its own bank. Other banks, the bank list, aliases, clones, transfers between banks, webhooks, global chunk and file lookups and bank config changes are refused, and agents can no longer reach Hindsight's API directly.
- The Hindsight UI still sees every bank.
- `tenants[].bankId` is checked: letters, digits, `.`, `_` and `-` only.

### Upgrading

- If you use `tenants[].existingSecret`, add `HINDSIGHT_API_KEY` (any random string, e.g. `openssl rand -hex 32`) to each of those Secrets **before** upgrading. A Secret without it doesn't break anything else, but that person's agent can't use memory until you add it. Secrets the chart creates get one automatically.
- Hindsight restarts once (about a minute without memory), and every agent restarts once to pick up its key.
- Adding a person later restarts Hindsight once, so the gateway picks up their key.

## [0.2.0] - 2026-11-12

Agents can send files into Open WebUI chats.

- A small read-only file server in each agent pod (`agent.outbox`, on by default) serves `/opt/data/outbox`, only to Open WebUI, only with that agent's `API_SERVER_KEY`.
- A new Open WebUI filter, [`openwebui/hermify_files.py`](openwebui/hermify_files.py), turns paths in that folder into download links owned by the person chatting.

### Upgrading

- Install the filter in Open WebUI: Admin Panel → Functions → New Function, paste the file, then switch it on and make it Global. Without it, nothing changes.
- Every agent restarts once.

## [0.1.2] - 2026-11-11

- GitHub Actions: CI (lint, render and schema-check every values file, must-fail cases, shellcheck) and a Release workflow that publishes the chart to `oci://ghcr.io/omar2535/charts/hermify`.
- Fixed: a box enabled without `authorizedKeys` crashed the template instead of showing the chart's own error.

## [0.1.1] - 2026-11-11

- Pod templates no longer carry the chart version, so a chart release alone doesn't restart pods.
- Docs and license cleanup for publishing.

## [0.1.0] - 2026-11-11

First release: one Hermes Agent per person, shared Hindsight memory with a bank each, Open WebUI with every agent as a model, optional SSH boxes, and NetworkPolicies.

[Unreleased]: https://github.com/omar2535/Hermify/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/omar2535/Hermify/releases/tag/v0.4.0
[0.3.0]: https://github.com/omar2535/Hermify/releases/tag/v0.3.0
[0.2.0]: https://github.com/omar2535/Hermify/releases/tag/v0.2.0
[0.1.2]: https://github.com/omar2535/Hermify/releases/tag/v0.1.2
[0.1.1]: https://github.com/omar2535/Hermify/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/omar2535/Hermify/tree/v0.1.0
