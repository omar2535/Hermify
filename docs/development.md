# Development and releases

## Image updates

Image tags are pinned in [`values.yaml`](../charts/hermify/values.yaml) (`agent.image`, `hindsight.image`, `openWebui.image`). Renovate ([`renovate.json`](../renovate.json)) opens a PR when a new one comes out, updates `appVersion` for Hermes Agent and bumps the chart's patch version along with it. Majors wait on the Dependency Dashboard.

You don't have to wait for a release to get a newer image; pin it in your own values.

## Releasing

1. Bump `version` in `charts/hermify/Chart.yaml`.
2. In [`CHANGELOG.md`](../CHANGELOG.md), rename `[Unreleased]` to the new version and date, with an **Upgrading** part if people need to do anything.
3. Tag `v<chart version>` and push the tag.

The Release workflow checks the tag against `Chart.yaml`, pushes the chart to `oci://ghcr.io/omar2535/charts/hermify` and creates the GitHub Release with that version's CHANGELOG section as its notes. It fails if the section is missing.

## CI

On every PR and push to `main`:

- `helm lint`, a render of every file in `ci/` and `examples/` validated with kubeconform, and the bad-values cases in `ci/invalid/` (which must fail with the chart's own error)
- shellcheck on the box script
- the tests in `tests/` for the Hindsight gateway, the outbox server and the Open WebUI filter, on Python 3.11 and 3.13. They're standard library only, so you can run them anywhere:

```sh
python3 -m unittest discover -s tests -t tests
```

To try a change on a real cluster, install it in a throwaway namespace:

```sh
helm install hermify ./charts/hermify -n hermify-test --create-namespace -f <values>
kubectl delete ns hermify-test
```

## Tested on

k3s 1.33 with the bundled Traefik, Longhorn, Flux 2.9, Hermes Agent v0.23.1, Hindsight 1.2.1 and Open WebUI v0.13.3. That's my setup; others should work but I haven't tried them. Issues and PRs welcome.
