// Field names mirror the backend JSON exactly (backend/app/api/schemas.py, sop/snapshot.py).

export type Role = "user" | "agent" | "system";

export interface ChatMessage {
  role: Role;
  text: string;
}

export interface QuickReply {
  label: string;
  action: string;
}

export interface IdentityStatus {
  field: string;
  status: string;
}

export interface MemoryItem {
  key: string;
  value: string;
  captured_phase: string;
  used_phase: string | null;
}

export interface TimelineEvent {
  turn: number;
  stage: string;
  summary: string;
}

export interface Snapshot {
  phase: string;
  sub_state: string;
  access_granted: boolean;
  caller_role: string | null;
  verification_failures: number;
  identity: IdentityStatus[];
  memory: MemoryItem[];
  active_case_id: string | null;
  discussed_case_ids: string[];
  primary_intent: string | null;
  emotion: { label: string; intensity: number } | null;
  counters: Record<string, unknown>;
  consent: { status: string; polls: number; scenario: string };
  email: { decision: string | null; preview: unknown };
  handoff: unknown;
  events: TimelineEvent[];
}

export type LlmError = "auth" | "rate_limit" | "timeout" | "other";

export interface TurnOut {
  messages: { role: string; text: string }[];
  state: Snapshot;
  quick_replies: QuickReply[];
  llm_error: LlmError | null;
}

export interface SessionOut {
  session_id: string;
  messages: { role: string; text: string }[];
  state: Snapshot;
  quick_replies: QuickReply[];
}

export interface AppConfig {
  has_server_key: boolean;
  provider: string | null;
  model: string | null;
  demo_today: string;
  consent_scenarios: string[];
}

export type Provider = "openai" | "deepseek" | "custom";

export interface ModelSettings {
  provider: Provider;
  apiKey: string;
  baseUrl?: string;
  model?: string;
}

export interface ValidateKeyOut {
  ok: boolean;
  error?: string | null;
}

export type ConsentScenario = "default" | "timeout";
