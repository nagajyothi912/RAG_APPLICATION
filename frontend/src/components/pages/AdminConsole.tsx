import { useEffect, useState } from 'react';
import type { AuthUser } from '../../services/api';
import { useLabsSwitch } from '../../hooks/useLabsSwitch';
import AppHeader from '../organisms/AppHeader';
import LabsMenu from '../molecules/LabsMenu';
import AdminHome from './AdminHome';
import RagPage from './RagPage';
import ErrorAnalysisPage from './ErrorAnalysisPage';
import Week6Page from './Week6Page';
import Week7Page from './Week7Page';
import Week8Page from './Week8Page';

type LabId = 'week3' | 'week4' | 'week5' | 'week6' | 'week7' | 'week8' | 'week9' | 'chatbot';
type ViewId = 'home' | LabId;

type LabDef = { id: LabId; hash: string; label: string; caption: string };

// The week-by-week course work. Hidden behind the Labs switch, never removed:
// these hashes open their lab whether the switch is on or off. Week 5 keeps the
// `#analysis` hash so existing links like #analysis/TR-0055, and the hash the
// error-analysis page writes when a trace is opened, still work.
const LABS: LabDef[] = [
  { id: 'week3', hash: 'week3', label: 'Week 3', caption: 'Baseline RAG' },
  { id: 'week4', hash: 'week4', label: 'Week 4', caption: 'Hybrid retrieval' },
  { id: 'week5', hash: 'analysis', label: 'Week 5', caption: 'Error analysis' },
  { id: 'week6', hash: 'week6', label: 'Week 6', caption: 'Judge validation' },
  { id: 'week7', hash: 'week7', label: 'Week 7', caption: 'Agent vs workflow' },
  { id: 'week8', hash: 'week8', label: 'Week 8', caption: 'Trajectory evals' },
  { id: 'week9', hash: 'week9', label: 'Week 9', caption: 'MCP agent' },
  { id: 'chatbot', hash: 'chatbot', label: 'Chatbot', caption: 'What users see' },
];

// The chat views stay mounted once opened so their conversation survives a view switch.
const KEEP_MOUNTED: LabId[] = ['week3', 'week4', 'week9', 'chatbot'];

function parseHash(): { view: ViewId; traceId?: string } {
  const [section, traceId] = window.location.hash.replace('#', '').split('/');
  const match = LABS.find((lab) => lab.hash === section);
  if (!match) return { view: 'home' };
  return { view: match.id, traceId: match.id === 'week5' ? traceId || undefined : undefined };
}

type AdminConsoleProps = {
  user: AuthUser;
  onLogout: () => void;
};

export default function AdminConsole({ user, onLogout }: AdminConsoleProps) {
  const [route, setRoute] = useState(parseHash);
  const [visited, setVisited] = useState<Set<ViewId>>(() => new Set([parseHash().view]));
  const { showLabs, setLabs } = useLabsSwitch();
  const view = route.view;
  const lab = LABS.find((item) => item.id === view) ?? null;

  useEffect(() => {
    const sync = () => setRoute(parseHash());
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  useEffect(() => {
    setVisited((current) => (current.has(view) ? current : new Set(current).add(view)));
  }, [view]);

  const openLab = (id: string) => {
    const next = LABS.find((item) => item.id === id);
    if (!next) return;
    window.location.hash = next.hash;
    setRoute({ view: next.id });
  };

  const goHome = () => {
    window.location.hash = 'home';
    setRoute({ view: 'home' });
  };

  const keptChat = (id: LabId) =>
    visited.has(id) ? (
      <div hidden={view !== id} style={{ height: '100%', width: '100%' }}>
        <RagPage variant={id === 'chatbot' ? 'chatbot' : (id as 'week3' | 'week4' | 'week9')} active={view === id} />
      </div>
    ) : null;

  return (
    <div className="app-shell">
      <AppHeader
        title="Ask My Documents · Admin console"
        subtitle="Knowledge base, MCP servers and the support assistant"
        user={user}
        onLogout={onLogout}
        actions={
          <>
            <button
              type="button"
              role="switch"
              aria-checked={showLabs}
              className={`header-btn labs-switch ${showLabs ? 'is-on' : ''}`}
              onClick={() => setLabs(!showLabs)}
              title="Show the week-by-week course labs in the header"
            >
              <span className="labs-switch-track" aria-hidden="true" />
              Labs
            </button>
            {showLabs ? <LabsMenu labs={LABS} currentId={lab?.id ?? null} onSelect={openLab} /> : null}
          </>
        }
      />

      {lab ? (
        <nav className="lab-bar" aria-label="Lab">
          <button type="button" className="lab-bar-back" onClick={goHome}>
            ← Console
          </button>
          <span className="lab-bar-title">
            <strong>{lab.label}</strong> · {lab.caption}
          </span>
          {showLabs ? null : (
            <span className="lab-bar-note">
              Course labs are hidden.{' '}
              <button type="button" onClick={() => setLabs(true)}>
                Show
              </button>
            </span>
          )}
        </nav>
      ) : null}

      <main className="app-main">
        {visited.has('home') ? (
          <div hidden={view !== 'home'} style={{ height: '100%', width: '100%' }}>
            <AdminHome active={view === 'home'} />
          </div>
        ) : null}
        {KEEP_MOUNTED.map((id) => (
          <div key={id} style={{ display: 'contents' }}>
            {keptChat(id)}
          </div>
        ))}
        {view === 'week5' ? <ErrorAnalysisPage active initialTraceId={route.traceId} /> : null}
        {view === 'week6' ? <Week6Page /> : null}
        {view === 'week7' ? <Week7Page /> : null}
        {view === 'week8' ? <Week8Page /> : null}
      </main>
    </div>
  );
}
