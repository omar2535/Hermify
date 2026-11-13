<p align="center">
  <img src="assets/icon.svg" alt="" width="120">
</p>

<h1 align="center">Hermify</h1>

A Helm chart for running [Hermes Agent](https://github.com/NousResearch/hermes-agent) for a few people on one Kubernetes cluster. I built it so everyone in my family could have their own agent without me running a separate box for each of them.

Each person gets their own agent pod, volume, Telegram bot and LLM key. Long-term memory goes through one shared [Hindsight](https://github.com/vectorize-io/hindsight) instance, with a bank per person. [Open WebUI](https://github.com/open-webui/open-webui) is the web frontend, and each agent shows up there as a model. If someone wants a shell, they can get an SSH "box" next to their agent with the `hermes` CLI, so `hermes setup` and friends work like on a normal install. NetworkPolicies keep everything except Open WebUI away from the agents, and everything except the agents away from Hindsight's API.

## What you need

- Kubernetes 1.29+ and Helm 3.
- An OpenAI-compatible LLM endpoint the cluster can reach: [LiteLLM](https://github.com/BerriAI/litellm), vLLM, Ollama's `/v1`, OpenRouter, whatever. Agents call tools constantly, so pick a model that's decent at tool calling. I use LiteLLM so everyone gets their own key and budget.
- A StorageClass that does ReadWriteOnce.
- A CNI that enforces NetworkPolicy (k3s's default one does). Without it, Hindsight's API, which has no auth, is open to the whole cluster.
- An ingress controller if you want the web UIs on a hostname. `kubectl port-forward` works too.
- Memory: plan on 300–600Mi per agent, about 1.5Gi for Hindsight (it spikes) and 1Gi for Open WebUI.

One thing that will bite you if you're not on k3s's bundled Traefik: the chart denies all ingress to its namespace and then lets your ingress controller's pods back in. The default selector matches k3s's Traefik. With anything else Open WebUI just times out until you set `networkPolicies.ingressFrom`. For ingress-nginx it looks like this:

```yaml
networkPolicies:
  ingressFrom:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
      podSelector:
        matchLabels:
          app.kubernetes.io/name: ingress-nginx
```

## Install

Copy [`examples/values-family.yaml`](examples/values-family.yaml), fill in your people, LLM endpoint and hostnames, then:

```sh
helm install hermify oci://ghcr.io/omar2535/charts/hermify --version 0.2.0 \
  -n hermify --create-namespace -f my-values.yaml
```

or from a clone of this repo:

```sh
helm install hermify ./charts/hermify -n hermify --create-namespace -f my-values.yaml
```

`helm show values oci://ghcr.io/omar2535/charts/hermify` prints every option, and releases are on the [Releases page](https://github.com/omar2535/Hermify/releases).

After it's up:

1. Open WebUI: the first account you create is the admin. Add everyone under Admin Panel → Users, then under Settings → Models make each `hermes-<name>` model visible to its owner only.
2. Install the files filter (see [Files in Open WebUI](#files-in-open-webui)) if you want agents to be able to hand back spreadsheets, PDFs and so on.
3. Set Admin Panel → Settings → Interface → Task Model to a plain LLM, not an agent. Otherwise every chat title and tag suggestion kicks off a full agent run.
4. Run `hermes setup` for each agent (Telegram, persona, etc.), either from their box or with `kubectl -n hermify exec -it deploy/hermes-<name> -c hermes -- hermes setup`, then restart the agent.

Use one release per namespace. Object names are fixed (`hermes-<name>`, `hindsight`, `open-webui`), so two releases in the same namespace would step on each other.

## Configuration

Everything is documented in [`values.yaml`](charts/hermify/values.yaml). The parts you'll actually touch:

| Key | What it's for |
|---|---|
| `tenants[]` | The people. `name` is used for the agent (`hermes-<name>`), the Hindsight bank, the Open WebUI model and the box login. |
| `tenants[].existingSecret` | A Secret with `API_SERVER_KEY` and the LLM key. Leave empty and the chart makes one. |
| `tenants[].replicas` | Set to `0` to stop someone's agent without losing their data. |
| `tenants[].box` | The SSH box: `enabled`, `authorizedKeys`, `service.type`, `traefikEntryPoint`. |
| `llm.baseUrl`, `llm.model` | Your endpoint and default model. |
| `llm.apiKeyEnv` | Name of the env var / Secret key holding the LLM key (`LLM_API_KEY` by default). |
| `storageClassName` | For every volume. Empty means the cluster default. |
| `agent.config` | The `config.yaml` each agent starts with. |
| `agent.outbox` | File delivery to Open WebUI. On by default. |
| `hindsight.*`, `openWebui.*` | Image, resources, persistence, ingress, and `enabled` if you don't want one. |
| `networkPolicies.ingressFrom` | Your ingress controller's pods (see above). |

### Secrets

If you don't set `existingSecret`, the chart creates `hermes-<name>-secrets`, `hindsight-secrets` and `open-webui-secrets` itself. Random keys are generated once and survive upgrades, and the Secrets are left behind on uninstall. The catch is that LLM keys then come from your values (`llm.apiKey`, `tenants[].llmApiKey`) and end up in Helm's release history. If your values live in Git, create the Secrets yourself (SOPS, Sealed Secrets, External Secrets) and point `existingSecret` at them:

| Secret | Keys |
|---|---|
| `tenants[].existingSecret` | `API_SERVER_KEY` (any random string), plus the key named by `llm.apiKeyEnv` |
| `hindsight.existingSecret` | `HINDSIGHT_API_LLM_API_KEY`, `HINDSIGHT_CP_ACCESS_KEY` (the UI login) |
| `openWebui.existingSecret` | `WEBUI_SECRET_KEY` |

Open WebUI reads each agent's `API_SERVER_KEY` straight out of that person's Secret, so you never have to copy keys around.

### SSH boxes

A box is a sidecar container in the person's agent pod, running the agent's own image. It mounts the agent's volume at `~/agent` and logs in as the person with the agent's UID, so both sides can edit the same files. Only the home directory, the SSH host key and the apt cache survive a restart; anything listed in `~/.box/apt-packages` gets reinstalled on start. `restart-agent` restarts just the agent container without dropping your SSH session.

Getting to a box from outside the cluster is up to you: a `LoadBalancer` Service (one IP per box), a `NodePort`, Tailscale or a tunnel in front, or a Traefik entrypoint per box. Raw TCP can't be routed by hostname, so with Traefik each box needs its own port; set `traefikEntryPoint` and the chart creates the `IngressRouteTCP`.

### Files in Open WebUI

Open WebUI talks to the agents over their chat API, which is text only. Ask an agent for a spreadsheet there and you'd get back a path to a file you can't reach. The fix has two halves.

Each agent pod runs a tiny read-only file server (`agent.outbox`) that serves `/opt/data/outbox` and nothing else, only to Open WebUI, and only with that agent's `API_SERVER_KEY`. Symlinks pointing outside the folder are refused.

The other half is an Open WebUI filter, [`openwebui/hermify_files.py`](openwebui/hermify_files.py). Add it under Admin Panel → Functions → New Function, then switch it on and make it Global. It only touches chats with Hermify agents. It tells the agent to save files in its outbox, and when the reply comes back it pulls each file over, stores it in Open WebUI as the person who's chatting, and swaps the path for a download link.

Telegram doesn't need any of this; the gateway already sends files there.

## Things worth knowing

- `agent.config` is only copied onto a volume that doesn't have a `config.yaml` yet. After the first boot the file belongs to the person, and changing the value won't touch it.
- Open WebUI only reads its connection list on first start. When you add someone later, add `http://hermes-<name>.<namespace>.svc.cluster.local:8642/v1` with their `API_SERVER_KEY` under Admin Panel → Settings → Connections.
- Hindsight recall is mostly the CPU reranker, and agents give up waiting after about 10 seconds. The defaults in `hindsight.env` (100 candidates, 300-token queries) keep it at 2–5s on a 4-vCPU node with AVX2. On a VM without AVX2 it's several times slower, so check your CPU type.
- The reranker's memory grows with query length. If Hindsight gets OOM-killed, raise its memory limit or lower `HINDSIGHT_API_RECALL_MAX_QUERY_TOKENS` / `HINDSIGHT_API_RECALL_MAX_CONCURRENT`.
- Only run one gateway per Telegram bot. Two gateways on the same token fight over updates.
- Volumes are kept when you uninstall (`helm.sh/resource-policy: keep`). Delete the PVCs yourself if you really want someone's data gone.

## Security

This is for people who trust each other, on a cluster you run. Some things to be aware of:

Agents have a shell. Tools, including the terminal, run inside the agent's own pod with internet access (`terminal.backend: local`), so anyone who can chat with an agent can get it to run commands. The pod is the boundary: other people's agents and files are out of reach, but that agent's own files, keys and memory aren't.

Boxes come with passwordless `sudo`. That's root inside the container, not on the node (the box isn't privileged and keeps default capabilities), but it can read the person's agent files, `.env` and LLM key included.

Hindsight's API has no auth, and any agent can ask for any bank. The NetworkPolicies keep non-agents out, but memory is only separated by convention between agents. Don't expose port 8888 outside the namespace.

Open WebUI decides who can talk to which agent, so keep sign-up off (the default) and keep each `hermes-<name>` model private. If it's on the internet, put something like an identity-aware proxy or a VPN in front of it. It can also read whatever an agent puts in its outbox, using a key it already has; nothing else on the agent's volume is served.

Secrets the chart generates are stored in Helm's release history next to your values. Use `existingSecret` for anything real.

## Tested on

k3s 1.33 with the bundled Traefik, Longhorn, Flux 2.9, Hermes Agent v0.23.1, Hindsight 1.2.1 and Open WebUI v0.13.3. That's my setup; others should work but I haven't tried them. Issues and PRs welcome.

## Moving an existing install onto the chart

If you already run these pieces with the same object names, Helm (and Flux's helm-controller, which adopts by default) will take over the existing objects, and volumes are reused as long as the name, size and StorageClass match. Diff before you switch:

```sh
helm template <release> ./charts/hermify -n <ns> -f values.yaml | kubectl diff -f -
```

## Updates and releases

Image tags are pinned in [`values.yaml`](charts/hermify/values.yaml), and Renovate ([`renovate.json`](renovate.json)) opens a PR when a new one comes out, bumping the chart's patch version along with it. Majors wait on the Dependency Dashboard. To release, tag `v<chart version>` and push the tag; the Release workflow checks the tag against `Chart.yaml`, pushes the chart to `oci://ghcr.io/omar2535/charts/hermify` and creates the GitHub Release. CI lints and renders every file in `ci/` and `examples/`, validates them with kubeconform, and checks that the bad-values cases fail.

You don't have to wait for a release to get a newer image; pin it in your own values.

## License

[MIT](LICENSE). Hermify only deploys the upstream images, and each of those projects has its own license.

Hermify isn't affiliated with or endorsed by Nous Research, Vectorize or Open WebUI.
