import { useState, useCallback, useEffect, useRef } from 'react';
import type { Message } from '../types';
import { sendChatMessage, fetchMessages } from '../api/chatApi';

interface UseChatResult {
  messages: Message[];
  isLoading: boolean;
  error: string | null;
  sendMessage: (text: string) => Promise<boolean>;
}

export function useChat(
  sessionId: string,
  getAccessToken: () => Promise<string | null>,
  modelId: string,
  thinkingLevel: string,
): UseChatResult {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // sessionIdRef holds the latest sessionId so in-flight callbacks can detect stale responses.
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  // generationRef increments every time the session context is reset (session switch or re-mount).
  // This distinguishes old in-flight requests from the current display context even when
  // the session ID is the same (e.g. user navigates A→B→A).
  const generationRef = useRef(0);

  useEffect(() => {
    setMessages([]);
    setError(null);
    setIsLoading(false);

    const thisGeneration = ++generationRef.current;
    let cancelled = false;

    const loadHistory = async () => {
      const token = await getAccessToken();
      if (cancelled || !token) return;
      try {
        const data = await fetchMessages(sessionId, token);
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
              }))
            : prev,
        );
      } catch {
        // non-fatal: start with empty messages if history unavailable
      }
    };

    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, [sessionId, getAccessToken]);

  const sendMessage = useCallback(
    async (text: string): Promise<boolean> => {
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
        const data = await sendChatMessage(requestSession, text, token, modelId, thinkingLevel);

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
        };

        setMessages((prev) => [...prev, assistantMessage]);
        return true;
      } catch (err) {
        if (!isCurrent()) return false;
        const message = err instanceof Error ? err.message : 'An unexpected error occurred';
        setError(message);
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
    [sessionId, getAccessToken, isLoading, modelId, thinkingLevel],
  );

  return { messages, isLoading, error, sendMessage };
}
