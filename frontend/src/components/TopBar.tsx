import type { ReactNode } from "react";
import type { AppConfig, ModelSettings } from "../types";

interface Props {
  config: AppConfig | null;
  userSettings: ModelSettings | null;
  onOpenKeyDialog: () => void;
  onReset: () => void;
  disabled: boolean;
  children: ReactNode;
}

const PROVIDER_LABEL: Record<string, string> = {
  openai: "OpenAI",
  deepseek: "DeepSeek",
  custom: "Custom",
};

export default function TopBar({ config, userSettings, onOpenKeyDialog, onReset, disabled, children }: Props) {
  const linkCls = "underline underline-offset-2 hover:text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 rounded";
  let keyStatus: JSX.Element;
  if (userSettings) {
    keyStatus = (
      <button type="button" onClick={onOpenKeyDialog} className={linkCls}>
        Your key ({PROVIDER_LABEL[userSettings.provider] ?? userSettings.provider})
      </button>
    );
  } else if (config?.has_server_key) {
    keyStatus = (
      <span>
        Using demo key{config.model ? ` · ${config.model}` : ""} &middot;{" "}
        <button type="button" onClick={onOpenKeyDialog} className={linkCls}>
          bring your own key
        </button>
      </span>
    );
  } else if (!config) {
    // Before /api/config answers (e.g. a sleeping free instance waking up), don't claim
    // there is no key: there may well be a demo key.
    keyStatus = <span className="text-slate-500">Connecting&hellip;</span>;
  } else {
    keyStatus = (
      <button type="button" onClick={onOpenKeyDialog} className={`${linkCls} text-amber-700`}>
        No key &mdash; add one
      </button>
    );
  }

  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-200 bg-white px-4 py-3">
      <h1 className="text-base font-semibold sm:text-lg">SOP Insurance Claims Agent</h1>
      {config && (
        <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-600">
          Demo date: {config.demo_today}
        </span>
      )}
      {children}
      <div className="ml-auto flex items-center gap-4 text-sm text-slate-600">
        {keyStatus}
        <button
          type="button"
          onClick={onReset}
          disabled={disabled}
          className="rounded-md border border-slate-300 px-3 py-1 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          Reset
        </button>
      </div>
    </header>
  );
}
