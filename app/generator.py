from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha1
import json
from statistics import mean

from .indexer import COLOR_ORDER, CardIndex, IndexedCardRecord
from .models import Color, DeckCard, GeneratedDeck, GenerationRequest


BASIC_LAND_BY_COLOR: dict[Color, tuple[str, str]] = {
    "W": ("plains", "Plains"),
    "U": ("island", "Island"),
    "B": ("swamp", "Swamp"),
    "R": ("mountain", "Mountain"),
    "G": ("forest", "Forest"),
}

ROLE_WEIGHTS: dict[str, float] = {
    "mana_dork": 4.0,
    "cheap_removal": 4.5,
    "cheap_interaction": 4.5,
    "card_draw": 3.5,
    "engine": 3.5,
    "ramp": 3.5,
    "fixing": 3.0,
    "token_maker": 3.0,
    "one_drop_pressure": 4.0,
    "two_drop_pressure": 3.5,
    "three_drop_pressure": 2.5,
    "top_end_finisher": 3.0,
    "payoff": 3.0,
    "recursion": 2.5,
    "stabilizer": 2.0,
}


@dataclass(frozen=True, slots=True)
class CandidatePlan:
    label: str
    shell_tags: tuple[str, ...]
    focus_roles: tuple[str, ...]
    curve_focus: str
    novelty_bias: float
    land_target_shift: int = 0


class DeckGenerator:
    def __init__(self, index: CardIndex) -> None:
        self._index = index

    def generate_candidates(
        self, request: GenerationRequest
    ) -> list[tuple[str, list[str], list[str], GeneratedDeck]]:
        required_counts = Counter(request.required_slugs)
        excluded = set(request.excluded_slugs)
        if excluded & set(required_counts):
            raise ValueError("required_slugs and excluded_slugs cannot overlap")

        required_records = [self._require_record(slug) for slug in sorted(required_counts)]
        target_colors = self._determine_colors(request, required_records)
        base_shell_tags = self._determine_shell_tags(request, required_records, target_colors)
        candidate_plans = self._candidate_plans(request, required_records, target_colors, base_shell_tags)

        rendered: list[tuple[str, list[str], list[str], GeneratedDeck]] = []
        seen_ids: set[str] = set()
        for plan in candidate_plans:
            deck = self._build_candidate_deck(
                request=request,
                required_counts=required_counts,
                required_records=required_records,
                target_colors=target_colors,
                excluded=excluded,
                plan=plan,
            )
            if deck.id in seen_ids:
                continue
            rendered.append((plan.label, list(plan.shell_tags), list(plan.focus_roles), deck))
            seen_ids.add(deck.id)
            if len(rendered) >= request.candidate_count:
                break

        if not rendered:
            raise ValueError("Unable to produce any candidate decks for the requested constraints")
        return rendered

    def _build_candidate_deck(
        self,
        *,
        request: GenerationRequest,
        required_counts: Counter[str],
        required_records: list[IndexedCardRecord],
        target_colors: list[Color],
        excluded: set[str],
        plan: CandidatePlan,
    ) -> GeneratedDeck:
        max_cards = request.max_cards
        selected_counts: Counter[str] = Counter(required_counts)
        selected_reason_codes: dict[str, set[str]] = {
            slug: {"required"} for slug in selected_counts
        }

        required_nonland_count = self._count_nonlands(selected_counts)
        if sum(selected_counts.values()) > max_cards:
            raise ValueError(f"required_slugs exceed the {max_cards}-card deck size")
        if required_nonland_count > max_cards - request.min_lands:
            raise ValueError("required_slugs leave too few slots to satisfy the minimum land count")

        base_land_target = self._choose_land_target(required_records)
        land_target = max(request.min_lands, base_land_target + plan.land_target_shift)
        if required_nonland_count > max_cards - land_target:
            land_target = max(request.min_lands, max_cards - required_nonland_count)
        nonland_target = max_cards - land_target

        candidate_records = self._sorted_candidates(
            excluded=excluded,
            required_slugs=set(selected_counts),
            target_colors=target_colors,
            shell_tags=list(plan.shell_tags),
            focus_roles=list(plan.focus_roles),
            curve_focus=plan.curve_focus,
            novelty_bias=plan.novelty_bias,
        )
        for _copy_round in range(1, 5):
            if self._count_nonlands(selected_counts) >= nonland_target:
                break
            for record in candidate_records:
                if self._count_nonlands(selected_counts) >= nonland_target:
                    break
                slug = record.entity.slug
                if selected_counts[slug] >= self._preferred_copies(record, list(plan.focus_roles), plan.curve_focus):
                    continue
                selected_counts[slug] += 1
                selected_reason_codes.setdefault(slug, set()).update(
                    self._reason_codes(record, list(plan.shell_tags), target_colors, list(plan.focus_roles))
                )

        if self._count_nonlands(selected_counts) < nonland_target:
            raise ValueError(f"not enough candidate nonland cards to complete a {max_cards}-card deck")

        required_land_count = self._count_lands(selected_counts)
        additional_lands_needed = max(0, land_target - required_land_count)
        selected_counts.update(self._build_basic_mana_base(selected_counts, additional_lands_needed, target_colors, excluded))

        while sum(selected_counts.values()) > max_cards:
            removable = self._find_trim_candidate(selected_counts, selected_reason_codes)
            if removable is None:
                break
            selected_counts[removable] -= 1
            if selected_counts[removable] == 0:
                del selected_counts[removable]

        if sum(selected_counts.values()) < max_cards:
            missing = max_cards - sum(selected_counts.values())
            selected_counts.update(self._build_basic_mana_base(selected_counts, missing, target_colors, excluded))

        deck_cards = self._render_deck_cards(selected_counts, selected_reason_codes)
        land_count = sum(card.quantity for card in deck_cards if card.is_land)
        nonland_count = sum(card.quantity for card in deck_cards if not card.is_land)
        deck_id = self._deck_id(request, deck_cards, plan.label)
        summary = self._summary(target_colors, list(plan.shell_tags), land_count, nonland_count, plan.label)
        explanation_lines = [
            f"Candidate profile: {plan.label}.",
            f"Colors: {'/'.join(target_colors) if target_colors else 'color-flexible'}.",
            f"Primary tags: {', '.join(plan.shell_tags) if plan.shell_tags else 'curve and interaction'}.",
            f"Role anchors: {', '.join(plan.focus_roles) if plan.focus_roles else 'balanced role mix'}.",
            f"Deck shape: {nonland_count} nonlands and {land_count} lands.",
            "Lands use a deterministic basic-first mana base for MVP transparency.",
        ]
        return GeneratedDeck(
            id=deck_id,
            name=self._deck_name(target_colors, list(plan.shell_tags), plan.label),
            colors=target_colors,
            preferred_tags=list(dict.fromkeys(plan.shell_tags)),
            summary=summary,
            explanation_lines=explanation_lines,
            cards=deck_cards,
            card_count=sum(card.quantity for card in deck_cards),
            land_count=land_count,
            nonland_count=nonland_count,
        )

    def _candidate_plans(
        self,
        request: GenerationRequest,
        required_records: list[IndexedCardRecord],
        target_colors: list[Color],
        base_shell_tags: list[str],
    ) -> list[CandidatePlan]:
        requested_roles = tuple(dict.fromkeys(request.preferred_roles))
        discovered_roles = self._discover_roles(required_records, target_colors)
        alternate_tags = self._discover_alternate_tags(target_colors, base_shell_tags)
        novelty_bias = 0.5 + (request.target_novelty - 0.35)

        plans: list[CandidatePlan] = [
            CandidatePlan(
                label="Balanced shell",
                shell_tags=tuple(base_shell_tags),
                focus_roles=requested_roles,
                curve_focus=request.target_tempo,
                novelty_bias=max(0.25, novelty_bias),
                land_target_shift=0,
            ),
            CandidatePlan(
                label="Tempo pressure",
                shell_tags=tuple(base_shell_tags),
                focus_roles=tuple(dict.fromkeys((*requested_roles, "one_drop_pressure", "two_drop_pressure", "cheap_interaction"))),
                curve_focus="fast",
                novelty_bias=max(0.1, novelty_bias - 0.15),
                land_target_shift=-1,
            ),
            CandidatePlan(
                label="Synergy engine",
                shell_tags=tuple(dict.fromkeys((*base_shell_tags, *alternate_tags[:1]))),
                focus_roles=tuple(dict.fromkeys((*requested_roles, "engine", "payoff", "card_draw"))),
                curve_focus="medium",
                novelty_bias=max(0.2, novelty_bias),
                land_target_shift=0,
            ),
            CandidatePlan(
                label="Novel angle",
                shell_tags=tuple(dict.fromkeys((*alternate_tags[:2], *base_shell_tags[:1]))),
                focus_roles=tuple(dict.fromkeys((*requested_roles, *discovered_roles[:2]))),
                curve_focus=request.target_tempo,
                novelty_bias=min(1.0, novelty_bias + 0.2),
                land_target_shift=1,
            ),
            CandidatePlan(
                label="Top-end posture",
                shell_tags=tuple(dict.fromkeys((*base_shell_tags[:2], *alternate_tags[1:2]))),
                focus_roles=tuple(dict.fromkeys((*requested_roles, "top_end_finisher", "stabilizer", "recursion"))),
                curve_focus="slow",
                novelty_bias=max(0.15, novelty_bias - 0.05),
                land_target_shift=1,
            ),
        ]
        deduped: list[CandidatePlan] = []
        seen: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
        for plan in plans:
            normalized = (
                plan.label,
                tuple(tag for tag in plan.shell_tags if tag),
                tuple(role for role in plan.focus_roles if role),
            )
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(plan)
        return deduped

    def _discover_alternate_tags(self, target_colors: list[Color], base_shell_tags: list[str]) -> list[str]:
        counts = Counter[str]()
        for record in self._index._records:
            if target_colors and record.entity.color_identity and not set(record.entity.color_identity).issubset(set(target_colors)):
                continue
            for tag in record.entity.synergy_tags:
                if tag.startswith("tribal:") or tag in base_shell_tags:
                    continue
                counts[tag] += 1
        return [tag for tag, _ in counts.most_common(5)]

    def _discover_roles(self, required_records: list[IndexedCardRecord], target_colors: list[Color]) -> list[str]:
        counts = Counter[str]()
        for record in required_records:
            counts.update(record.entity.role_tags)
        if counts:
            return [role for role, _ in counts.most_common(4)]
        for record in self._index._records:
            if target_colors and record.entity.color_identity and not set(record.entity.color_identity).issubset(set(target_colors)):
                continue
            counts.update(role for role in record.entity.role_tags if role in ROLE_WEIGHTS)
        return [role for role, _ in counts.most_common(4)]

    def _require_record(self, slug: str) -> IndexedCardRecord:
        record = self._index.get_record(slug)
        if record is None:
            raise ValueError(f"Unknown card slug: {slug}")
        return record

    def _determine_colors(self, request: GenerationRequest, required_records: list[IndexedCardRecord]) -> list[Color]:
        if request.colors:
            return list(dict.fromkeys(request.colors))

        required_colors = {color for record in required_records for color in (record.entity.color_identity or record.entity.colors)}
        if required_colors:
            return [color for color in COLOR_ORDER if color in required_colors]

        if request.preferred_tags:
            counts = Counter[Color]()
            for record in self._index._records:
                if set(request.preferred_tags) & set(record.entity.synergy_tags):
                    for color in record.entity.color_identity or record.entity.colors:
                        counts[color] += 1
            if counts:
                return [color for color, _ in counts.most_common(2)]

        corpus_counts = Counter[Color]()
        for card in self._index.cards:
            for color in card.color_identity or card.colors:
                corpus_counts[color] += 1
        return [color for color, _ in corpus_counts.most_common(2)] or ["G"]

    def _determine_shell_tags(
        self,
        request: GenerationRequest,
        required_records: list[IndexedCardRecord],
        target_colors: list[Color],
    ) -> list[str]:
        if request.preferred_tags:
            return list(dict.fromkeys(sorted(request.preferred_tags)))

        counts = Counter[str]()
        for record in required_records:
            counts.update(record.entity.synergy_tags)
        if not counts:
            for record in self._sorted_candidates(
                excluded=set(),
                required_slugs=set(),
                target_colors=target_colors,
                shell_tags=[],
                focus_roles=[],
                curve_focus=request.target_tempo,
                novelty_bias=request.target_novelty,
            )[:100]:
                counts.update(record.entity.synergy_tags)
        shell_tags = [tag for tag, _ in counts.most_common(3) if not tag.startswith("tribal:")]
        return shell_tags

    def _sorted_candidates(
        self,
        *,
        excluded: set[str],
        required_slugs: set[str],
        target_colors: list[Color],
        shell_tags: list[str],
        focus_roles: list[str],
        curve_focus: str,
        novelty_bias: float,
    ) -> list[IndexedCardRecord]:
        candidates: list[IndexedCardRecord] = []
        for record in self._index._records:
            entity = record.entity
            if entity.slug in excluded or entity.slug in required_slugs or entity.is_land:
                continue
            if target_colors and entity.color_identity and not set(entity.color_identity).issubset(set(target_colors)):
                continue
            candidates.append(record)
        return sorted(
            candidates,
            key=lambda record: self._candidate_sort_key(record, shell_tags, focus_roles, target_colors, curve_focus, novelty_bias),
        )

    def _candidate_sort_key(
        self,
        record: IndexedCardRecord,
        shell_tags: list[str],
        focus_roles: list[str],
        target_colors: list[Color],
        curve_focus: str,
        novelty_bias: float,
    ) -> tuple[float, int, str]:
        entity = record.entity
        score = 0.0
        shell_overlap = len(set(entity.synergy_tags) & set(shell_tags))
        score += shell_overlap * 8.0

        role_score = sum(ROLE_WEIGHTS.get(role, 2.0) for role in set(entity.role_tags) & set(focus_roles))
        baseline_roles = {"mana_dork", "cheap_removal", "cheap_interaction", "card_draw", "engine", "ramp", "fixing", "token_maker"}
        role_score += sum(ROLE_WEIGHTS.get(role, 1.5) * 0.45 for role in set(entity.role_tags) & baseline_roles)
        score += role_score

        if curve_focus == "fast":
            score += 3.0 if entity.mana_value in {1, 2} else 1.5 if entity.mana_value == 3 else 0.0
            score -= max(entity.mana_value - 4, 0) * 1.6
        elif curve_focus == "slow":
            score += 3.5 if entity.mana_value in {4, 5} else 1.5 if entity.mana_value >= 6 else 0.0
            score -= 1.25 if entity.mana_value == 1 else 0.0
        else:
            score += 2.5 if entity.mana_value in {2, 3} else 1.0 if entity.mana_value == 4 else 0.0
            score -= max(entity.mana_value - 5, 0) * 1.1

        if target_colors and entity.color_identity:
            score += len(set(entity.color_identity) & set(target_colors)) * 1.5

        score += entity.novelty_baseline_score * max(0.0, novelty_bias) * 6.0
        return (-score, entity.mana_value, entity.display_name.casefold())

    def _preferred_copies(self, record: IndexedCardRecord, focus_roles: list[str], curve_focus: str) -> int:
        entity = record.entity
        focus_role_set = set(focus_roles)
        if "legendary" in entity.synergy_tags and entity.mana_value >= 4:
            return 2
        if "top_end_finisher" in entity.role_tags or entity.mana_value >= 5:
            return 2
        if focus_role_set & {"engine", "payoff", "card_draw"} and set(entity.role_tags) & focus_role_set:
            return 3
        if curve_focus == "fast" and entity.mana_value <= 2:
            return 4
        if entity.mana_value == 4:
            return 3
        return 4

    def _reason_codes(
        self,
        record: IndexedCardRecord,
        shell_tags: list[str],
        target_colors: list[Color],
        focus_roles: list[str],
    ) -> list[str]:
        reasons: list[str] = []
        overlap = sorted(set(record.entity.synergy_tags) & set(shell_tags))
        if overlap:
            reasons.extend(f"tag:{tag}" for tag in overlap)
        focus_role_matches = sorted(set(record.entity.role_tags) & set(focus_roles))
        if focus_role_matches:
            reasons.extend(f"role:{role}" for role in focus_role_matches)
        if target_colors and set(record.entity.color_identity or record.entity.colors).issubset(set(target_colors)):
            reasons.append("on_color")
        if "cheap_removal" in record.entity.role_tags or "cheap_interaction" in record.entity.role_tags:
            reasons.append("interaction")
        if "card_draw" in record.entity.role_tags:
            reasons.append("velocity")
        if "mana_dork" in record.entity.role_tags or "ramp" in record.entity.role_tags:
            reasons.append("ramp")
        return reasons or ["curve"]

    def _choose_land_target(self, required_records: list[IndexedCardRecord]) -> int:
        nonland_mana_values = [record.entity.mana_value for record in required_records if not record.entity.is_land]
        average_mana_value = mean(nonland_mana_values) if nonland_mana_values else 2.7
        if average_mana_value >= 3.4:
            return 24
        if average_mana_value >= 2.8:
            return 23
        return 21

    def _build_basic_mana_base(
        self,
        selected_counts: Counter[str],
        land_slots: int,
        target_colors: list[Color],
        excluded_slugs: set[str],
    ) -> Counter[str]:
        mana_weights = Counter[Color]()
        for slug, quantity in selected_counts.items():
            record = self._index.get_record(slug)
            if record is None or record.entity.is_land:
                continue
            palette = record.entity.color_identity or record.entity.colors or target_colors
            for color in palette:
                mana_weights[color] += quantity

        ordered_colors = [color for color in COLOR_ORDER if color in mana_weights] or list(target_colors) or ["G"]
        total_weight = sum(mana_weights[color] for color in ordered_colors) or len(ordered_colors)
        lands = Counter[str]()
        allocated = 0
        for index, color in enumerate(ordered_colors):
            slots_remaining = land_slots - allocated
            if slots_remaining <= 0:
                break
            if index == len(ordered_colors) - 1:
                count = slots_remaining
            else:
                raw_count = land_slots * (mana_weights[color] or 1) / total_weight
                count = max(1, round(raw_count))
                count = min(count, slots_remaining - max(0, len(ordered_colors) - index - 1))
            land_slug, _ = BASIC_LAND_BY_COLOR[color]
            if land_slug in excluded_slugs:
                raise ValueError(f"excluded_slugs prevent building the required mana base: {land_slug}")
            lands[land_slug] += count
            allocated += count
        return lands

    def _find_trim_candidate(self, selected_counts: Counter[str], selected_reason_codes: dict[str, set[str]]) -> str | None:
        candidates: list[tuple[int, int, str]] = []
        for slug, quantity in selected_counts.items():
            if quantity <= 0 or "required" in selected_reason_codes.get(slug, set()):
                continue
            record = self._index.get_record(slug)
            if record is None or record.entity.is_land:
                continue
            candidates.append((record.entity.mana_value, quantity, slug))
        if not candidates:
            return None
        _, _, slug = sorted(candidates, reverse=True)[0]
        return slug

    def _render_deck_cards(self, selected_counts: Counter[str], selected_reason_codes: dict[str, set[str]]) -> list[DeckCard]:
        cards: list[DeckCard] = []
        for slug, quantity in selected_counts.items():
            record = self._require_record(slug)
            cards.append(
                DeckCard(
                    slug=slug,
                    display_name=record.entity.display_name,
                    quantity=quantity,
                    is_land=record.entity.is_land,
                    mana_value=record.entity.mana_value,
                    type_line=record.entity.type_line,
                    reason_codes=sorted(selected_reason_codes.get(slug, set())),
                )
            )
        return sorted(cards, key=lambda card: (card.is_land, card.mana_value, card.display_name.casefold()))

    def _deck_id(self, request: GenerationRequest, deck_cards: list[DeckCard], label: str) -> str:
        payload = {
            "label": label,
            "request": request.model_dump(mode="json"),
            "cards": [{"slug": card.slug, "quantity": card.quantity} for card in deck_cards],
        }
        digest = sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return digest[:12]

    def _deck_name(self, colors: list[Color], shell_tags: list[str], label: str) -> str:
        color_part = "-".join(colors) if colors else "Open"
        tag_part = shell_tags[0].replace("_", " ").title() if shell_tags else "Midrange"
        return f"{color_part} {tag_part} {label}"

    def _summary(
        self,
        colors: list[Color],
        shell_tags: list[str],
        land_count: int,
        nonland_count: int,
        label: str,
    ) -> str:
        color_label = "/".join(colors) if colors else "flexible"
        tag_label = ", ".join(shell_tags[:2]) if shell_tags else "balanced curve"
        return f"{label} candidate: deterministic {color_label} deck leaning on {tag_label}, with {nonland_count} nonlands and {land_count} lands."

    def _count_nonlands(self, selected_counts: Counter[str]) -> int:
        count = 0
        for slug, quantity in selected_counts.items():
            record = self._index.get_record(slug)
            if record is not None and not record.entity.is_land:
                count += quantity
        return count

    def _count_lands(self, selected_counts: Counter[str]) -> int:
        count = 0
        for slug, quantity in selected_counts.items():
            record = self._index.get_record(slug)
            if record is not None and record.entity.is_land:
                count += quantity
        return count
