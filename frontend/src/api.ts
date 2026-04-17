import type {
  CardDetailResponse,
  CardListResponse,
  GeneratedDeck,
  GenerationRequest,
  GenerationResponse,
  MetaResponse,
  SavedDeckListResponse
} from "./types";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    const message = typeof payload?.detail === "string" ? payload.detail : response.statusText;
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export async function getMeta(): Promise<MetaResponse> {
  return parseResponse(await fetch("/api/meta"));
}

export async function listCards(searchParams: Record<string, string>): Promise<CardListResponse> {
  const params = new URLSearchParams(searchParams);
  return parseResponse(await fetch(`/api/cards?${params.toString()}`));
}

export async function getCard(slug: string): Promise<CardDetailResponse> {
  return parseResponse(await fetch(`/api/cards/${slug}`));
}

export async function generateDecks(request: GenerationRequest): Promise<GenerationResponse> {
  return parseResponse(
    await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request)
    })
  );
}

export async function listSavedDecks(): Promise<SavedDeckListResponse> {
  return parseResponse(await fetch("/api/decks"));
}

export async function getSavedDeck(deckId: string): Promise<GeneratedDeck> {
  return parseResponse(await fetch(`/api/decks/${deckId}`));
}

export async function saveDeck(deck: GeneratedDeck): Promise<GeneratedDeck> {
  return parseResponse(
    await fetch("/api/decks/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deck })
    })
  );
}