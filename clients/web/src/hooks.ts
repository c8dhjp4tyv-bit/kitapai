import { useCallback, useEffect, useState } from 'react';
import type { TaxonomyResponse } from '@kitapai/shared';
import { api } from './api';

/** Tür/ruh listeleri sunucudan gelir; istemci sabit kodlamaz. */
export function useTaxonomy() {
  const [taxonomy, setTaxonomy] = useState<TaxonomyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .taxonomy()
      .then((t) => !cancelled && setTaxonomy(t))
      .catch((e) => !cancelled && setError(e.userMessage ?? String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  return { taxonomy, error };
}

type Theme = 'light' | 'dark';

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem('kitapai.theme') as Theme | null;
    if (stored) return stored;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('kitapai.theme', theme);
  }, [theme]);

  return { theme, toggle: () => setTheme((t) => (t === 'dark' ? 'light' : 'dark')) };
}

export interface LibraryEntry {
  work_key: string;
  title: string;
  addedAt: number;
}

/**
 * "Okudum" listesi. Sunucu `exclude_work_keys` alanını desteklediği için
 * buradaki kitaplar sonraki önerilerden otomatik çıkarılır.
 */
export function useLibrary() {
  const [entries, setEntries] = useState<LibraryEntry[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('kitapai.read') ?? '[]') as LibraryEntry[];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    localStorage.setItem('kitapai.read', JSON.stringify(entries));
  }, [entries]);

  const toggle = useCallback((work_key: string, title: string) => {
    setEntries((prev) =>
      prev.some((e) => e.work_key === work_key)
        ? prev.filter((e) => e.work_key !== work_key)
        : [...prev, { work_key, title, addedAt: Date.now() }],
    );
  }, []);

  const has = useCallback(
    (work_key: string) => entries.some((e) => e.work_key === work_key),
    [entries],
  );

  return { entries, toggle, has, clear: () => setEntries([]) };
}
