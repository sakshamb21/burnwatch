# BurnWatch — Next Steps

This checklist covers the work needed to take the current local prototype toward a safe field deployment. It intentionally does **not** prescribe an advanced GUI; the current frontend is only a temporary way to exercise the API.

## 1. Verify the local prototype

- Install the project and development dependencies: `pip install -e ".[dev]"`.
- Start the local service with `burnwatch api`, then open `http://127.0.0.1:8000`.
- Use the page to test health, telemetry submission, observation filtering, community-report submission, incident review, status changes, and audit history.
- Use **Create test incident** to run the complete simulated detector-to-incident workflow. Simulated incidents must not be confirmed; this is an intentional safety control.
- Run `pytest` and resolve any failures before changing deployment infrastructure.

## 2. Connect and validate the physical CanSat

- Freeze and document the on-wire telemetry format, device identity, sequence-number behavior, timestamps, and retry behaviour.
- Ground-station/serial ingestion path implemented and tested using `CanSatLiveSource` and `burnwatch live`.
- Calibrate, warm up, and log the MQ135 sensor’s operating conditions. Keep the product language clear: it detects relative changes, not pollutant identity or legal proof.
- Exercise loss of GPS fix, duplicate packets, gaps, stale data, sensor range errors, receiver restarts, and offline buffering with real hardware.
- Establish a repeatable field-test procedure and compare telemetry against a documented reference or investigation process.

## 3. Prepare AWS and access controls

- Choose the AWS account, region, naming convention, budget alerts, and separate development/staging/production environments.
- Configure AWS authentication for people and workloads through IAM Identity Center or role assumption; do not use long-lived credentials in source code or `.env` files.
- Create least-privilege execution roles for the API/Lambda, telemetry publisher, deployment pipeline, and operations staff.
- Configure `AWS_REGION`, `AWS_S3_BUCKET`, and `AWS_DYNAMODB_TABLE` only through deployment environment configuration or a secrets/configuration service.
- Install the optional cloud dependency with `pip install -e ".[aws]` for AWS integration work.

## 4. Build the cloud infrastructure

- Define the infrastructure as code (for example CDK, SAM, Terraform, or CloudFormation) and keep it under version control.
- Create an encrypted S3 bucket for raw observation payloads, with public access blocked, versioning as appropriate, lifecycle/retention rules, and access logging.
- Create the DynamoDB incident table, select the primary key and any required status/time indexes, enable encryption and point-in-time recovery, and define retention/backup policy.
- Package the FastAPI service for Lambda (adapter or container) and place API Gateway in front of it. Set timeouts, memory, concurrency, request limits, and payload limits deliberately.
- Configure CORS only for the deployed frontend origins. Do not expose the local development API publicly.
- Decide whether community reports, raw telemetry, and audit history need separate tables/objects or a dedicated event queue.
- Add a dead-letter/retry path for telemetry delivery and validate idempotency across retries.

## 5. Complete the backend’s cloud integration

- Add a production storage-selection configuration path; the current settings expose SQLite only, even though the AWS storage adapter exists.
- Verify that the AWS adapter satisfies every production query and pagination requirement. S3 prefix scans and DynamoDB scans need scalable index/key designs before production use.
- Add end-to-end tests against an isolated AWS test environment (or local AWS-compatible test tooling), covering S3 writes, DynamoDB writes, retries, IAM denial, and recovery.
- Decide and document the expected behavior during cloud failures. Any local fallback must preserve provenance, avoid data loss, and reconcile safely when connectivity returns.
- Version API routes, request/response schemas, and telemetry payloads before external devices integrate.

## 6. Secure the deployed API

- Add authentication and authorization at API Gateway and/or the application layer. Separate telemetry-ingest, reviewer, administrator, and read-only permissions.
- Protect public report submission with abuse controls such as throttling, input limits, CAPTCHA or a trusted submission channel, and moderation workflow where needed.
- Enforce HTTPS, request size/rate limits, secure headers, and strict CORS.
- Store only necessary personal data, define report/contact retention, and document consent, privacy, access, and deletion policies.
- Send structured audit logs to CloudWatch; never record credentials or unnecessary personal information.

## 7. Operate, observe, and recover

- Add CloudWatch dashboards and alarms for errors, latency, throttling, Lambda failures, S3/DynamoDB access errors, ingestion rate, anomaly rate, and incident-state changes.
- Set a budget alarm and recurring cost review for S3, DynamoDB, Lambda, API Gateway, logging, and data transfer.
- Define operational runbooks for detector anomalies, sensor failure, missing telemetry, false reports, access incidents, data recovery, and service rollback.
- Set backup, restore, disaster-recovery, and retention objectives; test restoration rather than merely enabling backups.
- Establish who is allowed to review, confirm, resolve, and monitor incidents, and how field evidence is attached to a decision.

## 8. Delivery quality and release process

- Add CI for formatting/linting, tests, dependency/security checks, package builds, and infrastructure validation.
- Keep environment configuration and deployment artifacts separate from application code; use reviewed pull requests and protected deployment environments.
- Add load, resilience, and security testing before real telemetry or public reports are accepted.
- Run a controlled pilot with clearly labeled simulated versus live data and collect feedback from reviewers and field operators.
- Define readiness criteria for production, including successful hardware tests, cloud recovery tests, access review, monitoring, privacy review, and incident-process approval.

## Advanced GUI (deferred)

Advanced GUI.
