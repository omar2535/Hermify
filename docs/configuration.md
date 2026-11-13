# Configuration

Every option is documented in [`values.yaml`](../charts/hermify/values.yaml), and `helm show values oci://ghcr.io/omar2535/charts/hermify` prints it. These are the parts you'll actually touch:

| Key | What it's for |
|---|---|
| `tenants[]` | The people. `name` is used for the agent (`hermes-<name>`), the Hindsight bank, the Open WebUI model and the box login. |
| `tenants[].existingSecret` | A Secret with `API_SERVER_KEY` and the LLM key. Leave empty and the chart makes one. |
| `tenants[].replicas` | Set to `0` to stop someone's agent without losing their data. |
| `tenants[].box` | The SSH box: `enabled`, `authorizedKeys`, `service.type`, `traefikEntryPoint`. See [SSH boxes](ssh-boxes.md). |
| `llm.baseUrl`, `llm.model` | Your endpoint and default model. |
| `llm.apiKeyEnv` | Name of the env var / Secret key holding the LLM key (`LLM_API_KEY` by default). |
| `storageClassName` | For every volume. Empty means the cluster default. |
| `agent.config` | The `config.yaml` each agent starts with (only on first boot, see [Operations](operations.md)). |
| `agent.outbox` | File delivery to Open WebUI. On by default. See [Files in Open WebUI](files-in-open-webui.md). |
| `hindsight.*`, `openWebui.*` | Image, resources, persistence, ingress, and `enabled` if you don't want one. |
| `hindsight.gateway` | Keeps each person's memory bank private (see [Security](security.md)). On by default. |
| `networkPolicies.ingressFrom` | Your ingress controller's pods (below). |

## Ingress controllers other than k3s's Traefik

The chart denies all ingress to its namespace and then lets your ingress controller's pods back in. The default selector matches k3s's bundled Traefik (`app.kubernetes.io/name: traefik` in `kube-system`). With anything else, Open WebUI just times out until you set `networkPolicies.ingressFrom`. For ingress-nginx:

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

Those pods can reach Open WebUI, the Hindsight UI and the boxes. If something else needs to reach Open WebUI (a Cloudflare tunnel, say), add it to `networkPolicies.openWebuiExtraFrom`.

## Secrets

If you don't set `existingSecret`, the chart creates `hermes-<name>-secrets`, `hindsight-secrets` and `open-webui-secrets` itself. Random keys are generated once and survive upgrades, and the Secrets are left behind on uninstall. The catch is that LLM keys then come from your values (`llm.apiKey`, `tenants[].llmApiKey`) and end up in Helm's release history.

If your values live in Git, create the Secrets yourself (SOPS, Sealed Secrets, External Secrets) and point `existingSecret` at them:

| Secret | Keys |
|---|---|
| `tenants[].existingSecret` | `API_SERVER_KEY` and `HINDSIGHT_API_KEY` (any random strings, e.g. `openssl rand -hex 32`), plus the key named by `llm.apiKeyEnv` |
| `hindsight.existingSecret` | `HINDSIGHT_API_LLM_API_KEY`, `HINDSIGHT_CP_ACCESS_KEY` (the UI login) |
| `openWebui.existingSecret` | `WEBUI_SECRET_KEY` |

Open WebUI reads each agent's `API_SERVER_KEY` straight out of that person's Secret, and the Hindsight gateway reads each `HINDSIGHT_API_KEY` the same way, so you never have to copy keys around. A Secret without `HINDSIGHT_API_KEY` doesn't break anything else, but that person's agent can't use memory until you add it (the gateway logs which bank has no key).
