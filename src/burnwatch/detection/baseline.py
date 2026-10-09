"""Rolling baseline tracker for MQ135 readings using rolling median and MAD.

Provides robust statistical baseline tracking that is resistant to outliers.
Uses Median Absolute Deviation (MAD) as the measure of dispersion.
"""

from __future__ import annotations

import logging
import statistics
from collections import deque

logger = logging.getLogger(__name__)


class RollingBaseline:
    """Rolling window baseline tracker for a single device stream.

    Maintains a fixed-size window of recent readings, calculating the rolling
    median and Median Absolute Deviation (MAD).

    Args:
        window_size: Maximum number of recent readings to retain in the window.
        min_mad_floor: Floor for MAD to avoid division by zero or inflated scores
                       in steady-state environments.
    """

    def __init__(self, window_size: int = 60, min_mad_floor: float = 1.0) -> None:
        self.window_size = window_size
        self.min_mad_floor = min_mad_floor
        self._window: deque[float] = deque(maxlen=window_size)

    def __len__(self) -> int:
        return len(self._window)

    @property
    def count(self) -> int:
        """Current number of samples in the baseline window."""
        return len(self._window)

    def add(self, value: float) -> None:
        """Add a new observation value to the rolling baseline window."""
        self._window.append(float(value))

    def is_ready(self, min_samples: int = 30) -> bool:
        """Check if enough samples have accumulated for reliable statistics."""
        return len(self._window) >= min_samples

    def get_median(self) -> float | None:
        """Calculate the median of current window samples, or None if empty."""
        if not self._window:
            return None
        return float(statistics.median(self._window))

    def get_mad(self) -> float | None:
        """Calculate the Median Absolute Deviation (MAD) of the window.

        MAD = median(|x_i - median(X)|)
        Returns None if window has fewer than 2 samples.
        """
        if len(self._window) < 2:
            return None
        med = statistics.median(self._window)
        abs_devs = [abs(x - med) for x in self._window]
        return float(statistics.median(abs_devs))

    def get_effective_mad(self) -> float | None:
        """Calculate MAD with minimum floor applied to prevent division by zero."""
        mad = self.get_mad()
        if mad is None:
            return None
        return max(mad, self.min_mad_floor)

    def calculate_score(self, value: float, min_samples: int = 30) -> float | None:
        """Calculate anomaly score in MAD units above the baseline median.

        Score = max(0.0, (value - median)) / effective_mad

        Args:
            value: The observed sensor value to evaluate.
            min_samples: Minimum samples required before scoring is enabled.

        Returns:
            Positive score in MAD units, or None if baseline is not ready.
        """
        if not self.is_ready(min_samples):
            return None

        median_val = self.get_median()
        eff_mad = self.get_effective_mad()

        if median_val is None or eff_mad is None or eff_mad <= 0:
            return None

        if value <= median_val:
            return 0.0

        return (value - median_val) / eff_mad

    def reset(self) -> None:
        """Clear all samples in the baseline window."""
        self._window.clear()
