#!/usr/bin/env python3
"""
trajectory_eval.py — Standalone CLI evaluation runner for Week 8.
Asserts expected tool sequences for 10 customer support cases,
computes trajectory metrics, measures outcome-vs-trajectory gap,
evaluates single mitigation, and checks full regression table.
"""

import sys
from pathlib import Path

# Add backend directory to sys.path
ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.ticket_reply_app.trajectory_eval import (
    ALL_FAILURE_MODES,
    EXPECTED_TRAJECTORIES,
    run_full_week8_experiment,
)


def main():
    print("Initializing Week 8 Trajectory Evaluation...")
    run_full_week8_experiment(output_dir=Path(__file__).parent)


if __name__ == "__main__":
    main()
