import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadSettings } from "../api";
import KeyDialog from "../components/KeyDialog";

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  sessionStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function open() {
  render(<KeyDialog open onClose={() => undefined} onChanged={() => undefined} />);
}

const input = (name: string) => screen.getByLabelText(name) as HTMLInputElement;

async function testConnection() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
  });
  return screen.getByRole("status").textContent ?? "";
}

describe("KeyDialog", () => {
  it.each([
    ["auth", "Key rejected"],
    ["rate_limit", "Rate limited — try again shortly"],
    ["timeout", "Timed out"],
    ["model_unavailable", "This key can't use that model"],
    ["other", "Couldn't connect"],
  ])("maps validate-key error %s to readable text", async (kind, text) => {
    fetchMock.mockResolvedValueOnce(response({ ok: false, error: kind }));
    open();
    fireEvent.change(input("API key"), { target: { value: "sk-test" } });
    const status = await testConnection();
    expect(status).toContain(text);
    expect(status).not.toContain(kind === "other" ? "other" : kind);
  });

  it("shows the backend detail for an invalid provider configuration", async () => {
    fetchMock.mockResolvedValueOnce(
      response({ code: "invalid_provider", detail: "Base URL must use https" }, 400),
    );
    open();
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "custom" } });
    fireEvent.change(input("API key"), { target: { value: "sk-test" } });
    fireEvent.change(input("Base URL"), { target: { value: "http://x.example.com/v1" } });
    fireEvent.change(input("Model"), { target: { value: "m" } });
    const status = await testConnection();
    expect(status).toContain("Base URL must use https");
    expect(status).not.toContain("Could not reach the server");
  });

  it("offers an optional Model field for OpenAI and DeepSeek with the default as placeholder", async () => {
    open();
    expect(input("Model").placeholder).toBe("gpt-4.1-mini");
    expect(input("Model").required).toBe(false);
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "deepseek" } });
    expect(input("Model").placeholder).toBe("deepseek-chat");
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "custom" } });
    expect(input("Model").required).toBe(true);
  });

  it("sends the chosen OpenAI model when testing and saves it for request headers", async () => {
    fetchMock.mockResolvedValueOnce(response({ ok: true }));
    open();
    fireEvent.change(input("API key"), { target: { value: "sk-test" } });
    fireEvent.change(input("Model"), { target: { value: "gpt-4o-mini" } });
    expect(await testConnection()).toContain("Connection OK");
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body).toMatchObject({ provider: "openai", model: "gpt-4o-mini", api_key: "sk-test" });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(loadSettings()).toEqual({ provider: "openai", apiKey: "sk-test", model: "gpt-4o-mini" });
  });

  it("omits the model when the field is left blank", () => {
    open();
    fireEvent.change(input("API key"), { target: { value: "sk-test" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(loadSettings()).toEqual({ provider: "openai", apiKey: "sk-test" });
  });

  it("requires a base URL and model before saving a Custom provider", () => {
    open();
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "custom" } });
    fireEvent.change(input("API key"), { target: { value: "sk-test" } });
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(input("Base URL"), { target: { value: "https://api.example.com/v1" } });
    fireEvent.change(input("Model"), { target: { value: "m" } });
    expect(save.disabled).toBe(false);
  });
});
