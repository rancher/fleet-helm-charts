# Fleet Helm Charts

<img src="./assets/fleet.svg" align="right" width="200" height="50%">

This repository hosts Helm charts for [Fleet], the GitOps at Scale project from Rancher.

[Fleet]: https://github.com/rancher/fleet

## Usage

The documentation is centralized in a unique place, checkout the [doc website].

[doc website]: https://fleet.rancher.io/

## Helm chart repo

This [repo] is used as Helm chart repository, by publishing the [index.yaml] through the github-pages feature.

[repo]: https://github.com/rancher/fleet-helm-charts
[index.yaml]: https://rancher.github.io/fleet-helm-charts/index.yaml

Fleet releases are automatically synced from the [rancher/fleet] repository to this helm chart repository daily.

[rancher/fleet]: https://github.com/rancher/fleet
[sync-fleet-releases]: .github/workflows/sync-fleet-releases.yml
