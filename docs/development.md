# Development and releases

## Image updates

Image tags are pinned in [`values.yaml`](../charts/hermify/values.yaml) (`agent.image`, `hindsight.image`, `openWebui.image`). Renovate ([`renovate.json`](../renovate.json)) opens a PR when a new one comes out, updates `appVersion` for Hermes Agent and bumps the chart's patch version along with it. Majors wait on the Dependency Dashboard.

You don't have to wait for a release to get a newer image; pin it in your own values.

## Releasing

Bump `version` in `charts/hermify/Chart.yaml`, then tag `v<chart version>` and push the tag. The Release workflow checks the tag against `Chart.yaml`, pushes the chart to `oci://ghcr.io/omar2535/charts/hermify` and creates the GitHub Release.

## CI

On every PR and push to `main`: `helm lint`, a render of every file in `ci/` and `examples/` validated with kubeconform, the bad-values cases in `ci/invalid/` (which must fail with the chart's own error), and shellcheck on the box script.

To try a change on a real cluster, install it in a throwaway namespace:

```sh
helm install hermify ./charts/hermify -n hermify-test --create-namespace -f <values>
kubectl delete ns hermify-test
```

## Tested on

k3s 1.33 with the bundled Traefik, Longhorn, Flux 2.9, Hermes Agent v0.23.1, Hindsight 1.2.1 and Open WebUI v0.13.3. That's my setup; others should work but I haven't tried them. Issues and PRs welcome.
