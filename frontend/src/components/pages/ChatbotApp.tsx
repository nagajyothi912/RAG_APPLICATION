import { useState } from 'react';
import type { AuthUser } from '../../services/api';
import AppHeader from '../organisms/AppHeader';
import RagPage from './RagPage';

type ChatbotAppProps = {
  user: AuthUser;
  onLogout: () => void;
};

/**
 * The customer-facing app: one assistant, no week tabs. It runs the full
 * pipeline the weeks built - hybrid BM25 + dense retrieval, reranking, the
 * refusal gate, cited answers - without exposing the controls used to study it.
 */
export default function ChatbotApp({ user, onLogout }: ChatbotAppProps) {
  const [resetKey, setResetKey] = useState(0);

  return (
    <div className="app-shell">
      <AppHeader
        title="AirFiber Support Assistant"
        subtitle="Answers from the AirFiber help centre"
        user={user}
        onLogout={onLogout}
        actions={
          <button type="button" className="header-btn" onClick={() => setResetKey((key) => key + 1)}>
            New chat
          </button>
        }
      />
      <main className="app-main">
        <RagPage variant="chatbot" resetKey={resetKey} />
      </main>
    </div>
  );
}
