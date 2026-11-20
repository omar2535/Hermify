# Security

Hermify is for people who trust each other, on a cluster you run. Some things to be aware of.

NetworkPolicies deny all ingress to the namespace, then allow: your ingress controller to Open WebUI, the Hindsight UI, the per-person Hindsight UI and the boxes; Open WebUI to the agents (API and outbox); the agents and the per-person UI to the Hindsight gateway's API port; and the gateway to Hindsight's API. Everything else is kept out.

Egress is open by default: an agent can reach anything its pod can, including your LAN, the Kubernetes API, the kubelet and admin UIs in other namespaces (Longhorn's has no login, for one). Turn on `networkPolicies.egress` to limit agents and their boxes to cluster DNS, the Hindsight gateway and the public internet, plus the rules you add, such as your LLM endpoint ([how](configuration.md#limiting-what-agents-can-reach)). Agent pods also get no service account token and run under the runtime's default seccomp profile.

Agents have a shell. Tools, including the terminal, run inside the agent's own pod with internet access (`terminal.backend: local`), so anyone who can chat with an agent can get it to run commands. The pod is the boundary: other people's agents and files are out of reach, but that agent's own files, keys and memory aren't.

Boxes come with passwordless `sudo`. That's root inside the container, not on the node (the box isn't privileged and keeps default capabilities), but it can read the person's agent files, `.env` and LLM key included.

Memory banks are private. Hindsight's own API has no per-bank auth, so agents never talk to it directly: they go through [hindsight-gateway](https://github.com/omar2535/hindsight-gateway) (`hindsight.gateway`), its own pod and the only thing allowed to reach Hindsight's API, and each sends its own `HINDSIGHT_API_KEY`. A key opens exactly one bank. Everything else is refused: other banks, deleting a whole bank, aliases, clones, transfers between banks, webhooks and bank config changes; the bank list, chunk lookups and export downloads answer for the key's own bank only. Endpoints Hindsight adds in later versions stay blocked until the gateway allows them. The Hindsight UI is the exception: whoever has its access key sees every bank, so treat it as an admin login. If you turn the gateway off, any agent can read any bank again. If you give the gateway a hostname (`hindsight.gateway.ingress`), the same rules apply to anyone who can reach it, but the keys are then the only thing between your network and the banks: keep that hostname off the public internet.

The per-person Hindsight UI (`hindsight.userUi`) is not an exception: it signs each person in with a gateway key and sends every call through the gateway with that key, so it shows one bank, and it can't delete the bank or change its config. Its pod may reach only cluster DNS and the gateway's API port, never Hindsight. Anyone holding a person's UI key sees that person's memory, so hand keys out like passwords; disabling one in the gateway's admin UI cuts it off at once.

The gateway's admin UI manages every key, so its password is effectively an admin login too. Agents can't reach its port (only the ingress controller can, if you give it a hostname). Keep it on your LAN or VPN, behind TLS.

Open WebUI decides who can talk to which agent, so keep sign-up off (the default) and keep each `hermes-<name>` model private. If it's on the internet, put something like an identity-aware proxy or a VPN in front of it. It can also read whatever an agent puts in its outbox, using a key it already has; nothing else on the agent's volume is served.

Secrets the chart generates are stored in Helm's release history next to your values. Use `existingSecret` for anything real (see [Configuration](configuration.md#secrets)).
