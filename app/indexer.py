from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re

from mtglib.scripts.mtglib_contract import CardModel, FaceModel, iter_markdown_files, parse_markdown_card

from .models import CardEntity, CardFaceEntity, CardFeatureVector, CardRelatedSummary, CardStats, Color, ManaCost, MetaResponse


COLOR_ORDER: tuple[Color, ...] = ("W", "U", "B", "R", "G")
CARD_TYPES = {
    "Artifact",
    "Battle",
    "Conspiracy",
    "Creature",
    "Dungeon",
    "Enchantment",
    "Instant",
    "Kindred",
    "Land",
    "Phenomenon",
    "Plane",
    "Planeswalker",
    "Scheme",
    "Sorcery",
    "Tribal",
    "Vanguard",
}
SUPERTYPES = {"Basic", "Legendary", "Ongoing", "Snow", "World"}
RULE_TEXT_COLOR_RE = re.compile(r"(?<![A-Za-z0-9])([WUBRG](?:/[WUBRGP])?|[WUBRG]/[WUBRG])(?![A-Za-z0-9])")
ADD_MANA_RE = re.compile(r"Add ([^.]+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class IndexedCardRecord:
    entity: CardEntity
    types: tuple[str, ...]
    subtypes: tuple[str, ...]
    produces_mana: tuple[Color, ...]
    search_blob: str


class CardIndex:
    def __init__(self, records: list[IndexedCardRecord], version: str, indexed_at: datetime) -> None:
        self._records = sorted(records, key=lambda record: record.entity.display_name.casefold())
        self._by_slug = {record.entity.slug: record for record in self._records}
        self.version = version
        self.indexed_at = indexed_at.astimezone(UTC)

        self._type_counts = Counter[str]()
        self._role_counts = Counter[str]()
        self._tag_counts = Counter[str]()
        for record in self._records:
            self._type_counts.update(record.types)
            self._role_counts.update(record.entity.role_tags)
            self._tag_counts.update(record.entity.synergy_tags)

    @classmethod
    def from_cards_directory(cls, cards_directory: Path) -> "CardIndex":
        markdown_files = iter_markdown_files([cards_directory])
        indexed_at = datetime.now(UTC)
        if not markdown_files:
            version = f"empty-{indexed_at.strftime('%Y%m%d%H%M%S')}"
            return cls([], version=version, indexed_at=indexed_at)

        records: list[IndexedCardRecord] = []
        latest_timestamp = 0.0
        for path in markdown_files:
            latest_timestamp = max(latest_timestamp, path.stat().st_mtime)
            model = parse_markdown_card(path.read_text(encoding="utf-8"))
            records.append(normalize_card_model(model))

        latest_marker = datetime.fromtimestamp(latest_timestamp, tz=UTC).strftime("%Y%m%d%H%M%S")
        version = f"cards-{len(records)}-{latest_marker}"
        return cls(records=records, version=version, indexed_at=indexed_at)

    @property
    def cards(self) -> list[CardEntity]:
        return [record.entity for record in self._records]

    def get(self, slug: str) -> CardEntity | None:
        record = self._by_slug.get(slug)
        return record.entity if record else None

    def get_record(self, slug: str) -> IndexedCardRecord | None:
        return self._by_slug.get(slug)

    def related_cards(self, slug: str, limit: int = 8) -> list[CardRelatedSummary]:
        origin = self._by_slug.get(slug)
        if origin is None:
            return []

        related: list[tuple[float, CardRelatedSummary]] = []
        origin_tags = set(origin.entity.synergy_tags)
        origin_roles = set(origin.entity.role_tags)
        origin_colors = set(origin.entity.color_identity or origin.entity.colors)
        origin_types = set(origin.types)
        for record in self._records:
            if record.entity.slug == slug:
                continue
            shared_tags = sorted(origin_tags & set(record.entity.synergy_tags))
            shared_roles = sorted(origin_roles & set(record.entity.role_tags))
            shared_types = origin_types & set(record.types)
            shared_colors = origin_colors & set(record.entity.color_identity or record.entity.colors)
            overlap_score = (
                len(shared_tags) * 2.0
                + len(shared_roles) * 1.25
                + len(shared_types) * 0.75
                + len(shared_colors) * 0.5
            )
            if overlap_score <= 0:
                continue
            related.append(
                (
                    overlap_score,
                    CardRelatedSummary(
                        slug=record.entity.slug,
                        display_name=record.entity.display_name,
                        type_line=record.entity.type_line,
                        colors=record.entity.colors,
                        shared_tags=shared_tags,
                        shared_roles=shared_roles,
                        overlap_score=round(overlap_score, 2),
                    ),
                )
            )

        related.sort(key=lambda item: (-item[0], item[1].display_name.casefold()))
        return [summary for _, summary in related[:limit]]

    def query(
        self,
        *,
        q: str = "",
        colors: list[Color] | None = None,
        types: list[str] | None = None,
        roles: list[str] | None = None,
        tags: list[str] | None = None,
        mana_value_min: int | None = None,
        mana_value_max: int | None = None,
        is_land: bool | None = None,
    ) -> list[CardEntity]:
        selected_colors = tuple(sorted(dict.fromkeys(colors or []), key=COLOR_ORDER.index))
        selected_types = {value.casefold() for value in (types or [])}
        selected_roles = {value.casefold() for value in (roles or [])}
        selected_tags = {value.casefold() for value in (tags or [])}
        query_text = q.strip().casefold()

        filtered: list[IndexedCardRecord] = []
        for record in self._records:
            entity = record.entity
            if selected_colors and not set(selected_colors).issubset(set(entity.color_identity or entity.colors)):
                continue
            if selected_types and not selected_types.issubset({item.casefold() for item in record.types}):
                continue
            if selected_roles and not selected_roles.issubset({item.casefold() for item in entity.role_tags}):
                continue
            if selected_tags and not selected_tags.issubset({item.casefold() for item in entity.synergy_tags}):
                continue
            if mana_value_min is not None and entity.mana_value < mana_value_min:
                continue
            if mana_value_max is not None and entity.mana_value > mana_value_max:
                continue
            if is_land is not None and entity.is_land != is_land:
                continue
            if query_text and query_text not in record.search_blob:
                continue
            filtered.append(record)

        filtered.sort(key=lambda record: self._sort_key(record, query_text))
        return [record.entity for record in filtered]

    def meta(self) -> MetaResponse:
        return MetaResponse(
            corpus_version=self.version,
            card_count=len(self._records),
            indexed_at=self.indexed_at.isoformat(),
            supported_filters={
                "colors": list(COLOR_ORDER),
                "types": sorted(self._type_counts, key=str.casefold),
                "roles": sorted(self._role_counts, key=str.casefold),
                "tags": sorted(self._tag_counts, key=str.casefold),
            },
            tag_distributions={
                "types": dict(sorted(self._type_counts.items())),
                "roles": dict(sorted(self._role_counts.items())),
                "tags": dict(sorted(self._tag_counts.items())),
            },
        )

    def _sort_key(self, record: IndexedCardRecord, query_text: str) -> tuple[int, int, str]:
        entity = record.entity
        exact_match = 0
        prefix_match = 0
        if query_text:
            if entity.slug.casefold() == query_text or entity.display_name.casefold() == query_text:
                exact_match = -1
            elif entity.slug.casefold().startswith(query_text) or entity.display_name.casefold().startswith(query_text):
                prefix_match = -1
        return (exact_match, prefix_match, entity.display_name.casefold())


def normalize_card_model(card: CardModel) -> IndexedCardRecord:
    faces = _normalize_faces(card)
    primary_face = faces[0]
    supertypes, types, subtypes = _parse_type_line(primary_face.type_line)
    rules_text = _aggregate_rules_text(faces)
    keywords = sorted({keyword for face in faces for keyword in face.keywords}, key=str.casefold)
    colors = _ordered_colors({color for face in faces for color in face.colors})
    produces_mana = _extract_produced_mana(rules_text)
    color_identity = _ordered_colors(set(colors) | set(produces_mana) | _extract_color_identity_from_text(rules_text))
    is_land = "Land" in types
    is_basic_land = is_land and primary_face.type_line.startswith("Basic ")
    mana_value = primary_face.mana_value
    role_tags = _infer_role_tags(
        type_line=primary_face.type_line,
        rules_text=rules_text,
        mana_value=mana_value,
        is_land=is_land,
        is_basic_land=is_basic_land,
        keywords=keywords,
        faces=faces,
        produces_mana=produces_mana,
    )
    synergy_tags = _infer_synergy_tags(
        type_line=primary_face.type_line,
        rules_text=rules_text,
        subtypes=subtypes,
        is_land=is_land,
    )
    feature_vector = _build_feature_vector(
        mana_value=mana_value,
        types=types,
        rules_text=rules_text,
        role_tags=role_tags,
        synergy_tags=synergy_tags,
        keywords=keywords,
        is_land=is_land,
    )
    entity = CardEntity(
        slug=card.slug,
        display_name=card.display_name,
        canonical_name=card.canonical_name,
        layout=card.layout,
        sets=card.sets,
        faces=faces,
        type_line=primary_face.type_line,
        supertypes=list(supertypes),
        types=list(types),
        subtypes=list(subtypes),
        mana_cost=primary_face.mana_cost,
        mana_value=mana_value,
        colors=colors,
        color_identity=color_identity,
        keywords=keywords,
        rules_text=rules_text,
        stats=primary_face.stats,
        loyalty=primary_face.loyalty,
        is_land=is_land,
        is_basic_land=is_basic_land,
        produces_mana=list(produces_mana),
        feature_vector=feature_vector,
        role_tags=role_tags,
        synergy_tags=synergy_tags,
        novelty_baseline_score=_novelty_baseline_score(feature_vector, synergy_tags),
    )
    search_blob = " ".join(
        [
            entity.slug,
            entity.display_name,
            entity.canonical_name,
            entity.type_line,
            entity.rules_text,
            " ".join(entity.role_tags),
            " ".join(entity.synergy_tags),
        ]
    ).casefold()
    return IndexedCardRecord(
        entity=entity,
        types=types,
        subtypes=subtypes,
        produces_mana=tuple(produces_mana),
        search_blob=search_blob,
    )


def _normalize_faces(card: CardModel) -> list[CardFaceEntity]:
    source_faces = card.faces or [
        FaceModel(
            name=card.display_name,
            mana=card.mana,
            type_line=card.type_line or "None",
            keywords=card.keywords,
            rules_text=card.rules_text or "None",
            power=card.power,
            toughness=card.toughness,
            loyalty=card.loyalty,
        )
    ]
    faces: list[CardFaceEntity] = []
    for face in source_faces:
        colors = _ordered_colors(_mana_breakdown_colors(face.mana))
        _, face_types, face_subtypes = _parse_type_line(face.type_line)
        faces.append(
            CardFaceEntity(
                name=face.name,
                mana_cost=_mana_cost_entity(face.mana),
                mana_value=_mana_value(face.mana),
                type_line=face.type_line,
                types=list(face_types),
                subtypes=list(face_subtypes),
                keywords=face.keywords,
                rules_text=face.rules_text,
                colors=colors,
                stats=CardStats(power=face.power, toughness=face.toughness)
                if face.power is not None and face.toughness is not None
                else None,
                loyalty=face.loyalty,
            )
        )
    return faces


def _mana_cost_entity(mana: object | None) -> ManaCost:
    if mana is None:
        return ManaCost()
    return ManaCost(
        printed=mana.printed,
        generic=int(mana.generic),
        white=int(mana.white),
        blue=int(mana.blue),
        black=int(mana.black),
        red=int(mana.red),
        green=int(mana.green),
        colorless=int(mana.colorless),
        hybrid=dict(mana.hybrid),
        phyrexian=dict(mana.phyrexian),
        variable=dict(mana.variable),
        snow=int(mana.snow),
    )


def _mana_value(mana: object | None) -> int:
    if mana is None:
        return 0
    return (
        int(mana.generic)
        + int(mana.white)
        + int(mana.blue)
        + int(mana.black)
        + int(mana.red)
        + int(mana.green)
        + int(mana.colorless)
        + sum(mana.hybrid.values())
        + sum(mana.phyrexian.values())
    )


def _mana_breakdown_colors(mana: object | None) -> set[Color]:
    if mana is None:
        return set()
    colors: set[Color] = set()
    if mana.white:
        colors.add("W")
    if mana.blue:
        colors.add("U")
    if mana.black:
        colors.add("B")
    if mana.red:
        colors.add("R")
    if mana.green:
        colors.add("G")
    for symbol_map in (mana.hybrid, mana.phyrexian, mana.variable):
        for symbol in symbol_map:
            colors.update(_colors_in_token(symbol))
    return colors


def _aggregate_rules_text(faces: list[CardFaceEntity]) -> str:
    if len(faces) == 1:
        return faces[0].rules_text
    return "\n\n".join(f"{face.name}: {face.rules_text}" for face in faces)


def _parse_type_line(type_line: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    left, _, right = type_line.partition(" - ")
    parts = [part for part in left.split() if part]
    supertypes = tuple(part for part in parts if part in SUPERTYPES)
    card_types = tuple(part for part in parts if part in CARD_TYPES)
    subtypes = tuple(part for part in right.split() if part)
    return supertypes, card_types, subtypes


def _build_feature_vector(
    *,
    mana_value: int,
    types: tuple[str, ...],
    rules_text: str,
    role_tags: list[str],
    synergy_tags: list[str],
    keywords: list[str],
    is_land: bool,
) -> CardFeatureVector:
    rules_lower = rules_text.casefold()
    role_tag_set = set(role_tags)
    type_set = set(types)
    synergy_density = _bounded((len(synergy_tags) / 6) + (0.1 if "engine" in role_tag_set else 0.0))
    board_immediacy = _bounded(
        (0.45 if mana_value <= 2 else 0.25 if mana_value <= 4 else 0.1)
        + (0.15 if "haste" in rules_lower or "flash" in rules_lower else 0.0)
        + (0.1 if "when " in rules_lower and " enters" in rules_lower else 0.0)
    )
    resource_velocity = _bounded(
        (0.35 if "card_draw" in role_tag_set else 0.0)
        + (0.2 if "ramp" in role_tag_set else 0.0)
        + (0.15 if "look at the top" in rules_lower or "scry" in rules_lower else 0.0)
        + (0.1 if "create" in rules_lower and "treasure" in rules_lower else 0.0)
    )
    resilience = _bounded(
        (0.2 if "recursion" in role_tag_set else 0.0)
        + (0.15 if "ward" in rules_lower or "hexproof" in rules_lower else 0.0)
        + (0.15 if "lifelink" in rules_lower or "indestructible" in rules_lower else 0.0)
        + (0.15 if mana_value >= 4 else 0.0)
    )
    return CardFeatureVector(
        mana_value_bucket=min(mana_value, 6),
        is_creature="Creature" in type_set,
        is_interaction=bool({"cheap_interaction", "counterspell", "removal", "sweeper"} & role_tag_set),
        is_removal="removal" in role_tag_set,
        is_card_draw="card_draw" in role_tag_set,
        is_selection="look at the top" in rules_lower or "scry" in rules_lower,
        is_ramp="ramp" in role_tag_set,
        is_fixing="fixing" in role_tag_set,
        is_token_maker="token_maker" in role_tag_set,
        is_recursion="recursion" in role_tag_set,
        is_sweeper="sweeper" in role_tag_set,
        is_counterspell="counterspell" in role_tag_set,
        is_combat_trick="Instant" in type_set and mana_value <= 2 and "target creature gets" in rules_text,
        is_engine_piece="engine" in role_tag_set,
        is_payoff="payoff" in role_tag_set or "top_end_finisher" in role_tag_set,
        is_enabler=bool({"mana_dork", "ramp", "fixing", "card_draw", "engine"} & role_tag_set),
        board_immediacy=board_immediacy,
        resource_velocity=resource_velocity,
        resilience=resilience,
        synergy_density=synergy_density,
    )


def _novelty_baseline_score(feature_vector: CardFeatureVector, synergy_tags: list[str]) -> float:
    rarity_bonus = 0.15 if any(tag.startswith("tribal:") for tag in synergy_tags) else 0.0
    return round(_bounded((feature_vector.synergy_density * 0.6) + rarity_bonus + (0.1 if len(synergy_tags) >= 3 else 0.0)), 3)


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))


def _extract_color_identity_from_text(rules_text: str) -> set[Color]:
    colors: set[Color] = set()
    for match in RULE_TEXT_COLOR_RE.finditer(rules_text):
        colors.update(_colors_in_token(match.group(1)))
    return colors


def _extract_produced_mana(rules_text: str) -> tuple[Color, ...]:
    colors: set[Color] = set()
    for raw_clause in ADD_MANA_RE.findall(rules_text):
        clause = raw_clause.strip()
        if "any color" in clause.casefold():
            colors.update(COLOR_ORDER)
            continue
        colors.update(_extract_color_identity_from_text(clause))
    return _ordered_colors(colors)


def _ordered_colors(colors: set[Color]) -> list[Color]:
    return [color for color in COLOR_ORDER if color in colors]


def _colors_in_token(token: str) -> set[Color]:
    return {color for color in COLOR_ORDER if color in token}


def _infer_role_tags(
    *,
    type_line: str,
    rules_text: str,
    mana_value: int,
    is_land: bool,
    is_basic_land: bool,
    keywords: list[str],
    faces: list[CardFaceEntity],
    produces_mana: tuple[Color, ...],
) -> list[str]:
    tags: set[str] = set()
    rules_lower = rules_text.casefold()
    type_lower = type_line.casefold()

    if is_land:
        tags.add("mana_base")
        if is_basic_land:
            tags.add("basic_land")
        if produces_mana:
            tags.add("fixing")
        return sorted(tags)

    if "creature" in type_lower and mana_value == 1:
        tags.add("one_drop_pressure")
    if "creature" in type_lower and mana_value == 2:
        tags.add("two_drop_pressure")
    if "creature" in type_lower and mana_value == 3:
        tags.add("three_drop_pressure")
    if "creature" in type_lower and mana_value >= 5:
        tags.add("top_end_finisher")
    if "tap: add" in rules_lower and "creature" in type_lower:
        tags.add("mana_dork")
        tags.add("ramp")
    if any(pattern in rules_lower for pattern in ("search your library for a basic land", "add one mana of any color", "add two mana")):
        tags.add("ramp")
    if any(pattern in rules_lower for pattern in ("add one mana of any color", "tap: add w or", "tap: add u or", "tap: add b or", "tap: add r or", "tap: add g or")):
        tags.add("fixing")
    if "draw " in rules_lower or "look at the top" in rules_lower or "scry " in rules_lower:
        tags.add("card_draw")
    if "counter target" in rules_lower:
        tags.add("counterspell")
        if mana_value <= 3:
            tags.add("cheap_interaction")
    if any(pattern in rules_lower for pattern in ("destroy target", "exile target", "deals", "fight target")):
        tags.add("removal")
        if mana_value <= 3:
            tags.add("cheap_removal")
            tags.add("cheap_interaction")
    if any(pattern in rules_lower for pattern in ("each creature", "all creatures", "each opponent")) and any(
        pattern in rules_lower for pattern in ("destroy", "exile", "gets -", "deals")
    ):
        tags.add("sweeper")
    if "create" in rules_lower and "token" in rules_lower:
        tags.add("token_maker")
    if "return target" in rules_lower and "graveyard" in rules_lower:
        tags.add("recursion")
    if any(keyword.casefold() in {"flying", "lifelink", "vigilance"} for keyword in keywords):
        tags.add("stabilizer")
    if "whenever" in rules_lower or "at the beginning" in rules_lower:
        tags.add("engine")
    if any(
        face.stats is not None and face.stats.power.isdigit() and int(face.stats.power) >= 4
        for face in faces
    ):
        tags.add("payoff")

    return sorted(tags)


def _infer_synergy_tags(*, type_line: str, rules_text: str, subtypes: tuple[str, ...], is_land: bool) -> list[str]:
    tags: set[str] = set()
    rules_lower = rules_text.casefold()
    type_lower = type_line.casefold()

    if "artifact" in type_lower or "artifact" in rules_lower:
        tags.add("artifacts")
    if "enchantment" in type_lower or "enchantment" in rules_lower:
        tags.add("enchantments")
    if "legendary" in type_lower:
        tags.add("legendary")
    if "token" in rules_lower:
        tags.add("tokens")
        tags.add("go_wide")
    if "+1/+1 counter" in rules_lower or "counter" in rules_lower:
        tags.add("counters")
    if "sacrifice" in rules_lower:
        tags.add("sacrifice")
    if "graveyard" in rules_lower:
        tags.add("graveyard")
    if "draw" in rules_lower or "instant" in type_lower or "sorcery" in type_lower:
        tags.add("spellslinger")
    if "gain" in rules_lower and "life" in rules_lower:
        tags.add("lifegain")
    if is_land or "land" in rules_lower:
        tags.add("lands")
    for subtype in subtypes:
        tags.add(f"tribal:{subtype.casefold()}")
    return sorted(tags)
