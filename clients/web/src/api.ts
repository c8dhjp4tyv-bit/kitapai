import { createClient } from '@kitapai/shared';

/**
 * API adresi sırayla şuradan okunur:
 *   1. `?api=` sorgu parametresi (telefonda hızlı geçiş için)
 *   2. localStorage (bir kez ayarlanınca kalıcı)
 *   3. VITE_API_URL (derleme zamanı)
 *   4. Sayfanın kendi kökü (aynı origin'den sunuluyorsa)
 */
function resolveBaseUrl(): string {
  const fromQuery = new URLSearchParams(window.location.search).get('api');
  if (fromQuery) {
    localStorage.setItem('kitapai.api', fromQuery);
    return fromQuery;
  }
  const stored = localStorage.getItem('kitapai.api');
  if (stored) return stored;
  const fromEnv = import.meta.env.VITE_API_URL as string | undefined;
  if (fromEnv) return fromEnv;
  return window.location.origin;
}

export const apiBaseUrl = resolveBaseUrl();

export const api = createClient({
  baseUrl: apiBaseUrl,
  apiKey: (import.meta.env.VITE_API_KEY as string | undefined) || undefined,
});

export function setApiBaseUrl(url: string): void {
  localStorage.setItem('kitapai.api', url.replace(/\/+$/, ''));
  window.location.reload();
}
