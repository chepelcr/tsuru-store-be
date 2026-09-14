"""Generate api-gateway/template.yml with inline DefinitionBody (no external JSON file).

Also refreshes swagger/backend.json by importing app/main.py directly
and calling app.openapi() — no running services required.

Usage:
  python scripts/gen_api_template.py              # refresh swagger + generate template
  python scripts/gen_api_template.py --skip-refresh  # use existing swagger files
"""
import argparse, json, os, subprocess, sys

SERVICES = ["backend"]

SKIP_PREFIXES = ("/health", "/docs", "/openapi.json", "/redoc")
COGNITO_ARN_EXPORT = "tsuru-cognito-UserPoolArn"
REQUIRE_AUTH = True
HTTP_METHODS = ("get", "post", "put", "patch", "delete")
I = [""] + ["  " * n for n in range(1, 12)]   # indentation levels

# Every header a browser may send on a cross-origin request. It is ONE constant
# because it is emitted twice — on the per-path OPTIONS mock and on the CORS
# gateway responses — and a header allowed by one but not the other fails the
# preflight in exactly the cases that matter.
#
# `Idempotency-Key` is not optional: the POS sends it on every manual-order POST
# so a pedido captured offline replays as one order rather than several. Without
# it the preflight fails, `fetch` rejects with a bare network error, and the POS
# reads that as "no connection" and queues the pedido forever — it never reaches
# the server and never surfaces an error. sales-be's gateway has always carried
# it; this one did not, which is why a manual order could be captured but never
# created.
CORS_ALLOW_HEADERS = (
    "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,"
    "x-user-id,Idempotency-Key"
)

CUSTOM_DOMAIN = "orders-api.tsuru.jcampos.dev"


# ── swagger refresh ────────────────────────────────────────────────────────────

def refresh_swagger():
    """Import app/main.py in a subprocess and dump app.openapi() to swagger/backend.json."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    swagger_dir = os.path.join(root_dir, "swagger")
    os.makedirs(swagger_dir, exist_ok=True)

    print("Refreshing swagger/backend.json from app/main.py...")

    # Create a temporary script that mocks the database connection
    temp_script = os.path.join(root_dir, "_temp_swagger_gen.py")
    script_content = f"""
import sys
import json
import os

sys.path.insert(0, r'{root_dir}')

# Set fake DB credentials
os.environ['DATABASE_HOST'] = 'localhost'
os.environ['DATABASE_PORT'] = '5432'
os.environ['DATABASE_USERNAME'] = 'fake'
os.environ['DATABASE_PASSWORD'] = 'fake'
os.environ['DATABASE_DBNAME'] = 'fake'
os.environ['ENVIRONMENT'] = 'development'

import sys
import json
import os

sys.path.insert(0, r'{root_dir}')

# Set fake DB credentials
os.environ['DATABASE_HOST'] = 'localhost'
os.environ['DATABASE_PORT'] = '5432'
os.environ['DATABASE_USERNAME'] = 'fake'
os.environ['DATABASE_PASSWORD'] = 'fake'
os.environ['DATABASE_DBNAME'] = 'fake'
os.environ['ENVIRONMENT'] = 'development'

# Mock database connection BEFORE any app imports
from unittest.mock import MagicMock, patch
import sys

# Create mock objects
mock_conn = MagicMock()
mock_engine = MagicMock()
mock_engine.connect.return_value.__enter__ = lambda self: mock_conn
mock_engine.connect.return_value.__exit__ = lambda self, *args: None
mock_engine.dispose = MagicMock()

# Patch at the module level before importing anything from app
sys.modules['psycopg'] = MagicMock()
sys.modules['psycopg'].connect = MagicMock(return_value=mock_conn)

# Now patch sqlalchemy and import
with patch('sqlalchemy.create_engine', return_value=mock_engine):
    from app.configuration.fast_api_config import FastApiConfig
    app = FastApiConfig().get_app()
    print(json.dumps(app.openapi()))
"""
    
    try:
        with open(temp_script, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        ok = fail = 0
        try:
            result = subprocess.run(
                [sys.executable, temp_script],
                capture_output=True, text=True, timeout=120,  # Increased to 120 seconds
                cwd=root_dir,
            )
            if result.returncode != 0:
                err = result.stderr.strip().splitlines()
                last = "\n".join(err[-5:]) if err else "(no stderr)"
                print(f"  [FAIL] backend:\n    {last}")
                fail += 1
            else:
                try:
                    spec = json.loads(result.stdout)
                    out_path = os.path.join(swagger_dir, "backend.json")
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump(spec, f, ensure_ascii=False, indent=2)
                    print(f"  [OK]   backend")
                    ok += 1
                except json.JSONDecodeError as e:
                    print(f"  [FAIL] backend: Invalid JSON output - {e}")
                    fail += 1
        except subprocess.TimeoutExpired:
            print(f"  [FAIL] backend: timed out")
            fail += 1
        except Exception as e:
            print(f"  [FAIL] backend: {e}")
            fail += 1
    finally:
        # Clean up temp script
        if os.path.exists(temp_script):
            os.remove(temp_script)

    print(f"Swagger refresh complete: {ok} ok, 0 skipped, {fail} failed\n")
    
    # If refresh failed and swagger file doesn't exist or is invalid, exit
    if fail > 0:
        swagger_path = os.path.join(swagger_dir, "backend.json")
        if not os.path.exists(swagger_path):
            print("ERROR: Swagger refresh failed and no existing swagger file found.")
            print("Cannot generate template without swagger spec.")
            sys.exit(1)
        try:
            with open(swagger_path, 'r', encoding='utf-8') as f:
                json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            print("ERROR: Swagger refresh failed and existing swagger file is corrupted.")
            print("Please fix or delete swagger/backend.json and try again.")
            sys.exit(1)
        print("WARNING: Swagger refresh failed but using existing swagger file.")


# ── helpers ────────────────────────────────────────────────────────────────────

def pascal(s):
    return "".join(p.capitalize() for p in s.split("-"))


def ys(v):
    """Quote a YAML string value if it contains special characters."""
    if not isinstance(v, str):
        return str(v)
    specials = (':', '#', '[', ']', '&', '*', '!', '|', '>', "'", '"', '%', '@', '`', '{', '}')
    if any(c in v for c in specials) or v.strip() != v or v in ('true', 'false', 'null', 'yes', 'no') or v == '':
        return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return v


def lambda_uri_sub(service):
    fn = "cd-backend-${Environment}-lambda"
    return ('"arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/'
            'arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:' + fn + '/invocations"')


# ── main ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--skip-refresh", action="store_true", help="Skip swagger refresh, use existing JSON files")
args = parser.parse_args()

if not args.skip_refresh:
    refresh_swagger()

# ── collect all methods per path from swagger/backend.json ────────────────────
all_paths = {}   # path -> {method: op}
path_file = "swagger/backend.json"
if os.path.exists(path_file):
    try:
        with open(path_file, encoding="utf-8") as f:
            spec = json.load(f)
        for path, path_item in spec.get("paths", {}).items():
            if any(path.startswith(p) for p in SKIP_PREFIXES):
                continue
            methods = {m: path_item[m] for m in HTTP_METHODS if m in path_item}
            if methods:
                all_paths[path] = methods
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"ERROR: Failed to read {path_file}: {e}")
        print("The swagger file may be corrupted. Please fix it or delete it and regenerate.")
        sys.exit(1)

# ── build YAML lines ──────────────────────────────────────────────────────────
lines = []


def L(s=""):
    lines.append(s)


# ── header ────────────────────────────────────────────────────────────────────
L("AWSTemplateFormatVersion: '2010-09-09'")
L("Transform: AWS::Serverless-2016-10-31")
L()
L("Parameters:")
L(I[1] + "Environment:")
L(I[2] + "Type: String")
L(I[2] + "Default: dev")
L(I[2] + "AllowedValues:")
L(I[3] + "- dev")
L(I[3] + "- stag")
L(I[3] + "- prod")
L(I[2] + "Description: Deployment environment")
L()
L(I[1] + "HostedZoneId:")
L(I[2] + "Type: String")
L(I[2] + "Description: Route53 Hosted Zone ID for jcampos.dev (resolved at deploy time)")
L()
L("Resources:")
L()

# ── log group ─────────────────────────────────────────────────────────────────
L(I[1] + "ApiGatewayLogGroup:")
L(I[2] + "Type: AWS::Logs::LogGroup")
L(I[2] + "Properties:")
L(I[3] + 'LogGroupName: !Sub "/aws/apigateway/tsuru-${Environment}-cd-backend-api"')
L(I[3] + "RetentionInDays: 14")
L()

# ── API Gateway Account (sets CloudWatch role for logging) ────────────────────
L(I[1] + "ApiGatewayAccount:")
L(I[2] + "Type: AWS::ApiGateway::Account")
L(I[2] + "Properties:")
L(I[3] + "CloudWatchRoleArn:")
L(I[4] + 'Fn::ImportValue: !Sub "tsuru-${Environment}-apigateway-cloudwatch-role-arn"')
L()

# ── API ───────────────────────────────────────────────────────────────────────
L(I[1] + "ApiGatewayRestApi:")
L(I[2] + "Type: AWS::Serverless::Api")
L(I[2] + "Properties:")
L(I[3] + 'Name: !Sub "tsuru-${Environment}-cd-backend-api"')
L(I[3] + "StageName: !Ref Environment")
L(I[3] + "AccessLogSetting:")
L(I[4] + "DestinationArn: !GetAtt ApiGatewayLogGroup.Arn")
L(I[4] + "Format: '$context.requestId $context.requestTime $context.httpMethod"
   " $context.resourcePath $context.status $context.responseLength $context.error.message'")
L(I[3] + "MethodSettings:")
L(I[4] + "- ResourcePath: '/*'")
L(I[5] + "HttpMethod: '*'")
L(I[5] + "LoggingLevel: INFO")
L(I[5] + "DataTraceEnabled: true")
L(I[5] + "MetricsEnabled: true")

# ── DefinitionBody ────────────────────────────────────────────────────────────
L(I[3] + "DefinitionBody:")
L(I[4] + "openapi: '3.0.1'")
L(I[4] + "info:")
L(I[5] + 'title: !Sub "tsuru-${Environment}-cd-backend-api"')
L(I[5] + "description: Cross-Docking Backend API")
L(I[5] + "version: '1.0.0'")
L(I[4] + "servers:")
L(I[5] + "- url: 'https://" + CUSTOM_DOMAIN + "'")
L(I[6] + "x-amazon-apigateway-endpoint-configuration:")
L(I[7] + "disableExecuteApiEndpoint: true")

# security scheme
L(I[4] + "components:")
L(I[5] + "securitySchemes:")
L(I[6] + "CognitoAuthorizer:")
L(I[7] + "type: apiKey")
L(I[7] + "name: Authorization")
L(I[7] + "in: header")
L(I[7] + "x-amazon-apigateway-authtype: cognito_user_pools")
L(I[7] + "x-amazon-apigateway-authorizer:")
L(I[8] + "type: cognito_user_pools")
L(I[8] + "providerARNs:")
L(I[9] + '- Fn::ImportValue: "' + COGNITO_ARN_EXPORT + '"')

# paths
L(I[4] + "paths:")

for path in sorted(all_paths.keys()):
    methods = all_paths[path]   # {method: op}
    service = "backend"
    allowed_methods = ",".join(m.upper() for m in methods) + ",OPTIONS"

    L(I[5] + ys(path) + ":")

    for method, op in methods.items():
        path_params = [p for p in op.get("parameters", []) if p.get("in") == "path"]
        query_params = [p for p in op.get("parameters", []) if p.get("in") == "query"]
        summary = op.get("summary", "")
        op_id = service + "_" + op.get("operationId", method)

        L(I[6] + method + ":")
        L(I[7] + "operationId: " + ys(op_id))
        if summary:
            L(I[7] + "summary: " + ys(summary))
        if path_params or query_params:
            L(I[7] + "parameters:")
            for p in path_params + query_params:
                req = "true" if p.get("required") else "false"
                ptype = (p.get("schema") or {}).get("type", "string")
                L(I[8] + "- name: " + ys(p["name"]))
                L(I[9] + "in: " + p["in"])
                L(I[9] + "required: " + req)
                L(I[9] + "schema:")
                L(I[9] + "  type: " + ptype)
        if method in ("post", "put", "patch"):
            L(I[7] + "requestBody:")
            L(I[8] + "required: true")
            L(I[8] + "content:")
            L(I[9] + "application/json:")
            L(I[10] + "schema:")
            L(I[11] + "type: object")
        L(I[7] + "responses:")
        L(I[8] + "'200':")
        L(I[9] + "description: OK")
        L(I[9] + "headers:")
        L(I[9] + "  Access-Control-Allow-Origin:")
        L(I[9] + "    schema:")
        L(I[9] + "      type: string")
        L(I[8] + "'400':")
        L(I[9] + "description: Bad Request")
        L(I[8] + "'404':")
        L(I[9] + "description: Not Found")
        if REQUIRE_AUTH:
            L(I[7] + "security:")
            L(I[8] + "- CognitoAuthorizer: []")
        L(I[7] + "x-amazon-apigateway-integration:")
        L(I[8] + "httpMethod: POST")
        L(I[8] + "uri: !Sub " + lambda_uri_sub(service))
        L(I[8] + "passthroughBehavior: when_no_match")
        L(I[8] + "contentHandling: CONVERT_TO_TEXT")
        L(I[8] + "type: aws_proxy")
        L(I[8] + "requestParameters:")
        L(I[9] + "integration.request.header.x-user-id: context.authorizer.claims.sub")

    # OPTIONS (CORS preflight) — allowed methods derived from actual path methods
    L(I[6] + "options:")
    L(I[7] + "responses:")
    L(I[8] + "'200':")
    L(I[9] + "description: CORS OK")
    L(I[9] + "headers:")
    for hdr in ("Access-Control-Allow-Origin", "Access-Control-Allow-Methods", "Access-Control-Allow-Headers"):
        L(I[9] + "  " + hdr + ":")
        L(I[9] + "    schema:")
        L(I[9] + "      type: string")
    L(I[7] + "x-amazon-apigateway-integration:")
    L(I[8] + "type: mock")
    L(I[8] + "requestTemplates:")
    L(I[9] + 'application/json: \'{"statusCode": 200}\'')
    L(I[8] + "responses:")
    L(I[9] + "default:")
    L(I[9] + "  statusCode: '200'")
    L(I[9] + "  responseParameters:")
    L(I[9] + "    method.response.header.Access-Control-Allow-Headers:"
       " \"'" + CORS_ALLOW_HEADERS + "'\"")
    L(I[9] + "    method.response.header.Access-Control-Allow-Methods: \"'" + allowed_methods + "'\"")
    L(I[9] + "    method.response.header.Access-Control-Allow-Origin: \"'*'\"")

L()

# ── CORS gateway responses ────────────────────────────────────────────────────
for rtype in ("DEFAULT_4XX", "DEFAULT_5XX", "UNAUTHORIZED", "ACCESS_DENIED"):
    rname = "GatewayResponse" + rtype.replace("_", "")
    L(I[1] + rname + ":")
    L(I[2] + "Type: AWS::ApiGateway::GatewayResponse")
    L(I[2] + "Properties:")
    L(I[3] + "ResponseParameters:")
    L(I[4] + "gatewayresponse.header.Access-Control-Allow-Headers:"
       " \"'" + CORS_ALLOW_HEADERS + "'\"")
    L(I[4] + "gatewayresponse.header.Access-Control-Allow-Methods: \"'GET,POST,PUT,PATCH,DELETE,OPTIONS'\"")
    L(I[4] + "gatewayresponse.header.Access-Control-Allow-Origin: \"'*'\"")
    L(I[3] + "ResponseType: " + rtype)
    L(I[3] + "RestApiId: !Ref ApiGatewayRestApi")
    L()

# ── SSL certificate ───────────────────────────────────────────────────────────
L(I[1] + "ApiCertificate:")
L(I[2] + "Type: AWS::CertificateManager::Certificate")
L(I[2] + "Properties:")
L(I[3] + "DomainName: " + CUSTOM_DOMAIN)
L(I[3] + "ValidationMethod: DNS")
L(I[3] + "DomainValidationOptions:")
L(I[4] + "- DomainName: " + CUSTOM_DOMAIN)
L(I[5] + "HostedZoneId: !Ref HostedZoneId")
L()

# ── custom domain (v2 — maps to root /) ──────────────────────────────────────
L(I[1] + "ApiDomainName:")
L(I[2] + "Type: AWS::ApiGatewayV2::DomainName")
L(I[2] + "Properties:")
L(I[3] + "DomainName: " + CUSTOM_DOMAIN)
L(I[3] + "DomainNameConfigurations:")
L(I[4] + "- EndpointType: REGIONAL")
L(I[5] + "CertificateArn: !Ref ApiCertificate")
L()

# ── API mapping — no ApiMappingKey = root / ───────────────────────────────────
L(I[1] + "ApiMapping:")
L(I[2] + "Type: AWS::ApiGatewayV2::ApiMapping")
L(I[2] + "Properties:")
L(I[3] + "ApiId: !Ref ApiGatewayRestApi")
L(I[3] + "DomainName: !Ref ApiDomainName")
L(I[3] + "Stage: !Ref Environment")
L()

# ── Route53 record ────────────────────────────────────────────────────────────
L(I[1] + "ApiDnsRecord:")
L(I[2] + "Type: AWS::Route53::RecordSet")
L(I[2] + "Properties:")
L(I[3] + "HostedZoneId: !Ref HostedZoneId")
L(I[3] + "Name: " + CUSTOM_DOMAIN)
L(I[3] + "Type: A")
L(I[3] + "AliasTarget:")
L(I[4] + "DNSName: !GetAtt ApiDomainName.RegionalDomainName")
L(I[4] + "HostedZoneId: !GetAtt ApiDomainName.RegionalHostedZoneId")
L()

# ── Lambda invoke permission ──────────────────────────────────────────────────
L(I[1] + "LambdaPermissionBackend:")
L(I[2] + "Type: AWS::Lambda::Permission")
L(I[2] + "Properties:")
L(I[3] + 'FunctionName: !Sub "cd-backend-${Environment}-lambda"')
L(I[3] + "Action: lambda:InvokeFunction")
L(I[3] + "Principal: apigateway.amazonaws.com")
L(I[3] + 'SourceArn: !Sub "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${ApiGatewayRestApi}/*"')
L()

# ── Outputs ───────────────────────────────────────────────────────────────────
L("Outputs:")
L(I[1] + "ApiId:")
L(I[2] + "Description: API Gateway ID")
L(I[2] + "Value: !Ref ApiGatewayRestApi")
L(I[2] + "Export:")
L(I[3] + 'Name: !Sub "${AWS::StackName}-ApiId"')
L()
L(I[1] + "ApiEndpoint:")
L(I[2] + "Description: Custom domain endpoint")
L(I[2] + "Value: https://" + CUSTOM_DOMAIN)
L(I[2] + "Export:")
L(I[3] + 'Name: !Sub "${AWS::StackName}-ApiEndpoint"')
L()
L(I[1] + "ApiInvokeUrl:")
L(I[2] + "Description: Direct invoke URL")
L(I[2] + 'Value: !Sub "https://${ApiGatewayRestApi}.execute-api.${AWS::Region}.amazonaws.com/${Environment}"')
L(I[2] + "Export:")
L(I[3] + 'Name: !Sub "${AWS::StackName}-ApiInvokeUrl"')

# ── write template ────────────────────────────────────────────────────────────
os.makedirs("api-gateway", exist_ok=True)
out = "\n".join(lines)
with open("api-gateway/template.yml", "w", encoding="utf-8") as f:
    f.write(out)

total_ops = sum(len(m) for m in all_paths.values())
print(f"Generated api-gateway/template.yml")
print(f"  Lines     : {len(lines)}")
print(f"  Paths     : {len(all_paths)}")
print(f"  Operations: {total_ops}")

# ── generate endpoints.json ───────────────────────────────────────────────────
BASE_URL = "https://" + CUSTOM_DOMAIN
JSON_SKIP = tuple(SKIP_PREFIXES)


def _infer_type(value):
    if value is None:
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _extract_fields(example):
    if not isinstance(example, dict):
        return []
    fields = []
    for key, val in example.items():
        field = {"name": key, "type": _infer_type(val), "nullable": val is None}
        if isinstance(val, dict):
            field["fields"] = _extract_fields(val)
        elif isinstance(val, list) and val and isinstance(val[0], dict):
            field["item_fields"] = _extract_fields(val[0])
        fields.append(field)
    return fields


def _extract_response(op):
    resp200 = op.get("responses", {}).get("200", {})
    content = resp200.get("content", {}).get("application/json", {})
    example = content.get("example")
    if example is None:
        return {"is_list": False, "fields": []}
    if isinstance(example, list):
        return {
            "is_list": True,
            "fields": _extract_fields(example[0]) if example and isinstance(example[0], dict) else [],
        }
    return {
        "is_list": False,
        "fields": _extract_fields(example) if isinstance(example, dict) else [],
    }


endpoints_json = {
    "base_url": BASE_URL,
    "auth": "Authorization: Bearer <cognito-id-token>",
    "cognito_pool_arn_export": COGNITO_ARN_EXPORT,
    "services": [],
}

svc_endpoints = []
if os.path.exists(path_file):
    with open(path_file, encoding="utf-8") as f:
        spec = json.load(f)

    for path in sorted(spec.get("paths", {}).keys()):
        if any(path.startswith(s) for s in JSON_SKIP):
            continue
        path_item = spec["paths"][path]
        for method in HTTP_METHODS:
            if method not in path_item:
                continue
            op = path_item[method]
            params = op.get("parameters", [])
            path_params = [
                {
                    "name": p["name"],
                    "type": (p.get("schema") or {}).get("type", "string"),
                    "required": bool(p.get("required")),
                    "description": p.get("description", ""),
                }
                for p in params if p.get("in") == "path"
            ]
            query_params = [
                {
                    "name": p["name"],
                    "type": (p.get("schema") or {}).get("type", "string"),
                    "required": bool(p.get("required")),
                    "description": p.get("description", ""),
                }
                for p in params if p.get("in") == "query"
            ]
            svc_endpoints.append({
                "path": path,
                "method": method.upper(),
                "operation_id": op.get("operationId", ""),
                "summary": op.get("summary", ""),
                "description": op.get("description", ""),
                "path_params": path_params,
                "query_params": query_params,
                "response": _extract_response(op),
            })

if svc_endpoints:
    endpoints_json["services"].append({"name": "backend", "endpoints": svc_endpoints})

with open("api-gateway/endpoints.json", "w", encoding="utf-8") as f:
    json.dump(endpoints_json, f, ensure_ascii=False, indent=2)

total_eps = sum(len(s["endpoints"]) for s in endpoints_json["services"])
print(f"Generated api-gateway/endpoints.json  ({len(endpoints_json['services'])} services, {total_eps} endpoints)")
