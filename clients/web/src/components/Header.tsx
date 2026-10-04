import { useEffect, useState } from 'react';
import type { HealthResponse } from '@kitapai/shared';
import { api, apiBaseUrl, setApiBaseUrl } from '../api';

/** 12 → "12 kitap", 1_450_000 → "1,4M kitap" */
function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toLocaleString('tr-TR', { maximumFractionDigits: 1 })}M kitap`;
  if (n >= 1_000) return `${Math.round(n / 1000)}b kitap`;
  return `${n} kitap`;
}

interface Props {
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
}

export function Header({ theme, onToggleTheme }: Props) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setOffline(true));
  }, []);

  function changeServer() {
    const next = window.prompt('API adresi', apiBaseUrl);
    if (next) setApiBaseUrl(next);
  }

  return (
    <header className="header">
      <span className="logo">📖 kitap.ai</span>
      <div className="header__right">
        <button
          type="button"
          className={offline ? 'status status--off' : 'status'}
          onClick={changeServer}
          title={
            offline
              ? `${apiBaseUrl} — bağlanılamadı, değiştirmek için tıkla`
              : `${apiBaseUrl}\n${health?.catalog_books.toLocaleString('tr-TR') ?? '?'} kitap · ${health?.engine ?? ''}`
          }
        >
          {offline ? 'bağlantı yok' : health ? formatCount(health.catalog_books) : '…'}
        </button>
        <button type="button" className="btn btn--ghost" onClick={onToggleTheme}>
          {theme === 'dark' ? '☀︎' : '☾'}
        </button>
      </div>
    </header>
  );
}
