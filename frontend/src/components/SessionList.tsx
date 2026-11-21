import { useEffect, useState, useCallback } from 'react';
import type { Session } from '../types';
import { fetchSessions, deleteSession } from '../api/chatApi';

interface Props {
  currentSessionId: string;
  getAccessToken: () => Promise<string | null>;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  onDeleteSession: (sessionId: string) => void;
  loadingSessionId?: string;
  refreshKey?: number;
  hidden?: boolean;
}

export function SessionList({
  currentSessionId,
  getAccessToken,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  loadingSessionId,
  refreshKey,
  hidden,
}: Props) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadSessions = useCallback(async () => {
    const token = await getAccessToken();
    if (!token) return;
    try {
      const data = await fetchSessions(token);
      setSessions(data.sessions);
    } catch {
      // non-fatal: silently fail
    } finally {
      setLoading(false);
    }
  }, [getAccessToken]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions, refreshKey]);

  const handleDeleteConfirm = useCallback(async () => {
    if (!pendingDeleteId) return;
    const token = await getAccessToken();
    if (!token) return;
    setDeleting(true);
    try {
      await deleteSession(pendingDeleteId, token);
      setSessions((prev) => prev.filter((s) => s.session_id !== pendingDeleteId));
      onDeleteSession(pendingDeleteId);
    } catch {
      // keep pendingDeleteId so user can retry
    } finally {
      setDeleting(false);
      setPendingDeleteId(null);
    }
  }, [pendingDeleteId, getAccessToken, onDeleteSession]);

  return (
    <div style={{ ...styles.container, ...(hidden ? { display: 'none' } : {}) }}>
      <div style={styles.header}>
        <span style={styles.title}>会話一覧</span>
        <button onClick={onNewSession} style={styles.newBtn} title="新しい会話">
          + 新規
        </button>
      </div>

      {loading && <p style={styles.hint}>読み込み中…</p>}

      {!loading && sessions.length === 0 && (
        <p style={styles.hint}>会話履歴なし</p>
      )}

      <ul style={styles.list}>
        {sessions.map((s) => (
          <li key={s.session_id} style={styles.item}>
            {pendingDeleteId === s.session_id ? (
              <div style={styles.confirmRow}>
                <span style={styles.confirmLabel}>
                  「{s.firstMessage || '(空の会話)'}」を削除しますか？
                </span>
                <div style={styles.confirmButtons}>
                  <button
                    onClick={() => void handleDeleteConfirm()}
                    disabled={deleting}
                    style={styles.confirmBtn}
                  >
                    削除
                  </button>
                  <button
                    onClick={() => setPendingDeleteId(null)}
                    disabled={deleting}
                    style={styles.cancelBtn}
                  >
                    キャンセル
                  </button>
                </div>
              </div>
            ) : (
              <div style={styles.sessionRow}>
                <button
                  onClick={() => onSelectSession(s.session_id)}
                  style={{
                    ...styles.sessionBtn,
                    ...(s.session_id === currentSessionId ? styles.activeBtn : {}),
                  }}
                >
                  <span style={styles.label}>
                    {s.firstMessage || '(空の会話)'}
                  </span>
                </button>
                <button
                  onClick={() => setPendingDeleteId(s.session_id)}
                  disabled={s.session_id === loadingSessionId}
                  style={{
                    ...styles.deleteBtn,
                    ...(s.session_id === loadingSessionId ? styles.deleteBtnDisabled : {}),
                  }}
                  title={s.session_id === loadingSessionId ? '生成中は削除できません' : '削除'}
                >
                  ×
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    width: '240px',
    minWidth: '200px',
    borderRight: '1px solid #e5e7eb',
    display: 'flex',
    flexDirection: 'column',
    backgroundColor: '#f9fafb',
    overflowY: 'auto',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '12px 16px',
    borderBottom: '1px solid #e5e7eb',
  },
  title: {
    fontWeight: 600,
    fontSize: '14px',
    color: '#374151',
  },
  newBtn: {
    fontSize: '13px',
    padding: '4px 10px',
    borderRadius: '6px',
    border: '1px solid #d1d5db',
    backgroundColor: '#fff',
    cursor: 'pointer',
    color: '#374151',
  },
  list: {
    listStyle: 'none',
    margin: 0,
    padding: '8px 0',
  },
  item: {
    margin: 0,
  },
  sessionRow: {
    display: 'flex',
    alignItems: 'center',
  },
  sessionBtn: {
    flex: 1,
    textAlign: 'left',
    padding: '8px 8px 8px 16px',
    border: 'none',
    backgroundColor: 'transparent',
    cursor: 'pointer',
    color: '#374151',
    minWidth: 0,
  },
  activeBtn: {
    backgroundColor: '#e0e7ff',
    color: '#1d4ed8',
    fontWeight: 500,
  },
  label: {
    display: 'block',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    fontSize: '13px',
  },
  deleteBtn: {
    flexShrink: 0,
    padding: '4px 8px',
    marginRight: '6px',
    border: 'none',
    backgroundColor: 'transparent',
    cursor: 'pointer',
    color: '#9ca3af',
    fontSize: '14px',
    lineHeight: 1,
  },
  deleteBtnDisabled: {
    opacity: 0.3,
    cursor: 'not-allowed',
  },
  confirmRow: {
    padding: '8px 12px',
    backgroundColor: '#fef2f2',
    borderLeft: '3px solid #ef4444',
  },
  confirmLabel: {
    display: 'block',
    fontSize: '12px',
    color: '#374151',
    marginBottom: '6px',
    wordBreak: 'break-all',
  },
  confirmButtons: {
    display: 'flex',
    gap: '6px',
  },
  confirmBtn: {
    fontSize: '12px',
    padding: '3px 10px',
    borderRadius: '4px',
    border: '1px solid #ef4444',
    backgroundColor: '#ef4444',
    color: '#fff',
    cursor: 'pointer',
  },
  cancelBtn: {
    fontSize: '12px',
    padding: '3px 10px',
    borderRadius: '4px',
    border: '1px solid #d1d5db',
    backgroundColor: '#fff',
    color: '#374151',
    cursor: 'pointer',
  },
  hint: {
    fontSize: '13px',
    color: '#9ca3af',
    padding: '8px 16px',
    margin: 0,
  },
};
