import { useEffect, useState } from "react";
import { ApiError, clearSettings, loadSettings, saveSettings, validateKey } from "../api";
import type { ModelSettings, Provider } from "../types";

interface Props {
  open: boolean;
  notice?: string;
  onClose: () => void;
  onChanged: () => void;
}

/** Placeholder for the optional Model field: the backend default for each preset. */
const DEFAULT_MODEL: Record<Provider, string> = {
  openai: "gpt-4.1-mini",
  deepseek: "deepseek-chat",
  custom: "model name",
};

const VALIDATE_ERRORS: Record<string, string> = {
  auth: "Key rejected",
  rate_limit: "Rate limited — try again shortly",
  timeout: "Timed out",
  model_unavailable: "This key can't use that model",
  other: "Couldn't connect",
};

type TestState = { kind: "idle" } | { kind: "testing" } | { kind: "ok" } | { kind: "failed"; message: string };

export default function KeyDialog({ open, notice, onClose, onChanged }: Props) {
  const [provider, setProvider] = useState<Provider>("openai");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [test, setTest] = useState<TestState>({ kind: "idle" });

  useEffect(() => {
    if (!open) return;
    const s = loadSettings();
    setProvider(s?.provider ?? "openai");
    setApiKey(s?.apiKey ?? "");
    setBaseUrl(s?.baseUrl ?? "");
    setModel(s?.model ?? "");
    setTest({ kind: "idle" });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const current = (): ModelSettings => {
    const s: ModelSettings = { provider, apiKey: apiKey.trim() };
    if (provider === "custom" && baseUrl.trim()) s.baseUrl = baseUrl.trim();
    if (model.trim()) s.model = model.trim();
    return s;
  };
  const isCustom = provider === "custom";
  const complete = apiKey.trim().length > 0 && (!isCustom || (baseUrl.trim().length > 0 && model.trim().length > 0));

  const runTest = async () => {
    setTest({ kind: "testing" });
    try {
      const r = await validateKey(current());
      setTest(
        r.ok ? { kind: "ok" } : { kind: "failed", message: VALIDATE_ERRORS[r.error ?? ""] ?? VALIDATE_ERRORS.other },
      );
    } catch (error) {
      const detail = error instanceof ApiError ? error.detail : undefined;
      setTest({ kind: "failed", message: detail ?? "Could not reach the server. Please try again." });
    }
  };

  const field = "mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="key-dialog-title" className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl">
        <h2 id="key-dialog-title" className="text-lg font-semibold">
          Model settings
        </h2>
        {notice && <p className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">{notice}</p>}
        <p className="mt-2 text-xs text-slate-500">
          Your key is kept only in this browser tab (session storage) and sent with your requests. It is never logged.
        </p>
        <div className="mt-4 space-y-3">
          <label className="block text-sm font-medium">
            Provider
            <select
              className={field}
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value as Provider);
                setModel(""); // a model name rarely carries over between providers
                setTest({ kind: "idle" });
              }}
            >
              <option value="openai">OpenAI</option>
              <option value="deepseek">DeepSeek</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          <label className="block text-sm font-medium">
            API key
            <input
              className={field}
              type="password"
              autoComplete="off"
              value={apiKey}
              placeholder="sk-..."
              onChange={(e) => {
                setApiKey(e.target.value);
                setTest({ kind: "idle" });
              }}
            />
          </label>
          {isCustom && (
            <label className="block text-sm font-medium">
              Base URL
              <input
                className={field}
                required
                value={baseUrl}
                placeholder="https://api.example.com/v1"
                onChange={(e) => {
                  setBaseUrl(e.target.value);
                  setTest({ kind: "idle" });
                }}
              />
            </label>
          )}
          <label className="block text-sm font-medium">
            Model
            <input
              className={field}
              required={isCustom}
              value={model}
              placeholder={DEFAULT_MODEL[provider]}
              onChange={(e) => {
                setModel(e.target.value);
                setTest({ kind: "idle" });
              }}
            />
          </label>
          {!isCustom && (
            <p className="-mt-2 text-xs text-slate-500">Optional — leave blank to use {DEFAULT_MODEL[provider]}.</p>
          )}
        </div>
        <div className="mt-3 min-h-[1.25rem] text-sm" role="status">
          {test.kind === "testing" && <span className="text-slate-500">Testing&hellip;</span>}
          {test.kind === "ok" && <span className="text-green-700">Connection OK</span>}
          {test.kind === "failed" && <span className="text-red-700">Connection failed: {test.message}</span>}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={runTest}
            disabled={!complete || test.kind === "testing"}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            Test connection
          </button>
          <button
            type="button"
            onClick={() => {
              clearSettings();
              setApiKey("");
              setTest({ kind: "idle" });
              onChanged();
            }}
            className="rounded-md px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
          >
            Clear
          </button>
          <span className="flex-1" />
          <button type="button" onClick={onClose} className="rounded-md px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50">
            Cancel
          </button>
          <button
            type="button"
            disabled={!complete}
            onClick={() => {
              saveSettings(current());
              onChanged();
              onClose();
            }}
            className="rounded-md bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
