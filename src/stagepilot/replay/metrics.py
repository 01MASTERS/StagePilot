"""Latency telemetry and SLA reporting engine for StagePilot replay."""

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional


class LatencyTracker:
    """Tracks per-decision latencies and produces SLA performance reports."""

    def __init__(self, sla_threshold_ms: float = 60000.0) -> None:
        self.sla_threshold_ms = sla_threshold_ms
        self.latencies_ms: List[float] = []

    def record(self, latency_ms: float) -> None:
        """Record an observed decision duration in milliseconds."""
        self.latencies_ms.append(float(latency_ms))

    def _percentile(self, sorted_vals: List[float], p: float) -> float:
        """Compute the p-th percentile (0.0 to 1.0) using nearest-rank or linear interpolation."""
        if not sorted_vals:
            return 0.0
        n = len(sorted_vals)
        if n == 1:
            return sorted_vals[0]
        rank = p * (n - 1)
        lower = math.floor(rank)
        upper = math.ceil(rank)
        weight = rank - lower
        return sorted_vals[lower] * (1.0 - weight) + sorted_vals[upper] * weight

    def get_summary(self) -> Dict[str, Any]:
        """Compute latency distribution metrics and SLA adherence statistics."""
        if not self.latencies_ms:
            return {
                "count": 0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "mean_ms": 0.0,
                "p50_ms": 0.0,
                "p90_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "sla_threshold_ms": self.sla_threshold_ms,
                "sla_breaches": 0,
                "sla_compliance_rate": 1.0,
            }

        sorted_vals = sorted(self.latencies_ms)
        count = len(sorted_vals)
        total = sum(sorted_vals)
        mean_val = total / count
        breaches = sum(1 for val in sorted_vals if val > self.sla_threshold_ms)
        compliance = (count - breaches) / count if count > 0 else 1.0

        return {
            "count": count,
            "min_ms": round(sorted_vals[0], 2),
            "max_ms": round(sorted_vals[-1], 2),
            "mean_ms": round(mean_val, 2),
            "p50_ms": round(self._percentile(sorted_vals, 0.50), 2),
            "p90_ms": round(self._percentile(sorted_vals, 0.90), 2),
            "p95_ms": round(self._percentile(sorted_vals, 0.95), 2),
            "p99_ms": round(self._percentile(sorted_vals, 0.99), 2),
            "sla_threshold_ms": self.sla_threshold_ms,
            "sla_breaches": breaches,
            "sla_compliance_rate": round(compliance, 4),
        }

    def save_json(self, output_path: Path) -> Path:
        """Write latency statistics formatted as JSON."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        summary = self.get_summary()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        return output_path
