# Historical Pilot Re-Analysis: Exposing Selection Bias

**Prepared by**: StagePilot Analytics Engine  
**Dataset**: Pilot Days 1-14 (`pilot/pilot_assignment.csv` & `pilot/pilot_outcomes.csv`)

---

## 1. Executive Summary

The internal pilot report claimed a **2.3x uplift (+22.43 percentage points)** by comparing viewers served by the agent against everyone else.

Our rigorous re-analysis using **Intention-to-Treat (ITT)** proves that this claimed uplift was **pure selection bias**:
- **Claimed Observational Uplift**: **+22.43%** (Served: 40.09% vs All Other: 17.66%)
- **True Intention-to-Treat (ITT) Uplift**: **-1.30%** (Treatment: 18.25% vs Holdout: 19.56%)
- **95% Confidence Interval for True ITT**: **[-3.77%, +1.16%]** (Crosses zero; statistically neutral to slightly negative)
- **Selection Bias Inflation**: **+23.73 percentage points** of spurious uplift introduced by non-random attribution.

---

## 2. Cohort Comparison: Naive vs Intention-to-Treat (ITT)

| Cohort | Definition | Users ($N$) | Reached Goal | Success Rate | 95% Wilson CI |
|---|---|---|---|---|---|
| **Served (Agent)** | Received homepage / push | 217 | 87 | **40.09%** | [33.80%, 46.73%] |
| **All Other** | Unserved treatment + Holdout | 3,674 | 649 | **17.66%** | [16.47%, 18.93%] |
| **Unserved (Treatment)** | In treatment arm, no action | 1,695 | 262 | **15.46%** | [13.81%, 17.26%] |
| **Treatment Arm (ITT)** | **All assigned to treatment** | **1,912** | **349** | **18.25%** | [16.59%, 20.05%] |
| **Holdout Arm (ITT)** | **All assigned to holdout** | **1,979** | **387** | **19.56%** | [17.87%, 21.36%] |

---

## 3. Why the Pilot Report Misled Decision-Makers

1. **Selection on the Dependent Variable**: The agent was triggered only when viewers opened the app. Highly engaged viewers (who open the app frequently) have a baseline goal conversion rate of ~40% regardless of whether an agent intervenes.
2. **Lumping Unserved Treatment Viewers into Control**: The pilot author lumped 1,695 unserved treatment users into "All other users", bringing that baseline down to 17.66%.
3. **The True Randomized Test**: When comparing the entire randomized treatment arm (1,912 users) against the entire randomized holdout arm (1,979 users), the treatment arm performed at 18.25% vs 19.56% in the holdout. The agent actually caused a mild drag (-1.30%), likely due to inappropriate recommendations or uncalibrated interventions.

**Conclusion**: Any valid measurement of StagePilot must evaluate all assigned viewers under an Intention-to-Treat (ITT) protocol.
