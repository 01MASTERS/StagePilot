# Known Limitations & Production Engineering Roadmap

## 1. Intentional Scope & Architecture Trade-Offs

StagePilot was engineered specifically to solve the STAGE hiring challenge: demonstrating a production-grade, stateful, dual-boundary autonomous lifecycle management system capable of executing deterministic replays, surviving adversarial data traps, and proving causal ITT impact.

To maximize reliability, transparency, and zero-dependency reproducibility within the assignment's operational scope, several deliberate architectural trade-offs were made.

---

## 2. Identified Limitations & Production Scaling Path

### 2.1 Single-Node Persistence vs. Distributed Streaming
- **Current Implementation**:
  - Local SQLite database with Write-Ahead Logging (WAL) and in-memory LRU caching.
  - Processes single-day historical replay (2,769 triggers, 4,869 viewer states) in a few seconds on a single developer machine with sub-2ms decision latencies.
- **Production Reality (10M Viewers, 40 Dialects)**:
  - A single SQLite database cannot support 100,000 concurrent write transactions per second during prime-time evening streaming across India.
- **Production Roadmap**:
  - **Message Broker**: Apache Kafka / AWS Kinesis with 128+ partitions keyed by `user_id` hash, guaranteeing monotonic event delivery per viewer.
  - **State Store**: ScyllaDB or Apache Cassandra (L2 persistence) coupled with an in-memory Redis cluster (L1 hot state) with partition affinity.
  - **Compute Tier**: Horizontally auto-scaled Kubernetes pods running stateless StagePilot worker runtimes.

### 2.2 Deterministic Rule Policies vs. Contextual Multi-Armed Bandits (MAB)
- **Current Implementation**:
  - Goal selection and intervention arm ranking use deterministic heuristic scoring based on explicit viewer signals (churn risk, dialect affinity, tenure, watch completion).
  - Deterministic mapping guarantees 100% auditability, zero stochastic drift, and reproducible test fixtures.
- **Limitation**:
  - Does not continuously explore arm variations or adapt dynamically to shifting seasonal preferences without human rule updates.
- **Production Roadmap**:
  - Integrate a **Contextual Multi-Armed Bandit** (e.g., LinUCB or Thompson Sampling) within the Generative Boundary.
  - The bandit balances exploration of new content arms with exploitation of proven high-conversion arms.
  - Crucially, the **Air-Gapped Safety Firewall remains strictly deterministic**, ensuring that bandit exploration never violates frequency caps, quiet hours, or holdout constraints.

### 2.3 Metadata-Driven Retrieval vs. Dense Semantic Embeddings
- **Current Implementation**:
  - Catalogue matching relies on structured metadata matching: dialect matching (`primary_dialect`), genre affinity, release recency, and episode index.
- **Limitation**:
  - Fails to capture subtle cross-genre thematic affinities (e.g., a viewer who loves intense rustic crime thrillers in Bhojpuri might enjoy a gritty political drama in Haryanvi, even if tagged with different primary genres).
- **Production Roadmap**:
  - Deploy a two-tower vector embedding model (user history tower + video content tower) indexed in Milvus or pgvector.
  - Enable semantic similarity retrieval while retaining strict metadata filtering for regional dialect preferences.

### 2.4 Multi-Device Concurrent Session Resolution
- **Current Implementation**:
  - State tracking assumes a single linear event stream per `user_id`.
- **Limitation**:
  - In Indian regional households, a single STAGE account is frequently shared across multiple devices (e.g., Smart TV in the living room and two mobile phones). Simultaneous playback on multiple devices can interleave events with conflicting pause/play states.
- **Production Roadmap**:
  - Introduce `session_id` and `device_id` as primary dimensions within `ViewerState`.
  - Implement a CRDT (Conflict-free Replicated Data Type) or Last-Write-Wins (LWW) per session to aggregate multi-device consumption into a unified viewer journey.

### 2.5 Offline Replay vs. Real-Time Distributed Push Gateways
- **Current Implementation**:
  - Actions are published to an append-only JSONL stream (`actions.jsonl`) for simulation and offline evaluation.
- **Limitation**:
  - Does not include real-time integration with external push notification vendors (CleverTap, MoEngage, Firebase Cloud Messaging, Gupshup SMS).
- **Production Roadmap**:
  - Implement an asynchronous outbound dispatcher tier with token bucket rate limiters, handling carrier DND (Do Not Disturb) registries, network retries, and delivery receipt webhooks.
