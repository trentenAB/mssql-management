#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
: "${AWS_ACCOUNT_ID:?Set AWS_ACCOUNT_ID}"
: "${AWS_REGION:?Set AWS_REGION}"
: "${ECR_REPOSITORY:?Set ECR_REPOSITORY}"
[[ "$AWS_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || { echo 'Invalid AWS account ID' >&2; exit 1; }
[[ "$AWS_REGION" =~ ^[a-z]{2}(-[a-z]+)+-[0-9]+$ ]] || { echo 'Invalid AWS region' >&2; exit 1; }
[[ "$ECR_REPOSITORY" =~ ^[a-z0-9]+([._/-][a-z0-9]+)*$ ]] || { echo 'Invalid ECR repository name' >&2; exit 1; }
TAG="${IMAGE_TAG:-$(git rev-parse --short=12 HEAD)}"
REGISTRY="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
IMAGE="$REGISTRY/$ECR_REPOSITORY:$TAG"
# Isolate Docker auth and remove it on exit. AWS uses the caller's normal credential chain.
TASK_DOCKER_CONFIG="$(mktemp -d)"
trap 'rm -rf "$TASK_DOCKER_CONFIG"' EXIT
export DOCKER_CONFIG="$TASK_DOCKER_CONFIG"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker build --pull -t "$IMAGE" .
docker push "$IMAGE"
printf 'Published %s\n' "$IMAGE"
