"""Opportunity score formula.

opportunity_score (0.0 - 1.0) estimates how valuable it would be for the
target domain to win visibility on a given query. Higher = more valuable.

Formula (weighted sum of four normalised 0-1 factors):

    opportunity_score = 0.35 * volume_factor
                       + 0.20 * ease_factor
                       + 0.30 * gap_factor
                       + 0.15 * intent_factor

- volume_factor (0.35): log-scaled search volume, normalised against a 10k/mo
  cap. Log scaling is used because raw search volume is extremely
  right-skewed (a handful of head terms can be 100x a typical long-tail
  question) — without it, volume alone would dominate the score.

- ease_factor (0.20): (100 - competitive_difficulty) / 100. Lower difficulty
  means it's more realistically achievable to win visibility soon, so it
  gets weighted, but deliberately less than volume and gap — a very easy,
  very low-value query still isn't a great opportunity.

- gap_factor (0.30): 1.0 if the domain is NOT currently visible for this
  query (full opportunity gap), 0.15 if it IS already visible (small residual
  value in reinforcing/defending an existing position, not zero). This is
  weighted second-highest because "not appearing at all" is the platform's
  core value proposition — the whole point of the product is closing this gap.

- intent_factor (0.15): commercial intent multiplier based on the query's
  intent classification from Agent 1. Comparison and best-of queries
  correlate with users close to a purchase decision, so they're worth more
  than the same volume/difficulty on a purely informational query.
    comparison      -> 1.00
    best_of         -> 0.90
    transactional    -> 0.85
    informational    -> 0.50

All four factors are already 0-1, and the weights sum to 1.0, so the result
is naturally bounded to [0, 1] without needing a final clamp — clamping is
kept anyway as a defensive guard against unexpected inputs.
"""
from __future__ import annotations

import math

VOLUME_CAP = 10_000  # search volumes above this don't add further score
INTENT_WEIGHTS = {
    "comparison": 1.00,
    "best_of": 0.90,
    "transactional": 0.85,
    "informational": 0.50,
}

WEIGHT_VOLUME = 0.35
WEIGHT_EASE = 0.20
WEIGHT_GAP = 0.30
WEIGHT_INTENT = 0.15

VISIBLE_RESIDUAL_GAP = 0.15  # small non-zero value even when already visible


def compute_opportunity_score(
    search_volume: int,
    competitive_difficulty: float,
    domain_visible: bool,
    intent: str,
) -> float:
    volume = max(0, search_volume)
    volume_factor = math.log1p(volume) / math.log1p(VOLUME_CAP)
    volume_factor = min(1.0, volume_factor)

    difficulty = min(100.0, max(0.0, competitive_difficulty))
    ease_factor = (100.0 - difficulty) / 100.0

    gap_factor = VISIBLE_RESIDUAL_GAP if domain_visible else 1.0

    intent_factor = INTENT_WEIGHTS.get(intent, INTENT_WEIGHTS["informational"])

    score = (
        WEIGHT_VOLUME * volume_factor
        + WEIGHT_EASE * ease_factor
        + WEIGHT_GAP * gap_factor
        + WEIGHT_INTENT * intent_factor
    )
    return round(min(1.0, max(0.0, score)), 4)
