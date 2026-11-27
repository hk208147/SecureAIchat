import { useEffect, useRef, useState } from 'react';
import { SourceDetails } from './ResearchControls';
import { getDocumentDownload, getHistoryFileDownload, requireAccessToken } from '../api/chatApi';
import type { Message, ResearchSource } from '../types';
import { THINKING_LEVEL_LABELS, MODELS } from '../types';

interface Props {
  sessionId: string;
  projectId?: string;
  messages: Message[];
  isLoading: boolean;
  error: string | null;
  historyError?: string | null;
  onRetryHistory?: () => void;
  getAccessToken: () => Promise<string | null>;
}

// USD per 1M tokens. AU Geo Cross-Region, on-demand Standard tier.
// Sources:
//   - AWS Bedrock pricing page: aws.amazon.com/bedrock/pricing/
//   - Anthropic public price list: anthropic.com/pricing — "In-Region & Geo Cross Region" rows
// Last verified: 2026-11.
const MODEL_PRICING: Record<string, { inputPer1M: number; outputPer1M: number }> = {
  'au.anthropic.claude-sonnet-4-6':  { inputPer1M: 3.30,  outputPer1M: 16.50 },
  'au.anthropic.claude-opus-4-6-v1': { inputPer1M: 5.50,  outputPer1M: 27.50 },
};

function estimatedCost(modelId?: string, inputTokens?: number, outputTokens?: number): string | null {
  if (!modelId || inputTokens == null || outputTokens == null) return null;
  const pricing = MODEL_PRICING[modelId];
  if (!pricing) return null;
  const cost = (inputTokens * pricing.inputPer1M + outputTokens * pricing.outputPer1M) / 1_000_000;
  return `~$${cost.toFixed(6)}`;
}

function modelLabel(modelId?: string): string {
  if (!modelId) return '';
  const found = MODELS.find((m) => m.id === modelId);
  return found ? found.label : modelId;
}

function AssistantMeta({ message }: { message: Message }) {
  const parts: string[] = [];
  if (message.model_used) parts.push(modelLabel(message.model_used));
  if (message.thinking_level) {
    const label = THINKING_LEVEL_LABELS[message.thinking_level as keyof typeof THINKING_LEVEL_LABELS];
    if (label) parts.push(`思考: ${label}`);
  }
  const cost = estimatedCost(message.model_used, message.usage?.input_tokens, message.usage?.output_tokens);
  if (cost) parts.push(cost);
  if (message.response_time_ms != null) {
    parts.push(`${(message.response_time_ms / 1000).toFixed(1)}秒`);
  }
  if (parts.length === 0) return null;
  return <p style={metaStyle}>{parts.join(' · ')}</p>;
}

const metaStyle: React.CSSProperties = {
  margin: '6px 0 0',
  fontSize: '11px',
  color: '#888',
};

export function MessageList({ messages, isLoading, error, historyError, onRetryHistory, getAccessToken, sessionId, projectId }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  return (
    <div style={styles.container}>
      {messages.length === 0 && !isLoading && historyError && (
        <div style={styles.historyError}>
          <p style={styles.historyErrorText}>{historyError}</p>
          {onRetryHistory && (
            <button onClick={onRetryHistory} style={styles.retryBtn}>再試行</button>
          )}
        </div>
      )}

      {messages.length === 0 && !isLoading && !historyError && (
        <p style={styles.empty}>メッセージを入力して会話を始めましょう。</p>
      )}

      {messages.map((msg) => (
        <div
          key={msg.id}
          style={{
            ...styles.row,
            justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
          }}
        >
          <div
            style={{
              ...styles.bubble,
              ...(msg.role === 'user' ? styles.userBubble : styles.assistantBubble),
            }}
          >
            <p style={styles.content}>{msg.content}</p>
            {msg.attachments && <HistoryAttachments attachment={msg.attachments} getAccessToken={getAccessToken}
              sessionId={sessionId} projectId={projectId} />}
            {msg.role === 'assistant' && (
              <>
                <AssistantMeta message={msg} />
                {!!msg.citations?.length && <ul className="research-citations" aria-label="回答の出典">
                  {msg.citations.map((source) => <li key={source.id}>
                    <SourceDetails source={source} />
                    {source.documentId && source.personaId && <DocumentDownload source={source} getAccessToken={getAccessToken} />}
                  </li>)}
                </ul>}
              </>
            )}
          </div>
        </div>
      ))}

      {isLoading && (
        <div style={{ ...styles.row, justifyContent: 'flex-start' }}>
          <div style={{ ...styles.bubble, ...styles.assistantBubble }}>
            <span style={styles.dots}>
              <span style={styles.dot} />
              <span style={{ ...styles.dot, animationDelay: '0.15s' }} />
              <span style={{ ...styles.dot, animationDelay: '0.3s' }} />
            </span>
          </div>
        </div>
      )}

      {error && (
        <div style={styles.error}>
          エラー: {error}
        </div>
      )}

      <div ref={bottomRef} />

      <style>{dotAnimation}</style>
    </div>
  );
}

function HistoryAttachments({ attachment, getAccessToken, sessionId, projectId }: {
  attachment: NonNullable<Message['attachments']>;
  getAccessToken: Props['getAccessToken'];
  sessionId: string;
  projectId?: string;
}) {
  const [status, setStatus] = useState('');
  return <ul className="research-selection" aria-label="送信済みの添付資料">
    {attachment.files.map((name, index) => <li key={index}>
      <button type="button" className="research-download" onClick={async () => {
        try {
          setStatus('');
          const token = await requireAccessToken(getAccessToken);
          const { url } = await getHistoryFileDownload(token, sessionId, attachment.id, index, projectId);
          if (!url.startsWith('https://')) throw new Error('ダウンロード先を確認できません。');
          window.location.assign(url);
        } catch (cause) {
          setStatus(cause instanceof Error ? cause.message : '添付資料を取得できませんでした。');
        }
      }}>{name}をダウンロード</button>
    </li>)}
    {status && <li role="status">{status}</li>}
  </ul>;
}

const dotAnimation = `
  @keyframes bounce {
    0%, 80%, 100% { transform: translateY(0); }
    40% { transform: translateY(-6px); }
  }
`;

function DocumentDownload({ source, getAccessToken }: {
  source: ResearchSource;
  getAccessToken: () => Promise<string | null>;
}) {
  const [status, setStatus] = useState('');
  return (
    <>
      <button type="button" className="research-download" onClick={async () => {
        if (!source.documentId || !source.personaId) return;
        try {
          setStatus('');
          const token = await requireAccessToken(getAccessToken);
          const { url } = await getDocumentDownload(token, source.personaId, source.documentId);
          if (!url.startsWith('https://')) throw new Error('ダウンロード先を確認できません。');
          window.location.assign(url);
        } catch {
          setStatus('原本を取得できませんでした。登録状態を確認してください。');
        }
      }}>原本をダウンロード</button>
      {status && <span role="status">{status}</span>}
    </>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    flex: 1,
    overflowY: 'auto',
    padding: '16px',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  empty: {
    textAlign: 'center',
    color: '#888',
    marginTop: '40px',
  },
  row: {
    display: 'flex',
  },
  bubble: {
    maxWidth: '75%',
    borderRadius: '16px',
    padding: '10px 14px',
    wordBreak: 'break-word',
  },
  userBubble: {
    backgroundColor: '#2563eb',
    color: '#fff',
  },
  assistantBubble: {
    backgroundColor: '#f3f4f6',
    color: '#111',
  },
  content: {
    margin: 0,
    whiteSpace: 'pre-wrap',
  },
  usage: {
    margin: '6px 0 0',
    fontSize: '11px',
    color: '#888',
  },
  dots: {
    display: 'flex',
    gap: '4px',
    alignItems: 'center',
    height: '20px',
  },
  dot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    backgroundColor: '#888',
    display: 'inline-block',
    animation: 'bounce 1.2s infinite',
  },
  error: {
    backgroundColor: '#fef2f2',
    border: '1px solid #fca5a5',
    borderRadius: '8px',
    padding: '10px 14px',
    color: '#b91c1c',
    fontSize: '14px',
  },
  historyError: {
    textAlign: 'center' as const,
    marginTop: '40px',
  },
  historyErrorText: {
    color: '#b91c1c',
    fontSize: '14px',
    margin: '0 0 10px',
  },
  retryBtn: {
    fontSize: '13px',
    padding: '5px 14px',
    borderRadius: '6px',
    border: '1px solid #d1d5db',
    backgroundColor: '#fff',
    color: '#374151',
    cursor: 'pointer',
  },
};
