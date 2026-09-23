#!/usr/bin/env bash
# Build the store-be image locally (arm64), push it, and point cd-backend at the
# new immutable digest — the whole manual code deploy, no CI involved.
#
#   bash deploys/deploy-image.sh <environment> <profile>
#
#   1. build  linux/arm64, provenance/SBOM off (Lambda rejects the OCI index a
#             plain `docker push` produces), tagged `<env>-<commit>` + `latest`
#             (cloudformation/template.yml references :latest)
#   2. reuse  if `<env>-<commit>` is already in ECR the build is skipped
#   3. update `update-function-code --image-uri <repo>@sha256:…` + wait
#   4. check  a `{"warmup": true}` invoke must not return FunctionError
#
# Requires a clean working tree (the tag names the commit); ALLOW_DIRTY=1
# overrides with a `-dirty` tag that is always rebuilt. Migrations
# (`alembic upgrade head`) and template changes (`deploys/deploy-lambda.sh`)
# are separate steps.
set -euo pipefail

ENVIRONMENT="${1:?usage: deploy-image.sh <environment> <profile>}"
PROFILE="${2:?usage: deploy-image.sh <environment> <profile>}"
REGION="${AWS_REGION:-us-east-1}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
export AWS_PROFILE="$PROFILE" AWS_REGION="$REGION"

REPO="cd-backend-ecr"
FUNCTION="cd-backend-${ENVIRONMENT}-lambda"

COMMIT="$(git rev-parse --short HEAD)"
if [[ -n "$(git status --porcelain)" ]]; then
  if [[ "${ALLOW_DIRTY:-}" != "1" ]]; then
    echo "Working tree is not clean — commit first (or ALLOW_DIRTY=1)." >&2
    git status --short >&2
    exit 1
  fi
  COMMIT="${COMMIT}-dirty"
fi
TAG="${ENVIRONMENT}-${COMMIT}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
aws ecr describe-repositories --repository-names "$REPO" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$REPO" >/dev/null
docker buildx inspect lambda-builder >/dev/null 2>&1 \
  || docker buildx create --name lambda-builder --driver docker-container >/dev/null

digest_of() {
  aws ecr describe-images --repository-name "$REPO" --image-ids "imageTag=$1" \
    --query 'imageDetails[0].imageDigest' --output text 2>/dev/null || true
}

DIGEST="$(digest_of "$TAG")"
if [[ "$DIGEST" =~ ^sha256: && "$COMMIT" != *-dirty ]]; then
  echo "Image ${TAG} already in ECR — reusing ${DIGEST:0:19}…"
else
  echo "Building ${TAG} (linux/arm64)…"
  docker buildx build --builder lambda-builder --platform linux/arm64 \
    --provenance=false --sbom=false \
    -t "${REGISTRY}/${REPO}:${TAG}" -t "${REGISTRY}/${REPO}:latest" --push .
  DIGEST="$(digest_of "$TAG")"
fi

aws lambda update-function-code --function-name "$FUNCTION" \
  --image-uri "${REGISTRY}/${REPO}@${DIGEST}" --query LastUpdateStatus --output text >/dev/null
aws lambda wait function-updated-v2 --function-name "$FUNCTION"

ERROR="$(aws lambda invoke --function-name "$FUNCTION" \
  --cli-binary-format raw-in-base64-out --payload '{"warmup": true}' \
  /tmp/deploy-image-warm.json --query FunctionError --output text)"
if [[ "$ERROR" != "None" ]]; then
  echo "Warm ping failed: $(head -c 300 /tmp/deploy-image-warm.json)" >&2
  exit 1
fi
echo "Deployed ${FUNCTION} from ${TAG} (${DIGEST:0:19}…)."
