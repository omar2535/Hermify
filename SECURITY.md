# Security

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private reporting instead: the **Security** tab of this repo → **Report a vulnerability**. I'll reply there.

Things I especially want to hear about:

- a way for one person's agent to read or change another person's memory bank (getting past the Hindsight gateway)
- a way to read files outside an agent's outbox through the outbox server
- a way to reach an agent, Hindsight or a box from outside what the NetworkPolicies allow
- secrets ending up somewhere the docs say they don't

Bugs in Hermes Agent, Hindsight or Open WebUI themselves belong with those projects.

## Supported versions

Fixes go into the latest release only. Upgrading is usually just bumping the chart version; [CHANGELOG.md](CHANGELOG.md) lists anything more.

## What Hermify does and doesn't protect

Hermify is for people who trust each other, and some things are by design: agents run commands in their own pod, box users have `sudo` in their box, and the Hindsight UI login sees every bank. [docs/security.md](docs/security.md) has the full picture.
