import type {
  AppConfig,
  ConsentScenario,
  ModelSettings,
  OutboxMessage,
  SessionOut,
  TurnOut,
  ValidateKeyOut,
} from "./types";

const STORAGE_KEY = "modelSettings";

export class SessionExpired extends Error {
  constructor() {
    super("session_expired");
  }
}
export class MissingKey extends Error {
  constructor() {
    super("missing_api_key");
  }
}
export class QuotaExceeded extends Error {
  constructor() {
    super("demo_quota_exceeded");
  }
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code);
  }
}

// ---- Model settings (sessionStorage; every access guarded) ----

export function loadSettings(): ModelSettings | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as ModelSettings;
    return s && typeof s.apiKey === "string" && s.apiKey ? s : null;
  } catch {
    return null;
  }
}

export function saveSettings(s: ModelSettings): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable: the key simply is not remembered */
  }
}

export function clearSettings(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

function keyHeaders(): Record<string, string> {
  const s = loadSettings();
  if (!s) return {};
  const h: Record<string, string> = {
    "X-OpenAI-Key": s.apiKey,
    "X-LLM-Provider": s.provider,
  };
  if (s.baseUrl) h["X-LLM-Base-URL"] = s.baseUrl;
  if (s.model) h["X-LLM-Model"] = s.model;
  return h;
}

// ---- Transport ----

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { ...keyHeaders() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let code = "unknown";
    try {
      const data = (await res.json()) as { code?: string };
      if (typeof data.code === "string") code = data.code;
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 404) throw new SessionExpired();
    if (res.status === 401) throw new MissingKey();
    if (res.status === 429 && code === "demo_quota_exceeded") throw new QuotaExceeded();
    throw new ApiError(res.status, code);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const createSession = (scenario: ConsentScenario = "default") =>
  request<SessionOut>("POST", "/sessions", { consent_scenario: scenario });

export const sendMessage = (id: string, body: { text?: string; action?: string }) =>
  request<TurnOut>("POST", `/sessions/${encodeURIComponent(id)}/messages`, body);

export const sendEvent = (id: string, type: "consent_poll") =>
  request<TurnOut>("POST", `/sessions/${encodeURIComponent(id)}/events`, { type });

export const getConfig = () => request<AppConfig>("GET", "/config");

export const validateKey = (s: ModelSettings) =>
  request<ValidateKeyOut>("POST", "/config/validate-key", {
    provider: s.provider,
    base_url: s.baseUrl || undefined,
    model: s.model || undefined,
    api_key: s.apiKey,
  });

export const getOutbox = (id: string) =>
  request<OutboxMessage[]>("GET", `/sessions/${encodeURIComponent(id)}/outbox`);

export const deleteSession = (id: string) =>
  request<void>("DELETE", `/sessions/${encodeURIComponent(id)}`);
