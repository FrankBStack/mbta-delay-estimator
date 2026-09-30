// Runs tick now, then again after whatever delay it returns, until the
// returned function stops it. A hidden tab doesn't poll at all; coming back
// runs tick at once.
export function startPolling(tick, doc = globalThis.document) {
  let alive = true;
  let running = false;
  let timer;
  const isAlive = () => alive;

  const run = async () => {
    if (running) return;
    running = true;
    clearTimeout(timer);
    let delay;
    try {
      delay = await tick(isAlive);
    } finally {
      running = false;
    }
    if (alive && doc?.visibilityState !== "hidden") timer = setTimeout(run, delay);
  };

  const onVisible = () => {
    if (doc.visibilityState === "visible") run();
  };
  doc?.addEventListener("visibilitychange", onVisible);
  run();

  return () => {
    alive = false;
    clearTimeout(timer);
    doc?.removeEventListener("visibilitychange", onVisible);
  };
}
