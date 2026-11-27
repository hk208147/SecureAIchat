import { useState, useCallback, useEffect, useRef } from 'react';
import type { Message, ResearchSource } from '../types';
import { sendChatMessage, fetchMessages, uploadChatFile, type ChatFile, type ChatOptions } from '../api/chatApi';

interface UseChatResult {
  messages: Message[];
  isLoading: boolean;
  error: string | null;
  historyError: string | null;
  retryHistory: () => void;
  sendMessage: (text: string, context?: ChatOptions, sources?: ResearchSource[], files?: File[], savedFiles?: ChatFile[]) => Promise<boolean>;
}

export function useChat(
  sessionId: string,
  getAccessToken: () => Promise<string | null>,
  modelId: string,
  thinkingLevel: string,
  projectId?: string,
): UseChatResult {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyLoadKey, setHistoryLoadKey] = useState(0);
  const retryHistory = useCallback(() => setHistoryLoadKey((k) => k + 1), []);

  // sessionIdRef holds the latest sessionId so in-flight callbacks can detect stale responses.
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  // generationRef increments every time the session context is reset (session switch or re-mount).
  // This distinguishes old in-flight requests from the current display context even when
  // the session ID is the same (e.g. user navigates A→B→A).
  const generationRef = useRef(0);
  const uploads = useRef(new WeakMap<File, { document: ChatFile; uploadedAt: number }>());

  useEffect(() => {
    setMessages([]);
    setError(null);
    setHistoryError(null);
    setIsLoading(false);
    uploads.current = new WeakMap();

    const thisGeneration = ++generationRef.current;
    let cancelled = false;

    const loadHistory = async () => {
      const token = await getAccessToken();
      if (cancelled || !token) return;
      try {
        const data = await fetchMessages(sessionId, token, projectId);
        // Discard if session changed or this generation is no longer current.
        if (cancelled || generationRef.current !== thisGeneration) return;
        // Only apply history when no user messages have been added yet in this generation
        // (i.e. the user sent a message before history finished loading).
        setMessages((prev) =>
          prev.length === 0
            ? data.messages.map((m) => ({
                id: crypto.randomUUID(),
                role: m.role,
                content: m.content,
                timestamp: new Date(m.timestamp),
                usage:
                  m.in_tok !== undefined
                    ? { input_tokens: m.in_tok, output_tokens: m.out_tok ?? 0 }
                    : undefined,
                model_used: m.model_used,
                thinking_level: m.thinking_level,
                response_time_ms: m.response_time_ms,
                citations: m.citations,
                research_context: m.research_context,
                attachments: m.attachments,
              }))
            : prev,
        );
      } catch {
        if (!cancelled && generationRef.current === thisGeneration) {
          setHistoryError('履歴の読み込みに失敗しました。');
        }
      }
    };

    void loadHistory();
    return () => {
      cancelled = true;
      generationRef.current++;
    };
  }, [sessionId, getAccessToken, historyLoadKey, projectId]);

  const sendMessage = useCallback(
    async (text: string, context?: ChatOptions, sources?: ResearchSource[], files: File[] = [], savedFiles: ChatFile[] = []): Promise<boolean> => {
      if (isLoading) return false;

      const requestSession = sessionId;
      const requestGeneration = generationRef.current;

      const userMessage: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        content: text,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, userMessage]);
      setIsLoading(true);
      setError(null);

      const isCurrent = () =>
        sessionIdRef.current === requestSession &&
        generationRef.current === requestGeneration;

      const token = await getAccessToken();
      if (!token) {
        if (isCurrent()) {
          setError('認証が切れました。ページをリロードしてください。');
          setMessages((prev) => prev.filter((m) => m.id !== userMessage.id));
          setIsLoading(false);
        }
        return false;
      }

      try {
        const uploaded = uploads.current;
        const temporary = await Promise.all(files.map(async (file) => {
          const existing = uploaded.get(file);
          if (existing && Date.now() - existing.uploadedAt < 24 * 60 * 60 * 1000) return existing.document;
          const document = await uploadChatFile(token, file, 'temporary', requestSession, projectId);
          uploaded.set(file, { document, uploadedAt: Date.now() });
          return document;
        }));
        if (!isCurrent()) return false;
        const refs = [
          ...temporary.map(({ id }) => ({ id, scope: 'temporary' as const })),
          ...savedFiles.map(({ id }) => ({ id, scope: 'saved' as const })),
        ];
        const data = await sendChatMessage(requestSession, text, token, modelId, thinkingLevel, context, sources, refs, projectId);

        if (!isCurrent()) return false;

        const assistantMessage: Message = {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: data.response,
          timestamp: new Date(),
          usage: data.usage,
          model_used: data.model_used,
          thinking_level: data.thinking_level,
          response_time_ms: data.response_time_ms,
          citations: data.citations,
          research_context: data.research_context,
        };

        setMessages((prev) => [...prev.map((message) => message.id === userMessage.id
          ? { ...message, attachments: data.attachments }
          : message), assistantMessage]);
        return true;
      } catch (err) {
        if (!isCurrent()) return false;
        const message = err instanceof Error ? err.message : 'An unexpected error occurred';
        setError(message);
        setMessages((prev) => prev.filter((m) => m.id !== userMessage.id));
        return false;
      } finally {
        // Only clear loading for the request that owns this context.
        // A stale request (session switched or re-mounted) must not reset the new session's
        // loading state.
        if (isCurrent()) {
          setIsLoading(false);
        }
      }
    },
    [sessionId, getAccessToken, isLoading, modelId, thinkingLevel, projectId],
  );

  return { messages, isLoading, error, historyError, retryHistory, sendMessage };
}
