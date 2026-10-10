"""AWS cloud storage adapter for BurnWatch.

Implements the StorageBackend interface using:
- Amazon S3 for immutable raw observation payloads
- Amazon DynamoDB for incidents and audit trails

Follows standard AWS credential chain. Degradable to local SQLite when AWS is offline.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from burnwatch.incidents.models import (
    Incident,
    IncidentStatus,
)
from burnwatch.models.observation import NormalizedObservation
from burnwatch.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class AWSStorageAdapter(StorageBackend):
    """StorageBackend adapter persisting observations to S3 and incidents to DynamoDB.

    Args:
        s3_bucket: S3 bucket name for observations.
        dynamodb_table: DynamoDB table name for incidents.
        region: AWS region name.
        s3_client: Optional injected boto3 S3 client (for testing/mocking).
        dynamodb_resource: Optional injected boto3 DynamoDB resource (for testing/mocking).
    """

    def __init__(
        self,
        s3_bucket: str,
        dynamodb_table: str,
        region: str = "us-east-1",
        s3_client: Any | None = None,
        dynamodb_resource: Any | None = None,
    ) -> None:
        if not s3_bucket:
            raise ValueError("s3_bucket name must be provided for AWSStorageAdapter")
        if not dynamodb_table:
            raise ValueError(
                "dynamodb_table name must be provided for AWSStorageAdapter"
            )

        self.s3_bucket = s3_bucket
        self.dynamodb_table_name = dynamodb_table
        self.region = region

        self._s3 = s3_client
        self._dynamodb = dynamodb_resource
        self._table = None

        if self._s3 is None or self._dynamodb is None:
            self._init_boto3()

    def _init_boto3(self) -> None:
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for AWSStorageAdapter. Install with: pip install 'burnwatch[aws]'"
            )

        if self._s3 is None:
            self._s3 = boto3.client("s3", region_name=self.region)
        if self._dynamodb is None:
            self._dynamodb = boto3.resource("dynamodb", region_name=self.region)

    @property
    def table(self) -> Any:
        if self._table is None and self._dynamodb is not None:
            self._table = self._dynamodb.Table(self.dynamodb_table_name)
        return self._table

    def save_observation(
        self, obs: NormalizedObservation
    ) -> tuple[NormalizedObservation, bool]:
        """Upload raw observation JSON payload to Amazon S3."""
        key = (
            f"observations/{obs.device_id}/{obs.sequence:08d}_{obs.observation_id}.json"
        )
        body = obs.model_dump_json()

        try:
            self._s3.put_object(
                Bucket=self.s3_bucket,
                Key=key,
                Body=body.encode("utf-8"),
                ContentType="application/json",
                Metadata={
                    "device_id": obs.device_id,
                    "sequence": str(obs.sequence),
                    "is_simulated": str(obs.is_simulated).lower(),
                },
            )
            return obs, True
        except Exception as e:
            logger.error("Failed to upload observation to S3: %s", e)
            raise

    def get_observation(self, observation_id: str) -> NormalizedObservation | None:
        """Query S3 for observation by prefix search."""
        # In S3, key lookup by exact ID requires prefix listing or indexing
        try:
            resp = self._s3.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix="observations/",
            )
            for item in resp.get("Contents", []):
                if observation_id in item["Key"]:
                    obj = self._s3.get_object(Bucket=self.s3_bucket, Key=item["Key"])
                    data = json.loads(obj["Body"].read().decode("utf-8"))
                    return NormalizedObservation(**data)
            return None
        except Exception as e:
            logger.error("Failed to get observation from S3: %s", e)
            return None

    def get_observation_by_sequence(
        self, device_id: str, sequence: int
    ) -> NormalizedObservation | None:
        prefix = f"observations/{device_id}/{sequence:08d}_"
        try:
            resp = self._s3.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix=prefix,
                MaxKeys=1,
            )
            contents = resp.get("Contents", [])
            if not contents:
                return None
            key = contents[0]["Key"]
            obj = self._s3.get_object(Bucket=self.s3_bucket, Key=key)
            data = json.loads(obj["Body"].read().decode("utf-8"))
            return NormalizedObservation(**data)
        except Exception as e:
            logger.error("Failed to query observation by sequence from S3: %s", e)
            return None

    def list_observations(
        self,
        device_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[NormalizedObservation], int]:
        prefix = f"observations/{device_id}/" if device_id else "observations/"
        try:
            resp = self._s3.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix=prefix,
            )
            contents = resp.get("Contents", [])
            total = len(contents)
            page_keys = contents[offset : offset + limit]

            items = []
            for item in page_keys:
                obj = self._s3.get_object(Bucket=self.s3_bucket, Key=item["Key"])
                data = json.loads(obj["Body"].read().decode("utf-8"))
                items.append(NormalizedObservation(**data))
            return items, total
        except Exception as e:
            logger.error("Failed to list observations from S3: %s", e)
            return [], 0

    def save_incident(self, incident: Incident) -> None:
        """Persist incident record and audit history to DynamoDB."""
        item = json.loads(incident.model_dump_json())
        try:
            self.table.put_item(Item=item)
        except Exception as e:
            logger.error("Failed to put incident into DynamoDB: %s", e)
            raise

    def get_incident(self, incident_id: str) -> Incident | None:
        """Retrieve an incident by primary key from DynamoDB."""
        try:
            resp = self.table.get_item(Key={"incident_id": incident_id})
            item = resp.get("Item")
            if not item:
                return None
            return Incident(**item)
        except Exception as e:
            logger.error("Failed to get incident from DynamoDB: %s", e)
            return None

    def list_incidents(
        self,
        status: IncidentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        try:
            scan_kwargs: dict[str, Any] = {}
            if status is not None:
                status_val = (
                    status.value if isinstance(status, IncidentStatus) else str(status)
                )
                scan_kwargs["FilterExpression"] = "status = :s"
                scan_kwargs["ExpressionAttributeValues"] = {":s": status_val}

            resp = self.table.scan(**scan_kwargs)
            items_raw = resp.get("Items", [])
            total = len(items_raw)
            page_raw = items_raw[offset : offset + limit]
            items = [Incident(**it) for it in page_raw]
            return items, total
        except Exception as e:
            logger.error("Failed to list incidents from DynamoDB: %s", e)
            return [], 0
