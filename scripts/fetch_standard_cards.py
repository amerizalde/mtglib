from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mtglib_contract import CardModel, card_model_from_scryfall, render_card, upsert_sets_section


STANDARD_URL = "https://magic.wizards.com/en/formats/standard"
SCRYFALL_SEARCH_URL = "https://api.scryfall.com/cards/search"
USER_AGENT = "mtglib-fetcher/1.0"
MAX_RETRIES = 5


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if cleaned:
            self.parts.append(cleaned)


def fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; mtglib-fetcher/1.0)",
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        },
    )
    for attempt in range(MAX_RETRIES):
        try:
            with urlopen(request) as response:  # noqa: S310
                return response.read().decode("utf-8")
        except HTTPError as error:
            if error.code != 429 or attempt == MAX_RETRIES - 1:
                raise
            retry_after = error.headers.get("Retry-After") if error.headers else None
            delay_seconds = float(retry_after) if retry_after else float(2 ** attempt)
            time.sleep(delay_seconds)

    raise RuntimeError(f"Failed to fetch {url}")


def fetch_json(url: str) -> dict[str, Any]:
    return json.loads(fetch_text(url))


def scrape_standard_set_names() -> list[str]:
    parser = _TextExtractor()
    parser.feed(fetch_text(STANDARD_URL))
    lines = parser.parts

    try:
        start = lines.index("What Sets Are Legal in Standard?") + 1
    except ValueError as error:
        raise RuntimeError("Could not find the Standard set list on the Wizards page") from error

    end_markers = {"Different Ways to Play", "Discover More MTG", "Latest Products"}
    set_names: list[str] = []
    for line in lines[start:]:
        if line in end_markers:
            break
        if not line:
            continue
        set_names.append(line)

    if not set_names:
        raise RuntimeError("Standard set scrape returned an empty list")
    return set_names


def normalized_set_aliases(set_names: list[str]) -> set[str]:
    aliases: set[str] = set()
    for set_name in set_names:
        aliases.add(_normalize_set_name(set_name))

        no_paren = re.sub(r"\s*\([^)]*\)", "", set_name).strip()
        if no_paren:
            aliases.add(_normalize_set_name(no_paren))

        parenthetical = re.findall(r"\(([^)]*)\)", set_name)
        for item in parenthetical:
            aliases.add(_normalize_set_name(item.replace("including", "").strip()))

        if "|" in set_name:
            aliases.add(_normalize_set_name(set_name.split("|", 1)[1].strip()))

    return {alias for alias in aliases if alias}


def fetch_standard_cards(today: dt.date, allowed_set_aliases: set[str], set_code: str | None = None) -> list[CardModel]:
    query = "game:paper legal:standard"
    if set_code:
        query = f"set:{set_code.lower()}"
    params = urlencode({"q": query, "unique": "prints", "order": "name"})
    next_url = f"{SCRYFALL_SEARCH_URL}?{params}"

    canonical_cards: dict[str, dict[str, Any]] = {}
    card_sets: dict[str, set[str]] = defaultdict(set)

    while next_url:
        payload = fetch_json(next_url)
        for card in payload.get("data", []):
            if set_code is None and card.get("digital"):
                continue
            if set_code is None and "paper" not in card.get("games", []):
                continue
            if set_code is None and card.get("legalities", {}).get("standard") != "legal":
                continue
            released_at = dt.date.fromisoformat(card["released_at"])
            if released_at > today:
                continue

            alias = _normalize_set_name(card.get("set_name", ""))
            if set_code is None and allowed_set_aliases and alias not in allowed_set_aliases:
                continue

            oracle_id = card.get("oracle_id") or card.get("id")
            card_sets[oracle_id].add(card.get("set_name", ""))
            if oracle_id not in canonical_cards:
                canonical_cards[oracle_id] = card

        next_url = payload.get("next_page")

    if not canonical_cards:
        if set_code:
            raise RuntimeError(f"No paper cards were returned for set {set_code.lower()}")
        raise RuntimeError("No current Standard-legal paper cards were returned")
    cards = [
        card_model_from_scryfall(card, set_names=sorted(card_sets[oracle_id], key=str.casefold))
        for oracle_id, card in canonical_cards.items()
    ]
    return sorted(cards, key=lambda item: item.slug)


def write_cards(cards: list[CardModel], output_dir: Path, dry_run: bool, limit: int | None, sync_pool: bool) -> tuple[int, list[str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = cards[:limit] if limit else cards
    written_slugs: list[str] = []
    count = 0

    for model in selected:
        output_path = output_dir / f"{model.slug}.md"
        written_slugs.append(model.slug)
        if not dry_run:
            if output_path.exists():
                existing_text = output_path.read_text(encoding="utf-8")
                updated_text = upsert_sets_section(existing_text, model.sets)
                if updated_text != existing_text:
                    output_path.write_text(updated_text, encoding="utf-8")
            else:
                output_path.write_text(render_card(model), encoding="utf-8")
        count += 1

    if not dry_run and sync_pool and limit is None:
        _remove_stale_markdown_files(output_dir, set(written_slugs))

    return count, written_slugs


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the MTGLib card pool into Markdown files from the current Standard pool or an explicit set.")
    parser.add_argument(
        "--cards-dir",
        default=str(Path(__file__).resolve().parent.parent / "cards"),
        help="Directory where Markdown card files should be written.",
    )
    parser.add_argument("--today", default=dt.date.today().isoformat(), help="Reference date in YYYY-MM-DD format.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N cards after filtering. Partial runs do not delete stale files.",
    )
    parser.add_argument(
        "--set-code",
        default=None,
        help="Optional Scryfall set code to fetch as a paper-card set import instead of the default Standard-pool sync.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and render metadata without writing files.")
    args = parser.parse_args()

    today = dt.date.fromisoformat(args.today)
    cards_dir = Path(args.cards_dir)

    try:
        set_names = scrape_standard_set_names()
        allowed_aliases = normalized_set_aliases(set_names)
        cards = fetch_standard_cards(today=today, allowed_set_aliases=allowed_aliases, set_code=args.set_code)
        written_count, written_slugs = write_cards(
            cards,
            cards_dir,
            dry_run=args.dry_run,
            limit=args.limit,
            sync_pool=args.set_code is None,
        )
    except Exception as error:  # noqa: BLE001
        print(f"Fetch failed: {error}", file=sys.stderr)
        return 1

    mode = "Would write" if args.dry_run else "Wrote"
    scope = f"paper cards from set {args.set_code.lower()}" if args.set_code else "Standard-legal cards"
    print(f"{mode} {written_count} {scope} into {cards_dir}")
    for slug in written_slugs[:10]:
        print(f"- {slug}")
    if written_count > 10:
        print(f"... and {written_count - 10} more")
    return 0


def _normalize_set_name(value: str) -> str:
    normalized = value.lower()
    normalized = normalized.replace("\u2014", " ").replace("\u2013", " ")
    normalized = normalized.replace("\u00ae", " ").replace("\u2122", " ")
    normalized = normalized.replace("magic: the gathering", " ")
    normalized = normalized.replace("magic the gathering", " ")
    normalized = normalized.replace("|", " ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _remove_stale_markdown_files(output_dir: Path, valid_slugs: set[str]) -> None:
    for existing_path in output_dir.glob("*.md"):
        if existing_path.stem not in valid_slugs:
            existing_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())