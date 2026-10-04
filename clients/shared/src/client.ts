/**
 * Tipli API istemcisi. Web ve Android aynı dosyayı kullanır.
 *
 * Tasarım notları:
 *  - Zaman aşımı zorunlu: Tailscale bağlantısı koparsa istek sonsuza kadar
 *    asılı kalmasın; model üretimi uzun sürebildiği için varsayılan 120 sn.
 *  - Hatalar `ApiError` olarak yükselir; sunucunun döndürdüğü `ErrorResponse`
 *    gövdesi korunur, böylece arayüz "katalog yok" ile "meşgul" arasında
 *    ayrım yapabilir.
 */

import type {
  Book,
  ErrorResponse,
  HealthResponse,
  RecommendRequest,
  RecommendResponse,
  SearchResponse,
  TaxonomyResponse,
} from './types';

export class ApiError extends Error {
  readonly status: number;
  readonly body: ErrorResponse | null;

  constructor(message: string, status: number, body: ErrorResponse | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }

  /** Kullanıcıya gösterilecek Türkçe mesaj. */
  get userMessage(): string {
    if (this.status === 0) {
      return 'Sunucuya ulaşılamadı. Tailscale bağlı mı, sunucu çalışıyor mu?';
    }
    if (this.status === 401) return 'API anahtarı geçersiz.';
    if (this.status === 503 && this.body?.error === 'katalog_yok') {
      return 'Sunucuda katalog kurulu değil.';
    }
    if (this.status === 503) return 'Sunucu şu an meşgul, birkaç saniye sonra tekrar dene.';
    if (this.status === 504) return 'İstek zaman aşımına uğradı.';
    return this.body?.detail || this.message;
  }
}

export interface ClientOptions {
  baseUrl: string;
  apiKey?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

const DEFAULT_TIMEOUT = 120_000;

export function createClient(options: ClientOptions) {
  const baseUrl = options.baseUrl.replace(/\/+$/, '');
  const doFetch = options.fetchImpl ?? fetch;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT;

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(init.headers as Record<string, string> | undefined),
    };
    if (options.apiKey) headers['X-API-Key'] = options.apiKey;

    let response: Response;
    try {
      response = await doFetch(`${baseUrl}${path}`, {
        ...init,
        headers,
        signal: controller.signal,
      });
    } catch (err) {
      const aborted = err instanceof Error && err.name === 'AbortError';
      throw new ApiError(
        aborted ? 'İstek zaman aşımına uğradı' : 'Ağ hatası',
        aborted ? 504 : 0,
      );
    } finally {
      clearTimeout(timer);
    }

    if (!response.ok) {
      let body: ErrorResponse | null = null;
      try {
        body = (await response.json()) as ErrorResponse;
      } catch {
        // gövde JSON değilse yok say
      }
      throw new ApiError(`HTTP ${response.status}`, response.status, body);
    }
    return (await response.json()) as T;
  }

  return {
    baseUrl,
    recommend: (body: RecommendRequest) =>
      request<RecommendResponse>('/api/recommend', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    search: (q: string, limit = 20) =>
      request<SearchResponse>(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
    book: (workKey: string) =>
      request<Book>(`/api/book/${workKey.replace('/works/', '')}`),
    similar: (workKey: string, limit = 8) =>
      request<SearchResponse>(
        `/api/similar/${workKey.replace('/works/', '')}?limit=${limit}`,
      ),
    taxonomy: () => request<TaxonomyResponse>('/api/taxonomy'),
    health: () => request<HealthResponse>('/health'),
  };
}

export type KitapaiClient = ReturnType<typeof createClient>;
