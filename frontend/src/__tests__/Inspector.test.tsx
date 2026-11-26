import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import Inspector from "../components/Inspector";
import type { Snapshot } from "../types";

afterEach(cleanup);

const snapshot: Snapshot = {
  phase: "PROCESS_CASE", sub_state: "ACTIVE", access_granted: true, caller_role: "policyholder",
  verification_failures: 0, identity: [], active_case_id: "CL-2102", discussed_case_ids: [],
  primary_intent: null, emotion: null, counters: {}, consent: { status: "not_requested", polls: 0, scenario: "default" },
  email: { decision: null, preview: null }, handoff: null, events: [],
  memory: [
    { key: "case_type", value: "auto", captured_phase: "PROCESS_CASE", captured_turn: 3, used_phase: "RESOLVE_INTENT", used_turn: 3 },
    { key: "intent", value: "status_inquiry", captured_phase: "PROCESS_CASE", captured_turn: 3, used_phase: null, used_turn: null },
  ],
};

it("shows when each memory slot was captured and used, by turn", () => {
  render(<Inspector sessionId="s1" snapshot={snapshot} />);
  fireEvent.click(screen.getByRole("tab", { name: "Memory" }));
  expect(screen.getByText(/captured turn 3 in PROCESS_CASE → used turn 3 in RESOLVE_INTENT \(claim lookup\)/)).toBeTruthy();
  expect(screen.getByText(/captured turn 3 in PROCESS_CASE → not used yet/)).toBeTruthy();
});
