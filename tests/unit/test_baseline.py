"""Unit tests for RollingBaseline tracker."""

from __future__ import annotations

from burnwatch.detection.baseline import RollingBaseline


class TestRollingBaseline:
    """Tests for RollingBaseline statistics and scoring."""

    def test_empty_baseline(self) -> None:
        bl = RollingBaseline(window_size=10)
        assert bl.count == 0
        assert not bl.is_ready(min_samples=5)
        assert bl.get_median() is None
        assert bl.get_mad() is None
        assert bl.calculate_score(100.0, min_samples=5) is None

    def test_window_size_cap(self) -> None:
        bl = RollingBaseline(window_size=5)
        for i in range(10):
            bl.add(i)
        assert bl.count == 5
        # The window contains [5, 6, 7, 8, 9]
        assert bl.get_median() == 7.0

    def test_median_and_mad_known_values(self) -> None:
        bl = RollingBaseline(window_size=10)
        # Series: [10, 12, 14, 16, 18] -> median is 14
        # Deviations: |10-14|=4, |12-14|=2, |14-14|=0, |16-14|=2, |18-14|=4
        # Sorted deviations: [0, 2, 2, 4, 4] -> median deviation (MAD) = 2
        for val in [10, 12, 14, 16, 18]:
            bl.add(val)
        assert bl.get_median() == 14.0
        assert bl.get_mad() == 2.0
        assert bl.get_effective_mad() == 2.0

    def test_zero_mad_floor_applied(self) -> None:
        bl = RollingBaseline(window_size=10, min_mad_floor=1.5)
        for _ in range(10):
            bl.add(300)
        assert bl.get_median() == 300.0
        assert bl.get_mad() == 0.0
        # Floor of 1.5 should be applied
        assert bl.get_effective_mad() == 1.5

    def test_calculate_score(self) -> None:
        bl = RollingBaseline(window_size=10, min_mad_floor=1.0)
        for val in [100, 100, 100, 100, 100]:
            bl.add(val)
        # median = 100, effective_mad = 1.0 (from floor)
        # Score for value 100 <= 100 -> 0.0
        assert bl.calculate_score(100, min_samples=5) == 0.0
        # Score for value 90 < 100 -> 0.0
        assert bl.calculate_score(90, min_samples=5) == 0.0
        # Score for value 105 -> (105 - 100) / 1.0 = 5.0
        assert bl.calculate_score(105, min_samples=5) == 5.0

    def test_not_ready_returns_none(self) -> None:
        bl = RollingBaseline(window_size=20)
        for val in [100, 105, 110]:
            bl.add(val)
        assert bl.calculate_score(150, min_samples=10) is None

    def test_reset(self) -> None:
        bl = RollingBaseline(window_size=10)
        for val in [10, 20, 30]:
            bl.add(val)
        bl.reset()
        assert bl.count == 0
        assert bl.get_median() is None
