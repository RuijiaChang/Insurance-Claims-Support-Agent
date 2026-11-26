import type { ChatMessage, LlmError, QuickReply, Role, Snapshot, TurnOut } from "./types";

export const MSG_QUOTA = "The demo quota is used up — add your own key to continue.";
export const MSG_MISSING_KEY = "An API key is needed — add one in Model settings to continue.";
export const MSG_AUTH = "The model rejected your key \u2014 please check it.";
export const MSG_GENERIC = "Something went wrong — please try again.";
/** Consecutive failed consent polls before polling stops and waits for Retry. */
export const MAX_POLL_FAILURES = 3;
export const MSG_LOST_CONNECTION = "Lost connection to the server — click Retry.";

/** One chat notice per model failure kind; the reply itself came from a fallback template. */
export const LLM_NOTICES: Record<LlmError, string> = {
  auth: "The model provider rejected the API key.",
  model_unavailable:
    "The selected model isn't available for this key; replies are using basic fallback templates. Open Model settings to choose another model.",
  rate_limit: "The model provider is rate-limiting requests; replies are using basic fallback templates for now.",
  timeout: "The model didn't respond in time; this reply used a basic fallback template.",
  other: "The model couldn't be reached; this reply used a basic fallback template.",
};

export interface State {
  sessionId: string | null;
  messages: ChatMessage[];
  quickReplies: QuickReply[];
  snapshot: Snapshot | null;
  pending: boolean;
  error?: string;
  keyDialogOpen: boolean;
  /** The model-failure notice shown on the previous turn, so a streak shows it only once. */
  llmNotice?: string;
  /** Consecutive failed consent polls; reaching MAX_POLL_FAILURES stops polling. */
  pollFailures: number;
  /** Consent polling gave up after repeated failures; the user restarts it with Retry. */
  pollStopped: boolean;
}

export const initialState: State = {
  sessionId: null,
  messages: [],
  quickReplies: [],
  snapshot: null,
  pending: false,
  keyDialogOpen: false,
  pollFailures: 0,
  pollStopped: false,
};

export type FailReason = "missing_key" | "quota_exceeded" | "other";

export type Action =
  | {
      type: "session_started";
      sessionId: string;
      messages: ChatMessage[];
      snapshot: Snapshot;
      quickReplies: QuickReply[];
      notice?: string;
    }
  | { type: "turn_started"; userText?: string }
  | { type: "turn_succeeded"; turn: TurnOut }
  | { type: "turn_failed"; reason: FailReason }
  | { type: "poll_failed" }
  | { type: "poll_retry" }
  | { type: "open_key_dialog" }
  | { type: "close_key_dialog" };

const system = (text: string): ChatMessage => ({ role: "system", text });

export function toChatMessages(raw: { role: string; text: string }[]): ChatMessage[] {
  return raw.map((m) => ({
    role: (m.role === "user" || m.role === "system" ? m.role : "agent") as Role,
    text: m.text,
  }));
}

export function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "session_started": {
      const history = action.notice ? [...state.messages, system(action.notice)] : [];
      return {
        ...state,
        sessionId: action.sessionId,
        messages: [...history, ...action.messages],
        quickReplies: action.quickReplies,
        snapshot: action.snapshot,
        pending: false,
        error: undefined,
        llmNotice: undefined,
        pollFailures: 0,
        pollStopped: false,
      };
    }
    case "turn_started":
      return {
        ...state,
        pending: true,
        error: undefined,
        messages: action.userText
          ? [...state.messages, { role: "user", text: action.userText }]
          : state.messages,
      };
    case "turn_succeeded": {
      const kind = action.turn.llm_error;
      const notice = kind ? LLM_NOTICES[kind] : undefined;
      const fresh = notice !== undefined && notice !== state.llmNotice;
      return {
        ...state,
        pending: false,
        messages: [
          ...state.messages,
          ...toChatMessages(action.turn.messages),
          ...(fresh ? [system(notice)] : []),
        ],
        quickReplies: action.turn.quick_replies,
        snapshot: action.turn.state,
        keyDialogOpen: state.keyDialogOpen || kind === "auth",
        error: kind === "auth" ? MSG_AUTH : undefined,
        llmNotice: notice,
        pollFailures: 0,
        // The server answered, so the connection is back: let consent polling resume.
        pollStopped: false,
      };
    }
    case "turn_failed": {
      const text =
        action.reason === "quota_exceeded"
          ? MSG_QUOTA
          : action.reason === "missing_key"
            ? MSG_MISSING_KEY
            : MSG_GENERIC;
      return {
        ...state,
        pending: false,
        error: text,
        keyDialogOpen: state.keyDialogOpen || action.reason !== "other",
        messages: [...state.messages, system(text)],
      };
    }
    case "poll_failed": {
      // Background polls retry silently; only giving up is worth a chat message.
      const pollFailures = state.pollFailures + 1;
      const base = { ...state, pending: false, pollFailures };
      return pollFailures >= MAX_POLL_FAILURES
        ? { ...base, pollStopped: true, messages: [...state.messages, system(MSG_LOST_CONNECTION)] }
        : base;
    }
    case "poll_retry":
      return { ...state, pollStopped: false, pollFailures: 0 };
    case "open_key_dialog":
      return { ...state, keyDialogOpen: true };
    case "close_key_dialog":
      return { ...state, keyDialogOpen: false, error: undefined };
  }
}
