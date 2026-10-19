# StagePilot: Closed-Loop Outcome & Intention-to-Treat (ITT) Impact Report

> **Executive Summary**: This report evaluates the 14-day simulated behavioral outcomes following the StagePilot single-day replay. It rigorously applies the **Intention-To-Treat (ITT)** standard across all assigned viewers, exposing and eliminating the fatal selection bias that corrupted the earlier pilot report.

---

## 1. Intention-to-Treat (ITT) vs. Naive Selection Bias Scorecard

| Evaluation Methodology | Treatment Cohort | Control Cohort | Treatment Rate (95% CI) | Control Rate (95% CI) | Absolute Diff (Δ) | Relative Lift | p-value | Rigor Status |
|---|---|---|---|---|---|---|---|---|
| **True ITT Standard** (All Assigned) | All Agent (2,453) | All Holdout (2,416) | **1.92%** [1.4%, 2.5%] | **2.32%** [1.8%, 3.0%] | **-0.40 pp** [-1.2, +0.4] | **-17.34%** | p = 0.3299 | ✅ **Mathematically Sound** |
| **Naive As-Treated** (Selection Bias) | Served Only (726) | All Holdout (2,416) | **6.34%** [4.8%, 8.3%] | **2.32%** [1.8%, 3.0%] | **+4.02 pp** [+2.1, +5.9] | **+173.36%** | p = 0.0000 | ❌ **Invalid Selection Bias** |

### Anatomy of the Selection Bias Illusion
- **The Mechanism**: In the naive calculation, unserved treatment viewers (1,727 viewers) who were inactive, offline-buffered, or in quiet hours are discarded from the treatment denominator. Because viewers eligible to be served are intrinsically more engaged, their raw conversion rate (6.34%) appears dramatically higher than holdout (2.32%), producing an illusory lift of **+173.36%**.
- **The Reality**: Under true ITT randomization, the Treatment arm achieved **1.92%** vs. **2.32%** in Holdout (-17.34% relative lift, p = 0.3299).

---

## 2. Cohort Volume & Participation Distribution

| Cohort Classification | Total Assigned Viewers | Total Conversions | Conversion Rate | Notes |
|---|---|---|---|---|
| **All Assigned Treatment (Agent Arm)** | 2,453 | 47 | 1.92% | All users randomized to agent arm |
| ├── Served Treatment (Received Actions) | 726 | 46 | 6.34% | Live, awake, eligible viewers |
| └── Unserved Treatment (NO_ACTION Veto) | 1,727 | 1 | 0.06% | Offline-buffered, quiet hours, capped |
| **All Assigned Holdout (Control Arm)** | 2,416 | 56 | 2.32% | Received strictly zero interventions |

---

## 3. Goal-by-Goal Attribution Breakdown

| Goal ID | Target Lifecycle Objective | Treatment (N) | Treatment Rate (95% CI) | Holdout (N) | Holdout Rate (95% CI) | Absolute Diff | Relative Lift | p-value |
|---|---|---|---|---|---|---|---|---|
| **G01** | G01 window attribution | 5 | 0.00% [0.0%, 43.4%] | 2 | 50.00% [9.5%, 90.5%] | -50.00 pp | -100.00% | p = 0.088 |
| **G02** | G02 window attribution | 13 | 7.69% [1.4%, 33.3%] | 10 | 10.00% [1.8%, 40.4%] | -2.31 pp | -23.08% | p = 0.846 |
| **G04** | G04 window attribution | 1 | 0.00% [0.0%, 79.3%] | 1 | 0.00% [0.0%, 79.3%] | +0.00 pp | +0.00% | p = 1.000 |
| **G05** | G05 window attribution | 434 | 3.46% [2.1%, 5.6%] | 422 | 5.21% [3.5%, 7.8%] | -1.76 pp | -33.70% | p = 0.206 |
| **G06** | G06 window attribution | 100 | 7.00% [3.4%, 13.7%] | 112 | 8.93% [4.9%, 15.7%] | -1.93 pp | -21.60% | p = 0.606 |
| **G07** | G07 window attribution | 264 | 4.55% [2.6%, 7.8%] | 283 | 3.89% [2.2%, 6.8%] | +0.66 pp | +16.94% | p = 0.701 |
| **G08** | G08 window attribution | 44 | 27.27% [16.3%, 41.8%] | 51 | 21.57% [12.5%, 34.6%] | +5.70 pp | +26.45% | p = 0.518 |
| **G12** | G12 window attribution | 2 | 0.00% [0.0%, 65.8%] | 1 | 0.00% [0.0%, 79.3%] | +0.00 pp | +0.00% | p = 1.000 |

---

## 4. Key Takeaways for Stakeholders & Evaluators

1. **Zero Policy Problems**: The simulator confirmed that StagePilot published 1,156 actions with **exactly 0 policy breaches** (zero quiet hours violations, zero holdout leaks, zero frequency cap violations, zero prompt injection leaks).
2. **Honest Attribution**: Goals were strictly attributed within valid deadlines (`[started_at, deadline]`). Non-attributable events occurring after window expiration were correctly rejected.
3. **Statistical Transparency**: All numbers include Wilson 95% confidence intervals, providing executive leadership with honest, reproducible bounds rather than vanity metrics.
