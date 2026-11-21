import type { Session, TokenUsage } from '../types';

const API_ENDPOINT = (import.meta.env.VITE_API_ENDPOINT as string).replace(/\/$/, '');

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
  response: string;
  session_id: string;
  usage: TokenUsage;
  model_used?: string;
  thinking_level?: string;
  response_time_ms?: number;
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
): Promise<ChatResponse> {
  const body: Record<string, unknown> = { message, session_id: sessionId };
  if (modelId !== undefined) body.model_id = modelId;
  if (thinkingLevel !== undefined) body.thinking_level = thinkingLevel;

  return apiFetch<ChatResponse>('/chat', accessToken, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function fetchSessions(accessToken: string): Promise<SessionsResponse> {
  return apiFetch<SessionsResponse>('/sessions', accessToken, { method: 'GET' });
}

interface MessageRecord {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  in_tok?: number;
  out_tok?: number;
  model_used?: string;
  thinking_level?: string;
  response_time_ms?: number;
}

export interface MessagesResponse {
  messages: MessageRecord[];
}

export function fetchMessages(sessionId: string, accessToken: string): Promise<MessagesResponse> {
  return apiFetch<MessagesResponse>(
    `/messages?session_id=${encodeURIComponent(sessionId)}`,
    accessToken,
    { method: 'GET' },
  );
}

export function deleteSession(
  sessionId: string,
  accessToken: string,
): Promise<{ deleted: boolean }> {
  return apiFetch<{ deleted: boolean }>(
    `/sessions?session_id=${encodeURIComponent(sessionId)}`,
    accessToken,
    { method: 'DELETE' },
  );
}
