import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  MissingKey,
  QuotaExceeded,
  SessionExpired,
  createSession,
  deleteSession,
  getConfig,
  loadSettings,
  sendMessage,
} from "./api";
import Chat from "./components/Chat";
import KeyDialog from "./components/KeyDialog";
import TopBar from "./components/TopBar";
import { initialState, reducer, toChatMessages, MSG_GENERIC, type FailReason } from "./reducer";
import type { AppConfig, QuickReply } from "./types";

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [userSettings, setUserSettings] = useState(loadSettings);
  const [bootError, setBootError] = useState(false);
  const [showInspector, setShowInspector] = useState(false);
  const booted = useRef(false);
  const sessionRef = useRef<string | null>(null);
  sessionRef.current = state.sessionId;

  const startSession = useCallback(async (notice?: string) => {
    const s = await createSession("default");
    dispatch({
      type: "session_started",
      sessionId: s.session_id,
      messages: toChatMessages(s.messages),
      snapshot: s.state,
      quickReplies: s.quick_replies,
      notice,
    });
  }, []);

  const boot = useCallback(async () => {
    setBootError(false);
    try {
      const cfg = await getConfig();
      setConfig(cfg);
      if (!cfg.has_server_key && !loadSettings()) dispatch({ type: "open_key_dialog" });
      await startSession();
    } catch {
      setBootError(true);
    }
  }, [startSession]);

  useEffect(() => {
    if (booted.current) return; // StrictMode double-invoke guard
    booted.current = true;
    void boot();
  }, [boot]);

  const failure = (e: unknown): FailReason =>
    e instanceof MissingKey ? "missing_key" : e instanceof QuotaExceeded ? "quota_exceeded" : "other";

  const send = useCallback(
    async (body: { text?: string; action?: string }, userText?: string) => {
      const id = sessionRef.current;
      if (!id) return;
      dispatch({ type: "turn_started", userText });
      try {
        dispatch({ type: "turn_succeeded", turn: await sendMessage(id, body) });
      } catch (e) {
        if (e instanceof SessionExpired) {
          try {
            await startSession("Session expired — started a new one.");
          } catch {
            dispatch({ type: "turn_failed", reason: "other" });
          }
        } else {
          dispatch({ type: "turn_failed", reason: failure(e) });
        }
      }
    },
    [startSession],
  );

  const reset = async () => {
    const id = sessionRef.current;
    if (id) await deleteSession(id).catch(() => undefined);
    try {
      await startSession();
    } catch {
      dispatch({ type: "turn_failed", reason: "other" });
    }
  };

  // Why the dialog opened (quota / missing key / rejected key); generic errors stay inline only.
  const keyNotice = state.error === MSG_GENERIC ? undefined : state.error;

  if (bootError) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-sm rounded-lg bg-white p-6 text-center shadow">
          <h1 className="text-lg font-semibold">SOP Insurance Claims Agent</h1>
          <p className="mt-2 text-sm text-slate-600">
            Can&rsquo;t reach the backend right now. Make sure it is running, then try again.
          </p>
          <button
            type="button"
            onClick={() => void boot()}
            className="mt-4 rounded-md bg-slate-800 px-4 py-2 text-sm text-white hover:bg-slate-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <TopBar
        config={config}
        userSettings={userSettings}
        onOpenKeyDialog={() => dispatch({ type: "open_key_dialog" })}
        onReset={() => void reset()}
        disabled={state.pending}
      />
      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="flex min-h-0 flex-col border-slate-200 lg:border-r">
          <div className="border-b border-slate-200 bg-white px-4 py-2 lg:hidden">
            <button
              type="button"
              aria-expanded={showInspector}
              onClick={() => setShowInspector((v) => !v)}
              className="text-sm text-slate-600 underline underline-offset-2"
            >
              {showInspector ? "Hide inspector" : "Show inspector"}
            </button>
          </div>
          {showInspector ? (
            <div className="p-4 lg:hidden">
              <InspectorPlaceholder />
            </div>
          ) : null}
          <div className={`${showInspector ? "hidden lg:flex" : "flex"} min-h-0 flex-1 flex-col`}>
            <Chat
              messages={state.messages}
              quickReplies={state.quickReplies}
              pending={state.pending}
              ready={state.sessionId !== null}
              onSend={(text) => void send({ text }, text)}
              onQuickReply={(r: QuickReply) => void send({ action: r.action }, r.label)}
            />
          </div>
        </div>
        <aside className="hidden overflow-y-auto bg-slate-50 p-4 lg:block" aria-label="Inspector">
          <InspectorPlaceholder />
        </aside>
      </main>
      <KeyDialog
        open={state.keyDialogOpen}
        notice={keyNotice}
        onClose={() => dispatch({ type: "close_key_dialog" })}
        onChanged={() => setUserSettings(loadSettings())}
      />
    </div>
  );
}

function InspectorPlaceholder() {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center">
      <h2 className="text-sm font-semibold text-slate-700">Inspector</h2>
      <p className="mt-1 text-xs text-slate-500">State, memory and timeline will appear here.</p>
    </div>
  );
}
