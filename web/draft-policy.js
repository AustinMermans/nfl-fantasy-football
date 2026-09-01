window.NFL_DRAFT_POLICY_AUDIT = {
  "generatedAt": "2026-09-01",
  "developmentSeasons": [2019, 2020, 2021, 2022, 2023, 2024],
  "holdoutSeason": 2025,
  "marketSource": "MyFantasyLeague AUG15 half-PPR ADP",
  "opponents": "noisy legal roster-aware ADP with common room draws",
  "lineupEvaluation": "weekly starters selected from preseason information, then scored on realized outcomes",
  "defaultPolicy": "capped_adp",
  "reason": "Exact market order with QB 2, TE 2, and K 1 caps was the only tested intervention with a positive multi-year managed-lineup result; unconstrained utility and probability lookahead remain unvalidated.",
  "policy": {
    "ordering": "selected live room ADP",
    "caps": {"QB": 2, "TE": 2, "K": 1},
    "otherLimits": "league roster maximums",
    "legalFinish": true
  },
  "holdoutResults": [
    {"teams": 8, "rooms": 160, "adpWinRate": 0.5389, "candidateWinRate": 0.5396, "winRateDelta": 0.0007, "pointDelta": -4.90},
    {"teams": 10, "rooms": 200, "adpWinRate": 0.5315, "candidateWinRate": 0.5323, "winRateDelta": 0.0008, "pointDelta": 2.21},
    {"teams": 12, "rooms": 240, "adpWinRate": 0.5004, "candidateWinRate": 0.5081, "winRateDelta": 0.0077, "pointDelta": 12.28},
    {"teams": 14, "rooms": 280, "adpWinRate": 0.5249, "candidateWinRate": 0.5301, "winRateDelta": 0.0052, "pointDelta": 7.05}
  ],
  "tenTeamYearResults": [
    {"season": 2020, "winRateDelta": 0.0040, "pointDelta": 7.06},
    {"season": 2021, "winRateDelta": -0.0014, "pointDelta": 2.74},
    {"season": 2022, "winRateDelta": 0.0087, "pointDelta": 10.75},
    {"season": 2023, "winRateDelta": 0.0153, "pointDelta": 20.85},
    {"season": 2024, "winRateDelta": 0.0075, "pointDelta": 16.28},
    {"season": 2025, "winRateDelta": 0.0020, "pointDelta": 6.28}
  ],
  "supersededFinding": "The earlier best-lineup-after-results evaluator leaked outcome information and is not used for the deployed conclusion."
};
