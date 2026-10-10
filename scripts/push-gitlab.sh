#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
: "${CI_REGISTRY:=registry.gitlab.com}"
: "${CI_REGISTRY_IMAGE:?Set CI_REGISTRY_IMAGE to registry.gitlab.com/group/project}"
: "${CI_REGISTRY_USER:?Set CI_REGISTRY_USER}"
: "${CI_REGISTRY_PASSWORD:?Set CI_REGISTRY_PASSWORD securely}"
[[ "$CI_REGISTRY" =~ ^[a-zA-Z0-9.-]+(:[0-9]+)?$ ]] || { echo 'Invalid registry host' >&2; exit 1; }
[[ "$CI_REGISTRY_IMAGE" == "$CI_REGISTRY/"* ]] || { echo 'Image must belong to CI_REGISTRY' >&2; exit 1; }
TAG="${IMAGE_TAG:-${CI_COMMIT_SHORT_SHA:-$(git rev-parse --short=12 HEAD)}}"
IMAGE="$CI_REGISTRY_IMAGE:$TAG"
TASK_DOCKER_CONFIG="$(mktemp -d)"
trap 'rm -rf "$TASK_DOCKER_CONFIG"' EXIT
export DOCKER_CONFIG="$TASK_DOCKER_CONFIG"
printf '%s' "$CI_REGISTRY_PASSWORD" | docker login --username "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
docker build --pull -t "$IMAGE" .
docker push "$IMAGE"
printf 'Published %s\n' "$IMAGE"
