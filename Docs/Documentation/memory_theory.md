"""Theoretical Foundations of Closed-Loop Cybernetic Memory

1. MEMORY VALUE FUNCTION
------------------------
Formal definition:
  V(m, t, c) = relevance(m, t) × freshness(m) × utility(m, c)

  relevance(m, t) = BM25_score(m, t)  ∈ [0, 1]
  freshness(m)    = exp(-age_days / τ) with τ = 30 days
  utility(m, c)   = 1 + α × ln(1 + usage_count)

Properties:
  - V → 0 as age → ∞ (memories decay exponentially)
  - V grows sublinearly with usage (diminishing returns)
  - V ∈ [0, ∞), but effectively bounded by BM25 ∈ [0, 1]

Adaptive cooldown:
  τ_cool(c) = τ_base × (1 - context_pressure)
  Context pressure ∈ [0, 1] measured by context_usage ratio.
  High pressure → shorter cooldown → more aggressive injection.
  Bounded: τ_cool ∈ [5s, 120s].

2. PID STABILITY (Lyapunov Analysis)
-------------------------------------
Consider the context PID controller:
  e(t) = usage(t) - setpoint  (setpoint = 0.70)
  u(t) = kp·e(t) + ki·∫e(t)dt + kd·e'(t)

Define Lyapunov candidate:
  V_L(e, ∫e) = (1/2)·e² + (ki/2)·(∫e)²

Then:
  V̇_L = e·ė + ki·(∫e)·e
       = e·(-kp·e - ki·∫e - kd·ė)/m + ki·(∫e)·e
       = -(kp/m)·e² - kd·e·ė

For kd·e·ė ≈ 0 at steady state, V̇_L < 0 when kp > 0.
The system is asymptotically stable: e(t) → 0 as t → ∞.

With anti-windup (integral clamping at I_max):
  V̇_L ≈ -(kp/m)·e² < 0  for |∫e| < I_max

3. INFORMATION PRESERVATION ACROSS TIERS
------------------------------------------
Memory tiers: WORKING → SHORT_TERM → LONG_TERM → ARCHIVAL

Information content I(m) of a memory:
  I(m) = -log₂(p(m is retrieved | task))

Tier transitions preserve:
  WORKING → SHORT_TERM: I preserved 100% (no compression)
  SHORT_TERM → LONG_TERM: I preserved 100%
  LONG_TERM → ARCHIVAL: I(m_arch) ≈ I(m) - ε
    where ε = -log₂(len(original)/len(summarized)) [compression loss]

4. RETRIEVAL QUALITY BOUNDS
-----------------------------
For a hybrid pipeline (BM25 + Reranker):
  P@3 ≥ max(P@3_bm25, P@3_rerank) [pipeline never worse than best component]

With domain weighting:
  noise_rate ≤ noise_bm25 × (1 - Jaccard(domains_entry, active_domains))

5. SPREADING ACTIVATION
------------------------
Activation propagates through related_to graph:
  a_j = Σ_i a_i × decay × sim(m_i, m_j)
  depth=1, decay=0.5, sim=Jaccard(m_i, m_j)

This implements Hebbian-style reinforcement: memories used together
become linked, and retrieval of one primes the other.

Implementation: memory_pipeline.py (T1, T2, T3)
"""
