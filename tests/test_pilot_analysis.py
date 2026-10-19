"""Unit tests for the pilot Intention-to-Treat (ITT) re-analysis engine."""

import pytest

from stagepilot.config import PathConfig
from stagepilot.analysis.pilot import (
    PilotAnalyzer,
    wilson_score_interval,
    diff_confidence_interval,
)


class TestPilotAnalysis:
    """Verifies that the historical pilot re-analysis exposes selection bias with mathematical precision."""

    def test_pilot_cohort_counts_and_conversions(self, path_config: PathConfig):
        """Verify ground-truth sample sizes and conversion counts."""
        analyzer = PilotAnalyzer(paths=path_config)
        result = analyzer.run_analysis()

        # Served cohort
        assert result.served.total == 217
        assert result.served.successes == 87
        assert pytest.approx(result.served.rate, abs=1e-4) == 0.4009

        # All other cohort (lumped unserved treatment + holdout)
        assert result.other.total == 3674
        assert result.other.successes == 649
        assert pytest.approx(result.other.rate, abs=1e-4) == 0.1766

        # Naive claimed uplift
        assert pytest.approx(result.naive_diff, abs=1e-4) == 0.2243
        assert pytest.approx(result.naive_uplift_ratio, abs=1e-2) == 2.27

        # Unserved treatment cohort
        assert result.unserved_treatment.total == 1695
        assert result.unserved_treatment.successes == 262
        assert pytest.approx(result.unserved_treatment.rate, abs=1e-4) == 0.1546

        # True randomized treatment arm
        assert result.treatment_all.total == 1912
        assert result.treatment_all.successes == 349
        assert pytest.approx(result.treatment_all.rate, abs=1e-4) == 0.1825

        # True randomized holdout arm
        assert result.holdout_all.total == 1979
        assert result.holdout_all.successes == 387
        assert pytest.approx(result.holdout_all.rate, abs=1e-4) == 0.1956

        # True Intention-to-Treat (ITT) difference
        assert pytest.approx(result.itt_diff, abs=1e-4) == -0.01308

        # Selection bias delta
        assert pytest.approx(result.selection_bias_delta, abs=1e-3) == 0.2373

    def test_confidence_interval_math(self):
        """Verify Wilson score confidence interval calculations."""
        # 10 successes out of 100
        lower, upper = wilson_score_interval(10, 100)
        assert 0.05 < lower < 0.10
        assert 0.10 < upper < 0.18

        # 0 successes out of 50
        lower_zero, upper_zero = wilson_score_interval(0, 50)
        assert lower_zero == 0.0
        assert upper_zero > 0.0

        # Difference interval
        diff, diff_l, diff_u = diff_confidence_interval(50, 100, 30, 100)
        assert pytest.approx(diff, abs=1e-4) == 0.20
        assert diff_l < 0.20 < diff_u

    def test_markdown_report_generation(self, path_config: PathConfig):
        """Verify generated markdown report contains required sections and tables."""
        analyzer = PilotAnalyzer(paths=path_config)
        result = analyzer.run_analysis()
        md = result.to_markdown()

        assert "# Historical Pilot Re-Analysis: Exposing Selection Bias" in md
        assert "40.09%" in md
        assert "17.66%" in md
        assert "-1.30%" in md
        assert "Intention-to-Treat (ITT)" in md
        assert "Selection on the Dependent Variable" in md
