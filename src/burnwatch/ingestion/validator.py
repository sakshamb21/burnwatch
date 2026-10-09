"""Observation validator for ingestion pipeline.

Provides validation beyond Pydantic schema validation, including
cross-field checks and business-rule validation.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from burnwatch.models.observation import RawObservation

logger = logging.getLogger(__name__)


class ValidationResult:
    """Result of validating a raw data dict."""

    def __init__(
        self,
        is_valid: bool,
        observation: RawObservation | None = None,
        errors: list[str] | None = None,
    ) -> None:
        self.is_valid = is_valid
        self.observation = observation
        self.errors = errors or []


def validate_observation(data: dict[str, Any]) -> ValidationResult:
    """Validate a raw data dictionary against the observation schema.

    Performs Pydantic validation and additional cross-field checks.

    Args:
        data: Raw observation data dictionary.

    Returns:
        ValidationResult with status, validated observation, and any errors.
    """
    errors: list[str] = []

    # Basic type check
    if not isinstance(data, dict):
        return ValidationResult(
            is_valid=False, errors=[f"Expected dict, got {type(data).__name__}"]
        )

    # Pydantic validation
    try:
        obs = RawObservation(**data)
    except ValidationError as e:
        return ValidationResult(
            is_valid=False,
            errors=[str(err) for err in e.errors()],
        )

    # Cross-field validation: GPS fix without coordinates
    if obs.gps_fix and (obs.latitude is None or obs.longitude is None):
        errors.append("gps_fix is True but coordinates are missing")

    # Warn about GPS fix with zero/default coordinates (but don't reject)
    if (
        obs.gps_fix
        and obs.latitude is not None
        and obs.longitude is not None
        and obs.latitude == 0.0
        and obs.longitude == 0.0
    ):
        errors.append("gps_fix is True but coordinates are (0, 0) — may be invalid")

    if errors:
        logger.warning("Validation warnings for seq=%d: %s", obs.sequence, errors)

    return ValidationResult(is_valid=True, observation=obs, errors=errors)
