"""Unit tests for the statistical rigor and ITT impact reporting engine."""

import json
from pathlib import Path
import pytest

from stagepilot.evaluation.impact_reporter import ImpactReporter, ProportionStats


class TestImpactReporter:
    """Verifies Wilson confidence interval math, two-proportion z-tests, and selection bias analysis."""

    @pytest.fixture
    def reporter(self) -> ImpactReporter:
        return ImpactReporter(confidence_level=0.95)

    def test_wilson_ci_computation(self, reporter: ImpactReporter):
        """Verify Wilson score confidence interval matches statistical benchmarks."""
        # 50 successes out of 100 trials: symmetric around 0.50, CI approximately [0.40, 0.60]
        low, high = reporter.compute_wilson_ci(50, 100)
        assert 0.40 <= low <= 0.41
        assert 0.59 <= high <= 0.61

        # 0 successes out of 100 trials: lower bound is strictly 0.0, upper bound > 0.0
        low_zero, high_zero = reporter.compute_wilson_ci(0, 100)
        assert low_zero == 0.0
        assert 0.03 <= high_zero <= 0.04

        # Empty trials
        low_empty, high_empty = reporter.compute_wilson_ci(0, 0)
        assert low_empty == 0.0
        assert high_empty == 0.0

    def test_compare_proportions_math(self, reporter: ImpactReporter):
        """Verify absolute difference, relative lift, z-score, and p-value math."""
        # Treatment: 200 / 1000 = 20.0%
        # Control: 160 / 1000 = 16.0%
        comparison = reporter.compare_proportions(
            t_successes=200,
            t_total=1000,
            c_successes=160,
            c_total=1000,
        )

        assert comparison.treatment.rate == 0.20
        assert comparison.control.rate == 0.16
        assert comparison.absolute_diff == pytest.approx(4.0, abs=0.01)  # +4.0 pp
        assert comparison.relative_lift_pct == pytest.approx(25.0, abs=0.1)  # +25.0%
        assert comparison.z_score > 0.0
        assert 0.0 < comparison.p_value < 0.05  # Statistically significant

    def test_itt_vs_selection_bias_contrast(self, reporter: ImpactReporter, tmp_path: Path):
        """Verify that dropping unserved treatment viewers produces inflated selection bias."""
        outcomes_file = tmp_path / "outcomes.jsonl"

        records = []
        # Treatment: 1,000 users total
        # - 400 served users: 160 succeeded (40% conversion rate)
        # - 600 unserved users: 20 succeeded (3.33% conversion rate)
        # Overall Treatment ITT: 180 / 1000 = 18.0%
        for i in range(400):
            records.append({
                "user_id": f"U-T-S-{i}",
                "arm": "agent",
                "served": True,
                "goal_id": "G05",
                "succeeded": i < 160,
            })
        for i in range(600):
            records.append({
                "user_id": f"U-T-U-{i}",
                "arm": "agent",
                "served": False,
                "goal_id": "G05",
                "succeeded": i < 20,
            })

        # Control (Holdout): 1,000 users total
        # - 190 succeeded (19.0% conversion rate)
        for i in range(1000):
            records.append({
                "user_id": f"U-H-{i}",
                "arm": "holdout",
                "served": False,
                "goal_id": "G05",
                "succeeded": i < 190,
            })

        with open(outcomes_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        analysis = reporter.analyze_outcomes(outcomes_file)

        # True ITT: 18.0% vs 19.0% -> -1.0 pp, negative lift (-5.26%)
        assert analysis["itt"].treatment.rate == 0.18
        assert analysis["itt"].control.rate == 0.19
        assert analysis["itt"].absolute_diff == pytest.approx(-1.0, abs=0.01)
        assert analysis["itt"].relative_lift_pct < 0.0

        # Naive As-Treated: 40.0% vs 19.0% -> +21.0 pp, +110.5% lift (MASSIVE SELECTION BIAS)
        assert analysis["naive_served"].treatment.rate == 0.40
        assert analysis["naive_served"].relative_lift_pct > 100.0

        # Verify markdown report generation
        md_report = reporter.generate_markdown_report(analysis)
        assert "Intention-to-Treat (ITT) vs. Naive Selection Bias Scorecard" in md_report
        assert "Anatomy of the Selection Bias Illusion" in md_report
        assert "Goal-by-Goal Attribution Breakdown" in md_report
