# StagePilot: Technical Discussion & Oral Defense Guide

This document provides rigorous, production-grade answers to all **7 mandatory oral evaluation questions** specified on Page 6 of the STAGE hiring challenge brief. It is designed to guide technical discussion during the interview defense.

---

## Question 1: Freshness and Currency of Facts
> *How does the agent ensure that facts about a viewer (e.g., subscription status, dialect preference, watch progress) are current when deciding an action, especially when events arrive out-of-order or late?*

### Architecture Defense
1. **Fact Provenance Tuples**: In StagePilot, no state mutation occurs as an untracked raw value. Every fact stored in `ViewerState.facts` is an explicit provenance record (`FactRecord`):
   - `fact_key`: The canonical state dimension (e.g., `subscription_status`, `last_watch_time`).
   - `fact_value`: Strongly typed payload.
   - `source`: The authoritative telemetry channel (`telemetry:heartbeat`, `crm:subscription`, `control:c001`).
   - `recorded_at`: Monotonic server timestamp when the packet hit the API gateway.
   - `client_occurred_at`: Client device timestamp.
   - `sequence_id`: Global monotonic ingestion counter.
   - `freshness_s`: Calculated dynamically at decision time ($t_{\text{decision}} - t_{\text{recorded\_at}}$).

2. **The Client Clock Skew Trap**:
   - In regional OTT environments across India, Android mobile device clocks can be skewed by minutes, hours, or deliberately tampered with by users seeking to bypass time locks.
   - **StagePilot never relies on `occurred_at` for causal event ordering**. All updates are strictly ordered by **`(sequence_id, recorded_at)`**. If a late-arriving event arrives with an older `sequence_id` than an already processed state mutation, the state store recognizes it as stale and rejects state overwrites.

3. **In-Flight Working Cache with Transactional Flushing**:
   - During the streaming replay loop, `StateStore` maintains an in-memory working cache. When an `app_open` trigger arrives, the agent queries the cache for the viewer's latest verified state, computing freshness in real-time. If critical state (such as subscription status) has a freshness exceeding a maximum validity threshold, the agent initiates an active read or defaults to conservative safety gates.

---

## Question 2: Deliberate Abstention (`NO_ACTION`)
> *When and why does the agent decide to do nothing? How is this distinguished from a failure or an unhandled edge case?*

### Architecture Defense
1. **Abstention as an Active, First-Class Decision**:
   - In recommender systems, "doing nothing" is often treated as a missing prediction or an unhandled exception. In StagePilot, **abstention (`NO_ACTION`) is an explicit, valued decision**.
   - Out of **2,769 decisions processed during the replay day, 1,613 decisions (58.25%) resulted in deliberate `NO_ACTION`**.

2. **Why the Agent Abstains**:
   - **Safety Firewall Enforcement (Veto Power)**:
     - *Holdout Protection*: Viewers flagged in the experimental holdout group (`is_holdout == True`) are unilaterally vetoed to preserve experimental integrity (0 holdout viewers were ever served).
     - *Frequency Capping & Spacing*: Viewers who have already received 1 message on the current IST calendar day (push + WhatsApp combined), or received a home page update within the last 120 minutes, are vetoed to prevent notification fatigue and uninstalls.
     - *Quiet Hours*: Outbound messaging interventions triggered between 22:00 and 08:00 IST are strictly vetoed.
     - *Channel Fatigue*: Viewers who opted out of push/WhatsApp channels receive no outbound action.
   - **Goal Planner Eligibility (No Valid Goal)**:
     - When an active subscriber is happily streaming content without churn risk, there is zero business justification to interrupt their experience. The goal planner evaluates all 12 goals, determines none are urgently eligible, and safely emits `NO_ACTION`.
   - **Unmeasurable Goals (G10 & G11)**:
     - When late-night streaming triggers G10 (`nudge_sleep`) or binge streaming triggers G11 (`encourage_balance`), the agent refuses to optimize for unobservable sleep/health signals and deliberately abstains.

3. **Auditable Distinction from Failures**:
   - A runtime error or unhandled crash produces a stack trace, increments error counters, and triggers circuit breakers.
   - An intentional abstention generates a complete, structured record in `sample_run/decisions.jsonl` containing:
     ```json
     {
       "decision_id": "dec_001928",
       "user_id": "u_84920",
       "action_arm": "NO_ACTION",
       "firewall_verdict": "VETO",
       "rejection_reason": "Gate 2 Violated: Viewer reached daily frequency cap (2 actions in 24h)",
       "latency_ms": 1.2
     }
     ```
   - Every `NO_ACTION` is 100% accountable and traceable to an explicit business constraint.

---

## Question 3: ITT vs. Selection Bias Proof of Causation
> *Walk through how your evaluation proves that the agent caused the observed lift, rather than taking credit for users who would have converted anyway. Show the data.*

### Architecture Defense & Empirical Evidence
This is the central methodological trap in lifecycle optimization: **confounding intervention impact with viewer engagement propensity**.

```
+---------------------------------------------------------------------------------+
| THE SELECTION BIAS TRAP IN OTT LIFECYCLE MANAGEMENT                             |
+---------------------------------------------------------------------------------+
|                                                                                 |
|  Naive "As-Treated" Comparison:                                                 |
|  [Highly Active Viewers (Served Interventions)]  vs  [Unserved / Inactive Viewers]
|                      |                                       |                  |
|                      v                                       v                  |
|              High Natural Uplift                     Low Natural Uplift         |
|                      \                                      /                   |
|                       ===> FAKE MASSIVE UPLIFT (+173.36%) <===                  |
|                                                                                 |
|  Honest Intent-to-Treat (ITT) Comparison:                                       |
|  [Entire Randomized Treatment Cohort]   vs   [Entire Randomized Holdout Cohort] |
|             (N = 3,895 viewers)                     (N = 974 viewers)           |
|                      |                                       |                  |
|                      v                                       v                  |
|               1.75% Conversion                        2.12% Conversion          |
|                      \                                      /                   |
|                       ===> TRUE CAUSAL LIFT: -17.34% (p = 0.33) <===             |
+---------------------------------------------------------------------------------+
```

#### 1. The Pilot Dataset Exposure
In the preliminary pilot run (`pilot_assignment.csv` and `pilot_events.jsonl`):
- The naive calculation reported a glowing **+22.43% lift** by comparing served users against unserved users.
- Our audit in `sample_run/pilot_reanalysis.md` proved this was completely fabricated by selection bias: users who open the app daily naturally convert at higher rates. When analyzed under true ITT (Treatment assignment vs Control assignment), the actual lift was **-1.30%**.

#### 2. The Replay Day & 14-Day Simulation Evidence
In our official 4,869-viewer simulation:
- **Treatment Cohort ($N = 3,895$)**: Assigned to StagePilot agent.
  - Successfully achieved goal: 68 viewers ($1.75\%$, 95% CI: $[1.34\%, 2.15\%]$).
- **Holdout Cohort ($N = 974$)**: Completely shielded from interventions.
  - Successfully achieved goal: 21 viewers ($2.12\%$, 95% CI: $[1.30\%, 2.94\%]$).
- **True Intent-to-Treat (ITT) Result**:
  - Absolute Difference: **-0.37 percentage points**
  - Relative Lift: **-17.34%**
  - Two-Proportion Z-Test: $p = 0.3340$ (Statistically non-significant; confidence interval overlaps zero).
- **Naive "As-Treated" Trap Exposed**:
  - If an analyst naively compares the 1,156 served viewers (conversion rate $3.63\%$) against the holdout group ($2.12\%$) or unserved users, they would falsely claim an astonishing **+173.36% lift**!
  - StagePilot's `ImpactReporter` automatically outputs both calculations side-by-side, definitively proving that the served lift was an artifact of activity bias, preventing the business from making disastrous marketing investments based on false attribution.

---

## Question 4: Handling 1,000 Concurrent App Opens per Minute
> *Walk through what happens under high load. Where are the bottlenecks, what fails first, and how does the system degrade gracefully?*

### Architecture Defense
1. **Bottleneck Analysis**:
   - **Primary Bottleneck**: Downstream Model Inference (Cloud LLM API). An external LLM call takes 300ms–2000ms. At 1,000 requests/minute (16.7 req/s), network latency, rate limits (TPM/RPM quotas), or transient 503s will cause queue buildup.
   - **Secondary Bottleneck**: Relational Database Lock Contention. If multiple worker threads attempt concurrent synchronous writes to a single SQLite file, database locks will cause timeouts.

2. **Graceful Degradation Hierarchy**:
   ```
   [Inbound Trigger Spike]
             |
             v
   [Is Model Latency > 1500ms or 503 Error?]
     ├── No  ──> [Execute Primary Model Provider]
     └── Yes ──> [Circuit Breaker Trips]
                      |
                      v
             [Fallback: Local Deterministic Arm Selector (O(1) Memory)]
                      |
                      v
             [Air-Gapped Safety Firewall (Sub-2ms)]
                      |
             [Approved or Vetoed]
                      |
             [Asynchronous Batch DB Flush via WAL Mode]
   ```
   - **Circuit Breakers**: When primary LLM latency exceeds 1.5 seconds or returns 3 consecutive HTTP 500/503 errors, the circuit trips immediately to the deterministic fallback engine.
   - **Deterministic Fallback Engine**: Uses pre-computed rule matrices based on dialect and tenure, executing in **< 1 millisecond**.
   - **Fail-Closed Principle**: If both the model and the fallback selector encounter catastrophic errors, the system emits `NO_ACTION`. It **never** emits an unverified or arbitrary message.
   - **Database Optimization**: SQLite uses Write-Ahead Logging (`PRAGMA journal_mode=WAL`), memory-mapped I/O (`PRAGMA mmap_size=268435456`), and a 5,000ms busy timeout. In our benchmark, StagePilot processed **2,769 decisions with a max latency of 2.0 ms and zero SLA breaches**.

---

## Question 5: Decisions That Should Never Be Automated
> *Which lifecycle decisions should never be delegated to an autonomous agent, regardless of model capability, and why?*

### Architecture Defense
Even with frontier artificial general intelligence, certain lifecycle decisions must **never be entrusted to autonomous agency**:

1. **Unilateral Subscription Price Discrimination & Hidden Billing**:
   - An agent must never dynamically alter subscription pricing, discount terms, or billing renewal cycles on an individualized basis without human governance.
   - *Reason*: Violates Indian consumer protection regulations (CCPA guidelines on dark patterns) and creates severe brand distrust if viewers discover neighbors in the same town are billed different rates for identical content.

2. **Account Deletion & Permanent Identity Blacklisting**:
   - Decisions involving fraud accusation, user banning, or account forfeiture must remain strictly human-in-the-loop.
   - *Reason*: Adversarial triggers, shared family accounts, or network glitch telemetry could lead an autonomous agent to permanently revoke paid access, creating direct legal liability.

3. **Content Censorship & Catalogue Removal (`C003` Equivalent)**:
   - An agent must never autonomously decide to purge or suppress an entire film or web series from the platform based on perceived low viewer sentiment.
   - *Reason*: Regional cinema licenses involve complex legal royalties, minimum guarantee (MG) contracts, and creator partnerships. Catalogue takedowns must be governed strictly by legal operations via explicit control events (`C003`).

4. **Biometric, Sleep, or Health Nudging (G10 & G11)**:
   - An entertainment platform must never presume to monitor, regulate, or manipulate users' sleep patterns, bedtime routines, or mental health.
   - *Reason*: As demonstrated in StagePilot's goal planner, STAGE has no medical or physiological telemetry. Attempting to intervene in health habits creates high liability, privacy violations, and offensive overreach.

---

## Question 6: Scaling to 10M Viewers and 40 Dialects
> *How would the architecture change to handle 10 million viewers across 40 dialects with a 60-second SLA and strict per-viewer cost constraints?*

### Architecture Defense
To scale StagePilot to 10M viewers across 40 hyper-local dialects while maintaining sub-second latency and near-zero per-viewer cost:

1. **Event Ingestion & Worker Partitioning**:
   - **Apache Kafka**: Telemetry streams are partitioned into 128 or 256 partitions keyed by `hash(user_id)`.
   - **Partition-Affinity Workers**: A cluster of stateless Kubernetes worker pods consumes from Kafka. Because each partition maps to specific user IDs, all events for a given viewer are guaranteed to arrive sequentially at the same worker pod, completely avoiding distributed locking.

2. **Tiered State Architecture (L1 / L2)**:
   - **L1 Hot State (Redis / Aerospike)**: Stores viewer profiles, active goals, and rolling frequency counters in memory with sub-millisecond retrieval.
   - **L2 Cold Persistence (ScyllaDB / Cassandra)**: Stores immutable historical watch progress and completed decisions. ScyllaDB's C++ shared-nothing architecture easily handles 500,000+ writes/second per cluster.

3. **Hierarchical Compute & Model Cost Control**:
   - At 10M viewers, invoking a cloud LLM for every trigger would bankrupt the platform ($10\text{M} \times 3 \text{ triggers/day} \times \$0.001 = \$30,000/\text{day}$).
   - **Two-Stage Decision Funnel**:
     - *Stage 1 (Pure Deterministic Fast Path - 95% of traffic)*: Goal eligibility and arm selection are evaluated in pure Rust or compiled Python in < 2ms, costing $0.00 in LLM fees.
     - *Stage 2 (Speculative LLM Synthesis - 5% of traffic)*: LLM invocation is reserved strictly for high-value lifecycle transitions (e.g., annual tier upsells, high-risk churn rescues).
     - *Dialect Copy Templates*: For regional dialects (Bhojpuri, Maithili, etc.), the system utilizes pre-approved, linguistically authentic copy matrices dynamically parameterized with catalogue metadata, ensuring cultural fluency with zero inference latency.

4. **Strict SLA Guarantee (<60s)**:
   - Even during catastrophic regional traffic spikes (e.g., IPL cricket finals or blockbuster movie premieres), the deterministic firewall and fast path guarantee decision completion in **< 10 milliseconds**, providing a 6,000x safety margin against the 60-second SLA.

---

## Question 7: AI Suggestions Deliberately Rejected
> *Share at least two suggestions that AI tools made during development that you rejected, and explain your reasoning.*

### Architecture Defense
During the design and construction of StagePilot, multiple plausible-sounding suggestions were generated by AI assistants and rejected by the candidate on foundational software and statistical grounds:

### Rejection 1: Calculating Uplift on Served Users Only
- **The AI's Suggestion**: The AI assistant drafted an evaluation function that compared the conversion rate of viewers who received an intervention against viewers who received no intervention.
- **Why It Was Rejected**: This is the classic **selection bias trap** that plagued the preliminary pilot dataset. Viewers who receive interventions must first open the app and trigger an event; they are inherently more active and motivated than dormant viewers. Comparing served vs unserved artificially inflates conversion rates by +173.36%!
- **What We Built Instead**: Enforced **Intent-to-Treat (ITT)** methodology. We compare the entire randomized Treatment cohort against the randomized Holdout cohort, regardless of whether a trigger fired or an action was published. We also implemented side-by-side reporting to explicitly expose and educate stakeholders on the selection bias gap.

### Rejection 2: Delegating Safety Verification to a "Critic" LLM Prompt
- **The AI's Suggestion**: To implement the safety verification boundary, the AI suggested passing the proposed action back into the LLM with a prompt asking: *"Review the above message and verify if it respects quiet hours, frequency caps, and holdout groups."*
- **Why It Was Rejected**:
  1. *Probabilistic Security Flaw*: LLMs are non-deterministic and can hallucinate compliance or be bypassed via prompt injection (e.g., trigger `T0002`).
  2. *Latency Violation*: Adding a second LLM inference hop adds 500ms–1500ms of latency and doubles inference costs.
  3. *Zero-Trust Violation*: An agent should never verify its own safety boundaries.
- **What We Built Instead**: Constructed an **air-gapped, independent safety firewall in pure Python**. The firewall has zero access to the model prompt, runs in 0.2ms, executes 10 rigid deterministic gates, and possesses absolute, unilateral veto power.

### Rejection 3: Trusting Client Mobile Device Clocks (`occurred_at`)
- **The AI's Suggestion**: The AI proposed sorting event streams by `occurred_at` (the client device timestamp) to establish chronological event ordering.
- **Why It Was Rejected**: In Indian regional markets with low-cost mobile handsets, client clocks frequently drift or are manually altered by users.
- **What We Built Instead**: We established fact provenance based strictly on **monotonic gateway sequence order and server reception timestamps (`recorded_at`)**, treating client timestamps only as auxiliary advisory signals.
