"""StagePilot Master Single-Command Runner Script.

Executes the entire autonomous lifecycle management pipeline end-to-end:
1. Chronological Replay Day Execution (October 1, 2026)
2. 14-Day Post-Replay Outcome Simulation
3. Attributable Goal Judging & ITT Impact Reporting
4. Complete Automated Test Suite (pytest)

Usage:
    python run_all.py
    python run_all.py --help
"""

import sys
from pathlib import Path
from stagepilot.cli import main

if __name__ == "__main__":
    # If no arguments were provided, default to executing the 'all' subcommand
    if len(sys.argv) == 1:
        sys.argv = ["stagepilot", "all"]
    elif sys.argv[1] not in ["all", "run-replay", "run-sim", "judge-outcomes", "pilot-analysis", "-h", "--help"]:
        # If flags were passed directly to run_all.py (e.g. python run_all.py --skip-tests)
        sys.argv = ["stagepilot", "all"] + sys.argv[1:]
    
    main()
