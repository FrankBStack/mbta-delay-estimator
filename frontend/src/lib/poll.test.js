import { afterEach, describe, expect, it, vi } from "vitest";
import { startPolling } from "./poll.js";

function fakeDocument() {
  const doc = new EventTarget();
  doc.visibilityState = "visible";
  doc.show = () => {
    doc.visibilityState = "visible";
    doc.dispatchEvent(new Event("visibilitychange"));
  };
  doc.hide = () => {
    doc.visibilityState = "hidden";
    doc.dispatchEvent(new Event("visibilitychange"));
  };
  return doc;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("startPolling", () => {
  it("does not poll while the tab is hidden", async () => {
    vi.useFakeTimers();
    const doc = fakeDocument();
    const tick = vi.fn(async () => 1000);
    const stop = startPolling(tick, doc);
    await vi.advanceTimersByTimeAsync(0);
    doc.hide();
    await vi.advanceTimersByTimeAsync(1000);
    expect(tick).toHaveBeenCalledTimes(2); // the one already scheduled runs
    await vi.advanceTimersByTimeAsync(10000);
    expect(tick).toHaveBeenCalledTimes(2); // then nothing
    doc.show();
    await vi.advanceTimersByTimeAsync(0);
    expect(tick).toHaveBeenCalledTimes(3);
    stop();
  });

  it("runs now and again after the delay tick returns", async () => {
    vi.useFakeTimers();
    const tick = vi.fn(async () => 5000);
    const stop = startPolling(tick, fakeDocument());
    await vi.advanceTimersByTimeAsync(0);
    expect(tick).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(tick).toHaveBeenCalledTimes(2);
    stop();
  });

  it("runs at once when the tab comes back instead of waiting out the timer", async () => {
    vi.useFakeTimers();
    const doc = fakeDocument();
    const tick = vi.fn(async () => 60000);
    const stop = startPolling(tick, doc);
    await vi.advanceTimersByTimeAsync(0);
    doc.hide();
    await vi.advanceTimersByTimeAsync(0);
    expect(tick).toHaveBeenCalledTimes(1);
    doc.show();
    await vi.advanceTimersByTimeAsync(0);
    expect(tick).toHaveBeenCalledTimes(2);
    // the old timer was replaced, not left to fire as well
    await vi.advanceTimersByTimeAsync(59999);
    expect(tick).toHaveBeenCalledTimes(2);
    stop();
  });

  it("does not start a second request while one is in flight", async () => {
    vi.useFakeTimers();
    const doc = fakeDocument();
    let finish;
    const tick = vi.fn(() => new Promise((resolve) => (finish = resolve)));
    const stop = startPolling(tick, doc);
    doc.show();
    expect(tick).toHaveBeenCalledTimes(1);
    finish(5000);
    await vi.advanceTimersByTimeAsync(5000);
    expect(tick).toHaveBeenCalledTimes(2);
    stop();
  });

  it("stops scheduling and tells an in-flight tick once stopped", async () => {
    vi.useFakeTimers();
    const doc = fakeDocument();
    let finish;
    let alive;
    const tick = vi.fn((isAlive) => {
      alive = isAlive;
      return new Promise((resolve) => (finish = resolve));
    });
    const stop = startPolling(tick, doc);
    stop();
    expect(alive()).toBe(false);
    finish(1000);
    doc.show();
    await vi.advanceTimersByTimeAsync(10000);
    expect(tick).toHaveBeenCalledTimes(1);
  });
});
