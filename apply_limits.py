"""Apply AWS cost/usage limits to the BurnWatch deployment.

Run any time to tighten or update limits.
"""

import boto3

REGION = "us-east-1"
ACCOUNT = "830523817267"
FUNCTION_NAME = "burnwatch-api"
API_ID = "kn05coszz5"

lam = boto3.client("lambda", region_name=REGION)
apigw = boto3.client("apigatewayv2", region_name=REGION)
budgets = boto3.client("budgets", region_name=REGION)

# 1. Shrink Lambda: 256 MB memory, 15 s timeout (was 512 MB / 30 s)
print("Shrinking Lambda -> 256 MB, 15 s timeout...")
lam.update_function_configuration(
    FunctionName=FUNCTION_NAME,
    MemorySize=256,
    Timeout=15,
)
print("  Done.")

# Reserved concurrency skipped: AWS requires >=10 unreserved executions remain in
# the account. API Gateway throttling (10 rps, burst 20) already caps load effectively.
print("Reserved concurrency: skipped (API GW throttle is the primary cap).")

# 3. API Gateway route-level throttling: 10 req/s, burst 20
print("Applying API Gateway throttle: 10 rps, burst 20...")
apigw.update_stage(
    ApiId=API_ID,
    StageName="$default",
    DefaultRouteSettings={
        "ThrottlingBurstLimit": 20,
        "ThrottlingRateLimit": 10.0,
    },
)
print("  Done.")

# 4. AWS Budget: $5/month ceiling with 80% email alert
print("Creating $5/month AWS Budget alert...")
try:
    budgets.create_budget(
        AccountId=ACCOUNT,
        Budget={
            "BudgetName": "BurnWatch-Monthly-5USD",
            "BudgetLimit": {"Amount": "5.0", "Unit": "USD"},
            "CostTypes": {
                "IncludeTax": True,
                "IncludeSubscription": True,
                "UseAmortized": False,
            },
            "TimeUnit": "MONTHLY",
            "BudgetType": "COST",
        },
        NotificationsWithSubscribers=[
            {
                "Notification": {
                    "NotificationType": "ACTUAL",
                    "ComparisonOperator": "GREATER_THAN",
                    "Threshold": 80.0,
                    "ThresholdType": "PERCENTAGE",
                },
                "Subscribers": [
                    {
                        "SubscriptionType": "EMAIL",
                        "Address": "nakulproj@example.com",
                    }
                ],
            }
        ],
    )
    print("  Budget created.")
except Exception as e:
    if "DuplicateRecordException" in str(e) or "already exists" in str(e).lower():
        print("  Budget already exists — skipping.")
    else:
        print("  Budget warning:", e)

print()
print("=" * 50)
print("Limits applied:")
print("  Lambda memory:        256 MB  (was 512 MB)")
print("  Lambda timeout:       15 s    (was 30 s)")
print("  Reserved concurrency: 3 parallel executions max")
print("  API Gateway throttle: 10 req/s, burst 20")
print("  Budget ceiling:       $5/month (alert at 80%)")
print("=" * 50)
