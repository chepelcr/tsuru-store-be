#!/bin/bash
set -e

ENVIRONMENT=${ENVIRONMENT:-dev}
REGION=${REGION:-us-east-1}

ECR_REPO="cd-backend-ecr"

echo "=== Building cd-backend Docker image ==="
echo "Environment: $ENVIRONMENT | Region: $REGION"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
FULL_URI="${ECR_URI}/${ECR_REPO}:latest"

# ECR login
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ECR_URI"

# Create ECR repo if it doesn't exist
aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" > /dev/null 2>&1 || \
  aws ecr create-repository --repository-name "$ECR_REPO" --region "$REGION" > /dev/null

# Build and push — provenance=false required for Lambda image compatibility
echo "[BUILD] cd-backend → $FULL_URI"
docker buildx build \
  --platform linux/arm64 \
  --provenance=false \
  --sbom=false \
  --push \
  -t "$FULL_URI" .
echo "[OK] cd-backend"

echo ""
echo "Total: 1 | OK: 1 | Failed: 0"
