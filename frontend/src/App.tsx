import { useEffect, useState } from 'react';
import RagPage from './components/pages/RagPage';
import ErrorAnalysisPage from './components/pages/ErrorAnalysisPage';

type Tab = 'chat' | 'analysis';

/**
 * Two tabs rather than a router: the app has exactly two screens and adding a
 * router dependency to switch between them would be more moving parts than the
 * problem has. The analysis tab is mounted lazily, so a session that never
 * opens it pays nothing for it.
 */
function parseHash(): { tab: Tab; traceId?: string } {
  const [section, traceId] = window.location.hash.replace('#', '').split('/');
  return section === 'analysis' ? { tab: 'analysis', traceId: traceId || undefined } : { tab: 'chat' };
}

export default function App() {
  // The tab lives in the URL hash so a trace review is a link someone can send,
  // and so a reload during one does not bounce back to the chat.
  const [route, setRoute] = useState(parseHash);
  const tab = route.tab;

  useEffect(() => {
    const sync = () => setRoute(parseHash());
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  const select = (next: Tab) => {
    window.location.hash = next === 'analysis' ? 'analysis' : '';
    setRoute({ tab: next });
  };

  return (
    <div className="app-shell">
      <nav className="app-tabs" role="tablist" aria-label="Sections">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'chat'}
          className={tab === 'chat' ? 'is-active' : undefined}
          onClick={() => select('chat')}
        >
          Ask my documents
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'analysis'}
          className={tab === 'analysis' ? 'is-active' : undefined}
          onClick={() => select('analysis')}
        >
          Error analysis
        </button>
      </nav>

      <div hidden={tab !== 'chat'}>
        <RagPage />
      </div>
      {tab === 'analysis' ? <ErrorAnalysisPage active initialTraceId={route.traceId} /> : null}
    </div>
  );
}
