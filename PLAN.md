## Plan: Standard Deck Builder Spec

Build a separate webapp on top of MTGLib's Markdown corpus that parses the local Standard snapshot in `f:/workspace/mtglib/cards/`, derives structured deck-building features, and recommends novel but strategically coherent 60-card decks. Recommended architecture: React + TypeScript + Vite frontend for the webapp shell and interaction model, plus a thin local FastAPI service for parsing, indexing, scoring, and deck generation. This keeps the MTGLib library separate, makes scoring transparent, and avoids pushing heavier recommendation logic into the browser.

**Steps**
1. Phase 1 - Indexing service: parse the MTGLib Markdown contract from `f:/workspace/mtglib/cards/`, normalize cards into structured entities, extract features, and publish a versioned in-memory index plus JSON cache. This blocks all other phases.
2. Phase 2 - Recommendation engine: implement deterministic heuristics for role tagging, synergy extraction, pattern clustering, and deck construction, then expose generation and rescore APIs. This depends on step 1.
3. Phase 3 - Webapp shell: implement card exploration, concept seeding, deck generation, deck editing, and score explanation routes against the local service. This depends on step 2 for live data, though route scaffolding can start earlier.
4. Phase 4 - Validation: test parser correctness, legality constraints, scoring stability, and UX flows for lock/swap/regenerate. This depends on steps 1 through 3.

**Concrete App Spec**

**Architecture**
- Frontend: React 19 + TypeScript + Vite, following the general workspace pattern used by `f:/workspace/iterative-visual-loop/package.json`.
- Backend: FastAPI service in Python for corpus parsing, feature extraction, deck generation, and explanation APIs.
- Source of truth: the MTGLib Markdown corpus in `f:/workspace/mtglib/cards/`.
- Legal pool boundary: all cards currently present in `cards/`; no live legality lookup at runtime.
- Persistence: local JSON files for saved decks and cached card index; no database required for v1.
- Recommendation style: deterministic heuristics first, optional ML or embeddings later.

**Frontend routes**
1. `/` - Home / Idea Seed
Description: Landing page that explains the app and offers quick-start inputs: colors, preferred tempo, theme tags, required cards, excluded cards, and novelty tolerance.
Primary actions: Generate deck, browse pool, open saved deck.
Data needed: format snapshot metadata, top themes, recent saved decks.

2. `/cards` - Card Browser
Description: Searchable and filterable Standard card browser.
Filters: colors, mana value, card type, land/nonland, keywords, inferred role tags, inferred synergy tags, novelty contribution band.
Data needed: paginated normalized card summaries and aggregate filter counts.

3. `/cards/:slug` - Card Detail
Description: Full normalized card view with face-aware rendering, role tags, synergy tags, and score contributions.
Data needed: full card entity, extracted features, related cards by synergy overlap.

4. `/generate` - Deck Generator
Description: Main generation workflow where the user specifies constraints and receives one or more deck candidates.
Inputs: locked cards, excluded cards, desired colors, desired archetype posture, target novelty, target tempo band.
Outputs: ranked candidate decks with explanations.

5. `/decks/:deckId` - Deck Detail / Editor
Description: View and edit a generated or saved deck, lock cards, swap cards, regenerate around shell, inspect mana curve and score breakdowns.
Data needed: deck entity, validation result, candidate replacements, explanation payload.

6. `/analysis/:deckId` - Deep Score Analysis
Description: Detailed breakdown of the deck's novelty, tempo, game-theory, synergy, and constraint scores, including contribution by card and by cluster.
Data needed: score vector, feature aggregates, explanation traces.

7. `/saved` - Saved Decks
Description: Local list of saved/generated decks with quick metadata and reopen/export actions.
Data needed: saved deck summaries.

8. `/about` - Methodology
Description: Explains how the app parses MTGLib, what constraints it enforces, and how novelty/tempo/game-theory scores are computed.
Data needed: static methodology and current corpus snapshot metadata.

**API routes**
1. `GET /api/health`
Returns service status and current card-index version.

2. `GET /api/meta`
Returns corpus version, card count, last index time, supported filters, and top-level tag distributions.

3. `GET /api/cards`
Query params: `q`, `colors`, `types`, `roles`, `tags`, `manaValueMin`, `manaValueMax`, `isLand`, `page`, `pageSize`.
Returns paginated normalized card summaries.

4. `GET /api/cards/{slug}`
Returns one full normalized card plus extracted features and related-card suggestions.

5. `POST /api/generate`
Request body: generation constraints and preferences.
Returns ranked deck candidates with full explanation objects.

6. `POST /api/decks/score`
Request body: a deck list or deck draft.
Returns validation status, score vector, warnings, and improvement suggestions.

7. `POST /api/decks/swap`
Request body: deck id or deck draft, slot to replace, locked cards, optional target constraints.
Returns replacement candidates and rescored deck variants.

8. `POST /api/decks/save`
Request body: deck entity.
Returns saved deck metadata.

9. `GET /api/decks/{deckId}`
Returns a saved deck and its latest score snapshot.

10. `GET /api/decks`
Returns saved deck summaries.

**Core data model**

**Card**
- `slug: string`
- `display_name: string`
- `canonical_name: string`
- `layout: 'single-face' | 'transform' | 'split' | 'adventure' | 'modal-dfc' | 'other'`
- `sets: string[]`
- `faces: CardFace[]`
- `type_line: string`
- `supertypes: string[]`
- `types: string[]`
- `subtypes: string[]`
- `mana_cost: ManaCost`
- `mana_value: number`
- `colors: Color[]`
- `color_identity: Color[]`
- `keywords: string[]`
- `rules_text: string`
- `stats?: { power: string, toughness: string }`
- `loyalty?: string`
- `is_land: boolean`
- `is_basic_land: boolean`
- `produces_mana: Color[]`
- `feature_vector: CardFeatureVector`
- `role_tags: RoleTag[]`
- `synergy_tags: SynergyTag[]`
- `tempo_profile: TempoProfile`
- `novelty_baseline_score: number`

**CardFace**
- `name: string`
- `mana_cost: ManaCost`
- `type_line: string`
- `keywords: string[]`
- `rules_text: string`
- `stats?: { power: string, toughness: string }`
- `loyalty?: string`
- `colors: Color[]`
- `types: string[]`
- `subtypes: string[]`

**ManaCost**
- `printed: string`
- `generic: number`
- `white: number`
- `blue: number`
- `black: number`
- `red: number`
- `green: number`
- `colorless: number`
- `hybrid: Record<string, number>`
- `phyrexian: Record<string, number>`
- `variable: Record<string, number>`
- `snow: number`

**CardFeatureVector**
- `mana_value_bucket: 0 | 1 | 2 | 3 | 4 | 5 | 6`
- `is_creature: boolean`
- `is_interaction: boolean`
- `is_removal: boolean`
- `is_card_draw: boolean`
- `is_selection: boolean`
- `is_ramp: boolean`
- `is_fixing: boolean`
- `is_token_maker: boolean`
- `is_recursion: boolean`
- `is_sweeper: boolean`
- `is_counterspell: boolean`
- `is_combat_trick: boolean`
- `is_engine_piece: boolean`
- `is_payoff: boolean`
- `is_enabler: boolean`
- `board_immediacy: number` from 0 to 1
- `resource_velocity: number` from 0 to 1
- `resilience: number` from 0 to 1
- `synergy_density: number` from 0 to 1

**RoleTag**
- Examples: `one_drop_pressure`, `cheap_removal`, `mana_dork`, `card_selection`, `top_end_finisher`, `sweeper`, `engine`, `tempo_bounce`, `graveyard_enabler`, `token_payoff`, `stabilizer`.

**SynergyTag**
- Examples: `artifacts`, `enchantments`, `tokens`, `counters`, `sacrifice`, `graveyard`, `spellslinger`, `go_wide`, `lifegain`, `legendary`, `landfall`, `draw_second`, `tribal:<subtype>`.

**DeckCard**
- `slug: string`
- `quantity: number`
- `zone: 'main'`
- `locked: boolean`
- `reason_codes: string[]`

**Deck**
- `id: string`
- `name: string`
- `format: 'standard'`
- `created_at: string`
- `updated_at: string`
- `cards: DeckCard[]`
- `land_count: number`
- `nonland_count: number`
- `color_profile: Record<Color, number>`
- `mana_curve: Record<number, number>`
- `primary_plan_tags: SynergyTag[]`
- `score: DeckScore`
- `explanations: DeckExplanation`
- `validation: DeckValidation`
- `seed_request: GenerationRequest`

**GenerationRequest**
- `colors?: Color[]`
- `required_slugs?: string[]`
- `excluded_slugs?: string[]`
- `preferred_tags?: SynergyTag[]`
- `preferred_roles?: RoleTag[]`
- `target_tempo?: 'fast' | 'medium' | 'slow'`
- `target_novelty?: number` from 0 to 1
- `min_lands?: number` default 21
- `max_cards?: number` default 60
- `allow_splash?: boolean`
- `candidate_count?: number`

**DeckScore**
- `overall: number`
- `constraint: number`
- `tempo: number`
- `synergy: number`
- `interaction: number`
- `resilience: number`
- `mana: number`
- `novelty: number`
- `game_theory: number`

**DeckValidation**
- `is_valid: boolean`
- `errors: string[]`
- `warnings: string[]`
- `card_count: number`
- `land_count: number`
- `off_color_count: number`

**DeckExplanation**
- `summary: string`
- `core_plan: string`
- `novel_angle: string`
- `tempo_story: string`
- `key_synergies: string[]`
- `card_reasons: Record<string, string[]>`
- `replacement_notes: string[]`

**Feature extraction rules**
- Infer `colors` from mana-cost color counts and mana symbols in face costs.
- Infer `produces_mana` from regex over rules text such as `Add W`, `Add U`, `Add B`, `Add R`, `Add G`, `Add C`.
- Infer `is_land` and basic-land status from `Type Line`.
- Infer `mana_value` from generic plus colored plus colorless counts; treat `X` as 0 for baseline scoring and add a variable-cost flag.
- Detect synergy and role tags from regex and keyword dictionaries over `Type Line`, `Keywords`, `Rules Text`, and subtype parsing.
- For multi-face cards, aggregate face features with front-face weight 0.7 and alternate-face weight 0.3 unless the layout implies equal halves.

**Generation pipeline**
1. Parse all cards and build normalized `Card` entities.
2. Filter to cards in the local Standard corpus snapshot.
3. Extract features and assign role/synergy tags.
4. Build motif clusters using tag overlap, color overlap, and rules-text pattern similarity.
5. Select a strategic shell from the seed request or top cluster candidates.
6. Build a legal mana base first-pass with minimum 21 lands, adjusted by curve and color demands.
7. Fill nonland slots by weighted beam search over candidate cards.
8. Rescore candidate decks, keep top N, and generate explanations.
9. Validate legality constraints before returning results.

**Scoring formulas**
All scores are normalized to a 0 to 100 scale before weighting.

1. Constraint score
Definition: hard validity score.
Formula:
- `constraint = 100` if `card_count <= max_cards` and `land_count >= min_lands` and all cards exist in corpus and off-color count is acceptable under chosen color profile.
- Otherwise return `0` and the deck is not surfaced as a valid recommendation.

2. Tempo score
Goal: reward low-friction curves, early board presence, cheap interaction, and mana efficiency.
Intermediate terms:
- `early_pressure = 0.4 * one_drop_pressure + 0.35 * two_drop_pressure + 0.25 * three_drop_pressure`
- `cheap_interaction = cheap_removal + cheap_countermagic + cheap_bounce`
- `curve_penalty = abs(actual_curve_1_2_3 - target_curve_1_2_3)` scaled to 0 to 1
- `tapland_penalty = tapped_land_ratio`
- `mana_smoothing = ramp_fixing_density`
Formula:
- `tempo = 100 * clamp(0.35 * early_pressure + 0.25 * cheap_interaction + 0.20 * mana_smoothing + 0.20 * board_immediacy_avg - 0.15 * curve_penalty - 0.10 * tapland_penalty, 0, 1)`

3. Synergy score
Goal: reward internal coherence between enablers and payoffs.
Intermediate terms:
- For each synergy tag `t`, compute `pair_score_t = min(enabler_count_t, payoff_count_t) / max(1, target_pairs_t)` capped at 1.
- `cluster_cohesion = average Jaccard overlap among the top 12 nonland cards by synergy density`.
- `dead_synergy_penalty = unsupported_payoff_count / nonland_count`.
Formula:
- `synergy = 100 * clamp(0.55 * mean(pair_score_t) + 0.30 * cluster_cohesion - 0.25 * dead_synergy_penalty, 0, 1)`

4. Interaction score
Goal: reward the ability to answer opposing threats efficiently.
Intermediate terms:
- `removal_density = cheap_removal_count / nonland_count`
- `stack_interaction_density = counterspell_count / nonland_count`
- `sweeper_coverage = min(1, sweeper_count / desired_sweeper_count)`
- `interaction_curve = proportion of interaction at mana value 1 to 3`
Formula:
- `interaction = 100 * clamp(0.45 * removal_density + 0.20 * stack_interaction_density + 0.15 * sweeper_coverage + 0.20 * interaction_curve, 0, 1)`

5. Resilience score
Goal: reward recovery after disruption and staying power in longer games.
Intermediate terms:
- `card_advantage_density`
- `recursion_density`
- `sticky_threat_density`
- `mana_sink_density`
Formula:
- `resilience = 100 * clamp(0.35 * card_advantage_density + 0.25 * recursion_density + 0.25 * sticky_threat_density + 0.15 * mana_sink_density, 0, 1)`

6. Mana score
Goal: reward functional color access and curve support.
Intermediate terms:
- `land_floor = min(1, land_count / recommended_land_count)`
- `color_match = 1 - color_source_shortfall_ratio`
- `curve_support = fraction of cards castable on-curve by estimated sources`
- `flood_penalty = max(0, land_count - recommended_land_count - 2) / 10`
Formula:
- `mana = 100 * clamp(0.30 * land_floor + 0.35 * color_match + 0.35 * curve_support - 0.10 * flood_penalty, 0, 1)`

7. Novelty score
Goal: reward combinations that are uncommon relative to the corpus baseline but still coherent.
Intermediate terms:
- `tag_rarity = average inverse document frequency of the deck's top synergy tags`
- `pair_uniqueness = average rarity of two-card and three-card tag combinations across generated motif clusters`
- `shell_distance = distance from the nearest common cluster centroid`
- `coherence_guard = synergy / 100`
Formula:
- `novelty = 100 * clamp((0.35 * tag_rarity + 0.35 * pair_uniqueness + 0.30 * shell_distance) * coherence_guard, 0, 1)`
Notes:
- Novelty is explicitly multiplied by coherence guard so bizarre but incoherent piles do not score highly.

8. Game-theory score
Goal: estimate how many strategic postures the deck can adopt and how well it can punish common opposing plans, without simulating the full metagame.
Intermediate terms:
- `initiative = tempo / 100`
- `answer_flexibility = interaction / 100`
- `pivot_capacity = average of resilience and card_selection_density`
- `threat_diversity = unique threat classes / target_threat_classes`
Formula:
- `game_theory = 100 * clamp(0.30 * initiative + 0.25 * answer_flexibility + 0.25 * pivot_capacity + 0.20 * threat_diversity, 0, 1)`

9. Overall deck score
Recommended weighting:
- `overall = 0.18 * tempo + 0.18 * synergy + 0.14 * interaction + 0.12 * resilience + 0.16 * mana + 0.12 * novelty + 0.10 * game_theory`
Constraint gating:
- if `constraint == 0`, mark deck invalid and omit from recommendation results.

**Recommended generator heuristics**
- Deck size target: generate exactly 60 cards in v1 for clarity, even though the hard cap is 60.
- Land rule: start at 21 lands, then add 1 land for every 6 cards above an average mana value threshold of 2.7, and add 1 land if three or more colors are present.
- Copy limits: default to up to 4 copies per non-basic card and any number of basic lands, unless future legality metadata says otherwise.
- Color commitment: avoid splashes unless a requested seed card or high-value synergy justifies it and mana score remains above threshold.
- Candidate search: use beam search with width 32 and keep the top 8 final deck candidates.

**Suggested implementation modules**
- Frontend modules: app shell, routing, card browser, card detail panel, generator form, deck editor, score breakdown views, saved decks view.
- Backend modules: MTGLib parser, feature extractor, cluster builder, deck generator, scoring engine, explanation engine, local storage service.

**Relevant files**
- `f:/workspace/mtglib/CONTRACT.md` - exact parsing contract and section order.
- `f:/workspace/mtglib/README.md` - Standard snapshot boundary and regeneration workflow.
- `f:/workspace/mtglib/PLAN.md` - confirms MTGLib is the data library, not the deck app.
- `f:/workspace/mtglib/cards/` - card corpus source.
- `f:/workspace/mtglib/cards/llanowar-elves.md` - single-face creature example.
- `f:/workspace/mtglib/cards/island.md` - land example.
- `f:/workspace/mtglib/cards/aang-at-the-crossroads-aang-destined-savior.md` - multi-face example.
- `f:/workspace/iterative-visual-loop/package.json` - nearby React + TypeScript + Vite stack reference.

**Verification**
1. Parser verification: compare normalized output for single-face, land, and multi-face cards against source markdown.
2. API verification: ensure `/api/cards`, `/api/generate`, `/api/decks/score`, and `/api/decks/swap` return stable typed payloads.
3. Constraint verification: assert all surfaced deck recommendations have exactly 60 cards and at least 21 lands.
4. Scoring verification: run golden tests on known deck shells to verify monotonic behavior, such as improved mana base increasing mana score and unsupported payoffs decreasing synergy score.
5. UX verification: confirm the generator route can lock cards, exclude cards, regenerate, and explain swaps without losing validity.

**Decisions**
- Included scope: Standard-only main-deck generation, corpus-backed browsing, explainable scoring, saved decks, and local-only persistence.
- Excluded scope: sideboards, online accounts, multiplayer formats, live metagame ingestion, price/budget optimization, and hidden black-box scoring.
- Recommended architecture choice: thin local API instead of pure client-side generation, because parsing and deck search are easier to test and tune outside the browser.
- Recommended novelty policy: reward unusual but defensible shells through rarity-weighted synergy combinations gated by coherence.

**Further Considerations**
1. If a pure TypeScript stack is preferred, the backend can be replaced with a Vite build-time indexer plus a Web Worker recommendation engine, but the data model and formulas should remain the same.
2. If future meta-deck data is added, novelty can be recalibrated against real archetype frequency rather than corpus-only motif rarity.
3. If sideboards are later added, introduce a second optimization pass for matchup coverage rather than mixing sideboard logic into the main-deck generator.