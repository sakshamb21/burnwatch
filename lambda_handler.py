"""AWS Lambda entry point for BurnWatch.

Wraps the FastAPI application with Mangum so it can be triggered by
API Gateway (HTTP API v2 or REST API v1) without any code changes to
the core application.

Environment variables expected in Lambda:
    BURNWATCH_STORAGE=aws
    AWS_S3_BUCKET=bucket-nakulproj
    AWS_DYNAMODB_TABLE=table_nakulproj
    AWS_REGION=us-east-1         (set automatically by Lambda runtime)
    BURNWATCH_DATA_SOURCE=cansat  (or simulated)
"""

from mangum import Mangum

from burnwatch.api.app import create_app

# Build the ASGI app once at module load time (cold start only).
_app = create_app()

# Mangum translates API Gateway events into ASGI scope.
handler = Mangum(_app, lifespan="off")
