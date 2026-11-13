# Operations

## Things worth knowing

- `agent.config` is only copied onto a volume that doesn't have a `config.yaml` yet. After the first boot the file belongs to the person, and changing the value won't touch it.
- Open WebUI only reads its connection list on first start. When you add someone later, add `http://hermes-<name>.<namespace>.svc.cluster.local:8642/v1` with their `API_SERVER_KEY` under Admin Panel → Settings → Connections.
- Only run one gateway per Telegram bot. Two gateways on the same token fight over updates.
- Volumes are kept when you uninstall (`helm.sh/resource-policy: keep`). Delete the PVCs yourself if you really want someone's data gone.
- Use one release per namespace. Object names are fixed (`hermes-<name>`, `hindsight`, `open-webui`), so two releases in the same namespace would step on each other.

## Hindsight

Recall is mostly the CPU reranker, and agents give up waiting after about 10 seconds. The defaults in `hindsight.env` (100 candidates, 300-token queries) keep it at 2–5s on a 4-vCPU node with AVX2. On a VM without AVX2 it's several times slower, so check your CPU type.

The reranker's memory grows with query length. If Hindsight gets OOM-killed, raise its memory limit or lower `HINDSIGHT_API_RECALL_MAX_QUERY_TOKENS` / `HINDSIGHT_API_RECALL_MAX_CONCURRENT`.

## Moving an existing install onto the chart

If you already run these pieces with the same object names, Helm (and Flux's helm-controller, which adopts by default) will take over the existing objects, and volumes are reused as long as the name, size and StorageClass match. Diff before you switch:

```sh
helm template <release> ./charts/hermify -n <ns> -f values.yaml | kubectl diff -f -
```
