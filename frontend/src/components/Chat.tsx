import { useEffect, useRef } from "react";
import type { ChatMessage, QuickReply } from "../types";
import QuickReplies from "./QuickReplies";
import SuggestionChips from "./SuggestionChips";

export const MAX_TEXT_LEN = 4000;

interface Props {
  messages: ChatMessage[];
  quickReplies: QuickReply[];
  pending: boolean;
  ready: boolean;
  draft: string;
  suggestions: string[];
  onDraft: (text: string) => void;
  onSend: (text: string) => void;
  onQuickReply: (reply: QuickReply) => void;
  /** The session reached CLOSED or HANDOFF: replace the composer with a restart button. */
  ended?: boolean;
  onNewChat?: () => void;
}

function Bubble({ m }: { m: ChatMessage }) {
  if (m.role === "system") {
    return (
      <div className="self-center rounded-md bg-amber-50 px-3 py-1.5 text-center text-xs text-amber-800" role="status">
        {m.text}
      </div>
    );
  }
  const user = m.role === "user";
  return (
    <div
      className={`max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-4 py-2 text-sm leading-relaxed ${
        user ? "self-end bg-slate-800 text-white" : "self-start border border-slate-200 bg-white text-slate-900"
      }`}
    >
      <span className="sr-only">{user ? "You: " : "Agent: "}</span>
      {m.text}
    </div>
  );
}

export default function Chat({ messages, quickReplies, pending, ready, draft, suggestions, onDraft, onSend, onQuickReply, ended = false, onNewChat }: Props) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const tooLong = draft.length > MAX_TEXT_LEN;
  const canSend = ready && !pending && draft.trim().length > 0 && !tooLong;

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  const submit = () => {
    if (!canSend) return;
    onSend(draft.trim());
    onDraft("");
  };

  // Quick replies reflect the latest server state, including after a failed request.

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label="Chat">
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4" role="log" aria-live="polite">
        {messages.length === 0 && !pending && (
          <p className="m-auto text-sm text-slate-500">Starting a conversation&hellip;</p>
        )}
        {messages.map((m, i) => (
          <Bubble key={i} m={m} />
        ))}
        {pending && (
          <div
            className="self-start rounded-2xl border border-slate-200 bg-white px-4 py-3"
            role="status"
            aria-label="Agent is typing"
          >
            <span className="flex gap-1" aria-hidden="true">
              {[0, 150, 300].map((d) => (
                <span
                  key={d}
                  className="h-2 w-2 animate-bounce rounded-full bg-slate-400"
                  style={{ animationDelay: `${d}ms` }}
                />
              ))}
            </span>
          </div>
        )}
        {!pending && ready && (
          <QuickReplies replies={quickReplies} disabled={pending} onPick={onQuickReply} />
        )}
        <div ref={endRef} />
      </div>
      {ended && !pending ? (
        <div className="flex items-center justify-between gap-3 border-t border-slate-200 bg-white p-3">
          <p className="text-sm text-slate-600">This conversation has ended.</p>
          <button
            type="button"
            onClick={onNewChat}
            className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            Start a new chat
          </button>
        </div>
      ) : (
      <form
        className="border-t border-slate-200 bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <SuggestionChips
          suggestions={suggestions}
          disabled={pending || !ready}
          onPick={(text) => onSend(text)}
        />
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            aria-label="Message"
            value={draft}
            rows={2}
            placeholder="Type your message (Enter to send, Shift+Enter for a new line)"
            onChange={(e) => onDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            className="min-h-[44px] min-w-0 flex-1 resize-none rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={!canSend}
            aria-label="Send message"
            className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            Send
          </button>
        </div>
        {tooLong && (
          <p className="mt-1 text-xs text-red-600" role="alert">
            Message is too long ({draft.length}/{MAX_TEXT_LEN} characters).
          </p>
        )}
      </form>
      )}
    </section>
  );
}
