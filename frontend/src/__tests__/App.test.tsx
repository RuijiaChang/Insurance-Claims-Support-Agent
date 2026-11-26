import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "../App";
import type { Snapshot } from "../types";

const snapshot: Snapshot = {
  phase: "VERIFY_ID", sub_state: "CONSENT_PENDING", access_granted: false, caller_role: null,
  verification_failures: 0, identity: [{ field: "dob", status: "provided" }], memory: [],
  active_case_id: null, discussed_case_ids: [], primary_intent: null, emotion: null,
  counters: {}, consent: { status: "pending", polls: 0, scenario: "default" },
  email: { decision: null, preview: null }, handoff: null, events: [],
};

const agent = [{ role: "agent", text: "Welcome" }];
const replies = [{ label: "Talk to a representative", action: "handoff" }];
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

const fetchMock = vi.fn<typeof fetch>();
const requests = (method: string, path: string) =>
  fetchMock.mock.calls.filter(([url, options]) => options?.method === method && url === path);

beforeEach(() => {
  vi.useFakeTimers();
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (url) => {
    if (url === "/api/config") return response({
      has_server_key: true, provider: "openai", model: "gpt-4.1-mini",
      demo_today: "2026-03-05", consent_scenarios: ["default", "timeout"],
    });
    if (url === "/api/sessions/s1") return new Response(null, { status: 204 });
    if (url === "/api/sessions") return response({
      session_id: "s1", messages: agent, state: snapshot, quick_replies: replies,
    });
    throw new Error("Unexpected request " + url);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function start() {
  await act(async () => { render(<App />); });
}

it("polls after four seconds without overlap and stops when consent expires", async () => {
  await start();
  let finishPoll!: (value: Response) => void;
  fetchMock.mockImplementationOnce(() => new Promise((resolve) => { finishPoll = resolve; }));
  await act(async () => { await vi.advanceTimersByTimeAsync(3999); });
  expect(requests("POST", "/api/sessions/s1/events")).toHaveLength(0);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(requests("POST", "/api/sessions/s1/events")).toHaveLength(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
  expect(requests("POST", "/api/sessions/s1/events")).toHaveLength(1);
  await act(async () => { finishPoll(response({
    messages: [{ role: "agent", text: "Consent expired" }], quick_replies: replies,
    state: { ...snapshot, sub_state: "CONSENT_EXPIRED" }, llm_error: null,
  })); });
  expect(screen.getByText("Consent expired")).toBeTruthy();
  expect(screen.getByRole("button", { name: replies[0].label })).toBeTruthy();
  await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
  expect(requests("POST", "/api/sessions/s1/events")).toHaveLength(1);
});

it("replaces the session once and suspends polling during reset", async () => {
  await start();
  let finishCreate!: (value: Response) => void;
  fetchMock.mockImplementationOnce(() => new Promise((resolve) => { finishCreate = resolve; }));
  const reset = screen.getByRole("button", { name: "Reset" });
  await act(async () => { fireEvent.click(reset); fireEvent.click(reset); });
  expect(requests("POST", "/api/sessions")).toHaveLength(2);
  await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
  expect(requests("POST", "/api/sessions/s1/events")).toHaveLength(0);
  await act(async () => { finishCreate(response({ session_id: "s2", messages: agent, state: snapshot, quick_replies: replies })); });
  expect(requests("DELETE", "/api/sessions/s1")).toHaveLength(1);
});

it("preserves quick replies after a failed turn", async () => {
  await start();
  fetchMock.mockResolvedValueOnce(response({}, 500));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: replies[0].label })); });
  expect(screen.getByText(/Something went wrong/)).toBeTruthy();
  expect(screen.getByRole("button", { name: replies[0].label })).toBeTruthy();
});

it("starts the timeout preset and prefills its opener without sending it", async () => {
  await start();
  await act(async () => {
    fireEvent.change(screen.getByLabelText("Scenario"), { target: { value: "david_timeout" } });
  });
  expect(requests("POST", "/api/sessions")[1]?.[1]?.body).toBe('{"consent_scenario":"timeout"}');
  expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value)
    .toContain("I'm David Chen");
  expect(requests("POST", "/api/sessions/s1/messages")).toHaveLength(0);
});

it("loads the current session's sent mail when Outbox opens", async () => {
  await start();
  fetchMock.mockResolvedValueOnce(response([
    { message_id: "m1", subject: "Claims summary", body: "Send an itemized bill." },
  ]));
  await act(async () => { fireEvent.click(screen.getByRole("tab", { name: "Outbox" })); });
  expect(screen.getByText("Claims summary")).toBeTruthy();
  expect(screen.getByText("Send an itemized bill.")).toBeTruthy();
});

it("restarts the poll interval after a transient failure", async () => {
  await start();
  fetchMock.mockResolvedValueOnce(response({}, 503));
  await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
  // A single failed background poll is retried silently: no error bubble.
  expect(screen.queryByText(/Something went wrong|Lost connection/)).toBeNull();
  fetchMock.mockResolvedValueOnce(response({
    messages: [], quick_replies: [], state: {
      ...snapshot,
      phase: "RESOLVE_INTENT",
      sub_state: "NONE",
      access_granted: true,
    }, llm_error: null,
  }));
  await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
  expect(requests("POST", "/api/sessions/s1/events")).toHaveLength(2);
  expect(screen.getByText(/Granted/)).toBeTruthy();
});

it("sends a phase suggestion on click and hides it once sent", async () => {
  await start();
  await act(async () => {
    fireEvent.change(screen.getByLabelText("Scenario"), { target: { value: "off_topic" } });
  });
  const textarea = screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;
  expect(textarea.value).toBe("What is reinforcement learning?");
  fetchMock.mockResolvedValueOnce(response({ messages: [{ role: "agent", text: "Only claims." }], quick_replies: [], state: snapshot }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Who won the World Cup?" }));
  });
  const sent = requests("POST", "/api/sessions/s1/messages");
  expect(sent).toHaveLength(1);
  expect(JSON.parse(String(sent[0][1]?.body))).toEqual({ text: "Who won the World Cup?" });
  expect(textarea.value).toBe("What is reinforcement learning?"); // the draft is left alone
  expect(screen.queryByRole("button", { name: "Who won the World Cup?" })).toBeNull();
  expect(screen.getByRole("button", { name: "Can you write me a poem?" })).toBeTruthy();
});

it("returns keyboard focus to the inspector trigger when the drawer closes", async () => {
  await start();
  const open = screen.getByRole("button", { name: "Show inspector" });
  fireEvent.click(open);
  expect(open.getAttribute("aria-expanded")).toBe("true");
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close inspector" }));
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(open.getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(open);
});

it("stops polling after three consecutive failures and resumes on Retry", async () => {
  await start();
  fetchMock.mockResolvedValueOnce(response({}, 503));
  fetchMock.mockResolvedValueOnce(response({}, 503));
  fetchMock.mockResolvedValueOnce(response({}, 503));
  for (let i = 0; i < 3; i++) {
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
  }
  expect(requests("POST", "/api/sessions/s1/events")).toHaveLength(3);
  expect(screen.getAllByText(/Lost connection to the server/)).toHaveLength(1);
  expect(screen.queryByText(/Something went wrong/)).toBeNull();
  await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
  expect(requests("POST", "/api/sessions/s1/events")).toHaveLength(3);
  fetchMock.mockResolvedValueOnce(response({
    messages: [{ role: "agent", text: "Still waiting" }], quick_replies: [], state: snapshot, llm_error: null,
  }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry" })); });
  expect(requests("POST", "/api/sessions/s1/events")).toHaveLength(4);
  expect(screen.getByText("Still waiting")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  // Polling resumes on its normal interval, and the failure count starts over.
  fetchMock.mockResolvedValueOnce(response({}, 503));
  await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
  expect(requests("POST", "/api/sessions/s1/events")).toHaveLength(5);
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
});

it("shows the server model next to the demo key", async () => {
  await start();
  expect(screen.getByText(/Using demo key · gpt-4\.1-mini/)).toBeTruthy();
});

it("shows a notice bubble when a reply fell back to templates", async () => {
  await start();
  fetchMock.mockResolvedValueOnce(response({
    messages: [{ role: "agent", text: "Template reply" }], quick_replies: [], state: snapshot,
    llm_error: "model_unavailable",
  }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: replies[0].label })); });
  expect(screen.getByText(/selected model isn't available for this key/)).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
});
