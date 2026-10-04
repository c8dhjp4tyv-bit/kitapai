import { createClient } from '@kitapai/shared';
import { loadString, saveString } from './storage';

/**
 * API adresi. Telefon sunucuya Tailscale üzerinden ulaşır; bu yüzden tailnet
 * IP'si ya da MagicDNS adı yazılır. iOS'tan farklı olarak Android düz HTTP'ye
 * izin verir (AndroidManifest içinde `usesCleartextTraffic`), yine de HTTPS
 * için `tailscale serve` önerilir.
 *
 * Değer uygulama içinden değiştirilebilir ve AsyncStorage'da saklanır.
 */
export const DEFAULT_API_URL = 'http://100.86.81.25:8000';

let currentUrl = DEFAULT_API_URL;
let currentKey: string | undefined;

/** Uygulama açılışında kayıtlı ayarları yükler. */
export async function hydrate(): Promise<string> {
  const url = await loadString('apiUrl');
  if (url) currentUrl = url;
  const key = await loadString('apiKey');
  if (key) currentKey = key;
  return currentUrl;
}

export function apiUrl(): string {
  return currentUrl;
}

export async function setApiUrl(url: string): Promise<void> {
  currentUrl = url.trim().replace(/\/+$/, '');
  await saveString('apiUrl', currentUrl);
}

export async function setApiKey(key: string): Promise<void> {
  currentKey = key || undefined;
  await saveString('apiKey', key);
}

/** Her çağrıda güncel ayarlarla yeni istemci üretir. */
export function client() {
  return createClient({ baseUrl: currentUrl, apiKey: currentKey });
}
