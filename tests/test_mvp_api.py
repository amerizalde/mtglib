from __future__ import annotations

import importlib

from fastapi.testclient import TestClient
import pytest

from mtglib.app.indexer import CardIndex
from mtglib.app.main import CARDS_DIR, app, get_card_index, get_deck_generator, get_deck_scorer, get_deck_store


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    storage_path = tmp_path / "saved-decks.json"
    monkeypatch.setattr("mtglib.app.main.SAVED_DECKS_PATH", storage_path)
    get_deck_store.cache_clear()
    get_deck_generator.cache_clear()
    get_deck_scorer.cache_clear()
    return TestClient(app)


def test_documented_package_import_path_loads_app() -> None:
    module = importlib.import_module("mtglib.app.main")
    assert module.app.title == "MTGLib MVP"


def test_index_normalizes_multiface_and_basic_land() -> None:
    index = get_card_index()

    aang = index.get("aang-at-the-crossroads-aang-destined-savior")
    assert aang is not None
    assert aang.layout == "transform"
    assert len(aang.faces) == 2
    assert aang.colors == ["W", "U", "G"]
    assert "legendary" in aang.synergy_tags
    assert aang.faces[0].mana_cost.printed == "2GWU"
    assert aang.feature_vector.is_creature is True

    forest = index.get("forest")
    assert forest is not None
    assert forest.is_land is True
    assert forest.is_basic_land is True
    assert forest.role_tags == ["basic_land", "fixing", "mana_base"]
    assert forest.produces_mana == ["G"]


def test_index_query_supports_filters() -> None:
    index = CardIndex.from_cards_directory(CARDS_DIR)
    results = index.query(q="llanowar", colors=["G"], roles=["mana_dork"])

    assert any(card.slug == "llanowar-elves" for card in results)


def test_api_endpoints_cover_browser_and_card_detail_flow(client: TestClient) -> None:
    health_response = client.get("/api/health")
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"

    cards_response = client.get("/api/cards", params={"q": "llanowar", "colors": "G", "pageSize": 5})
    assert cards_response.status_code == 200
    cards_payload = cards_response.json()
    assert cards_payload["total"] >= 1
    assert cards_payload["items"][0]["slug"] == "llanowar-elves"

    detail_response = client.get("/api/cards/llanowar-elves")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["card"]["display_name"] == "Llanowar Elves"
    assert detail_payload["card"]["feature_vector"]["is_creature"] is True
    assert detail_payload["related_cards"]


def test_generate_score_save_list_and_swap_flow(client: TestClient) -> None:
    generate_request = {
        "colors": ["G"],
        "required_slugs": ["llanowar-elves"],
        "excluded_slugs": ["swamp"],
        "preferred_tags": ["counters"],
        "preferred_roles": ["mana_dork"],
        "target_novelty": 0.55,
        "candidate_count": 3,
    }
    first_generate = client.post("/api/generate", json=generate_request)
    second_generate = client.post("/api/generate", json=generate_request)

    assert first_generate.status_code == 200
    assert second_generate.status_code == 200
    first_payload = first_generate.json()
    second_payload = second_generate.json()
    assert first_payload["primary_candidate_id"] == second_payload["primary_candidate_id"]
    assert first_payload["candidate_count"] == 3
    assert len(first_payload["candidates"]) == 3
    assert [candidate["deck"]["id"] for candidate in first_payload["candidates"]] == [
        candidate["deck"]["id"] for candidate in second_payload["candidates"]
    ]

    lead_candidate = first_payload["candidates"][0]
    lead_deck = lead_candidate["deck"]
    assert lead_candidate["rank"] == 1
    assert lead_deck["card_count"] == 60
    assert lead_deck["land_count"] >= 21
    assert lead_deck["validation"]["is_valid"] is True
    assert lead_deck["score"]["constraint"] == 100
    assert any(card["slug"] == "llanowar-elves" for card in lead_deck["cards"])

    score_request = {
        "deck": {
            "name": lead_deck["name"],
            "cards": [
                {"slug": card["slug"], "quantity": card["quantity"], "locked": card["locked"]}
                for card in lead_deck["cards"]
            ],
            "seed_request": generate_request,
        }
    }
    score_response = client.post("/api/decks/score", json=score_request)
    assert score_response.status_code == 200
    score_payload = score_response.json()
    assert score_payload["validation"]["is_valid"] is True
    assert score_payload["score"]["overall"] > 0

    save_response = client.post("/api/decks/save", json={"deck": score_payload})
    assert save_response.status_code == 200
    saved_payload = save_response.json()
    assert saved_payload["id"] == score_payload["id"]

    resave_response = client.post("/api/decks/save", json={"deck": saved_payload})
    assert resave_response.status_code == 200
    assert resave_response.json()["updated_at"] != saved_payload["updated_at"]

    list_response = client.get("/api/decks")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert any(item["id"] == saved_payload["id"] for item in list_payload["items"])

    get_response = client.get(f"/api/decks/{saved_payload['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == saved_payload["id"]

    swap_response = client.post(
        "/api/decks/swap",
        json={"deck_id": saved_payload["id"], "replace_slug": "llanowar-elves", "candidate_limit": 3},
    )
    assert swap_response.status_code == 200
    swap_payload = swap_response.json()
    assert swap_payload["replaced_slug"] == "llanowar-elves"
    assert swap_payload["candidates"]
    assert all(candidate["replacement_slug"] != "llanowar-elves" for candidate in swap_payload["candidates"])


def test_scoring_invalid_deck_returns_validation_failures(client: TestClient) -> None:
    response = client.post(
        "/api/decks/score",
        json={
            "deck": {
                "name": "Bad Deck",
                "cards": [{"slug": "llanowar-elves", "quantity": 1, "locked": False}],
                "seed_request": {"colors": ["G"]},
            }
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["validation"]["is_valid"] is False
    assert payload["score"]["constraint"] == 0
    assert any("exactly 60 cards" in error for error in payload["validation"]["errors"])


def test_generate_rejects_excluded_basic_when_mana_base_becomes_impossible(client: TestClient) -> None:
    response = client.post(
        "/api/generate",
        json={
            "colors": ["G"],
            "required_slugs": ["llanowar-elves"],
            "excluded_slugs": ["forest"],
        },
    )
    assert response.status_code == 400
    assert "mana base" in response.json()["detail"]
