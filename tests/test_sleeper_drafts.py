from io import BytesIO

import pandas as pd

import nfl_fantasy_football.sleeper_drafts as sleeper_drafts

from nfl_fantasy_football.sleeper_drafts import (
    collect_sleeper_draft_corpus,
    eligible_redraft_snake,
    normalize_sleeper_draft,
    SleeperAPIClient,
)


def _draft() -> dict[str, object]:
    return {
        "draft_id": "draft-1",
        "league_id": "league-1",
        "sport": "nfl",
        "type": "snake",
        "status": "complete",
        "season_type": "regular",
        "season": "2025",
        "start_time": 1_755_000_000_000,
        "settings": {
            "teams": 10,
            "rounds": 17,
            "slots_qb": 1,
            "slots_rb": 2,
            "slots_wr": 2,
            "slots_te": 1,
            "slots_flex": 2,
            "slots_k": 1,
            "slots_def": 0,
            "slots_bn": 8,
        },
        "metadata": {"scoring_type": "half_ppr", "name": "Redraft"},
    }


def test_sleeper_client_retries_transient_timeout(monkeypatch) -> None:
    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary")
        return BytesIO(b"{}")

    monkeypatch.setattr(sleeper_drafts, "urlopen", fake_urlopen)
    monkeypatch.setattr(sleeper_drafts.time, "sleep", lambda _: None)
    client = SleeperAPIClient(minimum_interval=0.0, maximum_attempts=2)

    assert client.get("state/nfl") == {}
    assert calls == 2


def test_eligible_redraft_snake_rejects_keeper_and_dynasty_shapes() -> None:
    draft = _draft()
    assert eligible_redraft_snake(draft, seasons={2025}, team_sizes={10})

    dynasty = {**draft, "metadata": {"name": "Home Dynasty"}}
    assert not eligible_redraft_snake(dynasty, seasons={2025}, team_sizes={10})
    assert not eligible_redraft_snake(draft, seasons={2024}, team_sizes={10})

    mock = {**draft, "league_id": None}
    assert not eligible_redraft_snake(mock, seasons={2025}, team_sizes={10})

    superflex = {**draft, "settings": {**draft["settings"], "slots_super_flex": 1}}
    assert not eligible_redraft_snake(superflex, seasons={2025}, team_sizes={10})

    two_qb = {**draft, "settings": {**draft["settings"], "slots_qb": 2}}
    assert not eligible_redraft_snake(two_qb, seasons={2025}, team_sizes={10})

    idp = {**draft, "settings": {**draft["settings"], "slots_idp_flex": 2}}
    assert not eligible_redraft_snake(idp, seasons={2025}, team_sizes={10})

    rookie_only = {**draft, "settings": {**draft["settings"], "player_type": 2}}
    assert not eligible_redraft_snake(rookie_only, seasons={2025}, team_sizes={10})

    labeled_dynasty = {
        **draft,
        "metadata": {"name": "Home League", "scoring_type": "dynasty_ppr"},
    }
    assert not eligible_redraft_snake(
        labeled_dynasty, seasons={2025}, team_sizes={10}
    )


def test_normalize_sleeper_draft_omits_user_identity_and_retains_defense_timing() -> None:
    picks = [
        {
            "player_id": "100",
            "picked_by": "private-user-id",
            "roster_id": "7",
            "round": 1,
            "draft_slot": 7,
            "pick_no": 4,
            "metadata": {
                "position": "RB",
                "team": "SEA",
                "first_name": "Test",
                "last_name": "Runner",
            },
            "is_keeper": None,
        },
        {
            "player_id": "DEN",
            "picked_by": "another-user",
            "roster_id": "3",
            "round": 1,
            "draft_slot": 3,
            "pick_no": 5,
            "metadata": {"position": "DEF", "team": "DEN"},
        },
    ]

    normalized = normalize_sleeper_draft(_draft(), picks)

    assert normalized["player_id"].tolist() == ["100", "DEN"]
    assert normalized["position"].tolist() == ["RB", "DEF"]
    assert "picked_by" not in normalized.columns
    assert "first_name" not in normalized.columns
    assert normalized.loc[0, "slots_flex"] == 2


def test_corpus_collector_writes_sanitized_content_addressed_snapshots(tmp_path) -> None:
    draft = _draft()
    draft["settings"]["rounds"] = 12
    picks = [
        {
            "player_id": str(index),
            "picked_by": f"private-user-{index % 10}",
            "roster_id": str(index % 10 + 1),
            "round": index // 10 + 1,
            "draft_slot": index % 10 + 1,
            "pick_no": index + 1,
            "metadata": {"position": ("QB", "RB", "WR", "TE", "K")[index % 5]},
        }
        for index in range(120)
    ]

    class FakeClient:
        def get(self, path: str):
            if path == "draft/draft-1":
                return draft
            if path == "draft/draft-1/picks":
                return picks
            raise AssertionError(path)

    destination = tmp_path / "picks.parquet"
    output, manifest = collect_sleeper_draft_corpus(
        seasons=[2025],
        draft_ids=["draft-1"],
        team_sizes=[10],
        destination=destination,
        raw_dir=tmp_path / "raw",
        client=FakeClient(),
    )

    assert output.exists()
    assert manifest.exists()
    assert len(list((tmp_path / "raw").glob("*.json"))) == 1
    combined_text = manifest.read_text() + next((tmp_path / "raw").glob("*.json")).read_text()
    assert "private-user" not in combined_text
    assert "draft-1" not in combined_text
    assert "league-1" not in combined_text
    assert len(pd.read_parquet(output)) == 120


def test_corpus_collector_can_discover_participant_drafts_without_saving_ids(
    tmp_path,
) -> None:
    seed = _draft()
    seed["draft_id"] = "seed"
    seed["draft_order"] = {"private-user": 1}
    related = _draft()
    related["draft_id"] = "related"
    related["start_time"] = seed["start_time"] + 1
    picks = [
        {
            "player_id": str(index),
            "picked_by": "private-user",
            "roster_id": str(index % 10 + 1),
            "round": index // 10 + 1,
            "draft_slot": index % 10 + 1,
            "pick_no": index + 1,
            "metadata": {"position": ("QB", "RB", "WR", "TE", "K")[index % 5]},
        }
        for index in range(170)
    ]

    class FakeClient:
        def get(self, path: str):
            payloads = {
                "draft/seed": seed,
                "user/private-user/drafts/nfl/2025": [related],
                "draft/seed/picks": picks,
                "draft/related/picks": picks,
            }
            return payloads[path]

    destination = tmp_path / "picks.parquet"
    output, manifest = collect_sleeper_draft_corpus(
        seasons=[2025],
        draft_ids=["seed"],
        team_sizes=[10],
        participant_crawl_depth=1,
        destination=destination,
        raw_dir=tmp_path / "raw",
        client=FakeClient(),
    )

    assert pd.read_parquet(output)["draft_id"].nunique() == 2
    assert "private-user" not in manifest.read_text()
