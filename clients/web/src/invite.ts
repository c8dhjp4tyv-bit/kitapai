/** Davet kodu: 24 hane, XXXXXX-XXXXXX-XXXXXX-XXXXXX biçiminde gösterilir. Doğrulama sunucuda yapılır. */

const KEY = 'kitapai.invite';
const EXPIRES = 'kitapai.invite.expires';

export const CODE_LENGTH = 24;

/** Harf ve rakam dışını atar, büyük harfe çevirir, 24 haneye kırpar. */
export function normalizeCode(raw: string): string {
  return raw.replace(/[^a-zA-Z0-9]/g, '').toUpperCase().slice(0, CODE_LENGTH);
}

/** Yazarken tire koyar: ABCDEF-GHJKMN-... */
export function formatCode(raw: string): string {
  const n = normalizeCode(raw);
  return (n.match(/.{1,6}/g) ?? []).join('-');
}

export function storedCode(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function storedExpiry(): number | null {
  try {
    const v = localStorage.getItem(EXPIRES);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

export function saveCode(code: string, expiresAt: number): void {
  try {
    localStorage.setItem(KEY, code);
    localStorage.setItem(EXPIRES, String(expiresAt));
  } catch {
    // depolama kapalıysa oturum yalnızca bu sayfada geçerli kalır
  }
}

export function clearCode(): void {
  try {
    localStorage.removeItem(KEY);
    localStorage.removeItem(EXPIRES);
  } catch {
    // yok say
  }
}

/** "71 sa 20 dk" / "45 dk" */
export function remaining(expiresAt: number, now = Date.now() / 1000): string {
  const s = Math.max(0, Math.floor(expiresAt - now));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h} sa ${m} dk` : `${m} dk`;
}
