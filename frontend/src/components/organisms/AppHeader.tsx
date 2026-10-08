import type { ReactNode } from 'react';
import type { AuthUser } from '../../services/api';

type AppHeaderProps = {
  title: string;
  subtitle: string;
  user: AuthUser;
  /** Buttons on the right, before Sign out. */
  actions?: ReactNode;
  onLogout: () => void;
};

const ROLE_LABEL = { chatbot: 'User', admin: 'Admin' } as const;

export default function AppHeader({ title, subtitle, user, actions, onLogout }: AppHeaderProps) {
  return (
    <header className="app-header">
      <div className="app-brand">
        <span className="app-brand-mark" aria-hidden="true">
          AF
        </span>
        <div>
          <p className="app-brand-title">{title}</p>
          <p className="app-brand-sub">{subtitle}</p>
        </div>
      </div>
      <div className="app-header-actions">
        {actions}
        <span className="user-chip" title={`Signed in as ${user.username}`}>
          <span className={`role-dot role-${user.role}`} aria-hidden="true" />
          <span className="user-chip-name">{user.username}</span>
          <span className="user-chip-role">{ROLE_LABEL[user.role]}</span>
        </span>
        <button type="button" className="header-btn" onClick={onLogout}>
          Sign out
        </button>
      </div>
    </header>
  );
}
