import { useEffect, useState } from 'react';
import RagPage from './components/pages/RagPage';
import ErrorAnalysisPage from './components/pages/ErrorAnalysisPage';
import Week7Page from './components/pages/Week7Page';

type Tab = 'chat' | 'analysis' | 'week7';

/**
 * Three tabs: chat, error analysis, and the Week 7 agent-vs-workflow view.
 * The hash drives navigation so links are shareable and reloads stay on tab.
 */
function parseHash(): { tab: Tab; traceId?: string } {
  const [section, traceId] = window.location.hash.replace('#', '').split('/');
  if (section === 'analysis') return { tab: 'analysis', traceId: traceId || undefined };
  if (section === 'week7')    return { tab: 'week7' };
  return { tab: 'chat' };
}

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const tab = route.tab;

  useEffect(() => {
    const sync = () => setRoute(parseHash());
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  const select = (next: Tab) => {
    window.location.hash =
      next === 'analysis' ? 'analysis' :
      next === 'week7'    ? 'week7' : '';
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
        <button
          type="button"
          role="tab"
          id="tab-week7"
          aria-selected={tab === 'week7'}
          className={tab === 'week7' ? 'is-active w7-tab-nav-btn' : 'w7-tab-nav-btn'}
          onClick={() => select('week7')}
        >
          Week 7 — Agent vs Workflow
        </button>
      </nav>

      <div hidden={tab !== 'chat'}>
        <RagPage />
      </div>
      {tab === 'analysis' ? <ErrorAnalysisPage active initialTraceId={route.traceId} /> : null}
      {tab === 'week7'    ? <Week7Page /> : null}
    </div>
  );
}
