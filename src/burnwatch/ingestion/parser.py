"""JSON/JSONL observation parser.

Handles parsing of raw JSON observation records from any source.
Malformed lines are logged and skipped without crashing the pipeline.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from burnwatch.models.observation import RawObservation

logger = logging.getLogger(__name__)


class ParseError:
    """Structured parse error for tracking and reporting."""

    def __init__(self, line_number: int, raw_line: str, error: str) -> None:
        self.line_number = line_number
        self.raw_line = raw_line[:200]  # Truncate for safety
        self.error = error

    def __repr__(self) -> str:
        return f"ParseError(line={self.line_number}, error={self.error!r})"


class ParseResult:
    """Result of parsing a single line: either a valid observation or an error."""

    def __init__(
        self,
        observation: RawObservation | None = None,
        raw_json: str | None = None,
        error: ParseError | None = None,
    ) -> None:
        self.observation = observation
        self.raw_json = raw_json
        self.error = error

    @property
    def is_valid(self) -> bool:
        return self.observation is not None

    @property
    def is_error(self) -> bool:
        return self.error is not None


def parse_json_line(line: str, line_number: int = 0) -> ParseResult:
    """Parse a single JSON line into a RawObservation.

    Args:
        line: Raw JSON string (one observation).
        line_number: Line number for error reporting.

    Returns:
        ParseResult with either a valid observation or a structured error.
    """
    stripped = line.strip()
    if not stripped:
        return ParseResult(error=ParseError(line_number, line, "Empty line"))

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as e:
        logger.warning("Malformed JSON at line %d: %s", line_number, e)
        return ParseResult(
            error=ParseError(line_number, line, f"JSON decode error: {e}")
        )

    if not isinstance(data, dict):
        logger.warning("Line %d is not a JSON object", line_number)
        return ParseResult(
            error=ParseError(
                line_number, line, "Expected JSON object, got " + type(data).__name__
            )
        )

    try:
        obs = RawObservation(**data)
    except ValidationError as e:
        logger.warning("Validation error at line %d: %s", line_number, e)
        return ParseResult(
            error=ParseError(line_number, line, f"Validation error: {e}")
        )

    return ParseResult(observation=obs, raw_json=stripped)


def parse_jsonl_file(path: Path) -> Iterator[ParseResult]:
    """Parse a JSONL file, yielding one ParseResult per line.

    Malformed lines produce ParseResult with error set.
    The parser never crashes on bad input.

    Args:
        path: Path to the JSONL file.

    Yields:
        ParseResult for each line in the file.
    """
    if not path.exists():
        logger.error("JSONL file not found: %s", path)
        return

    with open(path, encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            yield parse_json_line(line, line_number)


class SequenceTracker:
    """Track observation sequences per device for gap and duplicate detection.

    Tracks the last seen sequence number per device_id and detects:
    - Sequence gaps (missing packets)
    - Duplicate packets (same sequence number seen again)
    """

    def __init__(self) -> None:
        self._last_seen: dict[str, int] = {}

    def check(self, device_id: str, sequence: int) -> tuple[bool, bool, int]:
        """Check a sequence number and return status.

        Args:
            device_id: Device identifier.
            sequence: Packet sequence number.

        Returns:
            Tuple of (is_duplicate, has_gap, gap_size).
            gap_size is 0 if no gap, otherwise the number of missing packets.
        """
        last = self._last_seen.get(device_id)

        if last is None:
            # First observation from this device
            self._last_seen[device_id] = sequence
            return False, False, 0

        is_duplicate = sequence == last
        if is_duplicate:
            return True, False, 0

        expected_next = last + 1
        has_gap = sequence > expected_next
        gap_size = max(0, sequence - expected_next)

        # Only advance if this is a new (non-duplicate) sequence
        if sequence > last:
            self._last_seen[device_id] = sequence

        return False, has_gap, gap_size

    def reset(self, device_id: str | None = None) -> None:
        """Reset tracking state.

        Args:
            device_id: Reset only this device, or all if None.
        """
        if device_id is None:
            self._last_seen.clear()
        else:
            self._last_seen.pop(device_id, None)
