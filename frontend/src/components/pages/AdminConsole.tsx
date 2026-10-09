import { useEffect, useState } from 'react';
import type { AuthUser } from '../../services/api';
import AppHeader from '../organisms/AppHeader';
import RagPage from './RagPage';
import ErrorAnalysisPage from './ErrorAnalysisPage';
import Week6Page from './Week6Page';
import Week7Page from './Week7Page';
import Week8Page from './Week8Page';

type TabId = 'week3' | 'week4' | 'week5' | 'week6' | 'week7' | 'week8' | 'week9' | 'chatbot';

type TabDef = { id: TabId; hash: string; label: string; caption: string };

// Week 5 keeps the `#analysis` hash so existing links like #analysis/TR-0055,
// and the hash the error-analysis page writes when a trace is opened, still work.
const TABS: TabDef[] = [
  { id: 'week3', hash: 'week3', label: 'Week 3', caption: 'Baseline RAG' },
  { id: 'week4', hash: 'week4', label: 'Week 4', caption: 'Hybrid retrieval' },
  { id: 'week5', hash: 'analysis', label: 'Week 5', caption: 'Error analysis' },
  { id: 'week6', hash: 'week6', label: 'Week 6', caption: 'Judge validation' },
  { id: 'week7', hash: 'week7', label: 'Week 7', caption: 'Agent vs workflow' },
  { id: 'week8', hash: 'week8', label: 'Week 8', caption: 'Trajectory evals' },
  { id: 'week9', hash: 'week9', label: 'Week 9', caption: 'MCP agent' },
  { id: 'chatbot', hash: 'chatbot', label: 'Chatbot', caption: 'What users see' },
];

// The chat tabs stay mounted once opened so their conversation survives a tab switch.
const KEEP_MOUNTED: TabId[] = ['week3', 'week4', 'week9', 'chatbot'];

function parseHash(): { tab: TabId; traceId?: string } {
  const [section, traceId] = window.location.hash.replace('#', '').split('/');
  const match = TABS.find((tab) => tab.hash === section);
  if (!match) return { tab: 'week4' };
  return { tab: match.id, traceId: match.id === 'week5' ? traceId || undefined : undefined };
}

type AdminConsoleProps = {
  user: AuthUser;
  onLogout: () => void;
};

export default function AdminConsole({ user, onLogout }: AdminConsoleProps) {
  const [route, setRoute] = useState(parseHash);
  const [visited, setVisited] = useState<Set<TabId>>(() => new Set([parseHash().tab]));
  const tab = route.tab;

  useEffect(() => {
    const sync = () => setRoute(parseHash());
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  useEffect(() => {
    setVisited((current) => (current.has(tab) ? current : new Set(current).add(tab)));
  }, [tab]);

  const select = (next: TabDef) => {
    window.location.hash = next.hash;
    setRoute({ tab: next.id });
  };

  const keptChat = (id: TabId) =>
    visited.has(id) ? (
      <div hidden={tab !== id} style={{ height: '100%', width: '100%' }}>
        <RagPage variant={id === 'chatbot' ? 'chatbot' : (id as 'week3' | 'week4' | 'week9')} active={tab === id} />
      </div>
    ) : null;

  return (
    <div className="app-shell">
      <AppHeader
        title="Ask My Documents · Admin console"
        subtitle="Knowledge base and week-by-week evaluations"
        user={user}
        onLogout={onLogout}
      />
      <nav className="app-tabs admin-tabs" role="tablist" aria-label="Weeks">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={`${tab === item.id ? 'is-active' : ''} ${item.id === 'chatbot' ? 'tab-preview' : ''}`}
            onClick={() => select(item)}
          >
            <strong>{item.label}</strong>
            <span>{item.caption}</span>
          </button>
        ))}
      </nav>

      <main className="app-main">
        {KEEP_MOUNTED.map((id) => (
          <div key={id} style={{ display: 'contents' }}>
            {keptChat(id)}
          </div>
        ))}
        {tab === 'week5' ? <ErrorAnalysisPage active initialTraceId={route.traceId} /> : null}
        {tab === 'week6' ? <Week6Page /> : null}
        {tab === 'week7' ? <Week7Page /> : null}
        {tab === 'week8' ? <Week8Page /> : null}
      </main>
    </div>
  );
}
