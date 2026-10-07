#!/bin/bash
set -e

# Deploy JCAMPOS Cross-Docking Backend SSM Parameters
#
# Usage:
#   ./deploys/deploy-params.sh <environment> [options]
#
# Required:
#   --s3-bucket           S3 bucket name for file uploads
#   --pdf-domain          Public domain for serving PDF/file URLs
#   --email-sender        SES verified sender address
#   --email-recipient     Default email recipient
#   --api-services-url    Internal services API base URL
#   --api-orgs-url        Organizations API URL template
#
# Optional:
#   --cloudfront-id       CloudFront distribution ID (omit to skip)
#   --wkhtmltopdf-path    Path to wkhtmltopdf binary (omit to use default)
#   --region              AWS region (default: us-east-1)
#   --no-profile          Skip AWS profile (use IAM role, for CodeBuild)
#
# Note: DB credentials are managed separately via Infrastructure/secrets/build-secrets.sh
#       The shared secret jcampos/{env}/database is used (same as data-services).
#
# Example:
#   ./deploys/deploy-params.sh dev \
#     --s3-bucket tsuru-uploads-jcampos-dev \
#     --pdf-domain https://tsuru-uploads.jcampos.dev \
#     --email-sender entregas@modaslaura.net \
#     --email-recipient camdistribucin73@wal-mart.com \
#     --api-services-url https://private-api.dev.jcampos.io \
#     --api-orgs-url /api/organizations/%s \
#     --cloudfront-id E3VMEB1CL8LNEC

# ── Parse positional argument ─────────────────────────────────────────────
ENVIRONMENT=${1:-dev}
shift || true

REGION="us-east-1"
USE_PROFILE=true
S3_BUCKET=""
PDF_DOMAIN=""
EMAIL_SENDER=""
EMAIL_RECIPIENT=""
API_SERVICES_URL=""
API_ORGS_URL=""
CLOUDFRONT_ID=""
WKHTMLTOPDF_PATH=""

# ── Load .env file as defaults (values can still be overridden by flags) ──
ENV_FILE=".env"
if [ -f "$ENV_FILE" ]; then
  echo "Loading defaults from $ENV_FILE ..."
  # Export only the relevant vars; skip comments and blank lines
  set -a
  # shellcheck disable=SC1090
  source <(grep -E '^(S3_BUCKET|PDF_DOMAIN|EMAIL_SENDER|EMAIL_RECIPIENT|API_SERVICES_URL|API_ORGANIZATIONS_URL|CLOUDFRONT_DISTRIBUTION_ID|PATH_TO_WKHTMLTOPDF|AWS_REGION)=' "$ENV_FILE" | sed 's/\r//')
  set +a
  # Map env var names to script variables
  S3_BUCKET="${S3_BUCKET:-$S3_BUCKET}"
  PDF_DOMAIN="${PDF_DOMAIN:-$PDF_DOMAIN}"
  EMAIL_SENDER="${EMAIL_SENDER:-$EMAIL_SENDER}"
  EMAIL_RECIPIENT="${EMAIL_RECIPIENT:-$EMAIL_RECIPIENT}"
  API_SERVICES_URL="${API_SERVICES_URL:-$API_SERVICES_URL}"
  API_ORGS_URL="${API_ORGANIZATIONS_URL:-}"
  CLOUDFRONT_ID="${CLOUDFRONT_DISTRIBUTION_ID:-}"
  WKHTMLTOPDF_PATH="${PATH_TO_WKHTMLTOPDF:-}"
  REGION="${AWS_REGION:-$REGION}"
fi

# ── Parse named arguments (override .env values) ──────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --s3-bucket)         S3_BUCKET="$2";         shift 2 ;;
    --pdf-domain)        PDF_DOMAIN="$2";        shift 2 ;;
    --email-sender)      EMAIL_SENDER="$2";      shift 2 ;;
    --email-recipient)   EMAIL_RECIPIENT="$2";   shift 2 ;;
    --api-services-url)  API_SERVICES_URL="$2";  shift 2 ;;
    --api-orgs-url)      API_ORGS_URL="$2";      shift 2 ;;
    --cloudfront-id)     CLOUDFRONT_ID="$2";     shift 2 ;;
    --wkhtmltopdf-path)  WKHTMLTOPDF_PATH="$2";  shift 2 ;;
    --region)            REGION="$2";            shift 2 ;;
    --no-profile)        USE_PROFILE=false;       shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# ── AWS profile ───────────────────────────────────────────────────────────
PROFILE_ARG=""
if [ "$USE_PROFILE" = true ]; then
  PROFILE="PACIFIC-PROD"
  PROFILE_ARG="--profile $PROFILE"
fi

echo "============================================"
echo "JCAMPOS Cross-Docking Backend — SSM Parameters"
echo "  Environment : $ENVIRONMENT"
echo "  Region      : $REGION"
echo "  Profile     : ${PROFILE:-<IAM role>}"
echo "============================================"

if ! aws sts get-caller-identity $PROFILE_ARG > /dev/null 2>&1; then
  echo "ERROR: AWS credentials invalid."
  [ "$USE_PROFILE" = true ] && echo "Run: aws sso login --profile $PROFILE"
  exit 1
fi

# ============================================
# Deploy SSM Parameters stack
# ============================================
PARAMS_STACK="tsuru-${ENVIRONMENT}-cd-backend-ssm-params"

echo ""
echo "Deploying SSM Parameters: $PARAMS_STACK"

PARAM_OVERRIDES=(
  "Environment=$ENVIRONMENT"
  "S3Bucket=$S3_BUCKET"
  "PdfDomain=$PDF_DOMAIN"
  "EmailSender=$EMAIL_SENDER"
  "EmailRecipient=$EMAIL_RECIPIENT"
  "ApiServicesUrl=$API_SERVICES_URL"
  "ApiOrganizationsUrl=$API_ORGS_URL"
)
[ -n "$CLOUDFRONT_ID" ]    && PARAM_OVERRIDES+=("CloudfrontDistributionId=$CLOUDFRONT_ID")
[ -n "$WKHTMLTOPDF_PATH" ] && PARAM_OVERRIDES+=("WkhtmltopdfPath=$WKHTMLTOPDF_PATH")

aws cloudformation deploy \
  --template-file cloudformation/params.yml \
  --stack-name "$PARAMS_STACK" \
  --parameter-overrides "${PARAM_OVERRIDES[@]}" \
  --region "$REGION" \
  $PROFILE_ARG \
  --no-fail-on-empty-changeset

echo ""
echo "============================================"
echo "Done! SSM parameters under /tsuru/${ENVIRONMENT}/cd-backend/"
echo "  aws/stage                  -> $ENVIRONMENT"
echo "  aws/region                 -> $REGION"
echo "  aws/database               -> tsuru/${ENVIRONMENT}/database (shared secret, set by build-secrets.sh)"
echo "  s3/bucket                  -> ${S3_BUCKET:-<empty>}"
echo "  pdf/domain                 -> ${PDF_DOMAIN:-<empty>}"
echo "  email/sender               -> ${EMAIL_SENDER:-<empty>}"
echo "  email/recipient            -> ${EMAIL_RECIPIENT:-<empty>}"
echo "  api/services/url           -> ${API_SERVICES_URL:-<empty>}"
echo "  api/organizations/url      -> ${API_ORGS_URL:-<empty>}"
echo "  cloudfront/distribution/id -> ${CLOUDFRONT_ID:-<skipped>}"
echo "  path/to/wkhtmltopdf        -> ${WKHTMLTOPDF_PATH:-/usr/local/bin/wkhtmltopdf (default)}"
echo "============================================"
