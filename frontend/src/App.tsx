import { useState, useCallback, useEffect } from 'react';
import { signInWithRedirect } from 'aws-amplify/auth';
import { Hub } from 'aws-amplify/utils';
import { useAuth } from './hooks/useAuth';
import { SessionList } from './components/SessionList';
import { ChatInterface } from './components/ChatInterface';

function newSessionId(): string {
  return crypto.randomUUID();
}

export default function App() {
  const { isAuthenticated, isLoading, getAccessToken, signOut } = useAuth();
  const [sessionId, setSessionId] = useState(() => newSessionId());
  const [callbackError, setCallbackError] = useState<string | null>(null);
  const [sessionRefreshKey, setSessionRefreshKey] = useState(0);
  const [isMobile, setIsMobile] = useState(() => window.innerWidth <= 640);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isCurrentSessionLoading, setIsCurrentSessionLoading] = useState(false);

  // R01: listen for OAuth callback failure on /callback route
  useEffect(() => {
    if (window.location.pathname !== '/callback') return;
    const unsubscribe = Hub.listen('auth', ({ payload: { event } }) => {
      if (event === 'signInWithRedirect_failure') {
        setCallbackError('認証に失敗しました。再度サインインしてください。');
        unsubscribe();
      }
    });
    return () => unsubscribe();
  }, []);

  // R01: clean up /callback URL after successful auth
  useEffect(() => {
    if (!isLoading && isAuthenticated && window.location.pathname === '/callback') {
      window.history.replaceState({}, '', '/');
    }
  }, [isLoading, isAuthenticated]);

  // R13: track mobile breakpoint for responsive sidebar
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 640px)');
    const handler = (e: MediaQueryListEvent) => {
      setIsMobile(e.matches);
      if (!e.matches) setIsSidebarOpen(false);
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const handleNewSession = useCallback(() => {
    setSessionId(newSessionId());
    if (isMobile) setIsSidebarOpen(false);
  }, [isMobile]);

  const handleSelectSession = useCallback(
    (id: string) => {
      setSessionId(id);
      if (isMobile) setIsSidebarOpen(false);
    },
    [isMobile],
  );

  // R03: increment to trigger session list refresh after a message is sent
  const handleMessageSent = useCallback(() => {
    setSessionRefreshKey((k) => k + 1);
  }, []);

  const handleDeleteSession = useCallback(
    (deletedId: string) => {
      if (deletedId === sessionId) {
        setIsCurrentSessionLoading(false);
        setSessionId(newSessionId());
      }
    },
    [sessionId],
  );

  if (isLoading) {
    return (
      <div style={styles.center}>
        <p style={styles.hint}>認証確認中…</p>
      </div>
    );
  }

  // R01: show recoverable error if OAuth callback failed
  if (callbackError && window.location.pathname === '/callback') {
    return (
      <div style={styles.center}>
        <p style={styles.errorText}>{callbackError}</p>
        <button
          onClick={() => void signInWithRedirect()}
          style={styles.signInBtn}
        >
          再度サインイン
        </button>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div style={styles.center}>
        <h1 style={styles.title}>Secure AI Chat</h1>
        <button
          onClick={() => void signInWithRedirect()}
          style={styles.signInBtn}
        >
          サインイン
        </button>
      </div>
    );
  }

  return (
    <div style={styles.app}>
      <header style={styles.header}>
        {/* R13: hamburger button visible only on mobile */}
        {isMobile && (
          <button
            onClick={() => setIsSidebarOpen((o) => !o)}
            style={styles.hamburger}
            aria-label="メニュー"
          >
            ☰
          </button>
        )}
        <span style={styles.headerTitle}>Secure AI Chat</span>
        <button onClick={() => void signOut()} style={styles.signOutBtn}>
          サインアウト
        </button>
      </header>

      <div style={styles.main}>
        {/* R13: overlay closes sidebar on mobile backdrop tap */}
        {isMobile && isSidebarOpen && (
          <div
            onClick={() => setIsSidebarOpen(false)}
            style={styles.overlay}
            aria-hidden="true"
          />
        )}
        <SessionList
          currentSessionId={sessionId}
          getAccessToken={getAccessToken}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
          onDeleteSession={handleDeleteSession}
          loadingSessionId={isCurrentSessionLoading ? sessionId : undefined}
          refreshKey={sessionRefreshKey}
          hidden={isMobile && !isSidebarOpen}
        />
        <ChatInterface
          sessionId={sessionId}
          getAccessToken={getAccessToken}
          onMessageSent={handleMessageSent}
          onLoadingChange={setIsCurrentSessionLoading}
        />
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  app: {
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    fontSize: '14px',
    color: '#111',
    backgroundColor: '#fff',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '12px 20px',
    borderBottom: '1px solid #e5e7eb',
    backgroundColor: '#fff',
    flexShrink: 0,
  },
  headerTitle: {
    fontWeight: 700,
    fontSize: '16px',
  },
  hamburger: {
    fontSize: '18px',
    padding: '4px 8px',
    border: 'none',
    backgroundColor: 'transparent',
    cursor: 'pointer',
    color: '#374151',
    marginRight: '8px',
  },
  signOutBtn: {
    fontSize: '13px',
    padding: '6px 14px',
    borderRadius: '6px',
    border: '1px solid #d1d5db',
    backgroundColor: '#fff',
    cursor: 'pointer',
    color: '#374151',
  },
  main: {
    flex: 1,
    display: 'flex',
    overflow: 'hidden',
    position: 'relative',
  },
  overlay: {
    position: 'fixed',
    inset: 0,
    backgroundColor: 'rgba(0,0,0,0.3)',
    zIndex: 49,
  },
  center: {
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '24px',
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  title: {
    fontSize: '24px',
    fontWeight: 700,
    color: '#111',
    margin: 0,
  },
  hint: {
    color: '#6b7280',
    margin: 0,
  },
  errorText: {
    color: '#dc2626',
    margin: 0,
  },
  signInBtn: {
    padding: '12px 32px',
    backgroundColor: '#2563eb',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    fontSize: '16px',
    cursor: 'pointer',
  },
};
