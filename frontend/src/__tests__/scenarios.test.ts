import { expect, it } from "vitest";
import { SCENARIOS, suggestionsFor } from "../scenarios";

it("lists the nine presets in order", () => {
  expect(SCENARIOS.map(({ id }) => id)).toEqual([
    "margaret", "angry", "david_default", "david_timeout", "yawen_alias",
    "matian_national_id", "ava_no_claims", "off_topic", "lockout",
  ]);
});

it("provides Margaret's submission prompt during case processing", () => {
  expect(suggestionsFor("margaret", "PROCESS_CASE")).toContain("How soon do I need to submit?");
  expect(suggestionsFor("margaret", "POST_PROCESS")).toEqual([]);
});

it("returns an empty list for an unknown scenario or phase", () => {
  expect(suggestionsFor("unknown", "PROCESS_CASE")).toEqual([]);
  expect(suggestionsFor("margaret", "constructor")).toEqual([]);
});
