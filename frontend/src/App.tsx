import { useState, useCallback, useEffect } from 'react';
import { signInWithRedirect } from 'aws-amplify/auth';
import { Hub } from 'aws-amplify/utils';
import { useAuth } from './hooks/useAuth';
import { SavedFilesDialog } from './components/SavedFilesDialog';
import { SessionList } from './components/SessionList';
import { ChatInterface } from './components/ChatInterface';
import { createProject, fetchProjects, requireAccessToken } from './api/chatApi';
import type { Project } from './types';

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
  const [savedFilesOpen, setSavedFilesOpen] = useState(false);
  const [deletedFileId, setDeletedFileId] = useState<string>();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [isCurrentSessionLoading, setIsCurrentSessionLoading] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>();
  const [projectName, setProjectName] = useState('');
  const [projectError, setProjectError] = useState('');
  const [creatingProject, setCreatingProject] = useState(false);
  const [projectLoadAttempt, setProjectLoadAttempt] = useState(0);
  const project = projects.find(({ id }) => id === projectId);

  useEffect(() => {
    if (!isAuthenticated) return;
    let current = true;
    requireAccessToken(getAccessToken).then(fetchProjects).then(({ projects }) => {
      if (current) setProjects((previous) => {
        const byId = new Map(projects.map((item) => [item.id, item]));
        for (const item of previous) byId.set(item.id, item);
        return [...byId.values()];
      });
    }, () => {
      if (current) setProjectError('プロジェクト一覧を読み込めませんでした。');
    });
    return () => { current = false; };
  }, [isAuthenticated, getAccessToken, projectLoadAttempt]);

  function switchProject(id?: string) {
    setProjectId(id);
    setSessionId(newSessionId());
    setIsCurrentSessionLoading(false);
    setSavedFilesOpen(false);
    setDeletedFileId(undefined);
    setSettingsOpen(false);
    if (isMobile) setIsSidebarOpen(false);
  }

  async function addProject(event: React.FormEvent) {
    event.preventDefault();
    if (!projectName.trim() || creatingProject) return;
    setCreatingProject(true);
    setProjectError('');
    try {
      const created = await createProject(await requireAccessToken(getAccessToken), projectName.trim());
      setProjects((previous) => [...previous.filter(({ id }) => id !== created.id), created]);
      setProjectName('');
      switchProject(created.id);
    } catch (cause) {
      setProjectError(cause instanceof Error ? cause.message : 'プロジェクトを作成できませんでした。');
    } finally {
      setCreatingProject(false);
    }
  }

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
        <span style={styles.headerTitle}>Secure AI Chat · {project?.name ?? '一般チャット'}</span>
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
          key={`sessions:${projectId ?? 'general'}`}
          projectId={projectId}
          projectControls={
            <div className="project-controls">
              <label>プロジェクト
                <select value={projectId ?? ''} onChange={(event) => switchProject(event.target.value || undefined)}>
                  <option value="">一般チャット</option>
                  {projects.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
                </select>
              </label>
              <form onSubmit={(event) => void addProject(event)}>
                <input aria-label="新規プロジェクト名" placeholder="新規プロジェクト名"
                  value={projectName} maxLength={80} onChange={(event) => setProjectName(event.target.value)} />
                <button disabled={creatingProject || !projectName.trim()}>作成</button>
              </form>
              {projectError && <p role="alert">{projectError}{' '}
                <button type="button" onClick={() => {
                  setProjectError('');
                  setProjectLoadAttempt((attempt) => attempt + 1);
                }}>一覧を再読み込み</button>
              </p>}
            </div>
          }
          currentSessionId={sessionId}
          getAccessToken={getAccessToken}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
          onDeleteSession={handleDeleteSession}
          loadingSessionId={isCurrentSessionLoading ? sessionId : undefined}
          refreshKey={sessionRefreshKey}
          hidden={isMobile && !isSidebarOpen}
          onOpenSavedFiles={() => {
            setIsSidebarOpen(false);
            setSavedFilesOpen(true);
          }}
          onOpenSettings={() => {
            setIsSidebarOpen(false);
            setSettingsOpen(true);
          }}
        />
        <ChatInterface
          key={`chat:${projectId ?? 'general'}`}
          project={project}
          onProjectChange={(updated) => setProjects((previous) =>
            previous.map((item) => item.id === updated.id ? updated : item))}
          sessionId={sessionId}
          getAccessToken={getAccessToken}
          onMessageSent={handleMessageSent}
          onLoadingChange={setIsCurrentSessionLoading}
          settingsOpen={settingsOpen}
          deletedFileId={deletedFileId}
          onCloseSettings={() => setSettingsOpen(false)}
        />
      </div>
      {savedFilesOpen && <SavedFilesDialog getAccessToken={getAccessToken}
        projectId={projectId}
        onClose={() => setSavedFilesOpen(false)} onDelete={setDeletedFileId} />}
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
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
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
