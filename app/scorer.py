from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from hashlib import sha1
import json
from math import log
from statistics import mean

from .indexer import COLOR_ORDER, CardIndex, IndexedCardRecord
from .models import (
    CardFeatureVector,
    Color,
    DeckCard,
    DeckCardInput,
    DeckDraftInput,
    DeckExplanation,
    DeckScore,
    DeckValidation,
    GeneratedDeck,
    GenerationRequest,
    SavedDeckSummary,
)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


class DeckScorer:
    def __init__(self, index: CardIndex) -> None:
        self._index = index

    def finalize_generated_deck(self, deck: GeneratedDeck, seed_request: GenerationRequest) -> GeneratedDeck:
        validation = self._validate_cards(deck.cards, seed_request)
        score = self._score_cards(deck.cards, seed_request, validation)
        finalized_at = datetime.now(UTC).isoformat()
        return deck.model_copy(
            update={
                "updated_at": finalized_at,
                "created_at": deck.created_at or finalized_at,
                "format": "local-corpus",
                "primary_plan_tags": self._primary_plan_tags(deck.cards),
                "color_profile": self._color_profile(deck.cards),
                "mana_curve": self._mana_curve(deck.cards),
                "score": score,
                "validation": validation,
                "explanations": self._build_explanation(deck.cards, seed_request, validation, score),
                "seed_request": seed_request,
            }
        )

    def score_draft(self, draft: DeckDraftInput) -> GeneratedDeck:
        cards = self._normalize_draft_cards(draft.cards)
        deck_id = self._deck_id(cards, draft.seed_request)
        land_count = sum(card.quantity for card in cards if card.is_land)
        nonland_count = sum(card.quantity for card in cards if not card.is_land)
        generated = GeneratedDeck(
            id=deck_id,
            name=draft.name,
            colors=self._infer_deck_colors(cards),
            preferred_tags=list(dict.fromkeys(draft.seed_request.preferred_tags)),
            summary="Scored deck draft.",
            explanation_lines=[],
            cards=cards,
            card_count=sum(card.quantity for card in cards),
            land_count=land_count,
            nonland_count=nonland_count,
            seed_request=draft.seed_request,
        )
        return self.finalize_generated_deck(generated, draft.seed_request)

    def summarize(self, deck: GeneratedDeck) -> SavedDeckSummary:
        return SavedDeckSummary(
            id=deck.id,
            name=deck.name,
            updated_at=deck.updated_at,
            colors=deck.colors,
            primary_plan_tags=deck.primary_plan_tags,
            overall_score=deck.score.overall,
            card_count=deck.card_count,
            land_count=deck.land_count,
            validation_ok=deck.validation.is_valid,
        )

    def _normalize_draft_cards(self, deck_cards: list[DeckCardInput]) -> list[DeckCard]:
        merged: dict[str, DeckCard] = {}
        for entry in deck_cards:
            record = self._index.get_record(entry.slug)
            if record is None:
                merged.setdefault(
                    entry.slug,
                    DeckCard(
                        slug=entry.slug,
                        display_name=entry.slug.replace("-", " ").title(),
                        quantity=0,
                        locked=entry.locked,
                        is_land=False,
                        mana_value=0,
                        type_line="Unknown",
                        reason_codes=["unknown_card"],
                    ),
                )
                merged[entry.slug].quantity += entry.quantity
                continue

            card = merged.get(entry.slug)
            if card is None:
                card = DeckCard(
                    slug=entry.slug,
                    display_name=record.entity.display_name,
                    quantity=0,
                    locked=entry.locked,
                    is_land=record.entity.is_land,
                    mana_value=record.entity.mana_value,
                    type_line=record.entity.type_line,
                    reason_codes=[],
                )
                merged[entry.slug] = card
            card.quantity += entry.quantity
            card.locked = card.locked or entry.locked
        return sorted(merged.values(), key=lambda card: (card.is_land, card.mana_value, card.display_name.casefold()))

    def _validate_cards(self, deck_cards: list[DeckCard], seed_request: GenerationRequest) -> DeckValidation:
        errors: list[str] = []
        warnings: list[str] = []
        total_cards = sum(card.quantity for card in deck_cards)
        land_count = sum(card.quantity for card in deck_cards if card.is_land)
        off_color_count = 0
        allowed_colors = set(seed_request.colors) if seed_request.colors else set(self._infer_deck_colors(deck_cards))

        if total_cards != seed_request.max_cards:
            errors.append(f"Deck must contain exactly {seed_request.max_cards} cards; found {total_cards}.")
        if land_count < seed_request.min_lands:
            errors.append(f"Deck must contain at least {seed_request.min_lands} lands; found {land_count}.")

        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is None:
                errors.append(f"Unknown card slug: {card.slug}")
                continue
            if card.quantity > 4 and not record.entity.is_basic_land:
                errors.append(f"{record.entity.display_name} exceeds the four-copy limit.")
            if allowed_colors:
                palette = set(record.entity.color_identity or record.entity.colors)
                if palette and not palette.issubset(allowed_colors):
                    off_color_count += card.quantity

        if off_color_count > 0 and not seed_request.allow_splash:
            errors.append(f"Deck contains {off_color_count} off-color cards for the inferred color profile.")

        if land_count < 23:
            warnings.append("Mana base is lean; slower hands may stumble.")
        if self._density(deck_cards, lambda record: self._feature(record).is_interaction) < 0.18:
            warnings.append("Interaction density is low for a best-of-one main deck.")
        if self._density(deck_cards, lambda record: self._feature(record).is_card_draw or self._feature(record).is_selection) < 0.1:
            warnings.append("Card flow is thin; recovery from topdeck mode may be weak.")

        return DeckValidation(
            is_valid=not errors,
            errors=errors,
            warnings=warnings,
            card_count=total_cards,
            land_count=land_count,
            off_color_count=off_color_count,
        )

    def _score_cards(
        self,
        deck_cards: list[DeckCard],
        seed_request: GenerationRequest,
        validation: DeckValidation,
    ) -> DeckScore:
        constraint = 100.0 if validation.is_valid else 0.0
        tempo = self._tempo_score(deck_cards, seed_request)
        synergy = self._synergy_score(deck_cards)
        interaction = self._interaction_score(deck_cards)
        resilience = self._resilience_score(deck_cards)
        mana = self._mana_score(deck_cards, validation)
        novelty = self._novelty_score(deck_cards, synergy)
        game_theory = self._game_theory_score(deck_cards, tempo, interaction, resilience)
        overall = self._overall_score(constraint, tempo, synergy, interaction, resilience, mana, novelty, game_theory)

        return DeckScore(
            overall=round(overall, 2),
            constraint=round(constraint, 2),
            tempo=round(tempo, 2),
            synergy=round(synergy, 2),
            interaction=round(interaction, 2),
            resilience=round(resilience, 2),
            mana=round(mana, 2),
            novelty=round(novelty, 2),
            game_theory=round(game_theory, 2),
        )

    # Tempo rewards early plays, cheap interaction, and a curve that casts smoothly.
    def _tempo_score(self, deck_cards: list[DeckCard], seed_request: GenerationRequest) -> float:
        one_drop_pressure = _clamp(self._count_role(deck_cards, "one_drop_pressure") / 8)
        two_drop_pressure = _clamp(self._count_role(deck_cards, "two_drop_pressure") / 10)
        three_drop_pressure = _clamp(self._count_role(deck_cards, "three_drop_pressure") / 8)
        early_pressure = 0.4 * one_drop_pressure + 0.35 * two_drop_pressure + 0.25 * three_drop_pressure
        cheap_interaction = self._density(deck_cards, lambda record: "cheap_interaction" in record.entity.role_tags)
        mana_smoothing = self._density(deck_cards, lambda record: self._feature(record).is_ramp or self._feature(record).is_fixing)
        board_immediacy_avg = self._weighted_average(deck_cards, lambda record: self._feature(record).board_immediacy)
        curve_penalty = self._curve_penalty(deck_cards, seed_request.target_tempo)
        tapland_penalty = self._tapland_penalty(deck_cards)
        return 100 * _clamp(
            0.35 * early_pressure
            + 0.25 * cheap_interaction
            + 0.2 * mana_smoothing
            + 0.2 * board_immediacy_avg
            - 0.15 * curve_penalty
            - 0.1 * tapland_penalty
        )

    # Synergy rewards balanced enablers and payoffs while penalizing dead themes.
    def _synergy_score(self, deck_cards: list[DeckCard]) -> float:
        pair_scores = self._pair_scores(deck_cards)
        cluster_cohesion = self._cluster_cohesion(deck_cards)
        dead_synergy_penalty = self._dead_synergy_penalty(deck_cards)
        return 100 * _clamp(0.55 * mean(pair_scores or [0.0]) + 0.3 * cluster_cohesion - 0.25 * dead_synergy_penalty)

    # Interaction estimates how effectively the deck can answer opposing threats on curve.
    def _interaction_score(self, deck_cards: list[DeckCard]) -> float:
        removal_density = self._density(deck_cards, lambda record: self._feature(record).is_removal)
        stack_interaction_density = self._density(deck_cards, lambda record: self._feature(record).is_counterspell)
        sweeper_coverage = _clamp(self._count_role(deck_cards, "sweeper") / 2)
        interaction_curve = self._interaction_curve(deck_cards)
        return 100 * _clamp(
            0.45 * removal_density
            + 0.2 * stack_interaction_density
            + 0.15 * sweeper_coverage
            + 0.2 * interaction_curve
        )

    # Resilience captures draw, recursion, sticky threats, and usable late-game mana sinks.
    def _resilience_score(self, deck_cards: list[DeckCard]) -> float:
        card_advantage_density = self._density(deck_cards, lambda record: self._feature(record).is_card_draw or self._feature(record).is_selection)
        recursion_density = self._density(deck_cards, lambda record: self._feature(record).is_recursion)
        sticky_threat_density = self._density(deck_cards, lambda record: self._feature(record).resilience >= 0.55)
        mana_sink_density = self._density(deck_cards, lambda record: "X" in record.entity.mana_cost.variable or "engine" in record.entity.role_tags)
        return 100 * _clamp(
            0.35 * card_advantage_density
            + 0.25 * recursion_density
            + 0.25 * sticky_threat_density
            + 0.15 * mana_sink_density
        )

    # Mana focuses on land count, color access, and castability rather than raw land totals alone.
    def _mana_score(self, deck_cards: list[DeckCard], validation: DeckValidation) -> float:
        recommended_land_count = self._recommended_land_count(deck_cards)
        land_floor = _clamp(validation.land_count / max(1, recommended_land_count))
        color_match = self._color_match(deck_cards)
        curve_support = self._curve_support(deck_cards)
        flood_penalty = max(0.0, validation.land_count - recommended_land_count - 2) / 10
        return 100 * _clamp(0.3 * land_floor + 0.35 * color_match + 0.35 * curve_support - 0.1 * flood_penalty)

    # Novelty is coherence-gated so oddball piles do not outscore functional shells.
    def _novelty_score(self, deck_cards: list[DeckCard], synergy: float) -> float:
        tag_rarity = self._tag_rarity(deck_cards)
        pair_uniqueness = self._pair_uniqueness(deck_cards)
        shell_distance = self._shell_distance(deck_cards)
        coherence_guard = synergy / 100
        return 100 * _clamp((0.35 * tag_rarity + 0.35 * pair_uniqueness + 0.3 * shell_distance) * coherence_guard)

    # Game-theory is a lightweight proxy for initiative, flexibility, and threat diversity.
    def _game_theory_score(self, deck_cards: list[DeckCard], tempo: float, interaction: float, resilience: float) -> float:
        card_advantage_density = self._density(deck_cards, lambda record: self._feature(record).is_card_draw or self._feature(record).is_selection)
        initiative = tempo / 100
        answer_flexibility = interaction / 100
        pivot_capacity = ((resilience / 100) + card_advantage_density) / 2
        threat_diversity = self._threat_diversity(deck_cards)
        return 100 * _clamp(
            0.3 * initiative + 0.25 * answer_flexibility + 0.25 * pivot_capacity + 0.2 * threat_diversity
        )

    def _overall_score(
        self,
        constraint: float,
        tempo: float,
        synergy: float,
        interaction: float,
        resilience: float,
        mana: float,
        novelty: float,
        game_theory: float,
    ) -> float:
        if constraint <= 0:
            return 0.0
        return (
            0.18 * tempo
            + 0.18 * synergy
            + 0.14 * interaction
            + 0.12 * resilience
            + 0.16 * mana
            + 0.12 * novelty
            + 0.1 * game_theory
        )

    def _build_explanation(
        self,
        deck_cards: list[DeckCard],
        seed_request: GenerationRequest,
        validation: DeckValidation,
        score: DeckScore,
    ) -> DeckExplanation:
        primary_tags = self._primary_plan_tags(deck_cards)
        colors = self._infer_deck_colors(deck_cards)
        summary = (
            f"{'/'.join(colors) if colors else 'Color-flexible'} shell centered on "
            f"{', '.join(primary_tags[:2]) if primary_tags else 'curve pressure'}, scoring {score.overall:.1f} overall."
        )
        core_plan = (
            f"The deck leans on {', '.join(primary_tags[:3]) if primary_tags else 'a balanced curve'} "
            f"with {validation.land_count} lands and {validation.card_count - validation.land_count} nonlands."
        )
        novel_angle = (
            f"Novelty score {score.novelty:.1f} reflects rarer tag combinations that still maintain internal coherence."
        )
        tempo_story = (
            f"Tempo score {score.tempo:.1f} reflects the current one- to three-mana curve, low-cost interaction, and mana smoothing."
        )
        card_reasons = {
            card.slug: card.reason_codes
            for card in deck_cards
            if card.reason_codes
        }
        replacement_notes = list(validation.warnings)
        if not validation.is_valid:
            replacement_notes.extend(validation.errors)
        return DeckExplanation(
            summary=summary,
            core_plan=core_plan,
            novel_angle=novel_angle,
            tempo_story=tempo_story,
            key_synergies=primary_tags,
            card_reasons=card_reasons,
            replacement_notes=replacement_notes,
        )

    def _deck_id(self, cards: list[DeckCard], seed_request: GenerationRequest) -> str:
        payload = {
            "cards": [{"slug": card.slug, "quantity": card.quantity, "locked": card.locked} for card in cards],
            "seed_request": seed_request.model_dump(mode="json"),
        }
        digest = sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return digest[:12]

    def _primary_plan_tags(self, deck_cards: list[DeckCard]) -> list[str]:
        counts = Counter[str]()
        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is None or record.entity.is_land:
                continue
            for tag in record.entity.synergy_tags:
                counts[tag] += card.quantity
        return [tag for tag, _ in counts.most_common(4) if not tag.startswith("tribal:")]

    def _color_profile(self, deck_cards: list[DeckCard]) -> dict[str, int]:
        counts = Counter[str]()
        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is None:
                continue
            for color in record.entity.color_identity or record.entity.colors:
                counts[color] += card.quantity
        return {color: counts.get(color, 0) for color in COLOR_ORDER if counts.get(color, 0)}

    def _mana_curve(self, deck_cards: list[DeckCard]) -> dict[str, int]:
        counts = Counter[str]()
        for card in deck_cards:
            if card.is_land:
                continue
            bucket = str(min(card.mana_value, 6))
            counts[bucket] += card.quantity
        return {bucket: counts[bucket] for bucket in sorted(counts, key=int)}

    def _infer_deck_colors(self, deck_cards: list[DeckCard]) -> list[Color]:
        counts = Counter[Color]()
        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is None or record.entity.is_land:
                continue
            for color in record.entity.color_identity or record.entity.colors:
                counts[color] += card.quantity
        if not counts:
            return []
        return [color for color in COLOR_ORDER if counts[color] > 0]

    def _count_role(self, deck_cards: list[DeckCard], role: str) -> int:
        total = 0
        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is not None and role in record.entity.role_tags:
                total += card.quantity
        return total

    def _density(self, deck_cards: list[DeckCard], predicate) -> float:
        total = sum(card.quantity for card in deck_cards if not card.is_land)
        if total <= 0:
            return 0.0
        matched = 0
        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is None or record.entity.is_land:
                continue
            if predicate(record):
                matched += card.quantity
        return matched / total

    def _weighted_average(self, deck_cards: list[DeckCard], selector) -> float:
        values: list[float] = []
        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is None or record.entity.is_land:
                continue
            values.extend([selector(record)] * card.quantity)
        return mean(values) if values else 0.0

    def _curve_penalty(self, deck_cards: list[DeckCard], target_tempo: str) -> float:
        total = sum(card.quantity for card in deck_cards if not card.is_land)
        if total <= 0:
            return 1.0
        actual = sum(card.quantity for card in deck_cards if not card.is_land and card.mana_value <= 3) / total
        target = {"fast": 0.75, "medium": 0.6, "slow": 0.45}[target_tempo]
        return _clamp(abs(actual - target) / max(target, 0.01))

    def _tapland_penalty(self, deck_cards: list[DeckCard]) -> float:
        lands = [card for card in deck_cards if card.is_land]
        if not lands:
            return 0.0
        tapped = 0
        total = 0
        for card in lands:
            record = self._index.get_record(card.slug)
            if record is None:
                continue
            total += card.quantity
            if "enters tapped" in record.entity.rules_text.casefold():
                tapped += card.quantity
        return tapped / max(1, total)

    def _pair_scores(self, deck_cards: list[DeckCard]) -> list[float]:
        tag_enablers = Counter[str]()
        tag_payoffs = Counter[str]()
        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is None or record.entity.is_land:
                continue
            feature = self._feature(record)
            for tag in record.entity.synergy_tags:
                if feature.is_enabler or "engine" in record.entity.role_tags or feature.is_token_maker:
                    tag_enablers[tag] += card.quantity
                if feature.is_payoff or "payoff" in record.entity.role_tags or "top_end_finisher" in record.entity.role_tags:
                    tag_payoffs[tag] += card.quantity
        scores: list[float] = []
        for tag in sorted(set(tag_enablers) | set(tag_payoffs)):
            scores.append(min(tag_enablers[tag], tag_payoffs[tag]) / max(1, 2))
        return [_clamp(score) for score in scores]

    def _cluster_cohesion(self, deck_cards: list[DeckCard]) -> float:
        cards = self._top_synergy_cards(deck_cards, limit=12)
        if len(cards) < 2:
            return 0.0
        comparisons: list[float] = []
        for index, left in enumerate(cards[:-1]):
            left_tags = set(left.entity.synergy_tags)
            if not left_tags:
                continue
            for right in cards[index + 1 :]:
                right_tags = set(right.entity.synergy_tags)
                union = left_tags | right_tags
                if not union:
                    continue
                comparisons.append(len(left_tags & right_tags) / len(union))
        return mean(comparisons) if comparisons else 0.0

    def _dead_synergy_penalty(self, deck_cards: list[DeckCard]) -> float:
        nonland_total = sum(card.quantity for card in deck_cards if not card.is_land)
        if nonland_total <= 0:
            return 0.0
        pair_scores = self._pair_scores(deck_cards)
        unsupported = sum(1 for score in pair_scores if score == 0)
        return unsupported / max(1, len(pair_scores))

    def _interaction_curve(self, deck_cards: list[DeckCard]) -> float:
        interaction_cards = 0
        cheap_interaction_cards = 0
        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is None or record.entity.is_land:
                continue
            feature = self._feature(record)
            if feature.is_interaction:
                interaction_cards += card.quantity
                if card.mana_value <= 3:
                    cheap_interaction_cards += card.quantity
        if interaction_cards <= 0:
            return 0.0
        return cheap_interaction_cards / interaction_cards

    def _recommended_land_count(self, deck_cards: list[DeckCard]) -> int:
        mana_values = [card.mana_value for card in deck_cards if not card.is_land for _ in range(card.quantity)]
        average_value = mean(mana_values) if mana_values else 2.7
        recommendation = 21 + max(0, int((average_value - 2.7) * 6))
        if len(self._infer_deck_colors(deck_cards)) >= 3:
            recommendation += 1
        return recommendation

    def _color_match(self, deck_cards: list[DeckCard]) -> float:
        demand = Counter[Color]()
        sources = Counter[Color]()
        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is None:
                continue
            entity = record.entity
            if entity.is_land:
                colors = entity.produces_mana or entity.color_identity or entity.colors
                for color in colors:
                    sources[color] += card.quantity
                continue
            for color in entity.color_identity or entity.colors:
                demand[color] += card.quantity
        total_demand = sum(demand.values())
        if total_demand <= 0:
            return 1.0
        shortfall = 0
        for color, count in demand.items():
            shortfall += max(0, count - sources[color])
        return _clamp(1 - (shortfall / total_demand))

    def _curve_support(self, deck_cards: list[DeckCard]) -> float:
        land_count = sum(card.quantity for card in deck_cards if card.is_land)
        nonland_total = sum(card.quantity for card in deck_cards if not card.is_land)
        if nonland_total <= 0:
            return 1.0
        castable = sum(card.quantity for card in deck_cards if not card.is_land and card.mana_value <= land_count // 2 + 3)
        return castable / nonland_total

    def _tag_rarity(self, deck_cards: list[DeckCard]) -> float:
        primary_tags = self._primary_plan_tags(deck_cards)
        if not primary_tags:
            return 0.0
        total_cards = max(1, len(self._index.cards))
        values: list[float] = []
        for tag in primary_tags:
            df = sum(1 for card in self._index.cards if tag in card.synergy_tags)
            values.append(log((total_cards + 1) / (df + 1)) / log(total_cards + 1))
        return mean(values)

    def _pair_uniqueness(self, deck_cards: list[DeckCard]) -> float:
        tags = self._primary_plan_tags(deck_cards)
        if len(tags) < 2:
            return 0.0
        total_cards = max(1, len(self._index.cards))
        values: list[float] = []
        for index, left in enumerate(tags[:-1]):
            for right in tags[index + 1 :]:
                df = sum(1 for card in self._index.cards if left in card.synergy_tags and right in card.synergy_tags)
                values.append(log((total_cards + 1) / (df + 1)) / log(total_cards + 1))
        return mean(values) if values else 0.0

    def _shell_distance(self, deck_cards: list[DeckCard]) -> float:
        deck_tags = set(self._primary_plan_tags(deck_cards))
        if not deck_tags:
            return 0.0
        global_tags = Counter[str]()
        for card in self._index.cards:
            global_tags.update(tag for tag in card.synergy_tags if not tag.startswith("tribal:"))
        common_tags = {tag for tag, _ in global_tags.most_common(6)}
        union = deck_tags | common_tags
        if not union:
            return 0.0
        return 1 - (len(deck_tags & common_tags) / len(union))

    def _threat_diversity(self, deck_cards: list[DeckCard]) -> float:
        threat_classes: set[str] = set()
        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is None or record.entity.is_land:
                continue
            feature = self._feature(record)
            if feature.is_payoff:
                threat_classes.add("payoff")
            if feature.is_token_maker:
                threat_classes.add("tokens")
            if record.entity.mana_value <= 2 and feature.is_creature:
                threat_classes.add("pressure")
            if "counterspell" in record.entity.role_tags or feature.is_counterspell:
                threat_classes.add("stack")
            if feature.is_card_draw:
                threat_classes.add("velocity")
        return _clamp(len(threat_classes) / 5)

    def _top_synergy_cards(self, deck_cards: list[DeckCard], limit: int) -> list[IndexedCardRecord]:
        weighted: list[tuple[float, IndexedCardRecord]] = []
        for card in deck_cards:
            record = self._index.get_record(card.slug)
            if record is None or record.entity.is_land:
                continue
            weighted.append((self._feature(record).synergy_density, record))
        weighted.sort(key=lambda item: (-item[0], item[1].entity.display_name.casefold()))
        return [record for _, record in weighted[:limit]]

    def _feature(self, record: IndexedCardRecord) -> CardFeatureVector:
        return record.entity.feature_vector
