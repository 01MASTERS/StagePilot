"""Command-line interface for StagePilot replay, simulation, and analysis."""

import argparse
import json
import logging
import sys
from pathlib import Path

from stagepilot.analysis.pilot import PilotAnalyzer
from stagepilot.evaluation.impact_reporter import ImpactReporter
from stagepilot.evaluation.outcome_judge import OutcomeJudge
from stagepilot.evaluation.simulator_runner import SimulatorRunner
from stagepilot.ingest.arms import ArmStore
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.providers.selector import resolve_provider
from stagepilot.replay.harness import ReplayHarness


def main() -> None:
    """Main CLI entrypoint for StagePilot."""
    parser = argparse.ArgumentParser(
        prog="stagepilot",
        description="StagePilot: Dual-boundary autonomous agentic viewer lifecycle manager for STAGE.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: run-replay
    replay_parser = subparsers.add_parser(
        "run-replay", help="Execute chronological single-day replay harness."
    )
    replay_parser.add_argument(
        "--pack",
        type=Path,
        default=Path("docs/one_user_one_agent_pack"),
        help="Path to one_user_one_agent_pack directory (default: docs/one_user_one_agent_pack).",
    )
    replay_parser.add_argument(
        "--out",
        type=Path,
        default=Path("sample_run"),
        help="Target output directory (default: sample_run).",
    )
    replay_parser.add_argument(
        "--provider",
        type=str,
        default="mock",
        choices=["mock", "gemini", "ollama"],
        help="Model provider to use (default: mock for deterministic reproducibility).",
    )
    replay_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Specific model identifier to invoke.",
    )
    replay_parser.add_argument(
        "--max-triggers",
        type=int,
        default=None,
        help="Maximum triggers to process (useful for smoke tests).",
    )
    replay_parser.add_argument(
        "--no-historical",
        action="store_true",
        help="Skip pre-populating historical viewer events.",
    )

    # Command: run-sim
    sim_parser = subparsers.add_parser(
        "run-sim", help="Execute outcome simulator over published actions."
    )
    sim_parser.add_argument(
        "--pack",
        type=Path,
        default=Path("docs/one_user_one_agent_pack"),
        help="Path to one_user_one_agent_pack directory.",
    )
    sim_parser.add_argument(
        "--actions",
        type=Path,
        default=Path("sample_run/actions.jsonl"),
        help="Path to actions.jsonl file (default: sample_run/actions.jsonl).",
    )
    sim_parser.add_argument(
        "--out",
        type=Path,
        default=Path("sample_run/sim"),
        help="Output directory for simulator (default: sample_run/sim).",
    )
    sim_parser.add_argument(
        "--seed",
        type=str,
        default="oua-practice",
        help="Simulation seed (default: oua-practice).",
    )

    # Command: judge-outcomes
    judge_parser = subparsers.add_parser(
        "judge-outcomes", help="Judge simulated outcomes and compute ITT impact report."
    )
    judge_parser.add_argument(
        "--pack",
        type=Path,
        default=Path("docs/one_user_one_agent_pack"),
        help="Path to one_user_one_agent_pack directory.",
    )
    judge_parser.add_argument(
        "--run",
        type=Path,
        default=Path("sample_run"),
        help="Root path of replay run containing viewer_state/ and sim/ (default: sample_run).",
    )
    judge_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Target output directory (defaults to --run).",
    )

    # Command: pilot-analysis
    pilot_parser = subparsers.add_parser(
        "pilot-analysis", help="Run honest ITT vs selection bias analysis on pilot dataset."
    )
    pilot_parser.add_argument(
        "--pack",
        type=Path,
        default=Path("docs/one_user_one_agent_pack"),
        help="Path to one_user_one_agent_pack directory.",
    )
    pilot_parser.add_argument(
        "--out",
        type=Path,
        default=Path("sample_run/pilot_reanalysis.md"),
        help="Target output markdown path.",
    )

    # Command: all
    all_parser = subparsers.add_parser(
        "all", help="Execute complete pipeline end-to-end: replay, simulation, judging, and tests."
    )
    all_parser.add_argument(
        "--pack",
        type=Path,
        default=Path("docs/one_user_one_agent_pack"),
        help="Path to one_user_one_agent_pack directory.",
    )
    all_parser.add_argument(
        "--out",
        type=Path,
        default=Path("sample_run"),
        help="Target output directory (default: sample_run).",
    )
    all_parser.add_argument(
        "--provider",
        type=str,
        default="mock",
        choices=["mock", "gemini", "ollama"],
        help="Model provider to use (default: mock).",
    )
    all_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model identifier.",
    )
    all_parser.add_argument(
        "--seed",
        type=str,
        default="oua-practice",
        help="Simulation seed (default: oua-practice).",
    )
    all_parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running pytest suite at the end.",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "run-replay":
        print(f"=== StagePilot Replay Harness ===")
        print(f"Pack Directory: {args.pack}")
        print(f"Output Directory: {args.out}")
        print(f"Provider: {args.provider} (model: {args.model or 'auto'})")

        provider = resolve_provider(
            provider_name=args.provider,
            model_name=args.model,
        )

        harness = ReplayHarness(
            pack_dir=args.pack,
            output_dir=args.out,
            model_provider=provider,
            prepopulate_historical=not args.no_historical,
        )

        print("\n[1/3] Initializing stores, planners, and safety firewall...")
        harness.setup()

        if not args.no_historical:
            print("[2/3] Pre-populating historical viewer histories (September 2026)...")
            count = harness.prepopulate_history()
            print(f"      Pre-populated {count:,} historical events.")
        else:
            print("[2/3] Skipping historical pre-population.")

        print("[3/3] Streaming chronological replay day (October 1, 2026)...")
        summary = harness.run(max_triggers=args.max_triggers)

        print("\n=== Replay Execution Complete ===")
        print(f"Triggers Processed:      {summary['triggers_processed']:,}")
        print(f"Live Events Processed:   {summary['live_events_processed']:,}")
        print(f"Control Events Handled:  {summary['control_events_processed']:,}")
        print(f"Decisions Published:     {summary['decisions_published']:,}")
        print(f"Actions Published:       {summary['actions_published']:,}")
        print(f"Vetoed Actions (NO_ACT): {summary['vetoed_decisions']:,}")
        print(f"Viewer States Exported:  {summary['viewer_states_exported']:,}")

        lat = summary["latency"]
        print(f"\n--- Latency & SLA Performance ---")
        print(f"Mean Latency:    {lat['mean_ms']:.1f} ms")
        print(f"Median (p50):    {lat['p50_ms']:.1f} ms")
        print(f"95th Percentile: {lat['p95_ms']:.1f} ms")
        print(f"99th Percentile: {lat['p99_ms']:.1f} ms")
        print(f"Max Latency:     {lat['max_ms']:.1f} ms")
        print(f"SLA Compliance:  {lat['sla_compliance_rate'] * 100:.2f}% (Breaches: {lat['sla_breaches']})")
        print(f"\nOutputs written to: {args.out.resolve()}")

    elif args.command == "run-sim":
        print(f"=== StagePilot Outcome Simulator Runner ===")
        print(f"Pack Directory:    {args.pack}")
        print(f"Actions File:      {args.actions}")
        print(f"Output Directory:  {args.out}")
        print(f"Simulation Seed:   {args.seed}")

        runner = SimulatorRunner(
            pack_dir=args.pack,
            actions_path=args.actions,
            output_dir=args.out,
            seed=args.seed,
        )

        res = runner.run()
        print("\n=== Simulation Complete ===")
        print(f"Triggered Users Evaluated: {res['triggered_users']:,}")
        print(f"Outcome Events Generated:  {res['events_written']:,}")
        print(f"Policy Violations Count:   {res['policy_problem_count']}")

        if res["policy_problem_count"] == 0:
            print("[OK] ZERO POLICY PROBLEMS: Full compliance verified by simulator.")
        else:
            print(f"[WARNING] Found {res['policy_problem_count']} policy problems:")
            for p in res["policy_problems"]:
                print(f"   - {p}")

        print(f"Events written to: {res['outcome_events_path']}")

    elif args.command == "judge-outcomes":
        run_dir = args.run
        out_dir = args.out or run_dir
        viewer_state_dir = run_dir / "viewer_state"
        outcome_events_path = run_dir / "sim" / "outcome_events.jsonl"
        actions_path = run_dir / "actions.jsonl"

        print(f"=== StagePilot Closed-Loop Outcome Judge ===")
        print(f"Pack Directory:     {args.pack}")
        print(f"Viewer States:      {viewer_state_dir}")
        print(f"Outcome Events:     {outcome_events_path}")
        print(f"Target Output:      {out_dir}")

        catalogue_path = args.pack / "data" / "catalogue.csv"
        episodes_path = args.pack / "data" / "episodes.csv"
        catalogue = CatalogueStore.load(catalogue_path, episodes_path)

        arms_path = args.pack / "replay" / "arms.csv"
        if not arms_path.exists():
            arms_path = args.pack / "data" / "arms.csv"
        arms = ArmStore.load(arms_path) if arms_path.exists() else ArmStore()

        judge = OutcomeJudge(catalogue_store=catalogue, arm_store=arms)
        outcomes = judge.judge_all(
            viewer_state_dir=viewer_state_dir,
            outcome_events_path=outcome_events_path,
            actions_path=actions_path,
            output_dir=out_dir,
        )

        print(f"Successfully judged {len(outcomes):,} viewers.")
        print(f"Saved outcomes to: {out_dir / 'outcomes.jsonl'} and {out_dir / 'outcomes.csv'}")

        print("\n=== Generating Honest ITT Impact Analysis ===")
        reporter = ImpactReporter()
        analysis = reporter.analyze_outcomes(out_dir / "outcomes.jsonl")
        report_md = reporter.generate_markdown_report(analysis)

        report_path = out_dir / "impact_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_md)

        itt = analysis["itt"]
        naive = analysis["naive_served"]
        print(f"\n--- ITT vs. Selection Bias Scoreboard ---")
        print(f"True ITT Treatment Rate: {itt.treatment.rate * 100:.2f}% (95% CI: [{itt.treatment.ci_lower*100:.1f}%, {itt.treatment.ci_upper*100:.1f}%])")
        print(f"True ITT Holdout Rate:   {itt.control.rate * 100:.2f}% (95% CI: [{itt.control.ci_lower*100:.1f}%, {itt.control.ci_upper*100:.1f}%])")
        print(f"True ITT Relative Lift:  {itt.relative_lift_pct:+.2f}% (Diff = {itt.absolute_diff:+.2f} pp, p = {itt.p_value:.4f})")
        print(f"\nNaive As-Treated Lift:   {naive.relative_lift_pct:+.2f}% (SELECTION BIAS INFLATION)")
        print(f"Report written to:       {report_path}")

    elif args.command == "all":
        print("================================================================================")
        print("          STAGEPILOT: END-TO-END AUTONOMOUS LIFECYCLE REPLAY & EVALUATION        ")
        print("================================================================================")
        print(f"Pack Directory:   {args.pack}")
        print(f"Output Directory: {args.out}")
        print(f"Model Provider:   {args.provider} (model: {args.model or 'auto'})")
        print(f"Simulation Seed:  {args.seed}")

        # 1. Replay Execution
        print("\n--------------------------------------------------------------------------------")
        print("[STAGE 1/4] EXECUTING CHRONOLOGICAL REPLAY DAY (OCTOBER 1, 2026)")
        print("--------------------------------------------------------------------------------")
        provider = resolve_provider(provider_name=args.provider, model_name=args.model)
        harness = ReplayHarness(
            pack_dir=args.pack,
            output_dir=args.out,
            model_provider=provider,
            prepopulate_historical=True,
        )
        harness.setup()
        harness.prepopulate_history()
        replay_summary = harness.run()
        print(
            f"[OK] Replay completed: {replay_summary['triggers_processed']:,} triggers, "
            f"{replay_summary['actions_published']:,} actions published, "
            f"{replay_summary['vetoed_decisions']:,} vetoed to NO_ACTION."
        )

        # 2. Simulator Execution
        print("\n--------------------------------------------------------------------------------")
        print("[STAGE 2/4] SIMULATING 14-DAY POST-REPLAY BEHAVIORS")
        print("--------------------------------------------------------------------------------")
        sim_out_dir = args.out / "sim"
        actions_file = args.out / "actions.jsonl"
        sim_runner = SimulatorRunner(
            pack_dir=args.pack,
            actions_path=actions_file,
            output_dir=sim_out_dir,
            seed=args.seed,
        )
        sim_res = sim_runner.run()
        print(
            f"[OK] Simulation completed: {sim_res['events_written']:,} events generated across "
            f"{sim_res['triggered_users']:,} users."
        )
        if sim_res["policy_problem_count"] == 0:
            print("[OK] ZERO POLICY PROBLEMS: Full compliance verified by official simulator.")
        else:
            print(f"[WARNING] Simulator reported {sim_res['policy_problem_count']} policy problems.")

        # 3. Outcome Judging & ITT Impact Reporting
        print("\n--------------------------------------------------------------------------------")
        print("[STAGE 3/4] ATTRIBUTING GOAL OUTCOMES & COMPUTING HONEST ITT IMPACT")
        print("--------------------------------------------------------------------------------")
        catalogue = CatalogueStore.load(args.pack / "data/catalogue.csv", args.pack / "data/episodes.csv")
        arms_path = args.pack / "replay/arms.csv"
        if not arms_path.exists():
            arms_path = args.pack / "data/arms.csv"
        arms = ArmStore.load(arms_path) if arms_path.exists() else ArmStore()

        judge = OutcomeJudge(catalogue_store=catalogue, arm_store=arms)
        outcomes = judge.judge_all(
            viewer_state_dir=args.out / "viewer_state",
            outcome_events_path=sim_out_dir / "outcome_events.jsonl",
            actions_path=actions_file,
            output_dir=args.out,
        )
        print(f"[OK] Judged {len(outcomes):,} viewer lifecycle goals.")

        reporter = ImpactReporter()
        analysis = reporter.analyze_outcomes(args.out / "outcomes.jsonl")
        report_md = reporter.generate_markdown_report(analysis)
        report_path = args.out / "impact_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_md)
        print(f"[OK] ITT Impact report written to: {report_path}")

        # 4. Automated Test Suite (optional)
        if not args.skip_tests:
            print("\n--------------------------------------------------------------------------------")
            print("[STAGE 4/4] RUNNING COMPLETE AUTOMATED TEST SUITE (PYTEST)")
            print("--------------------------------------------------------------------------------")
            import subprocess
            test_res = subprocess.run([sys.executable, "-m", "pytest", "tests/"])
            if test_res.returncode == 0:
                print("[OK] ALL AUTOMATED TESTS PASSED GREEN (100%).")
            else:
                print(f"[ERROR] Test suite exited with code {test_res.returncode}.")

        # Final Scorecard
        itt = analysis["itt"]
        naive = analysis["naive_served"]
        print("\n================================================================================")
        print("                     STAGEPILOT EXECUTION COMPLETE SCORECARD                    ")
        print("================================================================================")
        print(f"Decisions Processed:       {replay_summary['decisions_published']:,}")
        print(f"Actions Published:         {replay_summary['actions_published']:,}")
        print(f"Vetoed (NO_ACTION):        {replay_summary['vetoed_decisions']:,}")
        print(f"Simulator Policy Breaches: {sim_res['policy_problem_count']}")
        print(f"Latency SLA Compliance:    {replay_summary['latency']['sla_compliance_rate'] * 100:.2f}% (Breaches: {replay_summary['latency']['sla_breaches']})")
        print(f"Max Decision Latency:      {replay_summary['latency']['max_ms']:.1f} ms")
        print(f"True ITT Treatment Rate:   {itt.treatment.rate * 100:.2f}% (95% CI: [{itt.treatment.ci_lower*100:.1f}%, {itt.treatment.ci_upper*100:.1f}%])")
        print(f"True ITT Holdout Rate:     {itt.control.rate * 100:.2f}% (95% CI: [{itt.control.ci_lower*100:.1f}%, {itt.control.ci_upper*100:.1f}%])")
        print(f"True ITT Relative Lift:    {itt.relative_lift_pct:+.2f}% (Diff = {itt.absolute_diff:+.2f} pp, p = {itt.p_value:.4f})")
        print(f"Naive As-Treated Lift:     {naive.relative_lift_pct:+.2f}% (Selection Bias Inflation)")
        print("================================================================================\n")

    elif args.command == "pilot-analysis":
        print(f"=== Running Pilot ITT Re-Analysis ===")
        events_path = args.pack / "pilot" / "pilot_events.jsonl"
        assignments_path = args.pack / "pilot" / "pilot_assignment.csv"

        analyzer = PilotAnalyzer(events_path, assignments_path)
        metrics = analyzer.run()
        report = analyzer.generate_markdown_report()

        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"Report saved to: {args.out}")
        print(f"Reported Treatment Lift: {metrics.reported_relative_lift_pct:+.2f}% (SELECTION BIAS)")
        print(f"True ITT Treatment Lift: {metrics.true_relative_lift_pct:+.2f}%")


if __name__ == "__main__":
    main()
