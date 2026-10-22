import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ApiError } from '@kitapai/shared';
import App from './App';
import { api } from './api';
import { InviteGate } from './components/InviteGate';
import { clearCode, saveCode, storedCode } from './invite';
import './styles.css';

type Gate = { kind: 'checking' } | { kind: 'locked'; notice: string | null } | { kind: 'open' };

function takeNotice(): string | null {
  try {
    const n = sessionStorage.getItem('kitapai.notice');
    sessionStorage.removeItem('kitapai.notice');
    return n;
  } catch {
    return null;
  }
}

/** Açılışta kayıtlı davet kodunu sunucuya doğrulatır; geçersizse kapıyı gösterir. */
function Root() {
  const [gate, setGate] = useState<Gate>(() =>
    storedCode() ? { kind: 'checking' } : { kind: 'locked', notice: takeNotice() },
  );

  useEffect(() => {
    const code = storedCode();
    if (!code) return;
    api
      .invite(code)
      .then((res) => {
        saveCode(code, res.expires_at);
        setGate({ kind: 'open' });
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearCode();
          setGate({ kind: 'locked', notice: err.userMessage });
        } else {
          setGate({ kind: 'open' }); // sunucuya ulaşılamıyor: uygulama kendi hatasını gösterir
        }
      });
  }, []);

  if (gate.kind === 'checking') return <div className="gate" aria-busy="true" />;
  if (gate.kind === 'locked') return <InviteGate notice={gate.notice} />;
  return <App />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
