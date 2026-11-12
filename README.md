# Hermify

A Helm chart that runs a household (or a small team) of [Hermes Agents](https://github.com/NousResearch/hermes-agent) on Kubernetes:

- **One agent per person**: its own pod, volume, settings, Telegram bot and LLM key.
- **Shared long-term memory** with [Hindsight](https://github.com/vectorize-io/hindsight): one memory bank per person, embeddings and reranking on CPU.
- **[Open WebUI](https://github.com/open-webui/open-webui)** as the chat frontend, where each agent shows up as a model.
- **Optional SSH boxes**: a Debian shell next to a person's agent, with the `hermes` CLI, so `hermes setup`, `hermes chat` and editing `~/agent/.env` work just as on a normal install.
- **NetworkPolicies** that let only Open WebUI talk to the agents and only the agents talk to the memory API.

```
            Open WebUI ──(API_SERVER_KEY)──▶ hermes-alice ─┐
 browser ─▶ (one model per agent)            hermes-bob   ─┼─▶ your LLM endpoint
                                             hermes-...   ─┤   (OpenAI-compatible)
 Telegram ◀───────────────────────────────── each agent  ─┘
                                                  │
 ssh alice@... ─▶ box (sidecar, same volume)      ▼
                                             Hindsight (bank per person)
```

## Requirements

- Kubernetes 1.29+ and Helm 3.
- An **OpenAI-compatible LLM endpoint** the cluster can reach ([LiteLLM](https://github.com/BerriAI/litellm), vLLM, Ollama's `/v1`, OpenRouter...). Agents call tools a lot, so use a model that's good at tool calling. With LiteLLM you can give each person their own key and budget.
- A StorageClass with ReadWriteOnce volumes.
- A CNI that enforces NetworkPolicy (k3s's default does). Without one, Hindsight's API, which has no auth, is open to the whole cluster.
- An ingress controller for the web UIs (any one; optional, since `kubectl port-forward` also works).

> [!IMPORTANT]
> **Not on k3s's bundled Traefik? Set `networkPolicies.ingressFrom`.** The chart denies all ingress to its namespace by default, then lets your ingress controller's pods through. The default selector is k3s's Traefik (`app.kubernetes.io/name: traefik` in `kube-system`). With anything else, Open WebUI just times out. For example, for ingress-nginx:
>
> ```yaml
> networkPolicies:
>   ingressFrom:
>     - namespaceSelector:
>         matchLabels:
>           kubernetes.io/metadata.name: ingress-nginx
>       podSelector:
>         matchLabels:
>           app.kubernetes.io/name: ingress-nginx
> ```
- Memory: roughly 300–600Mi per agent, ~1.5Gi for Hindsight (with bursts) and ~1Gi for Open WebUI.

## Install

```sh
git clone https://github.com/omar2535/Hermify && cd Hermify
cp examples/values-family.yaml my-values.yaml   # edit: people, LLM endpoint, hostnames
helm install hermify ./charts/hermify -n hermify --create-namespace -f my-values.yaml
```

Then:

1. **Open WebUI:** the first account you create becomes the admin. Add each person in *Admin Panel → Users*. Then in *Admin Panel → Settings → Models*, make each `hermes-<name>` model visible to its owner only (models are private by default).
2. **Task Model:** set *Admin Panel → Settings → Interface → Task Model* to a plain LLM connection, not an agent. Titles, tags and follow-ups would otherwise each trigger a full agent run and a memory lookup.
3. **Each agent:** set up Telegram, persona and so on with `hermes setup`, from the person's box or with `kubectl -n hermify exec -it deploy/hermes-<name> -c hermes -- hermes setup`. Then restart the agent.

Install **one release per namespace**. Object names are fixed (`hermes-<name>`, `hindsight`, `open-webui`), so two releases in one namespace would collide.

## Values

[`values.yaml`](charts/hermify/values.yaml) documents every option. The main ones:

| Key | What |
|---|---|
| `tenants[]` | The people. `name` becomes `hermes-<name>`, the Hindsight bank, the Open WebUI model and the box login. |
| `tenants[].existingSecret` | Secret holding `API_SERVER_KEY` and the LLM key. Leave it empty to have the chart create one. |
| `tenants[].replicas` | `0` stops someone's agent but keeps their data. |
| `tenants[].box` | SSH box: `enabled`, `authorizedKeys`, `service.type`, `traefikEntryPoint`. |
| `llm.baseUrl` / `llm.model` | The OpenAI-compatible endpoint and the default model. |
| `llm.apiKeyEnv` | The env var and Secret key name for the LLM key (default `LLM_API_KEY`). |
| `storageClassName` | Used by every volume. Empty means the cluster default. |
| `agent.config` | The first-boot `config.yaml` for every agent. |
| `hindsight.*`, `openWebui.*` | Image, resources, persistence, ingress. Each has `enabled` to turn it off. |
| `networkPolicies.ingressFrom` | Your ingress controller's pods. They may reach Open WebUI, the Hindsight UI and the boxes. The default is k3s's Traefik; change it for anything else. |

### Secrets

With no `existingSecret`, the chart creates `hermes-<name>-secrets`, `hindsight-secrets` and `open-webui-secrets`. Random keys are generated once and kept on upgrades, and a Secret stays behind on uninstall. LLM keys then come from values (`llm.apiKey`, `tenants[].llmApiKey`) and end up in Helm's release history. For a Git repo, create the Secrets yourself (SOPS, Sealed Secrets, External Secrets) and set `existingSecret`:

| Secret | Keys |
|---|---|
| `tenants[].existingSecret` | `API_SERVER_KEY` (any random string), `<llm.apiKeyEnv>` |
| `hindsight.existingSecret` | `HINDSIGHT_API_LLM_API_KEY`, `HINDSIGHT_CP_ACCESS_KEY` (login for its UI) |
| `openWebui.existingSecret` | `WEBUI_SECRET_KEY` |

Open WebUI gets each agent's `API_SERVER_KEY` straight from that person's Secret, so the keys always match.

### SSH boxes

A box is a sidecar container in the person's agent pod. It runs from the agent's own image and shares the agent's volume at `~/agent`. It logs in as the person with the agent's UID, so both can edit the same files. Only the home directory, SSH host key and apt cache persist. Extra packages listed in `~/.box/apt-packages` are reinstalled on every start. `restart-agent` restarts the agent container only, and the SSH session stays up.

To reach a box from outside the cluster:
- **`service.type: LoadBalancer`:** one IP per box, port 22.
- **Traefik:** add an entrypoint per box in Traefik's config (raw TCP can't be routed by hostname), then set `traefikEntryPoint`. The chart creates the `IngressRouteTCP`.
- **`NodePort`**, or a Cloudflare Tunnel / Tailscale in front.

## Good to know

- **Agent config is seeded once.** `agent.config` is copied onto an agent's volume only if it has no `config.yaml` yet. After that, the file on the volume belongs to the person.
- **Open WebUI reads connections on first start only.** For someone added later, add `http://hermes-<name>.<namespace>.svc.cluster.local:8642/v1` with their `API_SERVER_KEY` in *Admin Panel → Settings → Connections*.
- **Hindsight recall speed:** the CPU reranker is most of the recall time, and agents give up after about 10s. The default `hindsight.env` caps candidates at 100 and query length at 300 tokens, which keeps recall at 2–5s on a 4-vCPU node with AVX2. Without AVX2 (e.g. a VM with a generic CPU type) it's several times slower.
- **Hindsight memory:** its reranker's memory grows with query length. If it gets OOM-killed, raise `hindsight.resources.limits.memory` or lower `HINDSIGHT_API_RECALL_MAX_QUERY_TOKENS` / `HINDSIGHT_API_RECALL_MAX_CONCURRENT`.
- **One gateway per Telegram bot.** Don't run the same agent's gateway anywhere else. Two gateways on one token fight over updates.
- **Volumes are kept** on uninstall (`helm.sh/resource-policy: keep`). Delete the PVCs yourself to wipe someone's data.

## Security

Hermify is meant for people who trust each other, such as a household or a small team, on a cluster you control. Know what it gives them:

- **Agents have a shell.** Each agent runs its tools, including the terminal, inside its own pod, unsandboxed (`terminal.backend: local`), with open internet access. Anyone who can chat with an agent can get it to run commands there. The pod limits the damage: other people's agents and files aren't reachable, but that agent's own files, keys and memory are.
- **Boxes give root inside the container.** SSH users get passwordless `sudo` in their box. That's container root, not node root: the box isn't privileged and keeps the default capabilities. It can read that person's agent files, including their `.env`, and gets their LLM key.
- **Memory is separated by convention.** Hindsight's API has no auth, and any agent can name any bank. The NetworkPolicies keep everything except the agents away from it, but an agent told to read someone else's bank could. Never expose port 8888 outside the namespace.
- **Open WebUI is the front door.** Its accounts and per-model permissions decide who can talk to which agent. Keep sign-up off (the default) and make each `hermes-<name>` model private. If you put it on the internet, put a login in front, such as an identity-aware proxy or VPN.
- **Secrets created by the chart** live in Helm's release history along with your values. Use `existingSecret` with SOPS, Sealed Secrets or External Secrets for real keys.

## Tested on

k3s 1.33 (bundled Traefik), Longhorn, Flux 2.9, Hermes Agent v0.23.1, Hindsight 1.2.1, Open WebUI v0.13.3. Other setups should work, but haven't been tried yet. Issues and PRs are welcome.

## Adopting an existing install

If you already run these components with the same object names, Helm (and Flux's helm-controller, which adopts by default) takes over the existing objects. Volumes are reused as long as their names, sizes and StorageClass match. Diff first:

```sh
helm template <release> ./charts/hermify -n <ns> -f values.yaml | kubectl diff -f -
```

## Updates and releases

Image tags are pinned in [`values.yaml`](charts/hermify/values.yaml) (`agent.image`, `hindsight.image`, `openWebui.image`). [`renovate.json`](renovate.json) has Renovate open a PR for each new tag. The PR also updates `appVersion` for Hermes Agent and bumps the chart's patch version. Majors wait for approval on the Dependency Dashboard. After merging, tag the release (`git tag v<chart version> && git push --tags`) so installs pinned to a tag can move to it.

You can also pin any image in your own values without waiting for a chart release.

## License

[MIT](LICENSE). Hermify only deploys the upstream images; each project keeps its own license.

Hermify is an independent project. It isn't affiliated with or endorsed by Nous Research (Hermes Agent), Vectorize (Hindsight) or Open WebUI.
