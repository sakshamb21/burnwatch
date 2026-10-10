"""Create IAM role for Lambda, upload ZIP to S3, and deploy/update the Lambda function.

Run after build_lambda.py has produced lambda_package.zip.
"""

import json
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = "830523817267"
BUCKET = "bucket-nakulproj"
TABLE = "table_nakulproj"
FUNCTION_NAME = "burnwatch-api"
ROLE_NAME = "BurnWatchLambdaRole"
ZIP_PATH = Path(__file__).parent / "lambda_package.zip"

iam = boto3.client("iam", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
apigateway = boto3.client("apigatewayv2", region_name=REGION)

# ──────────────────────────────────────────────────────────────────────────────
# 1. IAM Role
# ──────────────────────────────────────────────────────────────────────────────
TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}

ACCESS_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "S3Access",
            "Effect": "Allow",
            "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
            "Resource": [
                f"arn:aws:s3:::{BUCKET}",
                f"arn:aws:s3:::{BUCKET}/*",
            ],
        },
        {
            "Sid": "DynamoDBAccess",
            "Effect": "Allow",
            "Action": [
                "dynamodb:PutItem",
                "dynamodb:GetItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
                "dynamodb:Scan",
                "dynamodb:Query",
            ],
            "Resource": [
                f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{TABLE}",
                f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{TABLE}/index/*",
            ],
        },
        {
            "Sid": "CloudWatchLogs",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
            ],
            "Resource": "arn:aws:logs:*:*:*",
        },
    ],
}

print("Step 1: Creating IAM role...")
role_arn = None
try:
    resp = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
        Description="BurnWatch Lambda execution role",
    )
    role_arn = resp["Role"]["Arn"]
    print(f"  Role created: {role_arn}")
except ClientError as e:
    if e.response["Error"]["Code"] == "EntityAlreadyExists":
        role_arn = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
        print(f"  Role already exists: {role_arn}")
    else:
        raise

# Attach inline policy
iam.put_role_policy(
    RoleName=ROLE_NAME,
    PolicyName="BurnWatchAccess",
    PolicyDocument=json.dumps(ACCESS_POLICY),
)
print("  Policy attached.")

# Short wait for IAM propagation
print("  Waiting 10s for IAM propagation...")
time.sleep(10)

# ──────────────────────────────────────────────────────────────────────────────
# 2. Upload ZIP to S3 (avoids 50MB direct upload limit)
# ──────────────────────────────────────────────────────────────────────────────
print("Step 2: Uploading deployment package to S3...")
s3_key = "lambda/burnwatch-api.zip"
s3.upload_file(str(ZIP_PATH), BUCKET, s3_key)
size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
print(f"  Uploaded {ZIP_PATH.name} ({size_mb:.1f} MB) to s3://{BUCKET}/{s3_key}")

# ──────────────────────────────────────────────────────────────────────────────
# 3. Create or update Lambda function
# ──────────────────────────────────────────────────────────────────────────────
ENV_VARS = {
    "BURNWATCH_STORAGE": "aws",
    "AWS_S3_BUCKET": BUCKET,
    "AWS_DYNAMODB_TABLE": TABLE,
    # AWS_REGION is reserved and auto-injected by the Lambda runtime
    "BURNWATCH_DATA_SOURCE": "cansat",
    "BURNWATCH_LOG_LEVEL": "INFO",
}

print("Step 3: Deploying Lambda function...")
try:
    resp = lam.create_function(
        FunctionName=FUNCTION_NAME,
        Runtime="python3.11",
        Role=role_arn,
        Handler="lambda_handler.handler",
        Code={"S3Bucket": BUCKET, "S3Key": s3_key},
        Timeout=15,
        MemorySize=256,
        Environment={"Variables": ENV_VARS},
        Description="BurnWatch FastAPI backend via Mangum",
    )
    print(f"  Lambda created: {resp['FunctionArn']}")
    function_arn = resp["FunctionArn"]
except ClientError as e:
    if e.response["Error"]["Code"] == "ResourceConflictException":
        print("  Function exists -- updating code...")
        lam.update_function_code(
            FunctionName=FUNCTION_NAME,
            S3Bucket=BUCKET,
            S3Key=s3_key,
        )
        # Wait for code update to finish before changing config
        print("  Waiting for code update to settle...")
        lam.get_waiter("function_updated").wait(FunctionName=FUNCTION_NAME)
        lam.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Environment={"Variables": ENV_VARS},
            Timeout=15,
            MemorySize=256,
        )
        function_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}"
        print(f"  Lambda updated: {function_arn}")
    else:
        raise

# Wait for function to become Active
print("  Waiting for Lambda to become Active...")
waiter = lam.get_waiter("function_active")
waiter.wait(FunctionName=FUNCTION_NAME)
print("  Lambda is Active.")

# ──────────────────────────────────────────────────────────────────────────────
# 4. Create API Gateway (HTTP API v2) → Lambda integration
# ──────────────────────────────────────────────────────────────────────────────
print("Step 4: Setting up API Gateway (HTTP API)...")

# Check if API already exists
existing_apis = apigateway.get_apis()
api_id = None
for api in existing_apis.get("Items", []):
    if api["Name"] == "burnwatch-http-api":
        api_id = api["ApiId"]
        print(f"  API Gateway already exists: {api_id}")
        break

if api_id is None:
    api_resp = apigateway.create_api(
        Name="burnwatch-http-api",
        ProtocolType="HTTP",
        CorsConfiguration={
            "AllowOrigins": ["*"],
            "AllowMethods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "AllowHeaders": ["Content-Type", "Authorization", "X-BurnWatch-Device-Key"],
        },
    )
    api_id = api_resp["ApiId"]
    print(f"  API Gateway created: {api_id}")

# Lambda integration
integration_resp = apigateway.create_integration(
    ApiId=api_id,
    IntegrationType="AWS_PROXY",
    IntegrationUri=function_arn,
    PayloadFormatVersion="2.0",
)
integration_id = integration_resp["IntegrationId"]
print(f"  Integration created: {integration_id}")

# Catch-all route: ANY /{proxy+}
try:
    apigateway.create_route(
        ApiId=api_id,
        RouteKey="$default",
        Target=f"integrations/{integration_id}",
    )
    print("  Default route created.")
except ClientError as e:
    if "ConflictException" in str(e) or "already exists" in str(e).lower():
        print("  Default route already exists.")
    else:
        raise

# Auto-deploy stage
try:
    stage_resp = apigateway.create_stage(
        ApiId=api_id,
        StageName="$default",
        AutoDeploy=True,
    )
    print("  Stage created.")
except ClientError as e:
    if "ConflictException" in str(e) or "already exists" in str(e).lower():
        print("  Stage already exists.")
    else:
        raise

# Grant API Gateway permission to invoke Lambda
try:
    lam.add_permission(
        FunctionName=FUNCTION_NAME,
        StatementId="APIGatewayInvoke",
        Action="lambda:InvokeFunction",
        Principal="apigateway.amazonaws.com",
        SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{api_id}/*/*",
    )
    print("  Lambda invoke permission granted.")
except ClientError as e:
    if "ResourceConflictException" in str(e):
        print("  Lambda permission already exists.")
    else:
        raise

api_url = f"https://{api_id}.execute-api.{REGION}.amazonaws.com"
print()
print("=" * 60)
print("DEPLOYMENT COMPLETE")
print("=" * 60)
print(f"  API URL:   {api_url}")
print(f"  Health:    {api_url}/health")
print(f"  Dashboard: {api_url}/")
print(f"  S3 Bucket: {BUCKET}")
print(f"  DynamoDB:  {TABLE}")
print(f"  Lambda:    {FUNCTION_NAME}")
print("=" * 60)
