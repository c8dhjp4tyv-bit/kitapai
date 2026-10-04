import { useState } from 'react';
import type { Book, Recommendation, TaxonomyResponse } from '@kitapai/shared';
import { api } from '../api';

interface Props {
  recommendation: Recommendation;
  taxonomy: TaxonomyResponse | null;
  isRead: boolean;
  onToggleRead: (workKey: string, title: string) => void;
  onPickSimilar: (book: Book) => void;
}

function labelOf(taxonomy: TaxonomyResponse | null, kind: 'genres' | 'moods', slug: string) {
  return taxonomy?.[kind].find((e) => e.slug === slug)?.label ?? slug;
}

function metaLine(book: Book): string {
  return [
    book.authors.join(', '),
    book.first_published ? String(book.first_published) : '',
    book.pages ? `${book.pages} sayfa` : '',
    book.rating ? `★ ${book.rating.average.toFixed(1)} (${book.rating.count})` : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

export function BookCard({
  recommendation,
  taxonomy,
  isRead,
  onToggleRead,
  onPickSimilar,
}: Props) {
  const { book, why, hooks, content_notes, confidence, rank } = recommendation;
  const [similar, setSimilar] = useState<Book[] | null>(null);
  const [loadingSimilar, setLoadingSimilar] = useState(false);

  async function loadSimilar() {
    if (similar) {
      setSimilar(null);
      return;
    }
    setLoadingSimilar(true);
    try {
      const res = await api.similar(book.work_key, 6);
      setSimilar(res.books);
    } catch {
      setSimilar([]);
    } finally {
      setLoadingSimilar(false);
    }
  }

  return (
    <article className="card book">
      <div className="book__head">
        {book.cover_url ? (
          <img className="book__cover" src={book.cover_url} alt="" loading="lazy" />
        ) : (
          <div className="book__cover book__cover--empty" aria-hidden="true">
            📖
          </div>
        )}
        <div className="book__title-block">
          <span className="book__rank">ÖNERİ {rank}</span>
          <h3 className="book__title">{book.title}</h3>
          {book.subtitle && <p className="book__subtitle">{book.subtitle}</p>}
          <p className="book__meta">{metaLine(book)}</p>
          <div className="tags">
            {book.genres.slice(0, 3).map((g) => (
              <span key={g} className="tag">
                {labelOf(taxonomy, 'genres', g)}
              </span>
            ))}
            {book.moods.slice(0, 2).map((m) => (
              <span key={m} className="tag tag--mood">
                {labelOf(taxonomy, 'moods', m)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <p className="book__why">{why}</p>

      {hooks.length > 0 && (
        <ul className="hooks">
          {hooks.map((h) => (
            <li key={h}>{h}</li>
          ))}
        </ul>
      )}

      {content_notes.length > 0 && (
        <p className="book__notes" role="note">
          İçerik uyarısı: {content_notes.join(', ')}
        </p>
      )}

      <div className="book__confidence" title={`Model güveni: ${Math.round(confidence * 100)}%`}>
        <div className="book__confidence-bar" style={{ width: `${confidence * 100}%` }} />
      </div>

      <div className="book__actions">
        <a className="btn btn--ghost" href={book.openlibrary_url} target="_blank" rel="noreferrer">
          Open Library
        </a>
        <button type="button" className="btn btn--ghost" onClick={loadSimilar}>
          {loadingSimilar ? 'Aranıyor…' : similar ? 'Benzerleri gizle' : 'Benzerleri'}
        </button>
        <button
          type="button"
          className={isRead ? 'btn btn--ghost btn--on' : 'btn btn--ghost'}
          onClick={() => onToggleRead(book.work_key, book.title)}
          title="İşaretlenen kitaplar bir sonraki önerilerden çıkarılır"
        >
          {isRead ? '✓ Okudum' : 'Okudum'}
        </button>
      </div>

      {similar && similar.length > 0 && (
        <ul className="similar">
          {similar.map((s) => (
            <li key={s.work_key}>
              <button type="button" onClick={() => onPickSimilar(s)}>
                {s.cover_url && <img src={s.cover_url} alt="" loading="lazy" />}
                <span>{s.title}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {similar && similar.length === 0 && <p className="muted">Benzer kitap bulunamadı.</p>}
    </article>
  );
}
