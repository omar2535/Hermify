# Security

Hermify is for people who trust each other, on a cluster you run. Some things to be aware of.

NetworkPolicies deny all ingress to the namespace, then allow: your ingress controller to Open WebUI, the Hindsight UI and the boxes; Open WebUI to the agents (API and outbox); and the agents to Hindsight's API. Everything else is kept out. Egress stays open, since agents need the LLM endpoint and the internet.

Agents have a shell. Tools, including the terminal, run inside the agent's own pod with internet access (`terminal.backend: local`), so anyone who can chat with an agent can get it to run commands. The pod is the boundary: other people's agents and files are out of reach, but that agent's own files, keys and memory aren't.

Boxes come with passwordless `sudo`. That's root inside the container, not on the node (the box isn't privileged and keeps default capabilities), but it can read the person's agent files, `.env` and LLM key included.

Hindsight's API has no auth, and any agent can ask for any bank. The NetworkPolicies keep non-agents out, but between agents memory is only separated by convention. Don't expose port 8888 outside the namespace.

Open WebUI decides who can talk to which agent, so keep sign-up off (the default) and keep each `hermes-<name>` model private. If it's on the internet, put something like an identity-aware proxy or a VPN in front of it. It can also read whatever an agent puts in its outbox, using a key it already has; nothing else on the agent's volume is served.

Secrets the chart generates are stored in Helm's release history next to your values. Use `existingSecret` for anything real (see [Configuration](configuration.md#secrets)).
