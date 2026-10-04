import { useCallback, useMemo, useRef, useState } from 'react';
import type { Book, RecommendRequest, RecommendResponse } from '@kitapai/shared';
import { ApiError } from '@kitapai/shared';
import { api } from './api';
import { useLibrary, useTaxonomy, useTheme } from './hooks';
import { BookCard } from './components/BookCard';
import { ChipGroup, ChipSelect } from './components/Chips';
import { Header } from './components/Header';

const EXAMPLES = [
  'çölde geçen, ağır olmayan epik bir bilim kurgu',
  'yas ve kayıp üzerine sakin bir roman',
  'uzun bir uçak yolculuğu için tırnak yediren bir polisiye',
  'ne okuyacağımı bilmiyorum, sen seç',
];

export default function App() {
  const { theme, toggle: toggleTheme } = useTheme();
  const { taxonomy, error: taxonomyError } = useTaxonomy();
  const library = useLibrary();

  const [query, setQuery] = useState('');
  const [genres, setGenres] = useState<string[]>([]);
  const [moods, setMoods] = useState<string[]>([]);
  const [era, setEra] = useState<string | null>(null);
  const [length, setLength] = useState<string | null>(null);
  const [audience, setAudience] = useState<string | null>(null);
  const [turkishOnly, setTurkishOnly] = useState(false);
  const [limit, setLimit] = useState(3);
  const [advanced, setAdvanced] = useState(false);

  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  const toggleIn = (list: string[], setList: (v: string[]) => void) => (slug: string) =>
    setList(list.includes(slug) ? list.filter((s) => s !== slug) : [...list, slug]);

  const buildRequest = useCallback(
    (overrides: Partial<RecommendRequest> = {}): RecommendRequest => ({
      query,
      genres,
      moods,
      era,
      length,
      audience,
      languages: turkishOnly ? ['tur'] : [],
      exclude_work_keys: library.entries.map((e) => e.work_key),
      limit,
      strictness: 'soft',
      ...overrides,
    }),
    [query, genres, moods, era, length, audience, turkishOnly, library.entries, limit],
  );

  const run = useCallback(
    async (overrides: Partial<RecommendRequest> = {}) => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.recommend(buildRequest(overrides));
        setResult(response);
        requestAnimationFrame(() =>
          resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
        );
      } catch (err) {
        setError(err instanceof ApiError ? err.userMessage : String(err));
        setResult(null);
      } finally {
        setLoading(false);
      }
    },
    [buildRequest],
  );

  const onPickSimilar = useCallback(
    (book: Book) => {
      setQuery(`${book.title} gibi bir kitap`);
      void run({ query: `${book.title} gibi bir kitap`, genres: [], moods: [] });
    },
    [run],
  );

  const activeFilters = useMemo(
    () => genres.length + moods.length + (era ? 1 : 0) + (length ? 1 : 0) + (audience ? 1 : 0),
    [genres, moods, era, length, audience],
  );

  return (
    <div className="app">
      <Header theme={theme} onToggleTheme={toggleTheme} />

      <section className="hero">
        <span className="eyebrow">✦ Open Library kataloğundan</span>
        <h1>
          Sana özel
          <br />
          <em>kitap önerileri</em>
        </h1>
        <p className="muted">
          Ne aradığını kendi cümlelerinle yaz. Öneriler gerçek kitaplardan gelir — uydurma yok.
        </p>
      </section>

      <form
        className="card form"
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
      >
        <label className="field">
          <span className="field__label">NE ARIYORSUN?</span>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Konu, his, durum ya da benzediği kitap…"
            rows={3}
            maxLength={500}
          />
        </label>

        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" className="chip chip--ghost" onClick={() => setQuery(ex)}>
              {ex}
            </button>
          ))}
        </div>

        {taxonomy && (
          <>
            <div className="field">
              <span className="field__label">TÜR</span>
              <ChipGroup
                entries={taxonomy.genres}
                selected={genres}
                onToggle={toggleIn(genres, setGenres)}
              />
            </div>
            <div className="field">
              <span className="field__label">RUH HALİ</span>
              <ChipGroup
                entries={taxonomy.moods}
                selected={moods}
                onToggle={toggleIn(moods, setMoods)}
              />
            </div>

            <button
              type="button"
              className="disclosure"
              onClick={() => setAdvanced((a) => !a)}
              aria-expanded={advanced}
            >
              {advanced ? '− Ayrıntılı filtreler' : '+ Ayrıntılı filtreler'}
              {!advanced && activeFilters > 0 && <span className="badge">{activeFilters}</span>}
            </button>

            {advanced && (
              <div className="advanced">
                <ChipSelect entries={taxonomy.eras} value={era} onChange={setEra} label="DÖNEM" />
                <ChipSelect
                  entries={taxonomy.lengths}
                  value={length}
                  onChange={setLength}
                  label="UZUNLUK"
                />
                <ChipSelect
                  entries={taxonomy.audiences}
                  value={audience}
                  onChange={setAudience}
                  label="OKUR"
                />
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={turkishOnly}
                    onChange={(e) => setTurkishOnly(e.target.checked)}
                  />
                  Yalnızca Türkçe baskısı olanlar
                </label>
                <label className="switch">
                  Kaç öneri?
                  <input
                    type="range"
                    min={1}
                    max={6}
                    value={limit}
                    onChange={(e) => setLimit(Number(e.target.value))}
                  />
                  <strong>{limit}</strong>
                </label>
              </div>
            )}
          </>
        )}

        {taxonomyError && <p className="error">{taxonomyError}</p>}
        {error && <p className="error">{error}</p>}

        <button type="submit" className="btn btn--primary" disabled={loading}>
          {loading ? 'Kitaplık taranıyor…' : 'Kitap Öner →'}
        </button>

        {library.entries.length > 0 && (
          <p className="muted small">
            {library.entries.length} okunmuş kitap önerilerden çıkarılıyor ·{' '}
            <button type="button" className="linklike" onClick={library.clear}>
              temizle
            </button>
          </p>
        )}
      </form>

      <div ref={resultsRef}>
        {loading && (
          <div className="results">
            {Array.from({ length: limit }).map((_, i) => (
              <div key={i} className="card skeleton" />
            ))}
          </div>
        )}

        {!loading && result && (
          <section className="results">
            <div className="results__head">
              <h2>Öneriler</h2>
              <span className="muted small">
                {result.meta.retrieved} aday · {result.meta.latency_ms} ms
                {result.meta.degraded && ' · yedek sıralama'}
              </span>
            </div>

            {result.recommendations.length === 0 && (
              <p className="muted">
                Bu kısıtlara uyan kitap bulunamadı. Filtreleri gevşetmeyi dene.
              </p>
            )}

            {result.recommendations.map((rec) => (
              <BookCard
                key={rec.book.work_key}
                recommendation={rec}
                taxonomy={taxonomy}
                isRead={library.has(rec.book.work_key)}
                onToggleRead={library.toggle}
                onPickSimilar={onPickSimilar}
              />
            ))}

            {result.followups.length > 0 && (
              <div className="followups">
                {result.followups.map((f) => (
                  <button
                    key={f}
                    type="button"
                    className="chip chip--ghost"
                    onClick={() => setQuery((q) => `${q} ${f}`.trim())}
                  >
                    {f}
                  </button>
                ))}
              </div>
            )}
          </section>
        )}
      </div>

      <footer className="footer muted small">
        Veri: Open Library (ODbL) · Öneriler ince ayarlı bir dil modelinden gelir,
        kitap bilgileri katalogdan.
      </footer>
    </div>
  );
}
