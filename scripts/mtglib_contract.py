from __future__ import annotations

import argparse
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
MANA_TOKEN_RE = re.compile(r"\{([^}]+)\}")


@dataclass(slots=True)
class ManaBreakdown:
    printed: str = "none"
    generic: int = 0
    white: int = 0
    blue: int = 0
    black: int = 0
    red: int = 0
    green: int = 0
    colorless: int = 0
    hybrid: dict[str, int] = field(default_factory=dict)
    phyrexian: dict[str, int] = field(default_factory=dict)
    variable: dict[str, int] = field(default_factory=dict)
    snow: int = 0


@dataclass(slots=True)
class FaceModel:
    name: str
    mana: ManaBreakdown
    type_line: str
    keywords: list[str]
    rules_text: str
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None


@dataclass(slots=True)
class CardModel:
    display_name: str
    canonical_name: str
    slug: str
    layout: str
    sets: list[str] = field(default_factory=list)
    mana: ManaBreakdown | None = None
    type_line: str | None = None
    keywords: list[str] = field(default_factory=list)
    rules_text: str | None = None
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None
    faces: list[FaceModel] = field(default_factory=list)


def slugify_name(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.replace("//", " ").replace("/", " ")
    ascii_name = re.sub(r"[^A-Za-z0-9\s-]", "", ascii_name)
    ascii_name = re.sub(r"[\s-]+", "-", ascii_name.strip().lower())
    return ascii_name


def normalize_display_name(name: str) -> str:
    return name.replace(" // ", " / ").strip()


def normalize_layout(layout: str, has_faces: bool) -> str:
    if not has_faces:
        return "single-face"
    return layout.replace("_", "-")


def parse_mana_cost(mana_cost: str) -> ManaBreakdown:
    if not mana_cost:
        return ManaBreakdown()

    breakdown = ManaBreakdown()
    printed_tokens: list[str] = []

    for token in MANA_TOKEN_RE.findall(mana_cost):
        token = token.upper()
        printed_tokens.append(_render_mana_token(token))

        if token.isdigit():
            breakdown.generic += int(token)
        elif token == "W":
            breakdown.white += 1
        elif token == "U":
            breakdown.blue += 1
        elif token == "B":
            breakdown.black += 1
        elif token == "R":
            breakdown.red += 1
        elif token == "G":
            breakdown.green += 1
        elif token == "C":
            breakdown.colorless += 1
        elif token == "S":
            breakdown.snow += 1
        elif token in {"X", "Y", "Z"}:
            breakdown.variable[token] = breakdown.variable.get(token, 0) + 1
        elif "/P" in token:
            breakdown.phyrexian[token] = breakdown.phyrexian.get(token, 0) + 1
        elif "/" in token:
            breakdown.hybrid[token] = breakdown.hybrid.get(token, 0) + 1

    breakdown.printed = "".join(printed_tokens) if printed_tokens else "none"
    return breakdown


def render_card(card: CardModel) -> str:
    validate_card(card)
    parts = [
        f"# {card.display_name}",
        "",
        "## Canonical Name",
        card.canonical_name,
        "",
        "## Slug",
        card.slug,
        "",
        "## Layout",
        card.layout,
        "",
    ]

    parts.extend(_render_sets_section(card.sets))

    if card.faces:
        parts.extend(["## Faces", ""])
        for index, face in enumerate(card.faces, start=1):
            parts.extend(_render_face(index, face))
    else:
        if card.mana is None or card.type_line is None or card.rules_text is None:
            raise ValueError(f"Single-face card {card.slug} is missing required fields")

        parts.extend(_render_mana_section("## Mana Cost", card.mana))
        parts.extend(["## Type Line", card.type_line or "None", ""])
        parts.extend(_render_keywords_section(card.keywords))
        parts.extend(["## Rules Text", card.rules_text or "None", ""])

        if card.power is not None and card.toughness is not None:
            parts.extend(["## Stats", f"- Power: {card.power}", f"- Toughness: {card.toughness}", ""])

        if card.loyalty is not None:
            parts.extend(["## Loyalty", f"- Starting Loyalty: {card.loyalty}", ""])

    while parts and parts[-1] == "":
        parts.pop()

    return "\n".join(parts) + "\n"


def parse_markdown_card(markdown_text: str) -> CardModel:
    lines = markdown_text.replace("\r\n", "\n").split("\n")
    if not lines or not lines[0].startswith("# "):
        raise ValueError("Card file is missing a top-level title")

    display_name = lines[0][2:].strip()
    sections = _parse_sections(lines[1:], expected_prefix="## ")
    canonical_name = _single_line(sections.get("Canonical Name", []), display_name)
    slug = _single_line(sections.get("Slug", []), slugify_name(canonical_name))
    layout = _single_line(sections.get("Layout", []), "single-face")
    sets = parse_sets_section(sections.get("Sets", []))

    if "Faces" in sections:
        faces = _parse_faces(sections["Faces"])
        return CardModel(
            display_name=display_name,
            canonical_name=canonical_name,
            slug=slug,
            layout=layout,
            sets=sets,
            faces=faces,
        )

    mana = parse_mana_section(sections.get("Mana Cost", []))
    keywords = parse_keywords_section(sections.get("Keywords", []))
    rules_text = _join_block(sections.get("Rules Text", []))
    stats = _parse_list_map(sections.get("Stats", []))
    loyalty_map = _parse_list_map(sections.get("Loyalty", []))

    return CardModel(
        display_name=display_name,
        canonical_name=canonical_name,
        slug=slug,
        layout=layout,
        sets=sets,
        mana=mana,
        type_line=_single_line(sections.get("Type Line", []), "None"),
        keywords=keywords,
        rules_text=rules_text or "None",
        power=stats.get("Power"),
        toughness=stats.get("Toughness"),
        loyalty=loyalty_map.get("Starting Loyalty"),
    )


def parse_mana_section(lines: list[str]) -> ManaBreakdown:
    mapping = _parse_list_map(lines)
    mana = ManaBreakdown()
    mana.printed = mapping.get("Printed", "none")
    mana.generic = int(mapping.get("Generic", "0"))
    mana.white = int(mapping.get("White", "0"))
    mana.blue = int(mapping.get("Blue", "0"))
    mana.black = int(mapping.get("Black", "0"))
    mana.red = int(mapping.get("Red", "0"))
    mana.green = int(mapping.get("Green", "0"))
    mana.colorless = int(mapping.get("Colorless", "0"))
    mana.hybrid = _parse_symbol_counts(mapping.get("Hybrid", "none"))
    mana.phyrexian = _parse_symbol_counts(mapping.get("Phyrexian", "none"))
    mana.variable = _parse_symbol_counts(mapping.get("Variable", "none"))
    mana.snow = int(mapping.get("Snow", "0"))
    return mana


def parse_keywords_section(lines: list[str]) -> list[str]:
    values = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped.startswith("- "):
            continue
        value = stripped[2:].strip()
        if value.lower() == "none":
            return []
        values.append(value)
    return values


def parse_sets_section(lines: list[str]) -> list[str]:
    values = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped.startswith("- "):
            continue
        value = normalize_ascii(stripped[2:].strip())
        if value.lower() == "none":
            return []
        values.append(value)
    return sorted(set(values), key=str.casefold)


def normalize_rules_text(text: str) -> str:
    if not text or text.strip().lower() == "none":
        return "None"

    normalized = (
        text.replace("\r\n", "\n")
        .replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2212", "-")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2022", "-")
    )
    normalized = MANA_TOKEN_RE.sub(lambda match: _render_rule_symbol(match.group(1)), normalized)

    cleaned_lines: list[str] = []
    for raw_line in normalized.split("\n"):
        line = re.sub(r"\s+", " ", raw_line.strip())
        line = re.sub(r"\s+([,.:;!?])", r"\1", line)
        cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or "None"


def card_model_from_scryfall(card: dict[str, Any], set_names: list[str] | None = None) -> CardModel:
    display_name = normalize_display_name(card["name"])
    canonical_name = display_name
    slug = slugify_name(canonical_name)
    faces_data = card.get("card_faces") or []

    if faces_data:
        root_keywords = [normalize_ascii(keyword) for keyword in card.get("keywords", [])]
        faces: list[FaceModel] = []
        for face in faces_data:
            face_rules = normalize_rules_text(face.get("oracle_text", ""))
            face_keywords = infer_face_keywords(face_rules, root_keywords)
            faces.append(
                FaceModel(
                    name=normalize_display_name(face["name"]),
                    mana=parse_mana_cost(face.get("mana_cost", "")),
                    type_line=normalize_ascii(face.get("type_line", "None")),
                    keywords=face_keywords,
                    rules_text=face_rules,
                    power=face.get("power"),
                    toughness=face.get("toughness"),
                    loyalty=face.get("loyalty"),
                )
            )

        return CardModel(
            display_name=display_name,
            canonical_name=canonical_name,
            slug=slug,
            layout=normalize_layout(card.get("layout", "normal"), True),
            sets=_normalize_set_names(set_names or [card.get("set_name", "")]),
            faces=faces,
        )

    return CardModel(
        display_name=display_name,
        canonical_name=canonical_name,
        slug=slug,
        layout="single-face",
        sets=_normalize_set_names(set_names or [card.get("set_name", "")]),
        mana=parse_mana_cost(card.get("mana_cost", "")),
        type_line=normalize_ascii(card.get("type_line", "None")),
        keywords=[normalize_ascii(keyword) for keyword in card.get("keywords", [])],
        rules_text=normalize_rules_text(card.get("oracle_text", "")),
        power=card.get("power"),
        toughness=card.get("toughness"),
        loyalty=card.get("loyalty"),
    )


def lint_card_file(path: Path, check_only: bool = False) -> bool:
    original = path.read_text(encoding="utf-8")
    model = parse_markdown_card(original)
    validate_card(model)
    rendered = render_card(model)
    target_path = path.with_name(f"{model.slug}.md")
    changed = rendered != original or target_path != path
    if changed and not check_only:
        if target_path.exists() and target_path != path:
            raise ValueError(f"Cannot rename {path.name} to {target_path.name}: destination already exists")
        target_path.write_text(rendered, encoding="utf-8")
        if target_path != path and path.exists():
            path.unlink()
    return changed


def iter_markdown_files(paths: list[Path]) -> list[Path]:
    discovered: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".md":
            discovered.append(path)
            continue
        if path.is_dir():
            discovered.extend(sorted(path.glob("*.md")))
    return sorted(set(discovered))


def infer_face_keywords(rules_text: str, declared_keywords: list[str]) -> list[str]:
    if not declared_keywords:
        return []
    rules_lines = [line.strip() for line in rules_text.splitlines() if line.strip()]
    found: list[str] = []
    for keyword in declared_keywords:
        for line in rules_lines:
            if line == keyword or line.startswith(f"{keyword} ") or line.startswith(f"{keyword}(") or line.startswith(f"{keyword} -"):
                found.append(keyword)
                break
    return found


def validate_card(card: CardModel) -> None:
    if card.faces:
        if not card.layout or card.layout == "single-face":
            raise ValueError(f"Multi-face card {card.slug} must use a multi-face layout token")
        for face in card.faces:
            _validate_face(face, card.slug)
        return

    if card.layout != "single-face":
        raise ValueError(f"Single-face card {card.slug} must use layout 'single-face'")
    if card.mana is None or card.type_line is None or card.rules_text is None:
        raise ValueError(f"Single-face card {card.slug} is missing required sections")
    _validate_type_requirements(card.type_line, card.power, card.toughness, card.loyalty, card.slug)


def _validate_face(face: FaceModel, slug: str) -> None:
    if not face.name or not face.type_line:
        raise ValueError(f"Face in {slug} is missing a required name or type line")
    _validate_type_requirements(face.type_line, face.power, face.toughness, face.loyalty, slug, face.name)


def _validate_type_requirements(
    type_line: str,
    power: str | None,
    toughness: str | None,
    loyalty: str | None,
    slug: str,
    face_name: str | None = None,
) -> None:
    target = face_name or slug
    if "Creature" in type_line and (power is None or toughness is None):
        raise ValueError(f"{target} is a creature and must include a Stats section")
    if "Planeswalker" in type_line and loyalty is None:
        raise ValueError(f"{target} is a planeswalker and must include a Loyalty section")


def _render_face(index: int, face: FaceModel) -> list[str]:
    parts = [f"### Face {index}", "", "#### Name", face.name, ""]
    parts.extend(_render_mana_section("#### Mana Cost", face.mana))
    parts.extend(["#### Type Line", face.type_line, ""])
    parts.extend(_render_keywords_section(face.keywords, heading="#### Keywords"))
    parts.extend(["#### Rules Text", face.rules_text or "None", ""])

    if face.power is not None and face.toughness is not None:
        parts.extend(["#### Stats", f"- Power: {face.power}", f"- Toughness: {face.toughness}", ""])

    if face.loyalty is not None:
        parts.extend(["#### Loyalty", f"- Starting Loyalty: {face.loyalty}", ""])

    return parts


def _render_mana_section(heading: str, mana: ManaBreakdown) -> list[str]:
    return [
        heading,
        f"- Printed: {mana.printed}",
        f"- Generic: {mana.generic}",
        f"- White: {mana.white}",
        f"- Blue: {mana.blue}",
        f"- Black: {mana.black}",
        f"- Red: {mana.red}",
        f"- Green: {mana.green}",
        f"- Colorless: {mana.colorless}",
        f"- Hybrid: {_render_symbol_counts(mana.hybrid)}",
        f"- Phyrexian: {_render_symbol_counts(mana.phyrexian)}",
        f"- Variable: {_render_symbol_counts(mana.variable)}",
        f"- Snow: {mana.snow}",
        "",
    ]


def _render_keywords_section(keywords: list[str], heading: str = "## Keywords") -> list[str]:
    lines = [heading]
    if keywords:
        lines.extend(f"- {keyword}" for keyword in keywords)
    else:
        lines.append("- None")
    lines.append("")
    return lines


def _render_sets_section(set_names: list[str]) -> list[str]:
    lines = ["## Sets"]
    if set_names:
        lines.extend(f"- {set_name}" for set_name in _normalize_set_names(set_names))
    else:
        lines.append("- None")
    lines.append("")
    return lines


def _render_mana_token(token: str) -> str:
    if token.isdigit() or token in {"W", "U", "B", "R", "G", "C", "X", "Y", "Z", "S"}:
        return token
    if "/P" in token:
        return token
    if "/" in token:
        return f"({token})"
    return token


def _render_rule_symbol(token: str) -> str:
    token = token.upper()
    if token == "T":
        return "Tap"
    if token == "Q":
        return "Untap"
    return token


def _parse_sections(lines: list[str], expected_prefix: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for raw_line in lines:
        if raw_line.startswith(expected_prefix):
            current_section = raw_line[len(expected_prefix) :].strip()
            sections[current_section] = []
            continue
        if current_section is not None:
            sections[current_section].append(raw_line)
    return sections


def _parse_faces(lines: list[str]) -> list[FaceModel]:
    faces: list[list[str]] = []
    current: list[str] = []
    for raw_line in lines:
        if raw_line.startswith("### Face "):
            if current:
                faces.append(current)
            current = [raw_line]
            continue
        if current:
            current.append(raw_line)
    if current:
        faces.append(current)

    parsed: list[FaceModel] = []
    for face_block in faces:
        sections = _parse_sections(face_block[1:], expected_prefix="#### ")
        keywords = parse_keywords_section(sections.get("Keywords", []))
        stats = _parse_list_map(sections.get("Stats", []))
        loyalty_map = _parse_list_map(sections.get("Loyalty", []))
        parsed.append(
            FaceModel(
                name=_single_line(sections.get("Name", []), "Unknown Face"),
                mana=parse_mana_section(sections.get("Mana Cost", [])),
                type_line=_single_line(sections.get("Type Line", []), "None"),
                keywords=keywords,
                rules_text=_join_block(sections.get("Rules Text", [])) or "None",
                power=stats.get("Power"),
                toughness=stats.get("Toughness"),
                loyalty=loyalty_map.get("Starting Loyalty"),
            )
        )
    return parsed


def _parse_list_map(lines: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped.startswith("- ") or ":" not in stripped:
            continue
        key, value = stripped[2:].split(":", 1)
        mapping[key.strip()] = value.strip()
    return mapping


def _parse_symbol_counts(raw_value: str) -> dict[str, int]:
    if not raw_value or raw_value.strip().lower() == "none":
        return {}
    mapping: dict[str, int] = {}
    for piece in raw_value.split(","):
        piece = piece.strip()
        if not piece or ":" not in piece:
            continue
        key, value = piece.split(":", 1)
        mapping[key.strip()] = int(value.strip())
    return mapping


def _render_symbol_counts(mapping: dict[str, int]) -> str:
    if not mapping:
        return "none"
    return ", ".join(f"{key}: {value}" for key, value in sorted(mapping.items()))


def _join_block(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    return normalize_rules_text(text)


def _single_line(lines: list[str], default: str) -> str:
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped:
            return normalize_ascii(stripped)
    return default


def _normalize_set_names(set_names: list[str]) -> list[str]:
    normalized = [normalize_ascii(set_name.strip()) for set_name in set_names if set_name and set_name.strip()]
    return sorted(set(normalized), key=str.casefold)


def upsert_sets_section(markdown_text: str, set_names: list[str]) -> str:
    newline = "\r\n" if "\r\n" in markdown_text else "\n"
    has_trailing_newline = markdown_text.endswith(("\n", "\r\n"))
    lines = markdown_text.replace("\r\n", "\n").split("\n")

    if lines and lines[-1] == "":
        lines = lines[:-1]

    layout_index = _find_heading_index(lines, "## Layout")
    if layout_index == -1:
        raise ValueError("Card file is missing a Layout section")

    first_body_heading = _find_next_heading_index(lines, layout_index + 1, "## ")
    if first_body_heading == -1:
        first_body_heading = len(lines)

    next_heading_title = lines[first_body_heading] if first_body_heading < len(lines) else None
    rendered_set_lines = [f"- {set_name}" for set_name in _normalize_set_names(set_names)]
    if not rendered_set_lines:
        rendered_set_lines = ["- None"]
    set_block = ["## Sets", *rendered_set_lines, ""]

    if next_heading_title == "## Sets":
        end_index = _find_next_heading_index(lines, first_body_heading + 1, "## ")
        if end_index == -1:
            end_index = len(lines)
        new_lines = lines[:first_body_heading] + set_block + lines[end_index:]
    else:
        new_lines = lines[:first_body_heading] + set_block + lines[first_body_heading:]

    rendered = newline.join(new_lines)
    if has_trailing_newline:
        rendered += newline
    return rendered


def _find_heading_index(lines: list[str], heading: str) -> int:
    for index, line in enumerate(lines):
        if line == heading:
            return index
    return -1


def _find_next_heading_index(lines: list[str], start_index: int, prefix: str) -> int:
    for index in range(start_index, len(lines)):
        if lines[index].startswith(prefix):
            return index
    return -1


def normalize_ascii(text: str) -> str:
    return (
        text.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("paths", nargs="*", help="Files or directories to lint")
    parser.add_argument("--check", action="store_true", help="Report formatting drift without rewriting files")
    return parser