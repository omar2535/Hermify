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
- Memory: roughly 300–600Mi per agent, ~1.5Gi for Hindsight (with bursts) and ~1Gi for Open WebUI.

## Install

```sh
git clone <this repo> && cd Hermify
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
| `networkPolicies.ingressFrom` | Your ingress controller's pods. They may reach Open WebUI, the Hindsight UI and the boxes. |

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

## Adopting an existing install

If you already run these components with the same object names, Helm (and Flux's helm-controller, which adopts by default) takes over the existing objects. Volumes are reused as long as their names, sizes and StorageClass match. Diff first:

```sh
helm template <release> ./charts/hermify -n <ns> -f values.yaml | kubectl diff -f -
```

## License

[MIT](LICENSE)
