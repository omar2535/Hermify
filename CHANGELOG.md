# Changelog

Each release's section here is also its GitHub Release notes. Upgrade steps are under **Upgrading** when a release needs any.

## [0.8.0] - 2026-11-15

- `networkPolicies.boxExtraFrom`: extra peers allowed to reach the SSH boxes on port 22, next to `ingressFrom`. For a tunnel connector in another namespace (a Cloudflare Tunnel, say), which reaches `ssh://<box-service>.<namespace>.svc.cluster.local:22` directly instead of through the ingress controller's per-box ports. Off by default, so the boxes stay reachable only from `ingressFrom`.

## [Unreleased]

## [0.7.0] - 2026-11-15

- `networkPolicies.egress`: limit what agents and their boxes can reach to cluster DNS, the Hindsight gateway and the public internet (everything outside `privateRanges`), plus `extraRules` for every agent and `tenants[].egress` for one. Without it, an agent reaches your LAN, the Kubernetes API, the kubelet and other namespaces' admin UIs. Off by default.
- Agent pods no longer mount a service account token, and run under the runtime's default seccomp profile.

## [0.6.0] - 2026-11-13

The Hindsight gateway is its own project now, [hindsight-gateway](https://github.com/omar2535/hindsight-gateway), with an admin UI for the keys.

- The gateway runs as its own Deployment (`hindsight-gateway`, image `ghcr.io/omar2535/hindsight-gateway`) with a small volume for its key database, instead of a sidecar in the Hindsight pod. Only the gateway may reach Hindsight's API.
- Its admin UI manages the keys: create, rename, move to another bank, disable, rotate, delete, and see when each was last used. The password is in `hindsight-gateway-secrets` (or your `hindsight.gateway.existingSecret`).
- `hindsight.gateway.ingress` is now one hostname for both: the API under `/api` and the admin UI under `/ui` (`apiPath`, `uiPath`).
- Each agent's `HINDSIGHT_API_KEY`, and `hindsight.gateway.extraKeys`, are imported as seed keys when the gateway starts. Changing keys no longer restarts Hindsight.
- Agents reach Hindsight at `hindsight-gateway:8888` instead of `hindsight:8888`.
- Removed: `hindsight.gateway.port` and `hindsight.gateway.resources` from the old sidecar (`hindsight.gateway.resources` now sizes the gateway pod).

### Upgrading

- Nothing to migrate: the agents' existing keys (and `extraKeys`) are imported on the gateway's first start, so every key keeps working.
- If you used `hindsight.gateway.ingress` (0.4.0+), agents outside the cluster now use `https://<host>/api` instead of `https://<host>`.
- Hindsight restarts once (the sidecar goes away), every agent restarts once (new Hindsight URL), and the gateway starts in its own pod. Memory is unavailable for about a minute.
- The gateway image must be pullable from your cluster: it's public on ghcr.io, or set `hindsight.gateway.imagePullSecrets` for a private mirror.

## [0.5.0] - 2026-11-13

- `hindsight.gateway.extraKeys`: more keys for the bank gateway, each opening one existing bank. Give an agent outside the cluster its own key to someone's memory, so it can be revoked without touching the cluster agent. The chart creates the Secret with a random key, or uses yours.
- The gateway log names the key behind each refused request.

### Upgrading

- Hindsight restarts once (about a minute without memory).

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

[Unreleased]: https://github.com/omar2535/Hermify/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/omar2535/Hermify/releases/tag/v0.8.0
[0.7.0]: https://github.com/omar2535/Hermify/releases/tag/v0.7.0
[0.6.0]: https://github.com/omar2535/Hermify/releases/tag/v0.6.0
[0.5.0]: https://github.com/omar2535/Hermify/releases/tag/v0.5.0
[0.4.0]: https://github.com/omar2535/Hermify/releases/tag/v0.4.0
[0.3.0]: https://github.com/omar2535/Hermify/releases/tag/v0.3.0
[0.2.0]: https://github.com/omar2535/Hermify/releases/tag/v0.2.0
[0.1.2]: https://github.com/omar2535/Hermify/releases/tag/v0.1.2
[0.1.1]: https://github.com/omar2535/Hermify/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/omar2535/Hermify/tree/v0.1.0
