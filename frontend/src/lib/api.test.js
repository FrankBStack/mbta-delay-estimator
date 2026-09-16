import { afterEach, describe, expect, it, vi } from "vitest";
import { RETRY_DELAY_MS, api } from "./api.js";

function fetchOk(body) {
  return vi.fn(async () => ({ ok: true, status: 200, statusText: "OK", json: async () => body }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("api network failures", () => {
  it("retries once when the request dies before a response", async () => {
    vi.useFakeTimers();
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ ok: true, status: 200, statusText: "OK", json: async () => ({ a: 1 }) });
    vi.stubGlobal("fetch", fetch);
    const pending = api.health();
    await vi.advanceTimersByTimeAsync(RETRY_DELAY_MS);
    await expect(pending).resolves.toEqual({ a: 1 });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("surfaces the original error when the retry fails too", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetch);
    const pending = api.health();
    pending.catch(() => {});
    await vi.advanceTimersByTimeAsync(RETRY_DELAY_MS);
    await expect(pending).rejects.toThrow("Failed to fetch");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("does not retry an HTTP error", async () => {
    const fetch = vi.fn(async () => ({ ok: false, status: 502, statusText: "Bad Gateway" }));
    vi.stubGlobal("fetch", fetch);
    await expect(api.health()).rejects.toThrow("502");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe("api.routeShape", () => {
  it("fetches a route once and serves later calls from memory", async () => {
    const fetch = fetchOk({ type: "Feature", geometry: null });
    vi.stubGlobal("fetch", fetch);
    await api.routeShape("cache-1");
    await api.routeShape("cache-1");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/routes/cache-1/shape");
  });

  it("does not cache a failure", async () => {
    const failing = vi.fn(async () => ({ ok: false, status: 500, statusText: "boom" }));
    vi.stubGlobal("fetch", failing);
    await expect(api.routeShape("cache-2")).rejects.toThrow("500");
    vi.stubGlobal("fetch", fetchOk({ type: "Feature" }));
    await expect(api.routeShape("cache-2")).resolves.toEqual({ type: "Feature" });
  });

  it("encodes the route id", async () => {
    const fetch = fetchOk({});
    vi.stubGlobal("fetch", fetch);
    await api.routeShape("Green-B/x");
    expect(fetch.mock.calls[0][0]).toBe("/api/routes/Green-B%2Fx/shape");
  });
});
