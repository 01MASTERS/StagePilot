"""Unit tests for the latency telemetry engine and SLA reporting."""

import json
from pathlib import Path
import pytest

from stagepilot.replay.metrics import LatencyTracker


class TestLatencyTracker:
    """Verifies statistical distribution math, SLA breach tracking, and JSON reporting."""

    def test_latency_tracker_empty(self):
        tracker = LatencyTracker(sla_threshold_ms=60000.0)
        summary = tracker.get_summary()
        assert summary["count"] == 0
        assert summary["min_ms"] == 0.0
        assert summary["max_ms"] == 0.0
        assert summary["mean_ms"] == 0.0
        assert summary["sla_breaches"] == 0
        assert summary["sla_compliance_rate"] == 1.0

    def test_latency_tracker_percentiles_calculation(self):
        tracker = LatencyTracker(sla_threshold_ms=60000.0)
        # Latencies from 10.0 to 100.0 ms
        for val in range(10, 110, 10):
            tracker.record(float(val))

        summary = tracker.get_summary()
        assert summary["count"] == 10
        assert summary["min_ms"] == 10.0
        assert summary["max_ms"] == 100.0
        assert summary["mean_ms"] == 55.0
        assert summary["p50_ms"] == 55.0
        assert summary["p90_ms"] == 91.0 or summary["p90_ms"] >= 90.0
        assert summary["p95_ms"] >= 95.0
        assert summary["p99_ms"] >= 99.0
        assert summary["sla_breaches"] == 0
        assert summary["sla_compliance_rate"] == 1.0

    def test_latency_tracker_sla_breach_detection(self):
        tracker = LatencyTracker(sla_threshold_ms=60000.0)
        for _ in range(9):
            tracker.record(15.0)
        # 1 SLA breach: 65,000 ms
        tracker.record(65000.0)

        summary = tracker.get_summary()
        assert summary["count"] == 10
        assert summary["sla_breaches"] == 1
        assert summary["sla_compliance_rate"] == 0.90
        assert summary["max_ms"] == 65000.0

    def test_latency_tracker_json_export(self, tmp_path: Path):
        tracker = LatencyTracker(sla_threshold_ms=60000.0)
        tracker.record(12.5)
        tracker.record(18.2)
        tracker.record(45.0)

        out_file = tmp_path / "latency_report.json"
        saved_path = tracker.save_json(out_file)
        assert saved_path.exists()

        with open(saved_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["count"] == 3
        assert "p50_ms" in data
        assert "p95_ms" in data
        assert "p99_ms" in data
        assert "sla_compliance_rate" in data
        assert data["sla_threshold_ms"] == 60000.0
