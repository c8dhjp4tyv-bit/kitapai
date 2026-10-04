/**
 * API sözleşmesi — `src/kitapai/schemas.py` ile birebir aynı.
 *
 * Bu dosya elle güncellenir, `tests/test_contract.py` ise iki tarafın
 * alanlarının aynı kaldığını her test koşusunda doğrular. Böylece sunucu
 * şeması değişip istemci unutulduğunda test kırmızıya döner.
 */

export type Language = 'tur' | 'eng';
export type Strictness = 'strict' | 'soft';

export interface Rating {
  average: number;
  count: number;
}

export interface Book {
  work_key: string;
  title: string;
  subtitle: string | null;
  authors: string[];
  first_published: number | null;
  description: string | null;
  genres: string[];
  moods: string[];
  subjects: string[];
  languages: string[];
  pages: number | null;
  isbns: string[];
  cover_url: string | null;
  openlibrary_url: string;
  rating: Rating | null;
  readers: number | null;
  popularity: number;
}

export interface Recommendation {
  rank: number;
  book: Book;
  why: string;
  hooks: string[];
  content_notes: string[];
  confidence: number;
  grounded: boolean;
  match_reasons: string[];
}

export interface RecommendRequest {
  query?: string;
  genres?: string[];
  moods?: string[];
  languages?: Language[];
  era?: string | null;
  length?: string | null;
  audience?: string | null;
  exclude_work_keys?: string[];
  limit?: number;
  strictness?: Strictness;
  seed?: number | null;
}

export interface ResponseMeta {
  request_id: string;
  model: string;
  engine: string;
  latency_ms: number;
  retrieved: number;
  grounded_ratio: number;
  degraded: boolean;
  notes: string[];
}

export interface RecommendResponse {
  recommendations: Recommendation[];
  followups: string[];
  meta: ResponseMeta;
}

export interface SearchResponse {
  books: Book[];
  total: number;
  meta: ResponseMeta;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  engine: string;
  model: string;
  catalog_books: number;
  catalog_path: string;
  vectors_loaded: boolean;
  device: string;
  uptime_s: number;
}

export interface TaxonomyEntry {
  slug: string;
  label: string;
  description: string;
}

export interface TaxonomyResponse {
  genres: TaxonomyEntry[];
  moods: TaxonomyEntry[];
  eras: TaxonomyEntry[];
  lengths: TaxonomyEntry[];
  audiences: TaxonomyEntry[];
}

export interface ErrorResponse {
  error: string;
  detail: string | null;
  request_id: string | null;
}
