import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  MissingKey,
  QuotaExceeded,
  SessionExpired,
  createSession,
  deleteSession,
  getConfig,
  loadSettings,
  sendEvent,
  sendMessage,
} from "./api";
import Chat from "./components/Chat";
import Inspector from "./components/Inspector";
import KeyDialog from "./components/KeyDialog";
import ScenarioPicker from "./components/ScenarioPicker";
import TopBar from "./components/TopBar";
import { initialState, reducer, toChatMessages, MSG_GENERIC, type FailReason } from "./reducer";
import { suggestionsFor, type Scenario } from "./scenarios";
import type { AppConfig, ConsentScenario, TurnOut } from "./types";

const CONSENT_POLL_MS = 4000;

function failure(error: unknown): FailReason {
  if (error instanceof MissingKey) return "missing_key";
  if (error instanceof QuotaExceeded) return "quota_exceeded";
  return "other";
}

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [userSettings, setUserSettings] = useState(loadSettings);
  const [bootError, setBootError] = useState(false);
  const [showInspector, setShowInspector] = useState(false);
  const [scenario, setScenario] = useState<Scenario>();
  const [consent, setConsent] = useState<ConsentScenario>("default");
  const [draft, setDraft] = useState("");
  const booted = useRef(false);
  const sessionRef = useRef<string | null>(null);
  // A ref guards requests within the same render as well as across renders.
  const busy = useRef(false);
  const inspectorButton = useRef<HTMLButtonElement>(null);
  const closeInspectorButton = useRef<HTMLButtonElement>(null);

  const startSession = useCallback(async (mode: ConsentScenario, notice?: string) => {
    const s = await createSession(mode);
    sessionRef.current = s.session_id;
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
    if (busy.current) return;
    busy.current = true;
    setBootError(false);
    try {
      const cfg = await getConfig();
      setConfig(cfg);
      if (!cfg.has_server_key && !loadSettings()) dispatch({ type: "open_key_dialog" });
      await startSession("default");
    } catch {
      setBootError(true);
    } finally {
      busy.current = false;
    }
  }, [startSession]);

  useEffect(() => {
    if (booted.current) return; // StrictMode double-invoke guard
    booted.current = true;
    void boot();
  }, [boot]);

  const runTurn = useCallback(
    async (request: (id: string) => Promise<TurnOut>, userText?: string, poll = false) => {
      const id = sessionRef.current;
      if (!id || busy.current) return;
      busy.current = true;
      dispatch({ type: "turn_started", userText });
      try {
        dispatch({ type: "turn_succeeded", turn: await request(id) });
      } catch (error) {
        if (error instanceof SessionExpired) {
          try {
            await startSession(consent, "Session expired — started a new one.");
          } catch {
            dispatch({ type: "turn_failed", reason: "other" });
          }
        } else if (poll) {
          dispatch({ type: "poll_failed" });
        } else {
          dispatch({ type: "turn_failed", reason: failure(error) });
        }
      } finally {
        busy.current = false;
      }
    },
    [consent, startSession],
  );

  const consentPending = state.snapshot?.sub_state === "CONSENT_PENDING";
  const pollConsent = useCallback(
    () => runTurn((id) => sendEvent(id, "consent_poll"), undefined, true),
    [runTurn],
  );
  useEffect(() => {
    if (!state.sessionId || !consentPending || state.pending || state.pollStopped) return;
    const timer = window.setTimeout(() => void pollConsent(), CONSENT_POLL_MS);
    return () => window.clearTimeout(timer);
  }, [state.sessionId, state.snapshot, state.messages, state.pending, state.pollFailures, state.pollStopped, consentPending, pollConsent]);

  const retryPolling = () => {
    dispatch({ type: "poll_retry" });
    void pollConsent();
  };

  const replaceSession = async (mode: ConsentScenario, preset?: Scenario) => {
    const previous = sessionRef.current;
    if (!previous || busy.current) return;
    busy.current = true;
    dispatch({ type: "turn_started" });
    try {
      await startSession(mode);
      setConsent(mode);
      setScenario(preset);
      setDraft(preset?.opener ?? "");
      if (previous !== sessionRef.current) void deleteSession(previous).catch(() => undefined);
    } catch {
      dispatch({ type: "turn_failed", reason: "other" });
    } finally {
      busy.current = false;
    }
  };

  const closeInspector = useCallback(() => {
    setShowInspector(false);
    inspectorButton.current?.focus();
  }, []);

  useEffect(() => {
    if (!showInspector) return;
    closeInspectorButton.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeInspector();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [showInspector, closeInspector]);

  const keyNotice = state.error === MSG_GENERIC ? undefined : state.error;
  const ready = state.sessionId !== null;

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
        onReset={() => void replaceSession(consent, scenario)}
        disabled={state.pending || !ready}
      >
        <ScenarioPicker
          scenarioId={scenario?.id ?? ""}
          consent={consent}
          disabled={state.pending || !ready}
          onScenario={(preset) => void replaceSession(preset?.consent ?? "default", preset)}
          onConsent={(mode) => void replaceSession(mode, scenario?.consent === mode ? scenario : undefined)}
        />
      </TopBar>
      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_400px]">
        <div className="flex min-h-0 min-w-0 flex-col border-slate-200 lg:border-r">
          <div className="border-b border-slate-200 bg-white px-4 py-2 lg:hidden">
            <button
              type="button"
              ref={inspectorButton}
              aria-expanded={showInspector}
              aria-controls="inspector"
              onClick={() => setShowInspector(true)}
              className="text-sm text-slate-600 underline underline-offset-2"
            >
              Show inspector
            </button>
          </div>
          {state.pollStopped && consentPending && (
            <div className="flex items-center justify-between gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
              <span>Consent status checks stopped after repeated connection errors.</span>
              <button
                type="button"
                onClick={retryPolling}
                className="rounded-md border border-amber-300 bg-white px-3 py-1 text-amber-900 hover:bg-amber-100"
              >
                Retry
              </button>
            </div>
          )}
          <Chat
            messages={state.messages}
            quickReplies={state.quickReplies}
            pending={state.pending}
            ready={ready}
            draft={draft}
            suggestions={suggestionsFor(scenario?.id ?? "", state.snapshot?.phase ?? "")}
            onDraft={setDraft}
            onSend={(text) => void runTurn((id) => sendMessage(id, { text }), text)}
            onQuickReply={(reply) => void runTurn((id) => sendMessage(id, { action: reply.action }), reply.label)}
          />
        </div>
        {showInspector && (
          <button
            type="button"
            aria-hidden="true"
            tabIndex={-1}
            onClick={closeInspector}
            className="fixed inset-0 z-10 bg-slate-950/40 lg:hidden"
          />
        )}
        <aside
          id="inspector"
          className={`${showInspector ? "fixed inset-y-0 right-0 z-20 w-full max-w-[400px] shadow-xl" : "hidden"} overflow-y-auto bg-slate-50 p-4 lg:static lg:block lg:w-auto lg:max-w-none lg:shadow-none`}
          aria-label="Inspector"
        >
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="font-semibold text-slate-900">Inspector</h2>
            <button
              type="button"
              ref={closeInspectorButton}
              onClick={closeInspector}
              className="rounded-md border border-slate-300 px-3 py-1 text-sm text-slate-700 lg:hidden"
            >
              Close inspector
            </button>
          </div>
          <Inspector sessionId={state.sessionId} snapshot={state.snapshot} />
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
