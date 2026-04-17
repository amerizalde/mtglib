import { startTransition, useDeferredValue, useEffect, useState } from "react";
import { Link, NavLink, Outlet, Route, Routes, useNavigate, useParams } from "react-router-dom";

import { generateDecks, getCard, getMeta, getSavedDeck, listCards, listSavedDecks, saveDeck } from "./api";
import type {
  CardDetailResponse,
  CardEntity,
  CardListResponse,
  GeneratedDeck,
  GenerationCandidate,
  GenerationRequest,
  GenerationResponse,
  MetaResponse,
  SavedDeckSummary
} from "./types";

const defaultGenerationRequest: GenerationRequest = {
  colors: ["G"],
  required_slugs: [],
  excluded_slugs: [],
  preferred_tags: ["counters"],
  preferred_roles: ["mana_dork"],
  target_tempo: "medium",
  target_novelty: 0.55,
  min_lands: 21,
  max_cards: 60,
  allow_splash: false,
  candidate_count: 3
};

export function App() {
  return (
    <Routes>
      <Route element={<DashboardShell />}>
        <Route index element={<HomePage />} />
        <Route path="/cards" element={<CardsPage />} />
        <Route path="/cards/:slug" element={<CardDetailPage />} />
        <Route path="/generate" element={<GeneratePage />} />
        <Route path="/saved" element={<SavedDecksPage />} />
        <Route path="/decks/:deckId" element={<DeckDetailPage />} />
        <Route path="/analysis/:deckId" element={<AnalysisPage />} />
        <Route path="/about" element={<AboutPage />} />
      </Route>
    </Routes>
  );
}

function DashboardShell() {
  return (
    <div className="app-shell">
      <div className="aurora aurora-left" />
      <div className="aurora aurora-right" />
      <aside className="sidebar">
        <div>
          <p className="eyebrow">MTGLib</p>
          <h1>Deck Studio</h1>
          <p className="sidebar-copy">A local-corpus deck lab for browsing cards, comparing generated shells, and keeping score rationale readable.</p>
        </div>
        <nav className="nav-list">
          <NavItem to="/">Home</NavItem>
          <NavItem to="/cards">Cards</NavItem>
          <NavItem to="/generate">Generate</NavItem>
          <NavItem to="/saved">Saved</NavItem>
          <NavItem to="/about">About</NavItem>
        </nav>
      </aside>
      <main className="content-panel">
        <Outlet />
      </main>
    </div>
  );
}

function NavItem({ to, children }: { to: string; children: string }) {
  return (
    <NavLink to={to} className={({ isActive }) => `nav-item${isActive ? " nav-item-active" : ""}`}>
      {children}
    </NavLink>
  );
}

function HomePage() {
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [savedDecks, setSavedDecks] = useState<SavedDeckSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getMeta(), listSavedDecks()])
      .then(([metaPayload, savedPayload]) => {
        if (cancelled) {
          return;
        }
        setMeta(metaPayload);
        setSavedDecks(savedPayload.items.slice(0, 4));
      })
      .catch((reason: Error) => {
        if (!cancelled) {
          setError(reason.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="page-grid">
      <section className="hero-card card">
        <p className="eyebrow">Local corpus dashboard</p>
        <h2>Compare ranked shells before you commit to a deck.</h2>
        <p className="lede">The frontend now assumes `/api/generate` returns multiple ranked candidates, so the main workflow is comparison-first rather than reroll-first.</p>
        <div className="hero-actions">
          <Link to="/generate" className="button button-primary">Open Generator</Link>
          <Link to="/cards" className="button button-secondary">Browse Cards</Link>
        </div>
      </section>
      <section className="stat-grid">
        <InfoCard title="Corpus Version" value={meta?.corpus_version ?? "Loading"} />
        <InfoCard title="Cards Indexed" value={meta ? String(meta.card_count) : "..."} />
        <InfoCard title="Saved Decks" value={String(savedDecks.length)} />
      </section>
      <section className="card">
        <div className="section-header">
          <h3>Top Theme Signals</h3>
          <span className="muted">From corpus metadata</span>
        </div>
        <div className="chip-row">
          {Object.entries(meta?.tag_distributions.tags ?? {})
            .sort((left, right) => right[1] - left[1])
            .slice(0, 8)
            .map(([tag, count]) => (
              <span key={tag} className="chip">{tag} · {count}</span>
            ))}
        </div>
        {error ? <p className="error-text">{error}</p> : null}
      </section>
      <section className="card">
        <div className="section-header">
          <h3>Recent Decks</h3>
          <Link to="/saved" className="text-link">View all</Link>
        </div>
        <div className="stack-list">
          {savedDecks.length === 0 ? <p className="muted">No saved decks yet.</p> : null}
          {savedDecks.map((deck) => (
            <Link key={deck.id} to={`/decks/${deck.id}`} className="list-row link-row">
              <div>
                <strong>{deck.name}</strong>
                <p className="muted">{deck.primary_plan_tags.join(", ") || "No plan tags yet"}</p>
              </div>
              <span className="pill">{deck.overall_score.toFixed(1)}</span>
            </Link>
          ))}
        </div>
      </section>
    </section>
  );
}

function CardsPage() {
  const [query, setQuery] = useState("");
  const [selectedColor, setSelectedColor] = useState("");
  const [cardResponse, setCardResponse] = useState<CardListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    let cancelled = false;
    listCards({ q: deferredQuery, colors: selectedColor, pageSize: "18" })
      .then((payload) => {
        if (!cancelled) {
          setCardResponse(payload);
        }
      })
      .catch((reason: Error) => {
        if (!cancelled) {
          setError(reason.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [deferredQuery, selectedColor]);

  return (
    <section className="page-grid">
      <section className="card filter-card">
        <div className="section-header">
          <h2>Card Browser</h2>
          <span className="muted">Searchable local corpus</span>
        </div>
        <div className="toolbar">
          <input
            className="text-input"
            value={query}
            onChange={(event) => {
              const nextValue = event.target.value;
              startTransition(() => setQuery(nextValue));
            }}
            placeholder="Search by name, rule text, or tag"
          />
          <div className="chip-row">
            {["", "W", "U", "B", "R", "G"].map((color) => (
              <button
                key={color || "all"}
                type="button"
                className={`chip-button${selectedColor === color ? " chip-button-active" : ""}`}
                onClick={() => startTransition(() => setSelectedColor(color))}
              >
                {color || "All colors"}
              </button>
            ))}
          </div>
        </div>
      </section>
      <section className="card">
        <div className="section-header">
          <h3>Results</h3>
          <span className="muted">{cardResponse?.total ?? 0} matches</span>
        </div>
        {error ? <p className="error-text">{error}</p> : null}
        <div className="results-grid">
          {cardResponse?.items.map((card) => (
            <Link key={card.slug} to={`/cards/${card.slug}`} className="result-card">
              <p className="eyebrow">{card.colors.join("/") || "Colorless"}</p>
              <h4>{card.display_name}</h4>
              <p className="muted">{card.type_line}</p>
              <p className="rules-snippet">{card.rules_text}</p>
            </Link>
          ))}
        </div>
      </section>
    </section>
  );
}

function CardDetailPage() {
  const { slug = "" } = useParams();
  const [detail, setDetail] = useState<CardDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCard(slug)
      .then((payload) => {
        if (!cancelled) {
          setDetail(payload);
        }
      })
      .catch((reason: Error) => {
        if (!cancelled) {
          setError(reason.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  if (error) {
    return <section className="card"><p className="error-text">{error}</p></section>;
  }

  if (!detail) {
    return <section className="card"><p className="muted">Loading card detail...</p></section>;
  }

  return (
    <section className="page-grid">
      <section className="card">
        <p className="eyebrow">{detail.card.colors.join("/") || "Colorless"}</p>
        <h2>{detail.card.display_name}</h2>
        <p className="muted">{detail.card.type_line}</p>
        <p className="detail-rules">{detail.card.rules_text}</p>
        <div className="chip-row">
          {detail.card.role_tags.map((tag) => <span key={tag} className="chip">{tag}</span>)}
          {detail.card.synergy_tags.map((tag) => <span key={tag} className="chip chip-alt">{tag}</span>)}
        </div>
      </section>
      <section className="card">
        <div className="section-header">
          <h3>Related Cards</h3>
          <span className="muted">Tag and role overlap</span>
        </div>
        <div className="stack-list">
          {detail.related_cards.map((related) => (
            <Link key={related.slug} to={`/cards/${related.slug}`} className="list-row link-row">
              <div>
                <strong>{related.display_name}</strong>
                <p className="muted">{related.shared_tags.join(", ") || related.shared_roles.join(", ")}</p>
              </div>
              <span className="pill">{related.overlap_score.toFixed(1)}</span>
            </Link>
          ))}
        </div>
      </section>
    </section>
  );
}

function GeneratePage() {
  const navigate = useNavigate();
  const [request, setRequest] = useState<GenerationRequest>(defaultGenerationRequest);
  const [response, setResponse] = useState<GenerationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingDeckId, setSavingDeckId] = useState<string | null>(null);

  async function handleGenerate() {
    setError(null);
    try {
      const payload = await generateDecks(request);
      setResponse(payload);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to generate candidates");
    }
  }

  async function handleSave(deck: GeneratedDeck) {
    setSavingDeckId(deck.id);
    try {
      const saved = await saveDeck(deck);
      navigate(`/decks/${saved.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to save deck");
    } finally {
      setSavingDeckId(null);
    }
  }

  return (
    <section className="page-grid generate-layout">
      <section className="card control-card">
        <div className="section-header">
          <h2>Generate Ranked Candidates</h2>
          <span className="muted">Comparison-first workflow</span>
        </div>
        <div className="form-grid">
          <label>
            Colors
            <input
              className="text-input"
              value={request.colors.join(",")}
              onChange={(event) => setRequest({ ...request, colors: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) as GenerationRequest["colors"] })}
            />
          </label>
          <label>
            Preferred tags
            <input
              className="text-input"
              value={request.preferred_tags.join(",")}
              onChange={(event) => setRequest({ ...request, preferred_tags: splitCsv(event.target.value) })}
            />
          </label>
          <label>
            Preferred roles
            <input
              className="text-input"
              value={request.preferred_roles.join(",")}
              onChange={(event) => setRequest({ ...request, preferred_roles: splitCsv(event.target.value) })}
            />
          </label>
          <label>
            Required cards
            <input
              className="text-input"
              value={request.required_slugs.join(",")}
              onChange={(event) => setRequest({ ...request, required_slugs: splitCsv(event.target.value) })}
            />
          </label>
          <label>
            Excluded cards
            <input
              className="text-input"
              value={request.excluded_slugs.join(",")}
              onChange={(event) => setRequest({ ...request, excluded_slugs: splitCsv(event.target.value) })}
            />
          </label>
          <label>
            Tempo
            <select className="text-input" value={request.target_tempo} onChange={(event) => setRequest({ ...request, target_tempo: event.target.value as GenerationRequest["target_tempo"] })}>
              <option value="fast">fast</option>
              <option value="medium">medium</option>
              <option value="slow">slow</option>
            </select>
          </label>
          <label>
            Novelty target
            <input className="text-input" type="range" min="0" max="1" step="0.05" value={request.target_novelty} onChange={(event) => setRequest({ ...request, target_novelty: Number(event.target.value) })} />
            <span className="muted">{request.target_novelty.toFixed(2)}</span>
          </label>
          <label>
            Candidate count
            <input className="text-input" type="number" min="1" max="8" value={request.candidate_count} onChange={(event) => setRequest({ ...request, candidate_count: Number(event.target.value) })} />
          </label>
        </div>
        <button type="button" className="button button-primary" onClick={handleGenerate}>Generate</button>
        {error ? <p className="error-text">{error}</p> : null}
      </section>
      <section className="card candidates-card">
        <div className="section-header">
          <h3>Ranked Outputs</h3>
          <span className="muted">{response?.candidate_count ?? 0} candidates</span>
        </div>
        <div className="stack-list">
          {response?.candidates.map((candidate) => (
            <CandidateCard key={candidate.deck.id} candidate={candidate} onSave={handleSave} savingDeckId={savingDeckId} />
          ))}
          {!response ? <p className="muted">Run the generator to compare ranked decks.</p> : null}
        </div>
      </section>
    </section>
  );
}

function CandidateCard({ candidate, onSave, savingDeckId }: { candidate: GenerationCandidate; onSave: (deck: GeneratedDeck) => void; savingDeckId: string | null }) {
  return (
    <article className="candidate-card">
      <div className="section-header">
        <div>
          <p className="eyebrow">Rank {candidate.rank}</p>
          <h4>{candidate.deck.name}</h4>
          <p className="muted">{candidate.label}</p>
        </div>
        <div className="score-cluster">
          <span className="score-value">{candidate.deck.score.overall.toFixed(1)}</span>
          <span className="pill">Novelty {candidate.deck.score.novelty.toFixed(1)}</span>
        </div>
      </div>
      <p>{candidate.deck.summary}</p>
      <div className="chip-row">
        {candidate.focus_tags.map((tag) => <span key={tag} className="chip">{tag}</span>)}
        {candidate.focus_roles.map((role) => <span key={role} className="chip chip-alt">{role}</span>)}
      </div>
      <div className="metric-row">
        <Metric label="Tempo" value={candidate.deck.score.tempo} />
        <Metric label="Synergy" value={candidate.deck.score.synergy} />
        <Metric label="Mana" value={candidate.deck.score.mana} />
      </div>
      <div className="hero-actions">
        <Link to={`/analysis/${candidate.deck.id}`} className="button button-secondary">Inspect</Link>
        <button type="button" className="button button-primary" onClick={() => onSave(candidate.deck)} disabled={savingDeckId === candidate.deck.id}>
          {savingDeckId === candidate.deck.id ? "Saving..." : "Save deck"}
        </button>
      </div>
    </article>
  );
}

function SavedDecksPage() {
  const [items, setItems] = useState<SavedDeckSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listSavedDecks()
      .then((payload) => {
        if (!cancelled) {
          setItems(payload.items);
        }
      })
      .catch((reason: Error) => {
        if (!cancelled) {
          setError(reason.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="card">
      <div className="section-header">
        <h2>Saved Decks</h2>
        <span className="muted">Local storage-backed</span>
      </div>
      {error ? <p className="error-text">{error}</p> : null}
      <div className="stack-list">
        {items.map((deck) => (
          <Link key={deck.id} to={`/decks/${deck.id}`} className="list-row link-row">
            <div>
              <strong>{deck.name}</strong>
              <p className="muted">{deck.colors.join("/") || "Open"} · {deck.primary_plan_tags.join(", ") || "No tags"}</p>
            </div>
            <span className="pill">{deck.overall_score.toFixed(1)}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

function DeckDetailPage() {
  const { deckId = "" } = useParams();
  const [deck, setDeck] = useState<GeneratedDeck | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSavedDeck(deckId)
      .then((payload) => {
        if (!cancelled) {
          setDeck(payload);
        }
      })
      .catch((reason: Error) => {
        if (!cancelled) {
          setError(reason.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [deckId]);

  if (error) {
    return <section className="card"><p className="error-text">{error}</p></section>;
  }

  if (!deck) {
    return <section className="card"><p className="muted">Loading deck...</p></section>;
  }

  return (
    <section className="page-grid">
      <section className="card">
        <p className="eyebrow">Deck detail</p>
        <h2>{deck.name}</h2>
        <p>{deck.explanations.summary}</p>
        <div className="metric-row">
          <Metric label="Overall" value={deck.score.overall} />
          <Metric label="Tempo" value={deck.score.tempo} />
          <Metric label="Novelty" value={deck.score.novelty} />
        </div>
        <Link to={`/analysis/${deck.id}`} className="button button-secondary">Open analysis</Link>
      </section>
      <section className="card">
        <div className="section-header">
          <h3>Main Deck</h3>
          <span className="muted">{deck.card_count} cards</span>
        </div>
        <div className="stack-list compact-list">
          {deck.cards.map((card) => (
            <div key={card.slug} className="list-row">
              <div>
                <strong>{card.quantity}× {card.display_name}</strong>
                <p className="muted">{card.type_line}</p>
              </div>
              <span className="pill">MV {card.mana_value}</span>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}

function AnalysisPage() {
  const { deckId = "" } = useParams();
  const [deck, setDeck] = useState<GeneratedDeck | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSavedDeck(deckId)
      .then((payload) => {
        if (!cancelled) {
          setDeck(payload);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDeck(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [deckId]);

  if (!deck) {
    return <section className="card"><p className="muted">Save a deck first to inspect analysis.</p></section>;
  }

  return (
    <section className="card">
      <div className="section-header">
        <h2>Score Analysis</h2>
        <span className="muted">{deck.name}</span>
      </div>
      <div className="analysis-grid">
        <Metric label="Constraint" value={deck.score.constraint} />
        <Metric label="Tempo" value={deck.score.tempo} />
        <Metric label="Synergy" value={deck.score.synergy} />
        <Metric label="Interaction" value={deck.score.interaction} />
        <Metric label="Resilience" value={deck.score.resilience} />
        <Metric label="Mana" value={deck.score.mana} />
        <Metric label="Novelty" value={deck.score.novelty} />
        <Metric label="Game Theory" value={deck.score.game_theory} />
      </div>
      <div className="stack-list">
        {deck.explanations.replacement_notes.map((note) => (
          <p key={note} className="list-row">{note}</p>
        ))}
      </div>
    </section>
  );
}

function AboutPage() {
  return (
    <section className="card prose-card">
      <p className="eyebrow">Methodology</p>
      <h2>How this deck studio thinks</h2>
      <p>The frontend stays thin. The FastAPI service parses the Markdown corpus, extracts features, scores generated lists, and returns ranked candidates so the browser can focus on comparison and inspection.</p>
      <p>The current implementation emphasizes deterministic candidate generation, readable score axes, and a browser-native workflow over heavyweight client-side logic.</p>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric-card">
      <span className="muted">{label}</span>
      <strong>{value.toFixed(1)}</strong>
    </div>
  );
}

function InfoCard({ title, value }: { title: string; value: string }) {
  return (
    <article className="metric-card">
      <span className="muted">{title}</span>
      <strong>{value}</strong>
    </article>
  );
}

function splitCsv(rawValue: string): string[] {
  return rawValue.split(",").map((value) => value.trim()).filter(Boolean);
}