<p align="center">
  <img src="assets/icon.svg" alt="" width="120">
</p>

<h1 align="center">Hermify</h1>

A Helm chart for running [Hermes Agent](https://github.com/NousResearch/hermes-agent) for a few people on one Kubernetes cluster. I built it so everyone in my family could have their own agent without me running a separate box for each of them.

Each person gets their own agent, volume, Telegram bot and LLM key. They share one [Hindsight](https://github.com/vectorize-io/hindsight) for long-term memory (a bank each) and one [Open WebUI](https://github.com/open-webui/open-webui), where every agent shows up as a model. Anyone who wants a shell can get an SSH box next to their agent.

## What you need

- Kubernetes 1.29+ and Helm 3
- An OpenAI-compatible LLM endpoint (LiteLLM, vLLM, Ollama, OpenRouter...) with a model that's decent at tool calling
- A StorageClass with ReadWriteOnce volumes, and a CNI that enforces NetworkPolicy
- Roughly 300–600Mi of memory per agent, plus about 1.5Gi for Hindsight and 1Gi for Open WebUI

Not on k3s's bundled Traefik? Set `networkPolicies.ingressFrom` to your ingress controller, or Open WebUI will time out ([how](docs/configuration.md#ingress-controllers-other-than-k3ss-traefik)).

## Install

Copy [`examples/values-family.yaml`](examples/values-family.yaml), fill in your people, LLM endpoint and hostnames, then:

```sh
helm install hermify oci://ghcr.io/omar2535/charts/hermify --version 0.3.0 \
  -n hermify --create-namespace -f my-values.yaml
```

Then:

1. Create the first Open WebUI account (it becomes the admin), add everyone, and make each `hermes-<name>` model visible to its owner only.
2. Set Admin Panel → Settings → Interface → Task Model to a plain LLM, not an agent.
3. Install the [files filter](docs/files-in-open-webui.md) so agents can send back spreadsheets, PDFs and so on.
4. Run `hermes setup` for each agent (from their box, or `kubectl -n hermify exec -it deploy/hermes-<name> -c hermes -- hermes setup`) and restart it.

## Docs

- [Configuration](docs/configuration.md): values, secrets, ingress
- [SSH boxes](docs/ssh-boxes.md)
- [Files in Open WebUI](docs/files-in-open-webui.md)
- [Operations](docs/operations.md): gotchas, Hindsight tuning, adopting an existing install
- [Security](docs/security.md)
- [Development and releases](docs/development.md)
- [Changelog](CHANGELOG.md) and [reporting a security issue](SECURITY.md)

## License

[MIT](LICENSE). Hermify only deploys the upstream images, each under its own license, and isn't affiliated with Nous Research, Vectorize or Open WebUI.
