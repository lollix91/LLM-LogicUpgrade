const API_BASE = '/api';

export interface PipelineStep {
  step: string;
  title: string;
  content: string;
  duration_ms: number | null;
}

export interface ChatResponse {
  conversation_id: string;
  answer: string;
  has_logic: boolean;
  reasoning_trace: PipelineStep[];
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  message_count: number;
}

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  reasoning_trace?: PipelineStep[] | null;
  has_logic?: boolean;
  created_at?: string;
}

export interface ConversationDetail {
  id: string;
  title: string;
  created_at: string;
  messages: Message[];
}

export interface ModelInfo {
  current_model: string;
  available_models: string[];
}

export async function sendMessage(message: string, conversationId?: string): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
  if (!res.ok) throw new Error(`Chat failed: ${res.statusText}`);
  return res.json();
}

export async function getConversations(): Promise<ConversationSummary[]> {
  const res = await fetch(`${API_BASE}/conversations`);
  if (!res.ok) throw new Error(`Failed to fetch conversations`);
  return res.json();
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const res = await fetch(`${API_BASE}/conversations/${id}`);
  if (!res.ok) throw new Error(`Failed to fetch conversation`);
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  await fetch(`${API_BASE}/conversations/${id}`, { method: 'DELETE' });
}

export async function getModelInfo(): Promise<ModelInfo> {
  const res = await fetch(`${API_BASE}/model`);
  if (!res.ok) throw new Error(`Failed to fetch model info`);
  return res.json();
}

export async function changeModel(model: string): Promise<void> {
  const res = await fetch(`${API_BASE}/model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model }),
  });
  if (!res.ok) throw new Error(`Failed to change model`);
}

export async function pullModel(model: string): Promise<void> {
  const res = await fetch(`${API_BASE}/model/pull`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model }),
  });
  if (!res.ok) throw new Error(`Failed to pull model`);
}
