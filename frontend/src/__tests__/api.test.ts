import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MissingKey,
  QuotaExceeded,
  SessionExpired,
  clearSettings,
  getConfig,
  saveSettings,
  sendMessage,
} from "../api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("api error mapping", () => {
  it("404 -> SessionExpired", async () => {
    mockFetch(404, { code: "session_not_found" });
    await expect(sendMessage("x", { text: "hi" })).rejects.toBeInstanceOf(SessionExpired);
  });
  it("401 -> MissingKey", async () => {
    mockFetch(401, { code: "missing_api_key" });
    await expect(sendMessage("x", { text: "hi" })).rejects.toBeInstanceOf(MissingKey);
  });
  it("429 demo_quota_exceeded -> QuotaExceeded", async () => {
    mockFetch(429, { code: "demo_quota_exceeded" });
    await expect(sendMessage("x", { text: "hi" })).rejects.toBeInstanceOf(QuotaExceeded);
  });
  it("other 429 -> generic ApiError, not QuotaExceeded", async () => {
    mockFetch(429, { code: "rate_limited" });
    const err = await sendMessage("x", { text: "hi" }).catch((e) => e);
    expect(err).not.toBeInstanceOf(QuotaExceeded);
    expect(err).toBeInstanceOf(Error);
  });
  it("non-JSON error body does not throw a parse error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => {
          throw new SyntaxError("bad json");
        },
      }),
    );
    const err = await getConfig().catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err).not.toBeInstanceOf(SyntaxError);
  });
});

describe("api headers", () => {
  it("sends no key headers when nothing is stored", async () => {
    const f = mockFetch(200, {});
    await getConfig();
    const headers = f.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["X-OpenAI-Key"]).toBeUndefined();
    expect(headers["X-LLM-Provider"]).toBeUndefined();
  });
  it("sends key headers when a key is stored", async () => {
    saveSettings({ provider: "custom", apiKey: "sk-test", baseUrl: "http://x/v1", model: "m" });
    const f = mockFetch(200, {});
    await getConfig();
    const headers = f.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["X-OpenAI-Key"]).toBe("sk-test");
    expect(headers["X-LLM-Provider"]).toBe("custom");
    expect(headers["X-LLM-Base-URL"]).toBe("http://x/v1");
    expect(headers["X-LLM-Model"]).toBe("m");
  });
  it("stops sending headers after clearSettings", async () => {
    saveSettings({ provider: "openai", apiKey: "sk-test" });
    clearSettings();
    const f = mockFetch(200, {});
    await getConfig();
    const headers = f.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["X-OpenAI-Key"]).toBeUndefined();
  });
});
