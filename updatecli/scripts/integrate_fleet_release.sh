#!/bin/sh

set -e

# Testing that we can run curl command from the GitHub Runner
curl --help > /dev/null

VERSION="$1"
if [ -z "$VERSION" ]
then
    echo "Empty version provided"
    exit 0
fi

CURRENT_VERSION="$(sed -n "s/^version: \([.0-9]*\)/\1/p" ./charts/fleet/Chart.yaml)"

if [ "$VERSION" = "$CURRENT_VERSION" ]
then
    echo "The Fleet chart is already up to date."
    exit 0
fi

if test "$DRY_RUN" == "true"
then
    echo "**DRY_RUN** Fleet would be bumped from ${CURRENT_VERSION} to ${VERSION}"
    exit 0
fi

# Remove old chart
rm -r ./charts/fleet*

for NAME in fleet fleet-crd fleet-agent
do
    curl -sS -L -o "/tmp/${NAME}-${VERSION}.tgz" "https://github.com/rancher/fleet/releases/download/v${VERSION}/${NAME}-${VERSION}.tgz"
    tar -xf "/tmp/${NAME}-${VERSION}.tgz" -C ./charts/
    rm "/tmp/${NAME}-${VERSION}.tgz"
done

