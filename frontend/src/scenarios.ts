import type { ConsentScenario } from "./types";

export const SOP_PHASES = ["VERIFY_ID", "RESOLVE_INTENT", "PROCESS_CASE", "POST_PROCESS"] as const;
type Phase = (typeof SOP_PHASES)[number] | "HANDOFF" | "CLOSED";

export interface Scenario {
  id: string;
  label: string;
  consent: ConsentScenario;
  opener: string;
  suggestions: Partial<Record<Phase, string[]>>;
}

const davidOpener =
  "Hi, I'm David Chen, calling for my mom Margaret Chen. Her DOB is 1985-03-15, SSN last four 4472, policy POL-9921.";
const wrongIdentity = "I'm Margaret Chen, DOB 1990-01-01, SSN last four 1111.";

export const SCENARIOS: Scenario[] = [
  {
    id: "margaret",
    label: "Margaret · denied claim",
    consent: "default",
    opener: "I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.",
    suggestions: {
      PROCESS_CASE: [
        "What exactly do I need to send?",
        "How soon do I need to submit?",
        "How long after I submit?",
        "And what about my auto claim?",
        "That's all, thanks",
      ],
    },
  },
  {
    id: "angry",
    label: "Margaret · frustrated caller",
    consent: "default",
    opener: "Hi, I'm Margaret Chen",
    suggestions: {
      VERIFY_ID: [
        "I already told you who I am. This is ridiculous. Just tell me why my claim was denied.",
        "My DOB is 1985-03-15 and my SSN last four is 4472. It's my denied healthcare claim from January.",
      ],
      PROCESS_CASE: ["That's all, thanks"],
    },
  },
  {
    id: "david_default",
    label: "David · consent approved",
    consent: "default",
    opener: davidOpener,
    suggestions: {
      RESOLVE_INTENT: ["I'm calling about her denied healthcare claim from January."],
      PROCESS_CASE: ["What exactly do I need to send?", "That's all, thanks"],
    },
  },
  {
    id: "david_timeout",
    label: "David · consent timeout",
    consent: "timeout",
    opener: davidOpener,
    suggestions: {},
  },
  {
    id: "yawen_alias",
    label: "Ya Wen · name alias",
    consent: "default",
    opener: "This is Yaven Li, email yawen.li@example.com, phone 650-521-2830.",
    suggestions: { RESOLVE_INTENT: ["Can you tell me the status of my claims?"] },
  },
  {
    id: "matian_national_id",
    label: "Ma Tian · national ID",
    consent: "default",
    opener: "Ma Tian here, born 1964-09-10, national ID last four 6688.",
    suggestions: { RESOLVE_INTENT: ["Can you tell me the status of my claims?"] },
  },
  {
    id: "ava_no_claims",
    label: "Ava · no claims",
    consent: "default",
    opener: "Ava Lopez, DOB 1990-08-21, SSN last 4 is 9180, phone 650-388-2920.",
    suggestions: { RESOLVE_INTENT: ["Do I have any claims on file?"] },
  },
  {
    id: "off_topic",
    label: "Repeated off-topic requests",
    consent: "default",
    opener: "What is reinforcement learning?",
    suggestions: { VERIFY_ID: ["Who won the World Cup?", "Can you write me a poem?"] },
  },
  {
    id: "lockout",
    label: "Margaret · verification lockout",
    consent: "default",
    opener: wrongIdentity,
    suggestions: {
      VERIFY_ID: [
        "My DOB is 1990-01-02 and my SSN last four is 2222.",
        "My DOB is 1990-01-03 and my SSN last four is 3333.",
      ],
    },
  },
];

export function suggestionsFor(scenarioId: string, phase: string): string[] {
  const suggestions = SCENARIOS.find(({ id }) => id === scenarioId)?.suggestions;
  return suggestions && Object.prototype.hasOwnProperty.call(suggestions, phase) ? suggestions[phase as Phase] ?? [] : [];
}
