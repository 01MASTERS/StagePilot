# AI Collaboration & Engineering Methodology

## 1. Transparency & Tooling

In accordance with the hiring challenge specification (Candidate Brief Page 5), this document transparently details how AI tools were utilized during the conception, design, implementation, and verification of **StagePilot**.

### AI Tool Stack
- **Primary AI Pair-Programming Assistant**: Claude / Google DeepMind Antigravity agentic environment.
- **Model Frameworks Evaluated**:
  - Google Gemini 2.5 Flash (`google-genai` SDK) for live cloud LLM reasoning and multimodal dialect intervention synthesis.
  - Ollama (`deepseek-r1:8b`, `llama3`) for private on-premises execution.
  - Deterministic `MockReplayModelProvider` for 100% reproducible, zero-API-key offline execution and CI/CD validation.

---

## 2. Test-Driven Verification & Quality Control

AI coding assistants can generate plausible-looking code that subtly fails edge cases or hallucinates platform invariants. To guarantee production-grade correctness, StagePilot followed a strict **Test-Driven Development (TDD)** discipline:

1. **Test-First Implementation**: For every phase, formal unit and integration tests were drafted *before* or *concurrently* with component logic.
2. **Deterministic Verification Suite**: The codebase includes **60 automated pytest tests** covering:
   - Catalogue and event ingestion with dialect isolation.
   - SQLite ACID transactions, WAL logging, and state export.
   - Goal planning eligibility rules (G01–G09) and explicit unmeasurable goal vetoing (G10/G11).
   - Intervention arm selection and provider abstraction.
   - Independent 10-gate safety firewall with unilateral veto enforcement.
   - Chronological replay pump and monotonic gateway sequence sorting.
   - Latency SLA telemetry (<60s) with microsecond precision.
   - Closed-loop outcome judging, causal attribution windows, and Intent-to-Treat (ITT) statistical calculation.
3. **Automated Verification Loop**: No phase was declared complete until `pytest tests/ -v` passed with 100% green status.

---

## 3. Concrete AI Suggestions Deliberately Rejected

The most critical engineering value delivered was **discerning when to reject AI recommendations**. Below are four major AI suggestions that were proposed during development and deliberately rejected by the engineer:

### Rejection 1: Trusting Mobile Device Clocks (`occurred_at`) for Event Sequencing
- **AI Proposal**: The AI assistant initially suggested sorting ingested telemetry events by `occurred_at` (the client phone's timestamp) to reconstruct user viewing journeys.
- **Why It Was Rejected**: In real-world OTT mobile applications (especially in regional markets with diverse Android device tiers), client device clocks suffer from severe clock skew, inaccurate timezone settings, and deliberate user manipulation (e.g., users setting phone clocks forward to unlock content or bypass cooldowns).
- **Engineering Resolution**: StagePilot establishes fact provenance using **monotonic gateway sequence order and server ingestion timestamps (`recorded_at`)**, treating client timestamps merely as auxiliary metadata.

### Rejection 2: Evaluating Uplift on Served Users Only ("As-Treated" Selection Bias)
- **AI Proposal**: When designing the outcome evaluation and impact reporting modules, the AI proposed computing uplift by comparing viewers who received an intervention against viewers who did not receive one.
- **Why It Was Rejected**: This is the classic **selection bias trap** that invalidated the preliminary pilot experiment (which claimed a fake +22.43% lift while the true ITT was -1.30%). Viewers who open the app frequently and engage deeply are far more likely to trigger and receive interventions. Comparing served vs unserved confounds treatment effect with viewer activity propensity.
- **Engineering Resolution**: Implemented strict **Intent-to-Treat (ITT)** analysis. The entire randomized treatment group is compared against the randomized holdout group, regardless of whether a trigger occurred or an action was published. Additionally, StagePilot computes the naive "As-Treated" metric side-by-side to expose the +173.36% selection bias inflation.

### Rejection 3: Asking the LLM to Self-Verify Its Own Safety Guardrails ("Self-Policing Fallback")
- **AI Proposal**: The AI suggested using a secondary "Safety & Policy Critic" LLM prompt to verify that proposed interventions complied with frequency caps, quiet hours, and holdout constraints.
- **Why It Was Rejected**: LLMs are probabilistic text generators. Relying on an LLM to police another LLM violates fundamental zero-trust security boundaries:
  - Subject to jailbreaks and adversarial prompt injection (e.g., trigger `T0002`).
  - Nondeterministic and prone to subtle policy hallucinations.
  - Adds unnecessary network roundtrips (hundreds of milliseconds) when evaluating a tight 60-second SLA.
- **Engineering Resolution**: Implemented an **air-gapped, independent safety firewall in pure Python**. The firewall has zero access to the model prompt, operates strictly on deterministic state and catalogue tables, and possesses unilateral veto power.

### Rejection 4: Re-processing Historical Viewer Events on Mid-Replay Rule Updates (`C004`)
- **AI Proposal**: Upon receiving dynamic control event `C004` (tightening the daily frequency cap from 2 to 1), the AI suggested re-running the historical event stream to retroactively adjust past states.
- **Why It Was Rejected**: In a production event-driven system, history is immutable. Past decisions published to users cannot be un-sent. Furthermore, retroactively modifying past state would violate causal temporal ordering and cause catastrophic latency spikes during live streaming.
- **Engineering Resolution**: Designed dynamic rules to apply **forward-only** from the exact sequence timestamp of the control event. In-memory firewall policies are updated in O(1) time without mutating immutable historical records.

---

## 4. Evaluation of LLM Reasoning Quality

During development, we evaluated both Gemini and local Ollama models on intervention generation:
- **Strengths**: LLMs excel at regional dialect nuance (e.g., crafting culturally authentic Bhojpuri or Haryanvi copy that respects informal colloquialisms without sounding like mechanical translations).
- **Weaknesses**: LLMs frequently hallucinated non-existent catalogue titles (`t_bollywood_blockbuster_99`) or attempted to format action parameters with creative freeform JSON keys unless constrained by rigid Pydantic schemas.
- **Architecture Defense**: StagePilot's Pydantic schema validation and Firewall Gate 7 (Catalogue Existence) completely neutralized model hallucinations before any action could reach the publishing pipeline.
