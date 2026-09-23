#!/bin/bash

ENVIRONMENT=${1:-dev}
REGION=${2:-us-east-1}

echo "🚀 Building and deploying Cross-Docking Backend for environment: $ENVIRONMENT in region: $REGION"

# Use J-CAMPOS profile
PROFILE="J-CAMPOS"

# Check if AWS credentials are valid
echo "🔐 Checking AWS credentials..."
set +e
aws.exe sts get-caller-identity --profile $PROFILE > /dev/null 2>&1
CRED_CHECK=$?
set -e

if [ $CRED_CHECK -ne 0 ]; then
    echo "❌ AWS credentials expired or invalid."
    exit 1
fi
echo "✅ AWS credentials valid"

# Get AWS Account ID
ACCOUNT_ID=$(aws.exe sts get-caller-identity --profile $PROFILE --query Account --output text)

# Load environment variables from .env file
echo "📋 Loading environment variables from .env..."
if [ ! -f ".env" ]; then
    echo "❌ Missing .env file with required variables"
    exit 1
fi

# Extract variables from .env file
DATABASE_HOST=$(grep '^DATABASE_HOST=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
DATABASE_PORT=$(grep '^DATABASE_PORT=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
DATABASE_USERNAME=$(grep '^DATABASE_USERNAME=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
DATABASE_PASSWORD=$(grep '^DATABASE_PASSWORD=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
DATABASE_DBNAME=$(grep '^DATABASE_DBNAME=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
S3_BUCKET=$(grep '^S3_BUCKET=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
PDF_DOMAIN=$(grep '^PDF_DOMAIN=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
CLOUDFRONT_DISTRIBUTION_ID=$(grep '^CLOUDFRONT_DISTRIBUTION_ID=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
EMAIL_SENDER=$(grep '^EMAIL_SENDER=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
EMAIL_RECIPIENT=$(grep '^EMAIL_RECIPIENT=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
API_SERVICES_URL=$(grep '^API_SERVICES_URL=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
API_ORGANIZATIONS_URL=$(grep '^API_ORGANIZATIONS_URL=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
PATH_TO_WKHTMLTOPDF=$(grep '^PATH_TO_WKHTMLTOPDF=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")

# Validate required variables
if [ -z "$DATABASE_HOST" ] || [ -z "$DATABASE_USERNAME" ] || [ -z "$DATABASE_PASSWORD" ]; then
    echo "❌ Missing required database environment variables in .env"
    exit 1
fi

echo "✅ Environment variables loaded"

# Create ECR repository if it doesn't exist
echo "🐳 Creating ECR repository if needed..."
aws.exe ecr describe-repositories --repository-names cross-docking-backend-ecr --region $REGION --profile $PROFILE > /dev/null 2>&1 || \
aws.exe ecr create-repository --repository-name cross-docking-backend-ecr --region $REGION --profile $PROFILE > /dev/null 2>&1

# Login to ECR
echo "🔑 Logging into ECR..."
aws.exe ecr get-login-password --region $REGION --profile $PROFILE | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com > /dev/null 2>&1

# Build Docker image
echo "🔨 Building Docker image..."
docker buildx build --platform linux/arm64 -t cross-docking-backend-ecr:latest .

# Tag and push Docker image
echo "📤 Pushing Docker image to ECR..."
docker tag cross-docking-backend-ecr:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/cross-docking-backend-ecr:latest > /dev/null 2>&1
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/cross-docking-backend-ecr:latest > /dev/null 2>&1

# Clean up existing log groups with Never Expire retention
echo "🧹 Cleaning up existing log groups..."
LOG_GROUP_PREFIX="//aws//lambda//cross-docking-$ENVIRONMENT-"
LOG_GROUPS=$(aws.exe logs describe-log-groups --log-group-name-prefix "$LOG_GROUP_PREFIX" --region $REGION --profile $PROFILE --query 'logGroups[?retentionInDays==`null`].logGroupName' --output text)
for LOG_GROUP in $LOG_GROUPS; do
    if [[ $LOG_GROUP =~ backend-api ]]; then
        echo "Deleting log group: $LOG_GROUP"
        aws.exe logs delete-log-group --log-group-name "$LOG_GROUP" --region $REGION --profile $PROFILE || true
    fi
done

# Deploy Lambda functions with SAM (no build needed)
echo "🚀 Deploying Lambda functions..."
sam deploy \
    --config-env $ENVIRONMENT \
    --profile $PROFILE \
    --resolve-image-repos \
    --force-upload \
    --no-fail-on-empty-changeset \
    --parameter-overrides \
        Environment=$ENVIRONMENT \
        DatabaseHost=$DATABASE_HOST \
        DatabasePort=$DATABASE_PORT \
        DatabaseName=$DATABASE_DBNAME \
        DatabaseUser=$DATABASE_USERNAME \
        DatabasePassword=$DATABASE_PASSWORD \
        S3BucketName=$S3_BUCKET \
        CorsOrigin="*" \
        PdfDomain=$PDF_DOMAIN \
        CloudFrontDistributionId=$CLOUDFRONT_DISTRIBUTION_ID \
        EmailSender=$EMAIL_SENDER \
        EmailRecipient=$EMAIL_RECIPIENT \
        ApiServicesUrl=$API_SERVICES_URL \
        ApiOrganizationsUrl=$API_ORGANIZATIONS_URL \
        PathToWkhtmltopdf=$PATH_TO_WKHTMLTOPDF

# Update Lambda function code
echo "🔄 Updating Lambda function code..."
echo "Updating function: cross-docking-$ENVIRONMENT-backend-api-lambda"
aws.exe lambda update-function-code \
    --function-name "cross-docking-$ENVIRONMENT-backend-api-lambda" \
    --image-uri "$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/cross-docking-backend-ecr:latest" \
    --region $REGION \
    --profile $PROFILE > /dev/null 2>&1 || true

echo "✅ All deployments completed successfully!"
