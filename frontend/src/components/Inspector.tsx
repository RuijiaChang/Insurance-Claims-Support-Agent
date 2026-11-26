import { useEffect, useState } from "react";
import type { KeyboardEvent } from "react";
import { getOutbox } from "../api";
import { SOP_PHASES } from "../scenarios";
import type { OutboxMessage, Snapshot } from "../types";

const TABS = ["State", "Memory", "Timeline", "Outbox"] as const;
type Tab = (typeof TABS)[number];
const phaseLabels = ["Verify ID", "Resolve intent", "Process case", "Post-process"];
const card = "rounded-lg border border-slate-200 bg-white p-3";

function Details({ title, rows }: { title: string; rows: [string, string | number][] }) {
  return (
    <section className={card}>
      <h3 className="mb-2 font-semibold text-slate-900">{title}</h3>
      <dl className="space-y-1">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-4 break-all">
            <dt className="text-slate-600">{label}</dt>
            <dd className="text-right font-medium">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function StatePanel({ snapshot }: { snapshot: Snapshot }) {
  const { phase, identity, consent, emotion, handoff } = snapshot;
  const current = SOP_PHASES.findIndex((step) => step === phase);
  return (
    <div className="space-y-3">
      <section className={card} aria-label="SOP phase">
        <ol className="grid grid-cols-4 gap-1">
          {SOP_PHASES.map((step, index) => (
            <li
              key={step}
              aria-current={phase === step ? "step" : undefined}
              className={`border-t-4 pt-1 ${phase === step ? "border-sky-600 font-semibold text-sky-900" : index < current ? "border-sky-300 text-slate-700" : "border-slate-200 text-slate-600"}`}
            >
              {phaseLabels[index]}
            </li>
          ))}
        </ol>
        <div className="mt-3 flex flex-wrap gap-2">
          {["HANDOFF", "CLOSED"].map((terminal) => (
            <span
              key={terminal}
              aria-current={phase === terminal ? "step" : undefined}
              className={`rounded-full px-2 py-1 ${phase === terminal ? "bg-sky-100 font-semibold text-sky-900" : "bg-slate-100 text-slate-600"}`}
            >
              {terminal}
            </span>
          ))}
        </div>
      </section>
      <Details title="Session" rows={[
        ["Phase", phase],
        ["Sub-state", snapshot.sub_state],
        ["Access", snapshot.access_granted ? "🔓 Granted" : "🔒 Locked"],
        ["Caller", snapshot.caller_role ?? "—"],
        ["Verification failures", snapshot.verification_failures],
        ["Intent", snapshot.primary_intent ?? "—"],
        ["Active case", snapshot.active_case_id ?? "—"],
        ["Discussed cases", snapshot.discussed_case_ids.join(", ") || "—"],
        ["Emotion", emotion ? `${emotion.label} (${emotion.intensity})` : "—"],
      ]} />
      <Details title="Identity" rows={identity.map(({ field, status }) => [field, status])} />
      <Details title="Consent" rows={[
        ["Status", consent.status], ["Scenario", consent.scenario], ["Polls", consent.polls],
      ]} />
      <Details title="Counters" rows={Object.entries(snapshot.counters).map(([key, value]) => [
        key, typeof value === "string" ? value : JSON.stringify(value) ?? "—",
      ])} />
      {handoff && <Details title="Handoff ticket" rows={[
        ["Ticket", handoff.ticket_id],
        ["Reason", handoff.reason],
        ["Verified", handoff.verified ? "Yes" : "No"],
        ["Intent", handoff.stated_intent ?? "—"],
        ["Case", handoff.case_id ?? "—"],
        ["Created on turn", handoff.created_turn],
      ]} />}
    </div>
  );
}

function Outbox({ sessionId, decision }: { sessionId: string; decision: string | null }) {
  const [items, setItems] = useState<OutboxMessage[]>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    void getOutbox(sessionId).then((messages) => {
      if (active) setItems(messages);
    }).catch(() => {
      if (active) setFailed(true);
    });
    return () => { active = false; };
  }, [sessionId, decision]);

  if (failed) return <p role="status">Couldn’t load the outbox. Reopen this tab to retry.</p>;
  if (!items) return <p role="status">Loading the outbox…</p>;
  if (items.length === 0) return <p>No summary emails sent yet.</p>;
  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item.message_id} className={card}>
          <h3 className="font-semibold">{item.subject}</h3>
          <p className="mb-2 text-xs text-slate-500">
            To {item.to_masked} · {new Date(item.sent_at).toLocaleString()}
          </p>
          <p className="whitespace-pre-wrap break-words text-slate-700">{item.body}</p>
        </li>
      ))}
    </ul>
  );
}

export default function Inspector({ sessionId, snapshot }: { sessionId: string | null; snapshot: Snapshot | null }) {
  const [tab, setTab] = useState<Tab>("State");
  const [outboxRevision, setOutboxRevision] = useState(0);

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const index = TABS.indexOf(tab);
    let next: Tab;
    switch (event.key) {
      case "ArrowLeft": next = TABS[(index + TABS.length - 1) % TABS.length]; break;
      case "ArrowRight": next = TABS[(index + 1) % TABS.length]; break;
      case "Home": next = TABS[0]; break;
      case "End": next = TABS[TABS.length - 1]; break;
      default: return;
    }
    event.preventDefault();
    setTab(next);
    document.getElementById(`inspector-tab-${next}`)?.focus();
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap gap-1 border-b border-slate-200" role="tablist" aria-label="Inspector views">
        {TABS.map((name) => (
          <button
            key={name}
            id={`inspector-tab-${name}`}
            type="button"
            role="tab"
            aria-selected={tab === name}
            aria-controls="inspector-panel"
            tabIndex={tab === name ? 0 : -1}
            onClick={() => {
              setTab(name);
              if (name === "Outbox") setOutboxRevision((revision) => revision + 1);
            }}
            onKeyDown={onTabKeyDown}
            className={`border-b-2 px-2.5 py-2 text-sm ${tab === name ? "border-sky-600 font-semibold text-sky-900" : "border-transparent text-slate-600 hover:text-slate-900"}`}
          >
            {name}
          </button>
        ))}
      </div>
      <div
        id="inspector-panel"
        role="tabpanel"
        aria-labelledby={`inspector-tab-${tab}`}
        tabIndex={0}
        className="text-xs text-slate-700"
      >
        {!snapshot || !sessionId ? <p>Waiting for a session…</p> : (
          <>
            {tab === "State" && <StatePanel snapshot={snapshot} />}
            {tab === "Memory" && (snapshot.memory.length ? (
              <ul className="space-y-2">
                {snapshot.memory.map(({ key, value, captured_phase, captured_turn, used_phase, used_turn }) => (
                  <li key={key} className={`${card} break-words`}>
                    <span className="font-semibold">{key}={value}</span>
                    <p className="mt-1 text-slate-600">
                      captured turn {captured_turn} in {captured_phase} &rarr;{" "}
                      {used_phase ? `used turn ${used_turn ?? "?"} in ${used_phase}${used_phase === "RESOLVE_INTENT" ? " (claim lookup)" : ""}` : "not used yet"}
                    </p>
                  </li>
                ))}
              </ul>
            ) : <p>No memory slots captured yet.</p>)}
            {tab === "Timeline" && (snapshot.events.length ? (
              <ol className="space-y-2">
                {snapshot.events.map(({ turn, stage, summary }, index) => (
                  <li key={index} className={`${card} break-words`}>
                    <span className="font-semibold">Turn {turn} · {stage}</span>
                    <p className="mt-1 whitespace-pre-wrap">{summary}</p>
                  </li>
                ))}
              </ol>
            ) : <p>No timeline events yet.</p>)}
            {tab === "Outbox" && (
              <Outbox
                key={`${sessionId}:${snapshot.email.decision}:${outboxRevision}`}
                sessionId={sessionId}
                decision={snapshot.email.decision}
              />
            )}
          </>
        )}
      </div>
    </>
  );
}
