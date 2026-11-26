import { describe, expect, it } from "vitest";
import { initialState, LLM_NOTICES, MSG_LOST_CONNECTION, reducer } from "../reducer";
import type { LlmError, Snapshot, TurnOut } from "../types";

const snap = (phase: string) => ({ phase }) as unknown as Snapshot;

const turn = (over: Partial<TurnOut> = {}): TurnOut => ({
  messages: [{ role: "agent", text: "Hello" }],
  state: snap("VERIFY_ID"),
  quick_replies: [{ label: "Yes", action: "yes" }],
  llm_error: null,
  ...over,
});

describe("reducer", () => {
  it("turn_started sets pending and appends the user message", () => {
    const s = reducer(initialState, { type: "turn_started", userText: "hi" });
    expect(s.pending).toBe(true);
    expect(s.messages).toEqual([{ role: "user", text: "hi" }]);
  });

  it("turn_started without text (quick reply) only sets pending", () => {
    const s = reducer(initialState, { type: "turn_started" });
    expect(s.pending).toBe(true);
    expect(s.messages).toEqual([]);
  });

  it("turn_succeeded appends messages and replaces quick replies", () => {
    let s = reducer(initialState, { type: "turn_started", userText: "hi" });
    s = { ...s, quickReplies: [{ label: "Old", action: "old" }] };
    s = reducer(s, { type: "turn_succeeded", turn: turn() });
    expect(s.pending).toBe(false);
    expect(s.messages.map((m) => m.text)).toEqual(["hi", "Hello"]);
    expect(s.quickReplies).toEqual([{ label: "Yes", action: "yes" }]);
    expect(s.snapshot?.phase).toBe("VERIFY_ID");
    expect(s.keyDialogOpen).toBe(false);
  });

  it("turn_succeeded with llm_error=auth opens the key dialog", () => {
    const s = reducer(initialState, {
      type: "turn_succeeded",
      turn: turn({ llm_error: "auth" }),
    });
    expect(s.keyDialogOpen).toBe(true);
    expect(s.error).toBeTruthy();
  });

  it("turn_failed with missing_key opens the key dialog and clears pending", () => {
    const s0 = reducer(initialState, { type: "turn_started" });
    const s = reducer(s0, { type: "turn_failed", reason: "missing_key" });
    expect(s.keyDialogOpen).toBe(true);
    expect(s.pending).toBe(false);
  });

  it("turn_failed with quota_exceeded opens the dialog with a quota message", () => {
    const s = reducer(initialState, { type: "turn_failed", reason: "quota_exceeded" });
    expect(s.keyDialogOpen).toBe(true);
    expect(s.messages[s.messages.length - 1]).toEqual({
      role: "system",
      text: "The demo quota is used up — add your own key to continue.",
    });
  });

  it("turn_failed with other adds a friendly inline message, no dialog", () => {
    const s = reducer(initialState, { type: "turn_failed", reason: "other" });
    expect(s.keyDialogOpen).toBe(false);
    expect(s.messages[s.messages.length - 1]?.text).toBe("Something went wrong — please try again.");
  });

  it("session_started replaces the conversation; a notice keeps history", () => {
    const payload = {
      sessionId: "s2",
      messages: [{ role: "agent" as const, text: "Welcome" }],
      snapshot: snap("VERIFY_ID"),
      quickReplies: [],
    };
    const base = reducer(initialState, { type: "turn_started", userText: "old" });
    const fresh = reducer(base, { type: "session_started", ...payload });
    expect(fresh.sessionId).toBe("s2");
    expect(fresh.messages.map((m) => m.text)).toEqual(["Welcome"]);
    const kept = reducer(base, {
      type: "session_started",
      ...payload,
      notice: "Session expired — started a new one.",
    });
    expect(kept.messages.map((m) => m.text)).toEqual([
      "old",
      "Session expired — started a new one.",
      "Welcome",
    ]);
    expect(kept.pending).toBe(false);
  });

  const notices: [LlmError, string][] = [
    ["auth", "The model provider rejected the API key."],
    [
      "model_unavailable",
      "The selected model isn't available for this key; replies are using basic fallback templates. Open Model settings to choose another model.",
    ],
    ["rate_limit", "The model provider is rate-limiting requests; replies are using basic fallback templates for now."],
    ["timeout", "The model didn't respond in time; this reply used a basic fallback template."],
    ["other", "The model couldn't be reached; this reply used a basic fallback template."],
  ];

  it.each(notices)("llm_error=%s appends one system bubble after the reply", (kind, text) => {
    expect(LLM_NOTICES[kind]).toBe(text);
    const s = reducer(initialState, { type: "turn_succeeded", turn: turn({ llm_error: kind }) });
    expect(s.messages).toEqual([
      { role: "agent", text: "Hello" },
      { role: "system", text },
    ]);
    expect(s.keyDialogOpen).toBe(kind === "auth");
  });

  it("does not repeat the same llm notice on consecutive turns", () => {
    let s = reducer(initialState, { type: "turn_succeeded", turn: turn({ llm_error: "timeout" }) });
    s = reducer(s, { type: "turn_succeeded", turn: turn({ llm_error: "timeout" }) });
    const count = (st: typeof s) => st.messages.filter((m) => m.role === "system").length;
    expect(count(s)).toBe(1);
    s = reducer(s, { type: "turn_succeeded", turn: turn({ llm_error: "rate_limit" }) });
    expect(count(s)).toBe(2);
    s = reducer(s, { type: "turn_succeeded", turn: turn() });
    s = reducer(s, { type: "turn_succeeded", turn: turn({ llm_error: "rate_limit" }) });
    expect(count(s)).toBe(3);
  });

  it("a successful turn without llm_error adds no system bubble", () => {
    const s = reducer(initialState, { type: "turn_succeeded", turn: turn() });
    expect(s.messages.filter((m) => m.role === "system")).toEqual([]);
  });

  it("poll failures are silent until the cap, then one lost-connection bubble", () => {
    let s = reducer(initialState, { type: "turn_started" });
    s = reducer(s, { type: "poll_failed" });
    expect(s.pending).toBe(false);
    s = reducer(s, { type: "poll_failed" });
    expect(s.messages).toEqual([]);
    expect(s.pollStopped).toBe(false);
    s = reducer(s, { type: "poll_failed" });
    expect(s.pollStopped).toBe(true);
    expect(s.messages).toEqual([{ role: "system", text: MSG_LOST_CONNECTION }]);
    s = reducer(s, { type: "poll_retry" });
    expect(s.pollStopped).toBe(false);
    expect(s.pollFailures).toBe(0);
  });

  it("open/close key dialog", () => {
    const o = reducer(initialState, { type: "open_key_dialog" });
    expect(o.keyDialogOpen).toBe(true);
    expect(reducer(o, { type: "close_key_dialog" }).keyDialogOpen).toBe(false);
  });
});
