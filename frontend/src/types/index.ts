export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  usage?: TokenUsage;
  model_used?: string;
  thinking_level?: string;
  response_time_ms?: number;
}

export interface Session {
  session_id: string;
  firstMessage: string;
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
