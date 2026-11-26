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
      has_server_key: true, demo_today: "2026-03-05", consent_scenarios: ["default", "timeout"],
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
  expect(screen.getByText(/Something went wrong/)).toBeTruthy();
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

it("fills the composer from a phase suggestion without sending it", async () => {
  await start();
  await act(async () => {
    fireEvent.change(screen.getByLabelText("Scenario"), { target: { value: "off_topic" } });
  });
  const textarea = screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;
  expect(textarea.value).toBe("What is reinforcement learning?");
  fireEvent.click(screen.getByRole("button", { name: "Who won the World Cup?" }));
  expect(textarea.value).toBe("Who won the World Cup?");
  expect(document.activeElement).toBe(textarea);
  expect(requests("POST", "/api/sessions/s1/messages")).toHaveLength(0);
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
