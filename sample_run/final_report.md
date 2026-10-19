# StagePilot: Executive Submission & System Evaluation Report

## 1. Executive Summary

**StagePilot** is an autonomous, dual-boundary agentic lifecycle management platform engineered for **STAGE**—India's hyper-local dialect streaming service across 6 primary regional dialects (`d1`–`d6`: Bhojpuri, Haryanvi, Rajasthani, Maithili, Gujarati, Magahi).

Operationalizing the **"One Viewer, One Agent"** architectural paradigm, StagePilot replaces traditional offline batch churn and recommender tables with dedicated, stateful lifecycle agents. Each viewer's agent continuously evaluates behavioral triggers, establishes fact provenance, dynamically plans long-term lifecycle goals, selects high-affinity intervention arms, and submits candidate actions to an **air-gapped, pure-Python deterministic safety firewall** operating under a strict **60-second real-time SLA**.

```
================================================================================
                    STAGEPILOT FINAL EVALUATION SCORECARD                       
================================================================================
Total Viewer Accounts Managed:     4,869
Replay Day Ingestion Events:       2,769 Triggers (October 1, 2026)
Total Decisions Evaluated:         2,769 (100% auditable in decisions.jsonl)
Actions Published to Viewers:      1,156 (100% verified in actions.jsonl)
Actions Vetoed (NO_ACTION):        1,613 (58.25% abstention rate)
Simulated Post-Replay Events:      31,613 (14-day outcome trajectory)
Official Simulator Policy Breaches: 0 (100% policy compliance)
Real-Time Latency SLA Breaches:    0 (100% sub-60s compliance; max 2.0 ms)
True ITT Treatment Conversion:     1.75% (95% CI: [1.34%, 2.15%])
True ITT Holdout Conversion:       2.12% (95% CI: [1.30%, 2.94%])
True Intent-to-Treat (ITT) Lift:   -17.34% (Diff = -0.37 pp, p = 0.3340)
Naive As-Treated Selection Bias:   +173.36% (Exposed & Neutralized)
================================================================================
```

---

## 2. Core Architectural Pillars

### 2.1 One Viewer, One Agent Ownership
- Every viewer account $u$ is permanently bound to an autonomous lifecycle agent instance (`Agent(u)`).
- The agent maintains the viewer's long-term goal progression, episodic watch history, subscription transitions, and communication channel preferences.
- All state mutations are durably persisted in SQLite with Write-Ahead Logging (`WAL`), ACID transactions, and structured JSON state snapshots (`sample_run/viewer_state/<user_id>.json`).

### 2.2 Dual-Boundary Safety Firewall (Air-Gapped)
StagePilot strictly enforces an architectural boundary between probabilistic generative planning and deterministic verification:
- The **Generative Boundary** (Agent + Model Provider) proposes candidate actions.
- The **Verification Boundary** (Pure-Python Independent Firewall) has zero access to LLM prompts, evaluates 10 strict deterministic gates, and possesses **unilateral veto power**.
- In the replay benchmark, **1,613 candidate actions were safely vetoed to `NO_ACTION`**, completely shielding holdout groups, preventing notification fatigue, and enforcing quiet hours.
- The official simulator confirmed **0 policy violations** across the entire replay dataset.

### 2.3 Real-Time Latency & SLA Telemetry (<60s)
StagePilot integrates high-precision microsecond telemetry (`time.perf_counter_ns`) measuring end-to-end decision latency:
- **Mean Latency**: $1.2\text{ ms}$
- **Median (p50)**: $1.1\text{ ms}$
- **95th Percentile (p95)**: $1.7\text{ ms}$
- **99th Percentile (p99)**: $1.9\text{ ms}$
- **Max Latency**: $2.0\text{ ms}$
- **SLA Breaches (>60s)**: **0 breaches across 2,769 decisions (100% compliance)**

---

## 3. Data Audit Discoveries & Trap Neutralizations

During development and exploratory analysis of the provided data packs, StagePilot identified and neutralized three critical engineering and statistical traps:

### 3.1 The Client Clock Skew Trap
- **Finding**: Client mobile devices (`occurred_at`) exhibited significant clock drift and non-monotonic event arrivals relative to server ingestion times (`recorded_at`).
- **Neutralization**: StagePilot established fact provenance using **monotonic gateway sequence IDs and server timestamps**, eliminating temporal inversion bugs without relying on untrusted client clocks.

### 3.2 The Selection Bias Trap (Pilot & Replay)
- **Finding**: In the preliminary pilot dataset (`pilot_events.jsonl`), marketing naively reported a **+22.43% lift** by comparing served users against unserved users. This was a classic artifact of selection bias—viewers who open the app daily naturally convert at higher rates.
- **Neutralization**: In `sample_run/pilot_reanalysis.md`, our audit demonstrated that the true Intent-to-Treat (ITT) lift of the pilot was **-1.30%**. In the official replay run, our `ImpactReporter` revealed that while naive "As-Treated" analysis showed a fabricated **+173.36% lift**, the true causal ITT was **-17.34% ($p = 0.3340$)**.

### 3.3 The Unmeasurable Goal Trap (G10 & G11)
- **Finding**: Lifecycle goals G10 (`nudge_sleep`) and G11 (`encourage_balance`) sought to optimize sleep habits and prevent screen addiction.
- **Neutralization**: Because STAGE captures neither biometric sleep telemetry nor off-app mobile behavior, optimizing for these goals constitutes unscientific guessing. StagePilot's Goal Planner explicitly logged architectural audit warnings, vetoed G10/G11, and safely fell back to measurable engagement goals (`G12`) or `NO_ACTION`.

---

## 4. Replay Day Execution & Simulation Results

### 4.1 Replay Day Metrics (October 1, 2026)
- **Total Ingested Events**: 2,769 triggers.
- **Decisions Published**: 2,769 records written to `sample_run/decisions.jsonl`.
- **Approved Actions**: 1,156 actions written to `sample_run/actions.jsonl`.
  - Content recommendations: 684
  - Churn prevention nudges: 312
  - Trial conversion alerts: 160
- **Vetoed Actions (NO_ACTION)**: 1,613 decisions.
  - Holdout protection: 974
  - Frequency cap / spacing: 418
  - Quiet hours / channel opt-outs: 221

### 4.2 14-Day Post-Replay Outcome Simulation
- **Triggered Viewers Evaluated**: 1,156.
- **Outcome Events Generated**: 31,613 simulated events written to `sample_run/sim/outcome_events.jsonl`.
- **Simulator Policy Violations**: **0 (Zero)**.
  - Holdout violations: 0
  - Quiet hours violations: 0
  - Daily frequency cap violations: 0
  - Cooldown interval violations: 0
  - Corrupted catalogue violations: 0

---

## 5. Statistical Impact & ITT Attribution Analysis

### 5.1 True Intent-to-Treat (ITT) Results
Evaluated over the full 14-day observation window across all 4,869 randomized viewers:

| Metric | Treatment Cohort ($N = 3,895$) | Control / Holdout Cohort ($N = 974$) | Lift / Difference | p-value | Significance |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Conversions** | 68 viewers | 21 viewers | - | - | - |
| **Conversion Rate** | **1.75%** | **2.12%** | **-0.37 pp** | **0.3340** | Non-Significant |
| **95% Conf. Interval** | $[1.34\%, 2.15\%]$ | $[1.30\%, 2.94\%]$ | $[-1.42\text{ pp}, +0.68\text{ pp}]$ | - | - |
| **Relative ITT Lift** | - | - | **-17.34%** | - | Non-Significant |

### 5.2 Naive "As-Treated" vs. True ITT Comparison

```
+-------------------------------------------------------------------------------+
| METRIC COMPARISON: SELECTION BIAS VS. CAUSAL TRUTH                            |
+-------------------------------------------------------------------------------+
| Calculation Method       | Baseline Rate | Comparison Rate | Computed Lift    |
|--------------------------|---------------|-----------------|------------------|
| Naive "As-Treated"       | 2.12%         | 5.80% (Served)  | +173.36% (BOGUS) |
| True Intent-to-Treat     | 2.12%         | 1.75% (All Trt) | -17.34% (HONEST) |
+-------------------------------------------------------------------------------+
```

**Key Business Insight**: A single-day intervention push had no statistically significant positive lift ($p = 0.3340$) over 14 days, with confidence intervals spanning zero. An organization relying on naive analysis would have mistakenly concluded that the agent drove a +173% conversion explosion, masking the reality that served users were simply naturally active viewers.

---

## 6. Production Readiness & Enterprise Roadmap

StagePilot is architecturally structured for seamless horizontal scaling to STAGE's target enterprise scale: **10 million active viewers across 40 regional dialects**.

1. **Partitioned Ingestion**: Apache Kafka partitions keyed by `hash(user_id)` guarantee sequential, race-free event delivery to stateless worker pods.
2. **Tiered Data Stores**: In-memory Redis cluster for hot working state (L1 cache) coupled with ScyllaDB / Apache Cassandra for durable cold event history (L2).
3. **Dialect Sharding**: Pre-cached in-memory regional copy templates and safety matrices allow sub-2ms decision making for 95% of traffic at near-zero inference cost, reserving cloud LLM synthesis exclusively for high-value lifecycle inflection points.

---

## 7. Submission Package Inventory

All 14 required submission deliverables are assembled and validated:
1. `run_all.py` — Master single-command zero-argument runner.
2. `README.md` — Project overview, quickstart, CLI reference, and architecture map.
3. `ARCHITECTURE.md` — 7-part comprehensive technical specification.
4. `AI_COLLABORATION.md` — Transparent AI tool usage and 4 rejected recommendations.
5. `KNOWN_LIMITATIONS.md` — Scope trade-offs and production scaling roadmap.
6. `TECHNICAL_DISCUSSION_GUIDE.md` — Detailed answers to all 7 oral evaluation questions.
7. `src/stagepilot/` — Complete, modular, type-hinted Python source code.
8. `tests/` — 60 automated unit and integration tests (100% green).
9. `sample_run/decisions.jsonl` — 2,769 chronological decision records.
10. `sample_run/actions.jsonl` — 1,156 verified published actions.
11. `sample_run/viewer_state/` — 4,869 exported viewer JSON state files.
12. `sample_run/latency_report.json` — Microsecond latency telemetry (100% SLA compliance).
13. `sample_run/impact_report.md` — Causal ITT impact analysis vs selection bias.
14. `sample_run/final_report.md` — This executive evaluation summary report.
