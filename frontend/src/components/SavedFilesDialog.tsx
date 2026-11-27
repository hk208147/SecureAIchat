import { useCallback, useEffect, useRef, useState } from 'react';
import {
  CHAT_FILE_ACCEPT, deleteSavedFile, fetchSavedFiles, importSavedFile, requireAccessToken, uploadChatFile,
  type ChatFile,
} from '../api/chatApi';
import './research.css';

interface Props {
  projectId?: string;
  getAccessToken: () => Promise<string | null>;
  onClose: () => void;
  onSelect?: (file: ChatFile) => void;
  selectedIds?: string[];
  onDelete?: (id: string) => void;
  full?: boolean;
}

export function SavedFilesDialog({ projectId, getAccessToken, onClose, onSelect, selectedIds, onDelete, full }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [files, setFiles] = useState<ChatFile[]>([]);
  const [cursor, setCursor] = useState<string | null>();
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [pendingDelete, setPendingDelete] = useState<string>();
  const [importing, setImporting] = useState(false);
  const [importedIds, setImportedIds] = useState<string[]>([]);

  const load = useCallback(async (next?: string) => {
    setBusy(true);
    setError('');
    try {
      const token = await requireAccessToken(getAccessToken);
      const list = await fetchSavedFiles(token, next, importing ? undefined : projectId);
      setFiles((previous) => next ? [...previous, ...list.documents] : list.documents);
      setCursor(list.nextCursor);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '資料一覧を読み込めませんでした。');
    } finally {
      setBusy(false);
    }
  }, [getAccessToken, importing, projectId]);

  useEffect(() => {
    if (!dialog.current?.open) dialog.current?.showModal();
    void load();
  }, [load]);

  async function save(file: File) {
    setBusy(true);
    setError('');
    try {
      const token = await requireAccessToken(getAccessToken);
      await uploadChatFile(token, file, 'saved', undefined, projectId);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '資料を保存できませんでした。');
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    setError('');
    try {
      const token = await requireAccessToken(getAccessToken);
      await deleteSavedFile(token, id, projectId);
      setFiles((previous) => previous.filter((file) => file.id !== id));
      setImportedIds((previous) => previous.filter((item) => item !== id));
      setPendingDelete(undefined);
      onDelete?.(id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '資料を削除できませんでした。');
    } finally {
      setBusy(false);
    }
  }

  async function importFile(id: string) {
    if (!projectId) return;
    setBusy(true);
    setError('');
    try {
      const token = await requireAccessToken(getAccessToken);
      await importSavedFile(token, projectId, id);
      setImportedIds((previous) => [...previous, id]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '資料を取り込めませんでした。');
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog className="research-settings" ref={dialog} onClose={onClose} aria-labelledby="saved-files-title">
      <div className="research-toolbar">
        <h2 id="saved-files-title">{importing ? '共通の保存済み資料' : projectId ? 'プロジェクト資料' : '保存済み資料'}</h2>
        <button type="button" onClick={() => dialog.current?.close()}>閉じる</button>
      </div>
      {projectId && <button type="button" disabled={busy} onClick={() => {
        setBusy(true);
        setFiles([]);
        setCursor(undefined);
        setPendingDelete(undefined);
        setImporting(!importing);
      }}>{importing ? 'プロジェクト資料に戻る' : '共通の保存済み資料から取り込む'}</button>}
      {!importing && <label>
        資料を保存（1ファイル10 MBまで）
        <input type="file" accept={CHAT_FILE_ACCEPT} disabled={busy} onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) void save(file);
        }} />
      </label>}
      {busy && <p role="status">処理中…</p>}
      {error && <p role="alert">{error} <button type="button" onClick={() => void load()}>一覧を再読み込み</button></p>}
      {!busy && !error && files.length === 0 && <p>保存済み資料はありません。</p>}
      {!importing && onSelect && full && <p>このチャットには5件まで選べます。</p>}
      <ul className="research-selection">
        {files.map((file) => (
          <li key={file.id}>
            {file.name} · {Math.ceil(file.size / 1000).toLocaleString()} KB
            {importing ? (
              <button type="button" disabled={busy || importedIds.includes(file.id)} onClick={() => void importFile(file.id)}>
                {importedIds.includes(file.id) ? '取り込み済み' : '取り込む'}
              </button>
            ) : onSelect ? (
              <button type="button" disabled={busy || full || selectedIds?.includes(file.id)} onClick={() => onSelect(file)}>
                {selectedIds?.includes(file.id) ? '選択済み' : 'このチャットで使う'}
              </button>
            ) : pendingDelete === file.id ? (
              <>
                <span>一覧から削除しても、有効な会話履歴からは引き続きダウンロードできます。</span>
                <button type="button" disabled={busy} onClick={() => void remove(file.id)}>削除する</button>
                <button type="button" disabled={busy} onClick={() => setPendingDelete(undefined)}>キャンセル</button>
              </>
            ) : <button type="button" disabled={busy} onClick={() => setPendingDelete(file.id)}>削除…</button>}
          </li>
        ))}
      </ul>
      {cursor && <button type="button" disabled={busy} onClick={() => void load(cursor)}>さらに表示</button>}
    </dialog>
  );
}
