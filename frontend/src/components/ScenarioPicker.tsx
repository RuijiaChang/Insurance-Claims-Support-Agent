import { SCENARIOS, type Scenario } from "../scenarios";
import type { ConsentScenario } from "../types";

interface Props {
  scenarioId: string;
  consent: ConsentScenario;
  disabled: boolean;
  onScenario: (scenario?: Scenario) => void;
  onConsent: (consent: ConsentScenario) => void;
}

const selectClass = "min-w-0 rounded-md border border-slate-300 bg-white px-2 py-1 text-sm disabled:opacity-50";
const labelClass = "flex min-w-0 items-center gap-2 text-xs text-slate-600";

export default function ScenarioPicker({ scenarioId, consent, disabled, onScenario, onConsent }: Props) {
  return (
    <div className="flex flex-wrap gap-2">
      <label className={labelClass}>
        Scenario
        <select
          className={selectClass}
          value={scenarioId}
          disabled={disabled}
          onChange={(event) => onScenario(SCENARIOS.find(({ id }) => id === event.target.value))}
        >
          <option value="">Free conversation</option>
          {SCENARIOS.map(({ id, label }) => <option key={id} value={id}>{label}</option>)}
        </select>
      </label>
      <label className={labelClass}>
        Consent
        <select
          className={selectClass}
          value={consent}
          disabled={disabled}
          onChange={(event) => onConsent(event.target.value === "timeout" ? "timeout" : "default")}
        >
          <option value="default">Default</option>
          <option value="timeout">Timeout</option>
        </select>
      </label>
    </div>
  );
}
