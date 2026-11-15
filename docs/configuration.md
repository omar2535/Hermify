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
| `networkPolicies.egress` | What agents may reach. Off by default (below). |

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

## Limiting what agents can reach

By default an agent can reach anything its pod can: your LAN, the Kubernetes API, the kubelet and every Service in the cluster. With `networkPolicies.egress.enabled`, agents and their boxes reach only cluster DNS, the Hindsight gateway and the public internet (any IPv4 address outside `privateRanges`). Everything else needs a rule. Your LLM endpoint is the one you'll almost always need, if it's in the cluster or on your LAN:

```yaml
networkPolicies:
  egress:
    enabled: true
    extraRules:
      - to:
          - namespaceSelector:
              matchLabels:
                kubernetes.io/metadata.name: litellm
        ports:
          - port: 4000
tenants:
  - name: alice
    # Only alice's agent: a Git server on the LAN.
    egress:
      - to:
          - ipBlock:
              cidr: 192.168.1.10/32
        ports:
          - port: 443
```

Rules are ordinary NetworkPolicy `egress` entries. Use the Pod's port, not the Service's (LiteLLM's Service may listen on 80 but the Pod on 4000). DNS defaults to k3s's CoreDNS (`k8s-app: kube-dns` in `kube-system`); change `egress.dns` if yours differs. After turning it on, check from an agent that the LLM, Hindsight and a public site still answer:

```sh
kubectl -n <ns> exec deploy/hermes-alice -c hermes -- curl -sS -o /dev/null -w '%{http_code}\n' <llm.baseUrl>/models
```

## Memory keys

Agents reach Hindsight through [hindsight-gateway](https://github.com/omar2535/hindsight-gateway), which gives each key one bank. Each agent's `HINDSIGHT_API_KEY` is imported from its Secret when the gateway starts; after that, its admin UI owns the keys. There you can create keys (for an agent outside the cluster, say), move a key to another bank, and disable, rotate or delete keys. A key you rotate or delete there stays that way: its Secret's old value isn't imported again. If you rotate an agent's key in the UI, put the new value in that agent's Secret and restart it.

## The gateway's hostname

Give the gateway one hostname, and it serves both the admin UI and the API for agents outside the cluster (Hermes on your laptop, say):

```yaml
hindsight:
  gateway:
    ingress:
      enabled: true
      className: traefik
      host: memory.example.com
      tls: {secretName: memory-tls}
      # apiPath: /api   (the defaults)
      # uiPath: /ui     ("" leaves the UI off this hostname)
```

- **`https://memory.example.com/ui/`**: the admin UI. Its password:
  ```sh
  kubectl -n hermify get secret hindsight-gateway-secrets -o jsonpath='{.data.HGW_ADMIN_PASSWORD}' | base64 -d
  ```
  The chart creates it unless you set `hindsight.gateway.existingSecret` to your own Secret with `HGW_ADMIN_PASSWORD`. Without a hostname, `kubectl -n hermify port-forward svc/hindsight-gateway 8890` and open `http://localhost:8890/ui/`.
- **`https://memory.example.com/api`**: the API. On the outside agent, use Hindsight in `local_external` mode with this URL and a key.

Only the gateway is exposed, never Hindsight's API, so every request still needs a key and opens just that key's bank. The pods in `networkPolicies.ingressFrom` are the ones allowed to reach it. Keep the hostname on your LAN or VPN, with TLS (the UI's login cookie is Secure-only).

The image is `ghcr.io/omar2535/hindsight-gateway`; set `hindsight.gateway.imagePullSecrets` if you mirror it somewhere private.

Give each outside agent its own key rather than reusing the cluster agent's, so you can revoke one without the other. The simplest way is **New key** in the admin UI. If you'd rather keep the key in Git, add it as a seed:

```yaml
hindsight:
  gateway:
    extraKeys:
      - name: alice-laptop     # its name in the UI and the log
        bank: hermes-alice     # shares alice's memory
```

With no `existingSecret`, the chart creates `hindsight-key-alice-laptop` with a random key; read it with `kubectl get secret hindsight-key-alice-laptop -o jsonpath='{.data.HINDSIGHT_API_KEY}' | base64 -d`. With `existingSecret` (and optionally `secretKey`), the key comes from your own Secret. Either way it's imported when the gateway starts. To revoke it, delete or disable it in the admin UI: that takes effect at once, without restarting anything.

## Secrets

If you don't set `existingSecret`, the chart creates `hermes-<name>-secrets`, `hindsight-secrets` and `open-webui-secrets` itself. Random keys are generated once and survive upgrades, and the Secrets are left behind on uninstall. The catch is that LLM keys then come from your values (`llm.apiKey`, `tenants[].llmApiKey`) and end up in Helm's release history.

If your values live in Git, create the Secrets yourself (SOPS, Sealed Secrets, External Secrets) and point `existingSecret` at them:

| Secret | Keys |
|---|---|
| `tenants[].existingSecret` | `API_SERVER_KEY` and `HINDSIGHT_API_KEY` (any random strings, e.g. `openssl rand -hex 32`), plus the key named by `llm.apiKeyEnv` |
| `hindsight.existingSecret` | `HINDSIGHT_API_LLM_API_KEY`, `HINDSIGHT_CP_ACCESS_KEY` (the UI login) |
| `openWebui.existingSecret` | `WEBUI_SECRET_KEY` |

Open WebUI reads each agent's `API_SERVER_KEY` straight out of that person's Secret, and the Hindsight gateway imports each `HINDSIGHT_API_KEY` the same way, so you never have to copy keys around. A Secret without `HINDSIGHT_API_KEY` doesn't break anything else, but that person's agent can't use memory until you add it (and restart the gateway) or create a key for them in the admin UI.
