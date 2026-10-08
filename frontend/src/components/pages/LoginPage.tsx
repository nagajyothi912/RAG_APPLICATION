import { useState, type FormEvent } from 'react';
import Button from '../atoms/Button';
import StatusMessage from '../atoms/StatusMessage';
import type { Role } from '../../services/api';

type LoginPageProps = {
  onLogin: (username: string, password: string, role: Role) => Promise<void>;
  notice: string | null;
};

const ROLES: { value: Role; title: string; body: string }[] = [
  {
    value: 'chatbot',
    title: 'User',
    body: 'Have a doubt about your AirFiber connection? Ask about plans, bills, refunds, installation or a connection problem.',
  },
  {
    value: 'admin',
    title: 'Admin',
    body: 'Manage the help-centre articles and review each week of the RAG and agent evaluations.',
  },
];

export default function LoginPage({ onLogin, notice }: LoginPageProps) {
  const [role, setRole] = useState<Role>('chatbot');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!username.trim() || !password) {
      setError('Enter a username and password.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onLogin(username.trim(), password, role);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.');
      setSubmitting(false);
    }
  };

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit} noValidate>
        <div className="login-brand">
          <span className="app-brand-mark" aria-hidden="true">
            AF
          </span>
          <div>
            <h1>Ask My Documents</h1>
            <p>AirFiber help centre · grounded answers with sources</p>
          </div>
        </div>

        <fieldset className="role-picker">
          <legend>Sign in as</legend>
          {ROLES.map((option) => (
            <label
              key={option.value}
              className={`role-option ${role === option.value ? 'is-active' : ''}`}
            >
              <input
                type="radio"
                name="role"
                value={option.value}
                checked={role === option.value}
                onChange={() => {
                  setRole(option.value);
                  setError(null);
                }}
              />
              <span className="role-option-title">
                <span className={`role-dot role-${option.value}`} aria-hidden="true" />
                {option.title}
              </span>
              <span className="role-option-body">{option.body}</span>
            </label>
          ))}
        </fieldset>

        <label className="login-field" htmlFor="login-username">
          <span>Username</span>
          <input
            id="login-username"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            disabled={submitting}
          />
        </label>
        <label className="login-field" htmlFor="login-password">
          <span>Password</span>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={submitting}
          />
        </label>

        <StatusMessage tone="info">{error ? null : notice}</StatusMessage>
        <StatusMessage tone="error">{error}</StatusMessage>

        <Button type="submit" loading={submitting}>
          {role === 'admin' ? 'Sign in to admin console' : 'Start chatting'}
        </Button>
      </form>
    </div>
  );
}
