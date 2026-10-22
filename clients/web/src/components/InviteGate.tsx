import { useState } from 'react';
import { ApiError } from '@kitapai/shared';
import { api } from '../api';
import { CODE_LENGTH, formatCode, normalizeCode, saveCode } from '../invite';

interface Props {
  /** Önceki oturumdan kalan bir hata (örn. "süresi dolmuş") */
  notice?: string | null;
}

export function InviteGate({ notice }: Props) {
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(notice ?? null);
  const [busy, setBusy] = useState(false);
  const ready = normalizeCode(value).length === CODE_LENGTH;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready || busy) return;
    const code = normalizeCode(value);
    setBusy(true);
    setError(null);
    try {
      // `api` kayıtlı kodla kurulu; burada henüz kayıtlı kod yok, bu yüzden gövdedeki kod doğrulanır.
      const res = await api.invite(code);
      saveCode(code, res.expires_at);
      window.location.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.userMessage : 'Sunucuya ulaşılamadı.');
      setBusy(false);
    }
  }

  return (
    <div className="gate">
      <form className="card gate__card" onSubmit={submit}>
        <span className="logo">📖 kitap.ai</span>
        <h1 className="gate__title">Davet kodunu gir</h1>
        <p className="muted">Bu sürüm yalnızca davetliler içindir. Sana verilen 24 haneli kodu yaz.</p>
        <input
          className="gate__input"
          value={formatCode(value)}
          onChange={(e) => setValue(e.target.value)}
          placeholder="XXXXXX-XXXXXX-XXXXXX-XXXXXX"
          autoFocus
          autoCapitalize="characters"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          inputMode="text"
          aria-label="Davet kodu"
          aria-invalid={error ? true : undefined}
        />
        {error && <p className="gate__error" role="alert">{error}</p>}
        <button type="submit" className="btn btn--primary" disabled={!ready || busy}>
          {busy ? 'Doğrulanıyor…' : 'Giriş yap'}
        </button>
      </form>
    </div>
  );
}
