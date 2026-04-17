from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Color = Literal["W", "U", "B", "R", "G"]


class ManaCost(BaseModel):
    model_config = ConfigDict(frozen=True)

    printed: str = "none"
    generic: int = 0
    white: int = 0
    blue: int = 0
    black: int = 0
    red: int = 0
    green: int = 0
    colorless: int = 0
    hybrid: dict[str, int] = Field(default_factory=dict)
    phyrexian: dict[str, int] = Field(default_factory=dict)
    variable: dict[str, int] = Field(default_factory=dict)
    snow: int = 0


class CardStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    power: str
    toughness: str


class CardFeatureVector(BaseModel):
    model_config = ConfigDict(frozen=True)

    mana_value_bucket: int
    is_creature: bool = False
    is_interaction: bool = False
    is_removal: bool = False
    is_card_draw: bool = False
    is_selection: bool = False
    is_ramp: bool = False
    is_fixing: bool = False
    is_token_maker: bool = False
    is_recursion: bool = False
    is_sweeper: bool = False
    is_counterspell: bool = False
    is_combat_trick: bool = False
    is_engine_piece: bool = False
    is_payoff: bool = False
    is_enabler: bool = False
    board_immediacy: float = 0.0
    resource_velocity: float = 0.0
    resilience: float = 0.0
    synergy_density: float = 0.0


class CardFaceEntity(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    mana_cost: ManaCost
    mana_value: int
    type_line: str
    types: list[str] = Field(default_factory=list)
    subtypes: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    rules_text: str
    colors: list[Color] = Field(default_factory=list)
    stats: CardStats | None = None
    loyalty: str | None = None


class CardEntity(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    display_name: str
    canonical_name: str
    layout: str
    sets: list[str] = Field(default_factory=list)
    faces: list[CardFaceEntity] = Field(default_factory=list)
    type_line: str
    supertypes: list[str] = Field(default_factory=list)
    types: list[str] = Field(default_factory=list)
    subtypes: list[str] = Field(default_factory=list)
    mana_cost: ManaCost = Field(default_factory=ManaCost)
    mana_value: int
    colors: list[Color] = Field(default_factory=list)
    color_identity: list[Color] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    rules_text: str
    stats: CardStats | None = None
    loyalty: str | None = None
    is_land: bool
    is_basic_land: bool
    produces_mana: list[Color] = Field(default_factory=list)
    feature_vector: CardFeatureVector = Field(default_factory=lambda: CardFeatureVector(mana_value_bucket=0))
    role_tags: list[str] = Field(default_factory=list)
    synergy_tags: list[str] = Field(default_factory=list)
    novelty_baseline_score: float = 0.0


class CardRelatedSummary(BaseModel):
    slug: str
    display_name: str
    type_line: str
    colors: list[Color] = Field(default_factory=list)
    shared_tags: list[str] = Field(default_factory=list)
    shared_roles: list[str] = Field(default_factory=list)
    overlap_score: float


class CardDetailResponse(BaseModel):
    card: CardEntity
    related_cards: list[CardRelatedSummary] = Field(default_factory=list)


class CardListResponse(BaseModel):
    items: list[CardEntity]
    page: int
    page_size: int
    total: int


class HealthResponse(BaseModel):
    status: str
    index_version: str
    card_count: int


class MetaResponse(BaseModel):
    corpus_version: str
    card_count: int
    indexed_at: str
    supported_filters: dict[str, list[str]]
    tag_distributions: dict[str, dict[str, int]]


class GenerationRequest(BaseModel):
    colors: list[Color] = Field(default_factory=list)
    required_slugs: list[str] = Field(default_factory=list)
    excluded_slugs: list[str] = Field(default_factory=list)
    preferred_tags: list[str] = Field(default_factory=list)
    preferred_roles: list[str] = Field(default_factory=list)
    target_tempo: Literal["fast", "medium", "slow"] = "medium"
    target_novelty: float = Field(default=0.35, ge=0.0, le=1.0)
    min_lands: int = Field(default=21, ge=0)
    max_cards: int = Field(default=60, ge=1, le=100)
    allow_splash: bool = False
    candidate_count: int = Field(default=3, ge=1, le=8)


class DeckCard(BaseModel):
    slug: str
    display_name: str
    quantity: int
    zone: Literal["main"] = "main"
    locked: bool = False
    is_land: bool
    mana_value: int
    type_line: str
    reason_codes: list[str] = Field(default_factory=list)


class DeckCardInput(BaseModel):
    slug: str
    quantity: int = Field(default=1, ge=1)
    locked: bool = False


class DeckValidation(BaseModel):
    is_valid: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    card_count: int = 0
    land_count: int = 0
    off_color_count: int = 0


class DeckScore(BaseModel):
    overall: float = 0.0
    constraint: float = 0.0
    tempo: float = 0.0
    synergy: float = 0.0
    interaction: float = 0.0
    resilience: float = 0.0
    mana: float = 0.0
    novelty: float = 0.0
    game_theory: float = 0.0


class DeckExplanation(BaseModel):
    summary: str = ""
    core_plan: str = ""
    novel_angle: str = ""
    tempo_story: str = ""
    key_synergies: list[str] = Field(default_factory=list)
    card_reasons: dict[str, list[str]] = Field(default_factory=dict)
    replacement_notes: list[str] = Field(default_factory=list)


class GeneratedDeck(BaseModel):
    id: str
    name: str
    format: Literal["local-corpus"] = "local-corpus"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    colors: list[Color] = Field(default_factory=list)
    preferred_tags: list[str] = Field(default_factory=list)
    primary_plan_tags: list[str] = Field(default_factory=list)
    summary: str
    explanation_lines: list[str] = Field(default_factory=list)
    cards: list[DeckCard]
    card_count: int
    land_count: int
    nonland_count: int
    color_profile: dict[str, int] = Field(default_factory=dict)
    mana_curve: dict[str, int] = Field(default_factory=dict)
    score: DeckScore = Field(default_factory=DeckScore)
    explanations: DeckExplanation = Field(default_factory=DeckExplanation)
    validation: DeckValidation = Field(default_factory=DeckValidation)
    seed_request: GenerationRequest = Field(default_factory=GenerationRequest)


class GenerationCandidate(BaseModel):
    rank: int
    label: str
    focus_tags: list[str] = Field(default_factory=list)
    focus_roles: list[str] = Field(default_factory=list)
    deck: GeneratedDeck


class GenerationResponse(BaseModel):
    request: GenerationRequest
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    candidate_count: int
    primary_candidate_id: str | None = None
    candidates: list[GenerationCandidate] = Field(default_factory=list)


class DeckDraftInput(BaseModel):
    id: str | None = None
    name: str = "Untitled Deck"
    cards: list[DeckCardInput] = Field(default_factory=list)
    seed_request: GenerationRequest = Field(default_factory=GenerationRequest)


class DeckScoreRequest(BaseModel):
    deck: DeckDraftInput


class DeckSaveRequest(BaseModel):
    deck: GeneratedDeck


class SavedDeckSummary(BaseModel):
    id: str
    name: str
    updated_at: str
    colors: list[Color] = Field(default_factory=list)
    primary_plan_tags: list[str] = Field(default_factory=list)
    overall_score: float = 0.0
    card_count: int = 0
    land_count: int = 0
    validation_ok: bool = False


class SavedDeckListResponse(BaseModel):
    items: list[SavedDeckSummary] = Field(default_factory=list)


class SwapRequest(BaseModel):
    replace_slug: str
    deck_id: str | None = None
    deck: DeckDraftInput | None = None
    locked_slugs: list[str] = Field(default_factory=list)
    candidate_limit: int = Field(default=5, ge=1, le=12)


class SwapCandidate(BaseModel):
    replacement_slug: str
    replacement_name: str
    reasons: list[str] = Field(default_factory=list)
    delta_overall: float = 0.0
    deck: GeneratedDeck


class SwapResponse(BaseModel):
    replaced_slug: str
    candidates: list[SwapCandidate] = Field(default_factory=list)
