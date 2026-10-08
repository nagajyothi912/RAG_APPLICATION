import { useAuth } from './hooks/useAuth';
import Spinner from './components/atoms/Spinner';
import LoginPage from './components/pages/LoginPage';
import ChatbotApp from './components/pages/ChatbotApp';
import AdminConsole from './components/pages/AdminConsole';

/**
 * Role-based entry point. Signed out: the login screen. The chatbot role gets
 * a single support assistant with every week's retrieval work folded in; the
 * admin role gets the console with one tab per week. The role comes from the
 * backend (login or /api/auth/me), and the backend enforces it on every route.
 */
export default function App() {
  const auth = useAuth();

  if (auth.restoring) {
    return (
      <div className="login-screen">
        <Spinner label="Restoring your session" />
      </div>
    );
  }

  if (!auth.user) {
    return <LoginPage onLogin={auth.login} notice={auth.notice} />;
  }

  return auth.user.role === 'admin' ? (
    <AdminConsole user={auth.user} onLogout={auth.logout} />
  ) : (
    <ChatbotApp user={auth.user} onLogout={auth.logout} />
  );
}
