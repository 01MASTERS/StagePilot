"""Simulator runner wrapper executing simulate_outcomes.py and verifying policy adherence."""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SimulatorRunner:
    """Orchestrates execution of the official Stage outcome simulator."""

    def __init__(
        self,
        pack_dir: Path,
        actions_path: Path,
        output_dir: Path,
        seed: str = "oua-practice",
        simulator_script_path: Optional[Path] = None,
    ) -> None:
        self.pack_dir = Path(pack_dir)
        self.actions_path = Path(actions_path)
        self.output_dir = Path(output_dir)
        self.seed = seed

        if simulator_script_path:
            self.simulator_script = Path(simulator_script_path)
        else:
            self.simulator_script = self.pack_dir / "simulator" / "simulate_outcomes.py"

    def run(self) -> Dict[str, Any]:
        """Execute the simulator subprocess and parse the output report."""
        if not self.simulator_script.exists():
            raise FileNotFoundError(
                f"Simulator script not found at: {self.simulator_script}"
            )
        if not self.actions_path.exists():
            raise FileNotFoundError(
                f"Published actions file not found at: {self.actions_path}"
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(self.simulator_script),
            "--pack",
            str(self.pack_dir),
            "--actions",
            str(self.actions_path),
            "--out",
            str(self.output_dir),
            "--seed",
            self.seed,
        ]

        logger.info("Executing simulator command: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            error_msg = (
                f"Simulator failed with code {result.returncode}.\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        report_path = self.output_dir / "simulator_report.json"
        outcome_events_path = self.output_dir / "outcome_events.jsonl"

        if not report_path.exists():
            raise FileNotFoundError(f"Simulator did not create report at: {report_path}")
        if not outcome_events_path.exists():
            raise FileNotFoundError(
                f"Simulator did not create outcome events at: {outcome_events_path}"
            )

        with open(report_path, "r", encoding="utf-8") as f:
            report_data = json.load(f)

        policy_problem_count = report_data.get("policy_problem_count", 0)
        policy_problems = report_data.get("policy_problems", [])

        return {
            "success": True,
            "seed": self.seed,
            "events_written": report_data.get("events_written", 0),
            "triggered_users": report_data.get("triggered_users", 0),
            "counts": report_data.get("counts", {}),
            "policy_problem_count": policy_problem_count,
            "policy_problems": policy_problems,
            "report_path": report_path,
            "outcome_events_path": outcome_events_path,
        }
