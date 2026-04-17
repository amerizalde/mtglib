from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .generator import DeckGenerator
from .indexer import COLOR_ORDER, CardIndex
from .models import (
    CardDetailResponse,
    CardListResponse,
    DeckCardInput,
    DeckDraftInput,
    DeckSaveRequest,
    DeckScoreRequest,
    GeneratedDeck,
    GenerationCandidate,
    GenerationRequest,
    GenerationResponse,
    HealthResponse,
    MetaResponse,
    SavedDeckListResponse,
    SwapCandidate,
    SwapRequest,
    SwapResponse,
)
from .scorer import DeckScorer
from .storage import DeckStore


ROOT_DIR = Path(__file__).resolve().parents[1]
CARDS_DIR = ROOT_DIR / "cards"
DATA_DIR = ROOT_DIR / "data"
SAVED_DECKS_PATH = DATA_DIR / "saved-decks.json"
FRONTEND_DIST_DIR = ROOT_DIR / "frontend" / "dist"


@lru_cache
def get_card_index() -> CardIndex:
    return CardIndex.from_cards_directory(CARDS_DIR)


@lru_cache
def get_deck_generator() -> DeckGenerator:
    return DeckGenerator(get_card_index())


@lru_cache
def get_deck_scorer() -> DeckScorer:
    return DeckScorer(get_card_index())


@lru_cache
def get_deck_store() -> DeckStore:
    return DeckStore(SAVED_DECKS_PATH)


app = FastAPI(title="MTGLib MVP", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    index = get_card_index()
    return HealthResponse(status="ok", index_version=index.version, card_count=len(index.cards))


@app.get("/api/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    return get_card_index().meta()


@app.get("/api/cards", response_model=CardListResponse)
def list_cards(
    q: str = "",
    colors: str = "",
    types: str = "",
    roles: str = "",
    tags: str = "",
    manaValueMin: int | None = Query(default=None, ge=0),
    manaValueMax: int | None = Query(default=None, ge=0),
    isLand: bool | None = None,
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=24, ge=1, le=100),
) -> CardListResponse:
    index = get_card_index()
    items = index.query(
        q=q,
        colors=_parse_colors(colors),
        types=_parse_csv(types),
        roles=_parse_csv(roles),
        tags=_parse_csv(tags),
        mana_value_min=manaValueMin,
        mana_value_max=manaValueMax,
        is_land=isLand,
    )
    total = len(items)
    start = (page - 1) * pageSize
    end = start + pageSize
    return CardListResponse(items=items[start:end], page=page, page_size=pageSize, total=total)


@app.get("/api/cards/{slug}", response_model=CardDetailResponse)
def get_card(slug: str) -> CardDetailResponse:
    index = get_card_index()
    card = index.get(slug)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Unknown card slug: {slug}")
    return CardDetailResponse(card=card, related_cards=index.related_cards(slug))


@app.post("/api/generate", response_model=GenerationResponse)
def generate(request: GenerationRequest) -> GenerationResponse:
    try:
        scorer = get_deck_scorer()
        raw_candidates = get_deck_generator().generate_candidates(request)
        finalized_candidates = [
            GenerationCandidate(
                rank=0,
                label=label,
                focus_tags=focus_tags,
                focus_roles=focus_roles,
                deck=scorer.finalize_generated_deck(deck, request),
            )
            for label, focus_tags, focus_roles, deck in raw_candidates
        ]
        ranked_candidates = _rank_generation_candidates(finalized_candidates, request)
        return GenerationResponse(
            request=request,
            candidate_count=len(ranked_candidates),
            primary_candidate_id=ranked_candidates[0].deck.id if ranked_candidates else None,
            candidates=ranked_candidates,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/decks/score", response_model=GeneratedDeck)
def score_deck(request: DeckScoreRequest) -> GeneratedDeck:
    return get_deck_scorer().score_draft(request.deck)


@app.post("/api/decks/save", response_model=GeneratedDeck)
def save_deck(request: DeckSaveRequest) -> GeneratedDeck:
    timestamp = datetime.now(UTC).isoformat()
    deck = request.deck.model_copy(
        update={
            "created_at": request.deck.created_at or timestamp,
            "updated_at": timestamp,
        }
    )
    return get_deck_store().save_deck(deck)


@app.get("/api/decks/{deck_id}", response_model=GeneratedDeck)
def get_saved_deck(deck_id: str) -> GeneratedDeck:
    deck = get_deck_store().get_deck(deck_id)
    if deck is None:
        raise HTTPException(status_code=404, detail=f"Unknown deck id: {deck_id}")
    return deck


@app.get("/api/decks", response_model=SavedDeckListResponse)
def list_saved_decks() -> SavedDeckListResponse:
    scorer = get_deck_scorer()
    decks = get_deck_store().list_decks()
    return SavedDeckListResponse(items=[scorer.summarize(deck) for deck in decks])


@app.post("/api/decks/swap", response_model=SwapResponse)
def swap_deck_slot(request: SwapRequest) -> SwapResponse:
    scorer = get_deck_scorer()
    source_deck = _resolve_source_deck(request)
    source_card = next((card for card in source_deck.cards if card.slug == request.replace_slug), None)
    if source_card is None:
        raise HTTPException(status_code=400, detail=f"Deck does not contain {request.replace_slug}.")
    if source_card.locked or request.replace_slug in request.locked_slugs:
        raise HTTPException(status_code=400, detail=f"{request.replace_slug} is locked and cannot be replaced.")

    index = get_card_index()
    source_record = index.get_record(request.replace_slug)
    if source_record is None:
        raise HTTPException(status_code=400, detail=f"Unknown card slug: {request.replace_slug}")

    target_colors = set(source_deck.seed_request.colors or source_deck.colors)
    existing_slugs = {card.slug for card in source_deck.cards if card.slug != request.replace_slug}
    variants: list[SwapCandidate] = []
    for record in index._records:
        entity = record.entity
        if entity.slug in existing_slugs or entity.slug == request.replace_slug:
            continue
        if entity.is_land != source_record.entity.is_land:
            continue
        if target_colors and entity.color_identity and not set(entity.color_identity).issubset(target_colors):
            continue
        if not source_record.entity.is_land and abs(entity.mana_value - source_record.entity.mana_value) > 1:
            continue
        shared_tags = sorted(set(entity.synergy_tags) & set(source_record.entity.synergy_tags))
        shared_roles = sorted(set(entity.role_tags) & set(source_record.entity.role_tags))
        if not source_record.entity.is_land and not shared_tags and not shared_roles and entity.mana_value != source_record.entity.mana_value:
            continue

        replacement_cards = [
            DeckCardInput(slug=card.slug, quantity=card.quantity, locked=card.locked)
            for card in source_deck.cards
            if card.slug != request.replace_slug
        ]
        replacement_cards.append(
            DeckCardInput(slug=entity.slug, quantity=source_card.quantity, locked=False)
        )
        variant = scorer.score_draft(
            DeckDraftInput(
                id=source_deck.id,
                name=source_deck.name,
                cards=replacement_cards,
                seed_request=source_deck.seed_request,
            )
        )
        reasons = []
        if shared_tags:
            reasons.extend(f"shared_tag:{tag}" for tag in shared_tags)
        if shared_roles:
            reasons.extend(f"shared_role:{role}" for role in shared_roles)
        if entity.mana_value == source_record.entity.mana_value:
            reasons.append("same_mana_value")
        if target_colors and set(entity.color_identity or entity.colors).issubset(target_colors):
            reasons.append("on_color")
        variants.append(
            SwapCandidate(
                replacement_slug=entity.slug,
                replacement_name=entity.display_name,
                reasons=reasons or ["curve_fit"],
                delta_overall=round(variant.score.overall - source_deck.score.overall, 2),
                deck=variant,
            )
        )

    variants.sort(key=lambda candidate: (-candidate.deck.score.overall, -candidate.delta_overall, candidate.replacement_name.casefold()))
    return SwapResponse(replaced_slug=request.replace_slug, candidates=variants[: request.candidate_limit])


def _parse_csv(raw_value: str) -> list[str]:
    return [value.strip() for value in raw_value.split(",") if value.strip()]


def _parse_colors(raw_value: str) -> list[str]:
    selected = [value.strip().upper() for value in raw_value.split(",") if value.strip()]
    return [color for color in COLOR_ORDER if color in selected]


def _resolve_source_deck(request: SwapRequest) -> GeneratedDeck:
    if request.deck_id:
        deck = get_deck_store().get_deck(request.deck_id)
        if deck is None:
            raise HTTPException(status_code=404, detail=f"Unknown deck id: {request.deck_id}")
        return deck
    if request.deck is not None:
        return get_deck_scorer().score_draft(request.deck)
    raise HTTPException(status_code=400, detail="Provide either deck_id or deck for swap analysis.")


def _rank_generation_candidates(
    candidates: list[GenerationCandidate], request: GenerationRequest
) -> list[GenerationCandidate]:
    novelty_target = request.target_novelty * 100

    def sort_key(candidate: GenerationCandidate) -> tuple[float, float, str]:
        novelty_distance = abs(candidate.deck.score.novelty - novelty_target)
        return (-candidate.deck.score.overall, novelty_distance, candidate.deck.name.casefold())

    ranked = sorted(candidates, key=sort_key)
    return [candidate.model_copy(update={"rank": index}) for index, candidate in enumerate(ranked, start=1)]


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str) -> FileResponse:
    if not FRONTEND_DIST_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found.")

    requested_path = FRONTEND_DIST_DIR / full_path
    index_path = FRONTEND_DIST_DIR / "index.html"
    if full_path and requested_path.is_file():
        return FileResponse(requested_path)
    return FileResponse(index_path)
