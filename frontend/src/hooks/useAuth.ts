import { useCallback, useEffect, useState } from 'react';
import {
  SESSION_EXPIRED_EVENT,
  getCurrentUser,
  getToken,
  login as loginRequest,
  setToken,
  type AuthUser,
  type Role,
} from '../services/api';

export type AuthState = {
  user: AuthUser | null;
  /** True while a stored token is being checked on first load. */
  restoring: boolean;
  login: (username: string, password: string, role: Role) => Promise<void>;
  logout: () => void;
  /** Set when the session ended on its own (expired, server restarted). */
  notice: string | null;
};

export function useAuth(): AuthState {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [restoring, setRestoring] = useState(() => Boolean(getToken()));
  const [notice, setNotice] = useState<string | null>(null);

  // A stored token is only a claim until the backend confirms it; the role in
  // it decides which app is shown, so it is never read client-side.
  useEffect(() => {
    if (!getToken()) {
      return;
    }
    getCurrentUser()
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setRestoring(false));
  }, []);

  useEffect(() => {
    const expired = () => {
      setToken(null);
      setUser(null);
      setNotice('Your session ended. Sign in again.');
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
  }, []);

  const login = useCallback(async (username: string, password: string, role: Role) => {
    const result = await loginRequest(username, password, role);
    setToken(result.token);
    setNotice(null);
    setUser(result.user);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setNotice(null);
    window.location.hash = '';
  }, []);

  return { user, restoring, login, logout, notice };
}
