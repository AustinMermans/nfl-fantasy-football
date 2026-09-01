from nfl_fantasy_football.espn import fetch_espn_market, parse_espn_market


def test_parse_espn_market_separates_adp_and_projection() -> None:
    payload = {
        "players": [
            {
                "player": {
                    "id": 7,
                    "fullName": "Example Runner",
                    "defaultPositionId": 2,
                    "injuryStatus": "ACTIVE",
                    "ownership": {"averageDraftPosition": 17.0},
                    "draftRanksByRankType": {
                        "STANDARD": {"rank": 15},
                        "PPR": {"rank": 19},
                    },
                    "stats": [
                        {
                            "seasonId": 2026,
                            "scoringPeriodId": 0,
                            "statSourceId": 1,
                            "statSplitTypeId": 0,
                            "appliedTotal": 250.0,
                            "stats": {"53": 60.0},
                        }
                    ],
                }
            }
        ]
    }

    row = parse_espn_market(payload, season=2026)[0]

    assert row["adp"] == 17.0
    assert row["halfPprRank"] == 17.0
    assert row["marketCenter"] == 17.0
    assert row["espnHalfPprPoints"] == 280.0


def test_fetch_espn_market_declares_applied_total_basis(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr("nfl_fantasy_football.espn.urlopen", lambda *args, **kwargs: Response())
    monkeypatch.setattr("nfl_fantasy_football.espn.json.load", lambda response: {"players": []})

    result = fetch_espn_market(2026)

    assert "standard scoring" in result["projectionScoringBasis"]
