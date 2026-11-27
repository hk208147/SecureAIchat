// Persona fields and editor workflow adapted from SABRC PersonaManager.jsx (MIT-0).
// Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
import { useEffect, useState, type FormEvent } from 'react';
import {
  deleteDocument, deletePersona, fetchDocuments, requireAccessToken, savePersona, uploadDocument,
} from '../api/chatApi';
import type { ChatType, Persona, PersonaForm, ResearchDocument } from '../types';
import { encodeDocument } from './documentText';

const blank: PersonaForm = { name: '', description: '', prompt: '', chatType: 'LLM' };

interface Props {
  persona?: Persona;
  knowledgeBase: boolean;
  getAccessToken: () => Promise<string | null>;
  onSave: (persona: Persona) => void;
  onDelete: (id: string) => void;
}

export function PersonaManager({ persona, knowledgeBase, getAccessToken, onSave, onDelete }: Props) {
  const [form, setForm] = useState<PersonaForm>(persona ?? blank);
  const [documents, setDocuments] = useState<ResearchDocument[]>([]);
  const [pendingFile, setPendingFile] = useState<{ file: File; id: string }>();
  const [confirmation, setConfirmation] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);

  const loadDocuments = async () => {
    if (!persona || !knowledgeBase) return;
    const token = await requireAccessToken(getAccessToken);
    const result = await fetchDocuments(token, persona.id);
    setDocuments(result.documents);
  };

  useEffect(() => {
    let active = true;
    if (persona && knowledgeBase) {
      requireAccessToken(getAccessToken).then((token) => fetchDocuments(token, persona.id)).then(
        (result) => { if (active) setDocuments(result.documents); },
        () => { if (active) setStatus('資料の状態を読み込めませんでした。'); },
      );
    }
    return () => { active = false; };
  }, [persona, knowledgeBase, getAccessToken]);

  const run = async (action: (token: string) => Promise<void>) => {
    setBusy(true);
    setStatus('');
    try {
      await action(await requireAccessToken(getAccessToken));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '操作に失敗しました。');
    } finally {
      setBusy(false);
    }
  };

  const handleSave = (event: FormEvent) => {
    event.preventDefault();
    void run(async (token) => {
      onSave(await savePersona(token, form, persona?.id));
      setStatus('Personaを保存しました。');
    });
  };

  const handleUpload = () => {
    if (!persona || !pendingFile) return;
    void run(async (token) => {
      const data = await encodeDocument(pendingFile.file);
      await uploadDocument(token, persona.id, pendingFile.id, pendingFile.file.name, data);
      setPendingFile(undefined);
      await loadDocuments();
    });
  };

  return (
    <div className="research-editor">
      <form onSubmit={handleSave}>
        <label>名前<input required maxLength={80} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>説明<input required maxLength={300} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
        <label>既定のチャット種別
          <select value={form.chatType} onChange={(e) => setForm({ ...form, chatType: e.target.value as ChatType })}>
            <option value="LLM">通常チャット</option>
            <option value="RAG" disabled={!knowledgeBase}>登録資料を使うチャット</option>
          </select>
        </label>
        <label>システムプロンプト
          <textarea required rows={4} maxLength={8000} value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })} />
        </label>
        <button type="submit" disabled={busy}>Personaを保存</button>
      </form>
      {persona && knowledgeBase && (
        <section>
          <h3>登録資料</h3>
          <input aria-label="登録する資料" type="file" accept=".pdf,.docx,.txt,.md" disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) setPendingFile({ file, id: crypto.randomUUID() });
              e.target.value = '';
            }} />
          <button type="button" disabled={busy || !pendingFile} onClick={handleUpload}>資料を登録</button>
          {pendingFile && <span> {pendingFile.file.name}</span>}
          <button type="button" disabled={busy} onClick={() => void run(loadDocuments)}>状態を更新</button>
          <ul>
            {documents.map((document) => (
              <li key={document.id}>
                {document.name} · {documentStatus(document.status)}
                {document.status === 'UPLOAD_INCOMPLETE' && <label>同じ資料で再開
                  <input aria-label={`${document.name}の登録を再開`} type="file" disabled={busy} onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) setPendingFile({ file, id: document.id });
                  }} />
                </label>}
                <button type="button" disabled={busy} onClick={() => {
                  if (confirmation !== document.id) { setConfirmation(document.id); return; }
                  void run(async (token) => {
                    await deleteDocument(token, persona.id, document.id);
                    setConfirmation('');
                    await loadDocuments();
                  });
                }}>{confirmation === document.id ? '資料の削除を確定' : '削除'}</button>
              </li>
            ))}
          </ul>
        </section>
      )}
      {persona && (
        <button type="button" disabled={busy} onClick={() => {
          if (confirmation !== persona.id) { setConfirmation(persona.id); return; }
          void run(async (token) => {
            await deletePersona(token, persona.id);
            onDelete(persona.id);
          });
        }}>{confirmation === persona.id ? 'Personaの削除を確定' : 'Personaを削除'}</button>
      )}
      {status && <p role="status">{status}</p>}
    </div>
  );
}

function documentStatus(status: string) {
  const labels: Record<string, string> = {
    INDEXED: '検索可能', PARTIALLY_INDEXED: '一部を検索可能', FAILED: '処理失敗',
    METADATA_UPDATE_FAILED: '処理失敗', METADATA_PARTIALLY_INDEXED: 'メタデータの一部のみ登録',
    UPLOAD_INCOMPLETE: '登録中断', DELETING: '削除中', DELETE_IN_PROGRESS: '削除中',
    IGNORED: '未登録', NOT_FOUND: '確認待ち',
  };
  return labels[status] ?? '処理中';
}
