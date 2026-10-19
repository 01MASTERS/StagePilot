# StagePilot: Dual-Boundary Agentic Lifecycle Management System

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-60%2F60%20passing-brightgreen.svg)]()
[![SLA](https://img.shields.io/badge/latency%20SLA-100%25%20compliance-success.svg)]()
[![Policy](https://img.shields.io/badge/simulator%20policy-0%20violations-brightgreen.svg)]()

> **STAGE Hiring Challenge Submission**: An autonomous, production-grade lifecycle agent system built for STAGE (India's leading hyper-local dialect OTT platform). Operationalizes the **"One Viewer, One Agent"** paradigm with an air-gapped deterministic safety firewall, real-time SLA enforcement, and honest causal Intent-to-Treat (ITT) measurement.

---

## Quickstart (Single-Command Execution)

StagePilot is engineered for **zero-dependency, zero-API-key evaluation**. The entire pipeline runs locally using the deterministic `MockReplayModelProvider` by default.

### 1. Prerequisites & Installation
Ensure Python 3.12+ is installed:
```bash
# Clone or navigate to the repository
cd StageAI

# Create and activate a virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies in editable mode
pip install -e .
```

### 2. Run the Full End-to-End Pipeline
Execute all 4 stages (Replay -> Simulation -> Outcome Judging & ITT Impact -> Test Suite) with a single command:
```bash
python run_all.py
```

Expected terminal summary:
```
================================================================================
                     STAGEPILOT EXECUTION COMPLETE SCORECARD                    
================================================================================
Decisions Processed:       2,769
Actions Published:         1,156
Vetoed (NO_ACTION):        1,613
Simulator Policy Breaches: 0
Latency SLA Compliance:    100.00% (Breaches: 0)
Max Decision Latency:      2.0 ms
True ITT Treatment Rate:   1.75% (95% CI: [1.3%, 2.2%])
True ITT Holdout Rate:     2.12% (95% CI: [1.3%, 2.9%])
True ITT Relative Lift:    -17.34% (Diff = -0.37 pp, p = 0.3340)
Naive As-Treated Lift:     +173.36% (Selection Bias Inflation)
================================================================================
```

---

## Key System Architecture

StagePilot enforces an air-gapped separation of concerns between **Generative Action Planning** and **Deterministic Safety Verification**:

```
[Inbound Events] ---> [Chronological Replay Pump]
                             |
                             v
                 [Per-Viewer Lifecycle Agent]
                 - Durable SQLite State & LRU Cache
                 - Fact Provenance Engine (Source, Sequence, Freshness)
                 - Goal Planning Engine (G01-G12 Evaluation)
                 - Multi-Provider Intervention Planner
                             | (Candidate Action)
                             v
                 [Air-Gapped Safety Firewall]
                 - 10 Pure-Python Deterministic Gates
                 - Unilateral Veto Power
                             |
             +---------------+---------------+
             |                               |
             v                               v
    [actions.jsonl]                   [decisions.jsonl]
   (Approved Actions)               (Full Decision Trail)
             |
             v
   [Outcome Simulator]
             |
             v
   [Outcome Judge & ITT Reporter]
   (True ITT vs Selection Bias)
```

For the complete technical specification, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## Repository Map

```
StageAI/
├── run_all.py                  # Master zero-argument single-command runner
├── ARCHITECTURE.md             # 7-part comprehensive technical architecture specification
├── AI_COLLABORATION.md         # Transparent AI usage notes & 4 rejected suggestions
├── KNOWN_LIMITATIONS.md        # Deliberate engineering scope trade-offs & scaling roadmap
├── TECHNICAL_DISCUSSION_GUIDE.md # Detailed answers for all 7 oral evaluation questions
├── pyproject.toml              # Build config & test dependencies
│
├── src/stagepilot/             # Core production package
│   ├── cli.py                  # Unified CLI tool (run-replay, run-sim, judge-outcomes, all)
│   ├── config.py               # Path definitions & system constants
│   ├── data/                   # Ingestion models (catalogue, profiles, events, arms)
│   ├── state/                  # SQLite store, models, and state manager
│   ├── goals/                  # 12 lifecycle goal evaluators (G01-G12) with G10/G11 veto
│   ├── verifier/               # Air-gapped 10-gate safety firewall
│   ├── interventions/          # Action arm selector & candidate synthesis
│   ├── models/                 # Provider abstraction (Mock, Gemini, Ollama)
│   ├── replay/                 # Replay pump, control events (C001-C004), latency metrics
│   ├── simulation/             # Official simulator runner interface
│   └── evaluation/             # Outcome judge & honest ITT impact reporter
│
├── tests/                      # 60 automated test cases (100% passing)
│   ├── test_ingest.py
│   ├── test_state_store.py
│   ├── test_goal_planner.py
│   ├── test_model_providers.py
│   ├── test_interventions.py
│   ├── test_verifier.py
│   ├── test_decision_pipeline.py
│   ├── test_replay_harness.py
│   ├── test_latency.py
│   ├── test_outcome_judge.py
│   ├── test_impact_reporter.py
│   └── test_pilot_analysis.py
│
├── docs/
│   ├── technical_discussion_guide.md   # Answers to all 7 oral evaluation questions
│   ├── assignment.pdf                  # Challenge specification
│   ├── Assignment_reference.pdf        # Architecture reference guide
│   └── one_user_one_agent_pack/        # Official data pack (profiles, replay, pilot)
│
└── sample_run/                         # Fully executed evaluation artifacts
    ├── decisions.jsonl                 # 2,769 chronological decision records
    ├── actions.jsonl                   # 1,156 verified actions (0 policy violations)
    ├── latency_report.json             # Microsecond latency telemetry (100% SLA compliance)
    ├── viewer_state/                   # 4,869 exported viewer JSON state files
    ├── sim/outcome_events.jsonl        # 31,613 simulated post-replay events
    ├── sim/simulator_report.json       # Official simulator verdict (0 policy problems)
    ├── outcomes.jsonl & outcomes.csv   # 4,869 judged viewer lifecycle outcomes
    ├── impact_report.md                # ITT vs Selection Bias impact analysis
    ├── pilot_reanalysis.md             # Pilot dataset bias audit
    └── final_report.md                 # Executive submission summary report
```

---

## CLI Reference

In addition to `run_all.py`, the `stagepilot` CLI provides granular control over individual stages:

```bash
# 1. Execute Replay Day with Mock Provider
stagepilot run-replay --pack docs/one_user_one_agent_pack --out sample_run --provider mock

# 2. Run the 14-day Outcome Simulator
stagepilot run-sim --pack docs/one_user_one_agent_pack --actions sample_run/actions.jsonl --out sample_run/sim

# 3. Judge Outcomes & Generate ITT Impact Report
stagepilot judge-outcomes --pack docs/one_user_one_agent_pack --run sample_run

# 4. Re-analyze the Preliminary Pilot Dataset
stagepilot pilot-analysis --pack docs/one_user_one_agent_pack --out sample_run/pilot_reanalysis.md

# 5. Execute Complete End-to-End Pipeline
stagepilot all --pack docs/one_user_one_agent_pack --out sample_run
```

---

## Model Provider Configuration

StagePilot provides pluggable provider backends configured via `--provider`:

### 1. Mock Provider (Default - No Setup Required)
```bash
stagepilot all --provider mock
```
Completely deterministic, sub-2ms latency, zero external API dependencies.

### 2. Google Gemini API (Optional)
Requires a Google Gemini API key:
```bash
# Set your API key
export GEMINI_API_KEY="your-api-key"      # Linux/macOS
set GEMINI_API_KEY="your-api-key"         # Windows CMD
$env:GEMINI_API_KEY="your-api-key"        # Windows PowerShell

# Run with Gemini 2.5 Flash
stagepilot all --provider gemini --model gemini-2.5-flash
```

### 3. Ollama Local LLM (Optional)
Run entirely locally and privately using Ollama:
```bash
# Pull model
ollama pull deepseek-r1:8b

# Run with Ollama
stagepilot all --provider ollama --model deepseek-r1:8b
```

---

## Verification & Testing

Run the full pytest suite:
```bash
pytest tests/ -v
```
All 60 tests will execute in ~6.5 seconds, asserting full coverage across state persistence, safety rules, replay streaming, and statistical analysis.

---

## Submission Checklist Compliance

| Item | Description | Path | Status |
| :--- | :--- | :--- | :--- |
| 1 | Single-Command Master Runner | `run_all.py` | Complete |
| 2 | System Overview & Setup | `README.md` | Complete |
| 3 | Technical Architecture (7 parts) | `ARCHITECTURE.md` | Complete |
| 4 | AI Collaboration & Rejected Suggestions | `AI_COLLABORATION.md` | Complete |
| 5 | Scope Trade-offs & Production Roadmap | `KNOWN_LIMITATIONS.md` | Complete |
| 6 | Oral Defense Interview Answers (7 questions) | `TECHNICAL_DISCUSSION_GUIDE.md` | Complete |
| 7 | Full Source Code Package | `src/stagepilot/` | Complete |
| 8 | Automated Test Suite (60 tests) | `tests/` | Complete (100% Green) |
| 9 | Chronological Decisions Stream | `sample_run/decisions.jsonl` | Complete (2,769 records) |
| 10 | Published Actions Stream | `sample_run/actions.jsonl` | Complete (1,156 actions) |
| 11 | Exported Viewer States | `sample_run/viewer_state/` | Complete (4,869 files) |
| 12 | Latency SLA Telemetry | `sample_run/latency_report.json` | Complete (0 breaches) |
| 13 | ITT Causal Impact Analysis | `sample_run/impact_report.md` | Complete |
| 14 | Executive Final Report | `sample_run/final_report.md` | Complete |
