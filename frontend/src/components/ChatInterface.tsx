import { useState, useRef, useEffect, type KeyboardEvent, type FormEvent } from 'react';
import { ResearchControls } from './ResearchControls';
import type { ChatFile, ChatOptions } from '../api/chatApi';
import { MessageList } from './MessageList';
import { useChat } from '../hooks/useChat';
import {
  MODELS,
  THINKING_LEVEL_LABELS,
  DEFAULT_MODEL_ID,
  DEFAULT_THINKING_LEVEL,
  type ResearchSource,
  type Project,
  type ThinkingLevel,
} from '../types';

interface Props {
  project?: Project;
  onProjectChange: (project: Project) => void;
  sessionId: string;
  getAccessToken: () => Promise<string | null>;
  onMessageSent?: () => void;
  onLoadingChange?: (loading: boolean) => void;
  settingsOpen: boolean;
  onCloseSettings: () => void;
  deletedFileId?: string;
}

export function ChatInterface({ project, onProjectChange, sessionId, getAccessToken, onMessageSent, onLoadingChange, settingsOpen, onCloseSettings, deletedFileId }: Props) {
  const [inputText, setInputText] = useState('');
  const [modelId, setModelId] = useState(DEFAULT_MODEL_ID);
  const [thinkingLevel, setThinkingLevel] = useState<ThinkingLevel>(DEFAULT_THINKING_LEVEL);
  const { messages, isLoading, error, historyError, retryHistory, sendMessage } = useChat(
    sessionId,
    getAccessToken,
    modelId,
    thinkingLevel,
    project?.id,
  );
  const [personaChoices, setPersonaChoices] = useState<Record<string, boolean>>({});
  const [selection, setSelection] = useState<{ sessionId: string; sources: ResearchSource[] }>();
  const [attachmentDraft, setAttachmentDraft] = useState<{ sessionId: string; files: File[] }>();
  const savedContext = [...messages].reverse().find((message) => message.research_context)?.research_context;
  const options: ChatOptions = {
    persona_enabled: personaChoices[sessionId] ?? savedContext?.persona_enabled ?? true,
  };
  const [savedSelections, setSavedSelections] = useState<Record<string, ChatFile[]>>({});
  const savedFiles = savedSelections[sessionId] ?? [];

  useEffect(() => {
    if (!deletedFileId) return;
    setSavedSelections((previous) => Object.fromEntries(Object.entries(previous).map(([id, selection]) => [
      id, selection.filter((file) => file.id !== deletedFileId),
    ])));
  }, [deletedFileId]);
  const sources = selection?.sessionId === sessionId ? selection.sources : [];
  const setSources = (next: ResearchSource[]) => setSelection({ sessionId, sources: next });
  const files = attachmentDraft?.sessionId === sessionId ? attachmentDraft.files : [];
  const setFiles = (next: File[]) => setAttachmentDraft({ sessionId, files: next });

  useEffect(() => {
    setAttachmentDraft((draft) => draft?.sessionId === sessionId ? draft : undefined);
  }, [sessionId]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    onLoadingChange?.(isLoading);
  }, [isLoading, onLoadingChange]);

  const currentModel = MODELS.find((m) => m.id === modelId) ?? MODELS[0];

  const handleModelChange = (newModelId: string) => {
    setModelId(newModelId);
    const model = MODELS.find((m) => m.id === newModelId);
    if (model && !model.thinkingLevels.includes(thinkingLevel)) {
      setThinkingLevel(model.thinkingLevels[1] as ThinkingLevel ?? model.thinkingLevels[0] as ThinkingLevel);
    }
  };

  const handleSubmit = async (e?: FormEvent) => {
    e?.preventDefault();
    const text = inputText.trim();
    if (!text || isLoading) return;
    const ok = await sendMessage(text, options, sources, files, savedFiles);
    if (ok) {
      setInputText('');
      setSources([]);
      onMessageSent?.();
    }
    textareaRef.current?.focus();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      void handleSubmit();
    }
  };

  return (
    <div style={styles.container}>
      {/* Model & thinking level toolbar */}
      <div style={styles.toolbar}>
        <div style={styles.toolbarGroup}>
          <span style={styles.toolbarLabel}>モデル</span>
          <div style={styles.segmentedGroup}>
            {MODELS.map((m) => (
              <button
                key={m.id}
                onClick={() => handleModelChange(m.id)}
                style={{
                  ...styles.segmentedBtn,
                  ...(modelId === m.id ? styles.segmentedBtnActive : {}),
                }}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
        <div style={styles.toolbarGroup}>
          <span style={styles.toolbarLabel}>思考量</span>
          <div style={styles.segmentedGroup}>
            {currentModel.thinkingLevels.map((level) => (
              <button
                key={level}
                onClick={() => setThinkingLevel(level)}
                style={{
                  ...styles.segmentedBtn,
                  ...(thinkingLevel === level ? styles.segmentedBtnActive : {}),
                }}
              >
                {THINKING_LEVEL_LABELS[level]}
              </button>
            ))}
          </div>
        </div>
      </div>

      <ResearchControls key={sessionId} project={project} onProjectChange={onProjectChange}
        options={options} sources={sources} files={files} savedFiles={savedFiles}
        onSavedFiles={(next) => setSavedSelections((previous) => ({ ...previous, [sessionId]: next }))}
        disabled={isLoading} settingsOpen={settingsOpen} onCloseSettings={onCloseSettings}
        onOptions={(next) => setPersonaChoices((previous) => ({
          ...previous, [sessionId]: next.persona_enabled !== false,
        }))}
        onSources={setSources} onFiles={setFiles} getAccessToken={getAccessToken} />
      <MessageList messages={messages} isLoading={isLoading} error={error}
        historyError={historyError} onRetryHistory={retryHistory}
        sessionId={sessionId} projectId={project?.id}
        getAccessToken={getAccessToken} />

      <form onSubmit={(e) => void handleSubmit(e)} style={styles.form}>
        <div style={styles.inputWrapper}>
          <textarea
            ref={textareaRef}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="メッセージを入力… (Ctrl+Enter で送信)"
            rows={3}
            disabled={isLoading}
            style={styles.textarea}
          />
        </div>
        <button
          type="submit"
          disabled={isLoading || inputText.trim().length === 0}
          style={styles.sendBtn}
        >
          送信
        </button>
      </form>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  toolbar: {
    display: 'flex',
    gap: '16px',
    padding: '8px 16px',
    borderBottom: '1px solid #e5e7eb',
    backgroundColor: '#f9fafb',
    flexShrink: 0,
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  toolbarGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  toolbarLabel: {
    fontSize: '12px',
    color: '#6b7280',
    whiteSpace: 'nowrap',
  },
  segmentedGroup: {
    display: 'flex',
    border: '1px solid #d1d5db',
    borderRadius: '6px',
    overflow: 'hidden',
  },
  segmentedBtn: {
    padding: '4px 10px',
    fontSize: '12px',
    border: 'none',
    borderRight: '1px solid #d1d5db',
    backgroundColor: '#fff',
    cursor: 'pointer',
    color: '#374151',
    whiteSpace: 'nowrap',
  },
  segmentedBtnActive: {
    backgroundColor: '#2563eb',
    color: '#fff',
  },
  form: {
    display: 'flex',
    gap: '8px',
    padding: '12px 16px',
    borderTop: '1px solid #e5e7eb',
    backgroundColor: '#fff',
    alignItems: 'flex-end',
  },
  inputWrapper: {
    flex: 1,
    position: 'relative',
  },
  textarea: {
    width: '100%',
    padding: '10px 12px',
    border: '1px solid #d1d5db',
    borderRadius: '8px',
    resize: 'none',
    fontSize: '14px',
    fontFamily: 'inherit',
    boxSizing: 'border-box',
    outline: 'none',
  },
  sendBtn: {
    padding: '10px 20px',
    backgroundColor: '#2563eb',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    fontSize: '14px',
    cursor: 'pointer',
    flexShrink: 0,
    alignSelf: 'flex-end',
  },
};
