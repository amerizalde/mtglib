from __future__ import annotations

from pathlib import Path
import json

from .models import GeneratedDeck


class DeckStore:
    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path

    def list_decks(self) -> list[GeneratedDeck]:
        if not self._storage_path.exists():
            return []
        payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        return [GeneratedDeck.model_validate(item) for item in payload]

    def get_deck(self, deck_id: str) -> GeneratedDeck | None:
        for deck in self.list_decks():
            if deck.id == deck_id:
                return deck
        return None

    def save_deck(self, deck: GeneratedDeck) -> GeneratedDeck:
        decks = self.list_decks()
        updated: list[GeneratedDeck] = []
        replaced = False
        for current in decks:
            if current.id == deck.id:
                updated.append(deck)
                replaced = True
            else:
                updated.append(current)
        if not replaced:
            updated.append(deck)
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = [item.model_dump(mode="json") for item in sorted(updated, key=lambda deck_item: deck_item.updated_at, reverse=True)]
        self._storage_path.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
        return deck