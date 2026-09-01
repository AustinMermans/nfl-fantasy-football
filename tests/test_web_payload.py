import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _published_payload() -> dict:
    raw = (PROJECT_ROOT / "web" / "projections.js").read_text(encoding="utf-8").strip()
    prefix = "window.NFL_DRAFT_DATA = "
    assert raw.startswith(prefix)
    return json.loads(raw[len(prefix) :].removesuffix(";"))


def test_preseason_payload_preserves_unconditional_ros_contract() -> None:
    payload = _published_payload()

    assert payload["forecastType"] == "preseason"
    assert "raw game-model diagnostics" in payload["componentProjectionTreatment"]
    for player in payload["players"]:
        assert player["restOfSeasonExpectedPoints"] == player["projectedPoints"]
        assert player["availabilityAdjustmentApplied"] is False
        assert "baselineDuration" in player["injuryRisk"]
        assert "reportWeek" in player["injury"]
        assert player["projectionRange"]["decisionUse"] is False
        assert player["inseasonComponentWeight"] == 0.0
        assert player["projectionCenterSource"] in {
            "season ensemble",
            "current role-prior fallback",
            "rookie analog prior",
        }


def test_live_components_are_labeled_as_unreconciled_diagnostics() -> None:
    source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert "Raw game-model components" in source
    assert "unreconciled diagnostic" in source


def test_live_board_defaults_to_capped_market_and_supports_full_history_editing() -> None:
    source = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
    html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")

    assert 'defaultPolicy: "capped_adp"' in source
    assert 'value="capped_adp">Validated capped market ADP' in html
    assert 'value="adp">Market ADP control' in html
    assert "const validatedCaps = { QB: 2, TE: 2, K: 1 };" in source
    assert 'id="marketSourceSelect"' in html
    assert 'id="draftHistoryBody"' in html
    assert 'data-history-action="delete"' in source
    assert 'data-history-action="up"' in source


def test_published_sleeper_cross_check_contains_current_half_ppr_adp() -> None:
    raw = (PROJECT_ROOT / "web" / "sleeper.js").read_text(encoding="utf-8").strip()
    prefix = "window.NFL_SLEEPER_MARKET = "

    assert raw.startswith(prefix)
    payload = json.loads(raw[len(prefix) :].removesuffix(";"))
    assert payload["season"] == 2026
    assert payload["field"] == "adp_half_ppr"
    assert len(payload["players"]) >= 100
