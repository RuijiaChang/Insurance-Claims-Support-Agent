import type { ChatMessage, QuickReply, Role, Snapshot, TurnOut } from "./types";

export const MSG_QUOTA = "The demo quota is used up — add your own key to continue.";
export const MSG_MISSING_KEY = "An API key is needed — add one in Model settings to continue.";
export const MSG_AUTH = "The model rejected your key \u2014 please check it.";
export const MSG_GENERIC = "Something went wrong — please try again.";

export interface State {
  sessionId: string | null;
  messages: ChatMessage[];
  quickReplies: QuickReply[];
  snapshot: Snapshot | null;
  pending: boolean;
  error?: string;
  keyDialogOpen: boolean;
}

export const initialState: State = {
  sessionId: null,
  messages: [],
  quickReplies: [],
  snapshot: null,
  pending: false,
  keyDialogOpen: false,
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
    case "turn_succeeded":
      return {
        ...state,
        pending: false,
        messages: [...state.messages, ...toChatMessages(action.turn.messages)],
        quickReplies: action.turn.quick_replies,
        snapshot: action.turn.state,
        keyDialogOpen: state.keyDialogOpen || action.turn.llm_error === "auth",
        error: action.turn.llm_error === "auth" ? MSG_AUTH : undefined,
      };
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
    case "open_key_dialog":
      return { ...state, keyDialogOpen: true };
    case "close_key_dialog":
      return { ...state, keyDialogOpen: false, error: undefined };
  }
}
