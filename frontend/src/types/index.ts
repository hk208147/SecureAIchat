export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface MessageAttachments {
  id: string;
  files: string[];
}

export interface Message {
  attachments?: MessageAttachments;
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  usage?: TokenUsage;
  model_used?: string;
  thinking_level?: string;
  response_time_ms?: number;
  citations?: ResearchSource[];
  research_context?: ResearchContext;
}

export interface Session {
  session_id: string;
  firstMessage: string;
}

export interface Project {
  id: string;
  name: string;
  persona_id: string;
}

export interface ChatState {
  messages: Message[];
  isLoading: boolean;
  error: string | null;
  sessionId: string;
}

export interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
}

export type ThinkingLevel = 'low' | 'medium' | 'high';

export interface ModelConfig {
  id: string;
  label: string;
  thinkingLevels: ThinkingLevel[];
}

export const MODELS: ModelConfig[] = [
  {
    id: 'au.anthropic.claude-sonnet-4-6',
    label: 'Sonnet 4.6',
    thinkingLevels: ['low', 'medium', 'high'],
  },
  {
    id: 'au.anthropic.claude-opus-4-6-v1',
    label: 'Opus 4.6',
    thinkingLevels: ['low', 'medium', 'high'],
  },
];

export const THINKING_LEVEL_LABELS: Record<ThinkingLevel, string> = {
  low: '軽い',
  medium: '通常',
  high: '深く考える',
};

export const DEFAULT_MODEL_ID = 'au.anthropic.claude-sonnet-4-6';
export const DEFAULT_THINKING_LEVEL: ThinkingLevel = 'medium';

export type ChatType = 'LLM' | 'RAG';
export type WritingMode = 'general' | 'write' | 'review';

export interface ResearchContext {
  persona_enabled?: boolean;
  persona_id: string;
  mode: WritingMode;
  chat_type: ChatType;
}

export interface ResearchSource {
  id?: string;
  kind: 'attachment' | 'web' | 'knowledge';
  title: string;
  excerpt: string;
  locator?: string;
  url?: string;
  publishedAt?: string;
  retrievedAt?: string;
  personaId?: string;
  documentId?: string;
}

export interface PersonaForm {
  name: string;
  description: string;
  prompt: string;
  chatType: ChatType;
}

export interface Persona extends PersonaForm {
  id: string;
  isDefault: boolean;
}

export interface ResearchDocument {
  id: string;
  name: string;
  status: string;
}
