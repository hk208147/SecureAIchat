import type { MessageAttachments, Persona, PersonaForm, Project, ResearchContext, ResearchDocument, ResearchSource, Session, TokenUsage } from '../types';

const API_ENDPOINT = (import.meta.env.VITE_API_ENDPOINT as string).replace(/\/$/, '');

export type ChatOptions = Partial<Pick<ResearchContext, 'mode' | 'chat_type' | 'persona_enabled'>>;

async function apiFetch<T>(
  path: string,
  accessToken: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_ENDPOINT}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken}`,
      ...(options?.headers ?? {}),
    },
  });

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { error?: string };
      if (body.error) message = body.error;
    } catch {
      // ignore parse errors
    }
    throw new Error(message);
  }

  return res.json() as Promise<T>;
}

export interface ChatResponse {
  attachments?: MessageAttachments;
  response: string;
  session_id: string;
  usage: TokenUsage;
  model_used?: string;
  thinking_level?: string;
  response_time_ms?: number;
  citations?: ResearchSource[];
  research_context?: ResearchContext;
}

export interface SessionsResponse {
  sessions: Session[];
}

export function sendChatMessage(
  sessionId: string,
  message: string,
  accessToken: string,
  modelId?: string,
  thinkingLevel?: string,
  context?: ChatOptions,
  sources?: ResearchSource[],
  files?: ChatFileReference[],
  projectId?: string,
): Promise<ChatResponse> {
  const body: Record<string, unknown> = { message, session_id: sessionId };
  if (modelId !== undefined) body.model_id = modelId;
  if (thinkingLevel !== undefined) body.thinking_level = thinkingLevel;

  if (context) Object.assign(body, context);
  if (sources?.length) body.sources = sources;
  if (files?.length) body.file_refs = files;
  if (projectId) body.project_id = projectId;

  return apiFetch<ChatResponse>('/chat', accessToken, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

function scopeQuery(projectId?: string, params: Record<string, string> = {}) {
  const query = new URLSearchParams(params);
  if (projectId) query.set('project_id', projectId);
  return query.size ? '?' + query : '';
}

export function fetchSessions(accessToken: string, projectId?: string): Promise<SessionsResponse> {
  return apiFetch<SessionsResponse>('/sessions' + scopeQuery(projectId), accessToken, { method: 'GET' });
}

interface MessageRecord {
  attachments?: MessageAttachments;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  in_tok?: number;
  out_tok?: number;
  model_used?: string;
  thinking_level?: string;
  response_time_ms?: number;
  citations?: ResearchSource[];
  research_context?: ResearchContext;
}

export interface MessagesResponse {
  messages: MessageRecord[];
}

export function fetchMessages(sessionId: string, accessToken: string, projectId?: string): Promise<MessagesResponse> {
  return apiFetch<MessagesResponse>(
    '/messages' + scopeQuery(projectId, { session_id: sessionId }),
    accessToken,
    { method: 'GET' },
  );
}

export function deleteSession(
  sessionId: string,
  accessToken: string,
  projectId?: string,
): Promise<{ deleted: boolean }> {
  return apiFetch<{ deleted: boolean }>(
    '/sessions' + scopeQuery(projectId, { session_id: sessionId }),
    accessToken,
    { method: 'DELETE' },
  );
}

export function fetchProjects(token: string) {
  return apiFetch<{ projects: Project[] }>('/research/projects', token);
}

export function createProject(token: string, name: string) {
  return apiFetch<Project>('/research/projects', token, {
    method: 'POST', body: JSON.stringify({ name }),
  });
}

export function setProjectPersona(token: string, projectId: string, personaId: string) {
  return apiFetch<Project>('/research/projects', token, {
    method: 'PUT', body: JSON.stringify({ project_id: projectId, persona_id: personaId }),
  });
}

export function fetchPersonas(token: string) {
  return apiFetch<{ personas: Persona[]; activePersonaId: string; knowledgeBase: boolean; webSearch: boolean }>(
    '/research/personas', token,
  );
}

export function setActivePersona(token: string, id: string) {
  return apiFetch<{ activePersonaId: string }>('/research/personas/active', token, {
    method: 'PUT', body: JSON.stringify({ persona_id: id }),
  });
}

export function savePersona(token: string, form: PersonaForm, id?: string) {
  return apiFetch<Persona>('/research/personas', token, {
    method: 'POST', body: JSON.stringify({ ...form, id }),
  });
}

export function deletePersona(token: string, id: string) {
  return apiFetch<{ deleted: boolean }>(`/research/personas?id=${encodeURIComponent(id)}`, token, { method: 'DELETE' });
}

export function fetchDocuments(token: string, personaId: string) {
  return apiFetch<{ documents: ResearchDocument[] }>(
    `/research/documents?persona_id=${encodeURIComponent(personaId)}`, token,
  );
}

export function uploadDocument(token: string, personaId: string, id: string, name: string, data: string) {
  return apiFetch<{ id: string; status: string }>('/research/documents', token, {
    method: 'POST', body: JSON.stringify({ persona_id: personaId, id, name, data }),
  });
}

function documentQuery(personaId: string, id: string) {
  return new URLSearchParams({ persona_id: personaId, id });
}

export function deleteDocument(token: string, personaId: string, id: string) {
  return apiFetch<{ deleted: boolean }>(
    `/research/documents?${documentQuery(personaId, id)}`, token, { method: 'DELETE' },
  );
}

export function getDocumentDownload(token: string, personaId: string, id: string) {
  return apiFetch<{ url: string }>(`/research/documents/download?${documentQuery(personaId, id)}`, token);
}

export function searchSources(token: string, query: string) {
  return apiFetch<{ sources: ResearchSource[] }>('/research/search', token, {
    method: 'POST', body: JSON.stringify({ query }),
  });
}

export async function requireAccessToken(getAccessToken: () => Promise<string | null>) {
  const token = await getAccessToken();
  if (!token) throw new Error('ログインし直してください。');
  return token;
}

export interface ChatFile {
  id: string;
  name: string;
  size: number;
}

export interface ChatFileReference {
  id: string;
  scope: 'saved' | 'temporary';
}

export const MAX_CHAT_FILE_BYTES = 10_000_000;
export const MAX_CHAT_FILES = 5;
export const CHAT_FILE_ACCEPT = '.pdf,.docx,.txt,.md';

export function validateChatFile(file: File) {
  if (!/\.(pdf|docx|txt|md)$/i.test(file.name)) {
    throw new Error('PDF、DOCX、TXT、Markdownを選んでください。');
  }
  if (file.size < 1 || file.size > MAX_CHAT_FILE_BYTES) {
    throw new Error('ファイルは空でない10 MB以下のものを選んでください。');
  }
}

export async function uploadChatFile(token: string, file: File, scope: ChatFileReference['scope'], sessionId?: string, projectId?: string) {
  validateChatFile(file);
  const destination = { scope, session_id: sessionId, project_id: projectId };
  const upload = await apiFetch<{ id: string; url: string; fields: Record<string, string> }>(
    '/research/files/upload', token, {
      method: 'POST', body: JSON.stringify({ ...destination, name: file.name, size: file.size }),
    },
  );
  const form = new FormData();
  for (const [name, value] of Object.entries(upload.fields)) form.append(name, value);
  form.append('file', file);
  const response = await fetch(upload.url, { method: 'POST', body: form, credentials: 'omit' });
  if (!response.ok) throw new Error('ファイルのアップロードに失敗しました。再試行してください。');
  return apiFetch<ChatFile>('/research/files/complete', token, {
    method: 'POST', body: JSON.stringify({ ...destination, id: upload.id }),
  });
}

export function fetchSavedFiles(token: string, cursor?: string, projectId?: string) {
  const query = scopeQuery(projectId, cursor ? { cursor } : {});
  return apiFetch<{ documents: ChatFile[]; nextCursor?: string | null }>('/research/files' + query, token);
}

export function deleteSavedFile(token: string, id: string, projectId?: string) {
  return apiFetch<{ deleted: boolean }>('/research/files' + scopeQuery(projectId, { id }), token, {
    method: 'DELETE',
  });
}

export function importSavedFile(token: string, projectId: string, id: string) {
  return apiFetch<ChatFile>('/research/files/import', token, {
    method: 'POST', body: JSON.stringify({ project_id: projectId, id }),
  });
}

export function getHistoryFileDownload(token: string, sessionId: string, turnId: string, index: number, projectId?: string) {
  return apiFetch<{ url: string }>('/research/files/history' + scopeQuery(projectId, {
    session_id: sessionId, turn_id: turnId, index: String(index),
  }), token);
}
