"""Unit tests for AWSStorageAdapter using mocked boto3 clients."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock

import pytest

from burnwatch.aws.adapter import AWSStorageAdapter
from burnwatch.incidents.models import Incident
from burnwatch.models.observation import (
    NormalizedObservation,
    RawObservation,
    SourceMode,
)


@pytest.fixture
def mock_s3() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_dynamodb() -> MagicMock:
    mock_res = MagicMock()
    mock_table = MagicMock()
    mock_res.Table.return_value = mock_table
    return mock_res


@pytest.fixture
def aws_adapter(mock_s3: MagicMock, mock_dynamodb: MagicMock) -> AWSStorageAdapter:
    return AWSStorageAdapter(
        s3_bucket="test-burnwatch-bucket",
        dynamodb_table="test-incidents-table",
        region="us-east-1",
        s3_client=mock_s3,
        dynamodb_resource=mock_dynamodb,
    )


class TestAWSStorageAdapter:
    """Tests for AWS adapter operations using mocked AWS clients."""

    def test_missing_bucket_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="s3_bucket"):
            AWSStorageAdapter(s3_bucket="", dynamodb_table="tbl")

    def test_missing_table_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="dynamodb_table"):
            AWSStorageAdapter(s3_bucket="bkt", dynamodb_table="")

    def test_save_observation_puts_to_s3(
        self, aws_adapter: AWSStorageAdapter, mock_s3: MagicMock
    ) -> None:
        raw = RawObservation(
            device_id="cansat-01",
            sequence=10,
            device_time_ms=10000,
            mq135_raw=300,
            gps_fix=True,
            satellites=7,
        )
        obs = NormalizedObservation.from_raw(raw, SourceMode.CANSAT)

        saved, is_new = aws_adapter.save_observation(obs)
        assert is_new is True
        assert saved.observation_id == obs.observation_id

        # Verify put_object was called
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-burnwatch-bucket"
        assert "observations/cansat-01/00000010_" in call_kwargs["Key"]
        assert call_kwargs["ContentType"] == "application/json"

    def test_get_observation_from_s3(
        self, aws_adapter: AWSStorageAdapter, mock_s3: MagicMock
    ) -> None:
        raw = RawObservation(
            device_id="cansat-01",
            sequence=5,
            device_time_ms=5000,
            mq135_raw=300,
            gps_fix=True,
            satellites=6,
        )
        obs = NormalizedObservation.from_raw(raw, SourceMode.CANSAT)
        body_bytes = obs.model_dump_json().encode("utf-8")

        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": f"observations/cansat-01/00000005_{obs.observation_id}.json"}
            ]
        }
        mock_s3.get_object.return_value = {"Body": io.BytesIO(body_bytes)}

        fetched = aws_adapter.get_observation(obs.observation_id)
        assert fetched is not None
        assert fetched.observation_id == obs.observation_id
        assert fetched.sequence == 5

    def test_save_incident_puts_to_dynamodb(
        self, aws_adapter: AWSStorageAdapter, mock_dynamodb: MagicMock
    ) -> None:
        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.0,
        )
        aws_adapter.save_incident(inc)

        mock_dynamodb.Table.return_value.put_item.assert_called_once()
        item = mock_dynamodb.Table.return_value.put_item.call_args[1]["Item"]
        assert item["incident_id"] == inc.incident_id
        assert item["status"] == "candidate"

    def test_get_incident_from_dynamodb(
        self, aws_adapter: AWSStorageAdapter, mock_dynamodb: MagicMock
    ) -> None:
        inc = Incident(
            device_id="cansat-01",
            source_mode=SourceMode.CANSAT,
            trigger_observation_id="obs-1",
            peak_mq135=600,
            peak_anomaly_score=4.0,
        )
        item_data = json.loads(inc.model_dump_json())
        mock_dynamodb.Table.return_value.get_item.return_value = {"Item": item_data}

        fetched = aws_adapter.get_incident(inc.incident_id)
        assert fetched is not None
        assert fetched.incident_id == inc.incident_id
        assert fetched.device_id == "cansat-01"

    def test_get_incident_not_found(
        self, aws_adapter: AWSStorageAdapter, mock_dynamodb: MagicMock
    ) -> None:
        mock_dynamodb.Table.return_value.get_item.return_value = {}
        fetched = aws_adapter.get_incident("missing-id")
        assert fetched is None
