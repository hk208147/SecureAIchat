// Persona management and source presentation adapted from SABRC (MIT-0).
// Copyright 2026 Amazon.com, Inc. or its affiliates.
import { useEffect, useRef, useState, type Dispatch, type FormEvent, type SetStateAction } from 'react';
import {
  CHAT_FILE_ACCEPT, MAX_CHAT_FILES, fetchPersonas, requireAccessToken, searchSources, setActivePersona,
  setProjectPersona, validateChatFile, type ChatFile, type ChatOptions,
} from '../api/chatApi';
import type { Persona, Project, ResearchSource } from '../types';
import { PersonaManager } from './PersonaManager';
import { SavedFilesDialog } from './SavedFilesDialog';
import './research.css';

interface Props {
  project?: Project;
  onProjectChange: (project: Project) => void;
  options: ChatOptions;
  sources: ResearchSource[];
  files: File[];
  savedFiles: ChatFile[];
  onSavedFiles: (files: ChatFile[]) => void;
  disabled: boolean;
  settingsOpen: boolean;
  onCloseSettings: () => void;
  onOptions: (options: ChatOptions) => void;
  onSources: (sources: ResearchSource[]) => void;
  onFiles: (files: File[]) => void;
  getAccessToken: () => Promise<string | null>;
}

export function ResearchControls({
  options, sources, files, savedFiles, onSavedFiles, disabled, settingsOpen, onCloseSettings,
  onOptions, onSources, onFiles, getAccessToken, project, onProjectChange,
}: Props) {
  const [data, setData] = useState<Awaited<ReturnType<typeof fetchPersonas>>>();
  const [loadError, setLoadError] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [webPanel, setWebPanel] = useState(false);
  const [savedFilesOpen, setSavedFilesOpen] = useState(false);
  const [attachmentError, setAttachmentError] = useState('');
  const [projectError, setProjectError] = useState('');
  const [savingProject, setSavingProject] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const active = data?.personas.find((persona) => persona.id === (project?.persona_id ?? data.activePersonaId));
  const attachmentCount = files.length + savedFiles.length;

  useEffect(() => {
    let cancelled = false;
    setLoadError(false);
    requireAccessToken(getAccessToken).then(fetchPersonas).then(
      (next) => { if (!cancelled) setData(next); },
      () => { if (!cancelled) setLoadError(true); },
    );
    return () => { cancelled = true; };
  }, [getAccessToken, loadAttempt]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (settingsOpen && dialog && !dialog.open) dialog.showModal();
  }, [settingsOpen]);

  function addFiles(incoming: File[]) {
    try {
      const next = [...files, ...incoming];
      if (next.length + savedFiles.length > MAX_CHAT_FILES) {
        throw new Error('1チャットに添付できる資料は5件までです。');
      }
      for (const file of incoming) validateChatFile(file);
      onFiles(next);
      setAttachmentError('');
    } catch (error) {
      setAttachmentError(error instanceof Error ? error.message : '資料を添付できませんでした。');
    }
  }

  async function changeProjectPersona(personaId: string) {
    if (!project) return;
    setSavingProject(true);
    setProjectError('');
    try {
      const token = await requireAccessToken(getAccessToken);
      onProjectChange(await setProjectPersona(token, project.id, personaId));
    } catch (cause) {
      setProjectError(cause instanceof Error ? cause.message : 'Personaを更新できませんでした。');
    } finally {
      setSavingProject(false);
    }
  }

  return (
    <>
      <fieldset className="research-controls" disabled={disabled} aria-label="チャット設定と参考資料">
        <div className="research-toolbar">
          <label>チャット種別
            <select value={options.persona_enabled === false ? 'off' : 'on'} onChange={(event) =>
              onOptions({ persona_enabled: event.target.value === 'on' })}>
              <option value="on">ペルソナ有効</option>
              <option value="off">ペルソナ無効</option>
            </select>
          </label>
          {options.persona_enabled !== false && <span>{active?.name ?? 'アシスタント'}</span>}
          {data?.webSearch && <button type="button" aria-expanded={webPanel} onClick={() =>
            setWebPanel(!webPanel)}>Webで根拠を探す</button>}
        </div>
        <div className="research-toolbar research-attachments">
          <label>ファイルを添付
            <input type="file" multiple accept={CHAT_FILE_ACCEPT} onChange={(event) => {
              addFiles(Array.from(event.target.files ?? []));
              event.target.value = '';
            }} />
          </label>
          <button type="button" onClick={() => setSavedFilesOpen(true)}>{project ? 'プロジェクト資料から選ぶ' : '保存済み資料から選ぶ'}</button>
          <span>{attachmentCount}/{MAX_CHAT_FILES}件</span>
        </div>
        {attachmentError && <p role="alert">{attachmentError}</p>}
        {attachmentCount > 0 && <>
          <p>ファイル全体をこのチャットの送信時に使用します。外すと次の送信から使われません。</p>
          <ul className="research-selection" aria-label="添付ファイル">
            {files.map((file, index) => <li key={index}>
              資料 {index + 1} · {file.name}
              <button type="button" aria-label={file.name + 'を外す'} onClick={() => {
                onFiles(files.filter((_, i) => i !== index));
                setAttachmentError('');
              }}>外す</button>
            </li>)}
            {savedFiles.map((file, index) => <li key={file.id}>
              資料 {files.length + index + 1} · {file.name}
              <button type="button" aria-label={file.name + 'を外す'} onClick={() => {
                onSavedFiles(savedFiles.filter(({ id }) => id !== file.id));
                setAttachmentError('');
              }}>外す</button>
            </li>)}
          </ul>
        </>}
        {webPanel && data?.webSearch && <WebSourcePicker getAccessToken={getAccessToken}
          addSource={(source) => onSources([...sources, source])} selectionFull={sources.length >= 5} />}
        {sources.length > 0 && <ul className="research-selection" aria-label="次の送信で使うWeb出典">
          {sources.map((source, index) => <li key={index}>
            {source.title}{source.locator ? ` · ${source.locator}` : ''}
            <button type="button" onClick={() => onSources(sources.filter((_, i) => i !== index))}>外す</button>
          </li>)}
        </ul>}
      </fieldset>
      {savedFilesOpen && <SavedFilesDialog getAccessToken={getAccessToken}
        projectId={project?.id}
        onClose={() => setSavedFilesOpen(false)}
        selectedIds={savedFiles.map(({ id }) => id)} full={attachmentCount >= MAX_CHAT_FILES}
        onSelect={(file) => {
          if (attachmentCount < MAX_CHAT_FILES && !savedFiles.some(({ id }) => id === file.id)) {
            onSavedFiles([...savedFiles, file]);
          }
        }} />}
      {settingsOpen && <dialog className="research-settings" ref={dialogRef} aria-labelledby="research-settings-title"
        onClose={onCloseSettings}>
        <div className="research-toolbar">
          <h2 id="research-settings-title">設定</h2>
          <button type="button" onClick={() => dialogRef.current?.close()}>閉じる</button>
        </div>
        {loadError && <p role="alert">Persona設定を取得できませんでした。
          <button type="button" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>再試行</button>
        </p>}
        {!data && !loadError && <p role="status">設定を読み込み中…</p>}
        {data && project && <section>
          <h3>{project.name}のプロジェクト設定</h3>
          <label>既定のPersona
            <select value={active?.id ?? 'default'} disabled={savingProject}
              onChange={(event) => void changeProjectPersona(event.target.value)}>
              {data.personas.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
            </select>
          </label>
          {projectError && <p role="alert">{projectError}</p>}
        </section>}
        {data && <PersonaSettings data={data} setData={setData} getAccessToken={getAccessToken} />}
      </dialog>}
    </>
  );
}

type PersonaData = Awaited<ReturnType<typeof fetchPersonas>>;

function PersonaSettings({ data, setData, getAccessToken }: {
  data: PersonaData;
  setData: Dispatch<SetStateAction<PersonaData | undefined>>;
  getAccessToken: Props['getAccessToken'];
}) {
  const [editorId, setEditorId] = useState<string>();
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState('');
  const editor = data.personas.find((persona) => persona.id === editorId && !persona.isDefault);

  async function changeActive(id: string) {
    setPending(true);
    setStatus('');
    try {
      const result = await setActivePersona(await requireAccessToken(getAccessToken), id);
      setData((current) => ({ ...(current ?? data), activePersonaId: result.activePersonaId }));
      setStatus('一般チャットに適用しました。');
    } catch {
      setStatus('Personaの適用に失敗しました。もう一度選んでください。');
    } finally {
      setPending(false);
    }
  }

  function updatePersona(persona: Persona) {
    setData((current = data) => ({
      ...current,
      personas: [...current.personas.filter((item) => item.id !== persona.id), persona],
    }));
    setEditorId(persona.id);
  }

  return (
    <section className="research-editor" aria-label="Persona設定">
      <label>すべてのチャットで使うPersona
        <select value={data.activePersonaId} disabled={pending} onChange={(e) => void changeActive(e.target.value)}>
          {data.personas.map((persona) => <option value={persona.id} key={persona.id}>{persona.name}</option>)}
        </select>
      </label>
      <p role="status">{status}</p>
      <label>編集するPersona
        <select value={editorId ?? ''} disabled={pending} onChange={(e) => setEditorId(e.target.value || undefined)}>
          <option value="">選択してください</option>
          {data.personas.filter((persona) => !persona.isDefault).map((persona) =>
            <option value={persona.id} key={persona.id}>{persona.name}</option>)}
        </select>
      </label>
      <button type="button" disabled={pending} onClick={() => setEditorId('new')}>Personaを作成</button>
      <fieldset disabled={pending} className="research-settings-editor">
        {(editorId === 'new' || editor) && <PersonaManager key={editorId} persona={editor}
          knowledgeBase={data.knowledgeBase} getAccessToken={getAccessToken} onSave={updatePersona}
          onDelete={(id) => {
            setData((current = data) => ({ ...current, personas: current.personas.filter((persona) => persona.id !== id),
              activePersonaId: current.activePersonaId === id ? 'default' : current.activePersonaId }));
            setEditorId(undefined);
          }} />}
      </fieldset>
    </section>
  );
}

function WebSourcePicker({ getAccessToken, addSource, selectionFull }: {
  getAccessToken: Props['getAccessToken'];
  addSource: (source: ResearchSource) => void;
  selectionFull: boolean;
}) {
  const [results, setResults] = useState<ResearchSource[]>([]);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');

  async function search(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setResults([]);
    setStatus('');
    try {
      const result = await searchSources(await requireAccessToken(getAccessToken), query.trim());
      setResults(result.sources);
      if (result.sources.length === 0) setStatus('参照できる出典が見つかりませんでした。');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '資料を取得できませんでした。');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="research-editor">
      <form onSubmit={(e) => void search(e)}>
        <label>AWSに送信する検索語
          <input required maxLength={200} value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <button type="submit" disabled={busy || !query.trim()}>この語で検索</button>
      </form>
      {busy && <p role="status">取得中…</p>}
      {status && <p role="status">{status}</p>}
      {results.length > 0 && <ul className="research-results">
        {results.map((source) => <li key={source.url}>
          <SourceDetails source={source} />
          <button type="button" disabled={selectionFull || !source.excerpt.trim()} onClick={() =>
            addSource(source)}>次の質問に使う</button>
        </li>)}
      </ul>}
      {selectionFull && <p role="status">一度の送信で使えるWeb出典は5件までです。</p>}
    </section>
  );
}

export function SourceDetails({ source }: { source: ResearchSource }) {
  const url = source.url && /^https?:\/\//i.test(source.url) ? source.url : undefined;
  const date = (value: string) => { const d = new Date(value); return isNaN(d.getTime()) ? value : d.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' }); };
  return (
    <details>
      <summary>{source.id && `[${source.id}] `}{source.title}{source.locator && ` · ${source.locator}`}</summary>
      {url && <a href={url} target="_blank" rel="noreferrer noopener">出典を開く</a>}
      {source.retrievedAt && <p>検索日時 {date(source.retrievedAt)}</p>}
      {source.publishedAt && <p>公開日時 {date(source.publishedAt)}</p>}
      <pre className="research-excerpt">{source.excerpt}</pre>
    </details>
  );
}
