import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api.js";

function fetchOk(body) {
  return vi.fn(async () => ({ ok: true, status: 200, statusText: "OK", json: async () => body }));
}

afterEach(() => {
  vi.unstubAllGlobals();
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
