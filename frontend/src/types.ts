export type Color = "W" | "U" | "B" | "R" | "G";

export interface CardFeatureVector {
  mana_value_bucket: number;
  is_creature: boolean;
  is_interaction: boolean;
  is_removal: boolean;
  is_card_draw: boolean;
  is_selection: boolean;
  is_ramp: boolean;
  is_fixing: boolean;
  is_token_maker: boolean;
  is_recursion: boolean;
  is_sweeper: boolean;
  is_counterspell: boolean;
  is_combat_trick: boolean;
  is_engine_piece: boolean;
  is_payoff: boolean;
  is_enabler: boolean;
  board_immediacy: number;
  resource_velocity: number;
  resilience: number;
  synergy_density: number;
}

export interface CardFace {
  name: string;
  mana_value: number;
  type_line: string;
  rules_text: string;
  keywords: string[];
  colors: Color[];
}

export interface CardEntity {
  slug: string;
  display_name: string;
  canonical_name: string;
  layout: string;
  faces: CardFace[];
  type_line: string;
  mana_value: number;
  colors: Color[];
  color_identity: Color[];
  keywords: string[];
  rules_text: string;
  is_land: boolean;
  is_basic_land: boolean;
  role_tags: string[];
  synergy_tags: string[];
  feature_vector: CardFeatureVector;
  novelty_baseline_score: number;
}

export interface CardRelatedSummary {
  slug: string;
  display_name: string;
  type_line: string;
  colors: Color[];
  shared_tags: string[];
  shared_roles: string[];
  overlap_score: number;
}

export interface CardListResponse {
  items: CardEntity[];
  page: number;
  page_size: number;
  total: number;
}

export interface CardDetailResponse {
  card: CardEntity;
  related_cards: CardRelatedSummary[];
}

export interface MetaResponse {
  corpus_version: string;
  card_count: number;
  indexed_at: string;
  supported_filters: Record<string, string[]>;
  tag_distributions: Record<string, Record<string, number>>;
}

export interface GenerationRequest {
  colors: Color[];
  required_slugs: string[];
  excluded_slugs: string[];
  preferred_tags: string[];
  preferred_roles: string[];
  target_tempo: "fast" | "medium" | "slow";
  target_novelty: number;
  min_lands: number;
  max_cards: number;
  allow_splash: boolean;
  candidate_count: number;
}

export interface DeckCard {
  slug: string;
  display_name: string;
  quantity: number;
  locked: boolean;
  is_land: boolean;
  mana_value: number;
  type_line: string;
  reason_codes: string[];
}

export interface DeckScore {
  overall: number;
  constraint: number;
  tempo: number;
  synergy: number;
  interaction: number;
  resilience: number;
  mana: number;
  novelty: number;
  game_theory: number;
}

export interface DeckValidation {
  is_valid: boolean;
  errors: string[];
  warnings: string[];
  card_count: number;
  land_count: number;
  off_color_count: number;
}

export interface DeckExplanation {
  summary: string;
  core_plan: string;
  novel_angle: string;
  tempo_story: string;
  key_synergies: string[];
  card_reasons: Record<string, string[]>;
  replacement_notes: string[];
}

export interface GeneratedDeck {
  id: string;
  name: string;
  colors: Color[];
  preferred_tags: string[];
  primary_plan_tags: string[];
  summary: string;
  explanation_lines: string[];
  cards: DeckCard[];
  card_count: number;
  land_count: number;
  nonland_count: number;
  color_profile: Record<string, number>;
  mana_curve: Record<string, number>;
  score: DeckScore;
  explanations: DeckExplanation;
  validation: DeckValidation;
  updated_at: string;
}

export interface GenerationCandidate {
  rank: number;
  label: string;
  focus_tags: string[];
  focus_roles: string[];
  deck: GeneratedDeck;
}

export interface GenerationResponse {
  request: GenerationRequest;
  generated_at: string;
  candidate_count: number;
  primary_candidate_id: string | null;
  candidates: GenerationCandidate[];
}

export interface SavedDeckSummary {
  id: string;
  name: string;
  updated_at: string;
  colors: Color[];
  primary_plan_tags: string[];
  overall_score: number;
  card_count: number;
  land_count: number;
  validation_ok: boolean;
}

export interface SavedDeckListResponse {
  items: SavedDeckSummary[];
}