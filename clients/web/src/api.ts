import { createClient } from '@kitapai/shared';
import { clearCode, storedCode } from './invite';

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

/** Sunucu davet kodunu reddederse (süre doldu / geçersiz) kodu sil ve kapıya dön. */
const guardedFetch: typeof fetch = async (input, init) => {
  const response = await fetch(input, init);
  if (response.status === 401 && !String(input).endsWith('/api/invite')) {
    const body = (await response.clone().json().catch(() => null)) as { error?: string; detail?: string } | null;
    if (body?.error?.startsWith('invite_')) {
      clearCode();
      try {
        sessionStorage.setItem('kitapai.notice', body.detail ?? 'Davet kodu geçersiz.');
      } catch {
        // yok say
      }
      window.location.reload();
    }
  }
  return response;
};

export const api = createClient({
  fetchImpl: guardedFetch,
  baseUrl: apiBaseUrl,
  // Davet kodu sunucuda denetlenen anahtardır (X-API-Key). Kod girilince sayfa yeniden yüklenir.
  apiKey: storedCode() || (import.meta.env.VITE_API_KEY as string | undefined) || undefined,
});

export function setApiBaseUrl(url: string): void {
  localStorage.setItem('kitapai.api', url.replace(/\/+$/, ''));
  window.location.reload();
}
