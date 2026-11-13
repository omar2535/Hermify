# SSH boxes

A box is a Debian shell next to someone's agent, with the `hermes` CLI, so `hermes setup`, `hermes chat` and editing `~/agent/.env` work like on a normal install. Turn one on per person with `tenants[].box.enabled` and their public key in `authorizedKeys`.

It's a sidecar container in the person's agent pod, running the agent's own image. It mounts the agent's volume at `~/agent` and logs in as the person with the agent's UID, so both sides can edit the same files.

Only the home directory, the SSH host key and the apt cache survive a restart. Anything listed in `~/.box/apt-packages` gets reinstalled on start. `restart-agent` restarts just the agent container without dropping your SSH session.

## Reaching a box from outside the cluster

That's up to you:

- a `LoadBalancer` Service (`box.service.type`), one IP per box on port 22
- a `NodePort`
- Tailscale or a tunnel in front
- a Traefik entrypoint per box. Raw TCP can't be routed by hostname, so each box needs its own port. Add the entrypoint to Traefik's config, set `traefikEntryPoint`, and the chart creates the `IngressRouteTCP`.

Boxes come with passwordless `sudo`; see [Security](security.md) for what that does and doesn't give someone.
