export function recordRetrievalDiagnostics(page, { limit = 60, lifetimeMs = 165000 } = {}) {
  const events = [];
  const safeUrl = value => { try { const url = new URL(value); return `${url.origin}${url.pathname}`; } catch { return ""; } };
  const push = value => { if (events.length < limit) events.push({ at: new Date().toISOString(), ...value }); };
  const failed = request => push({ kind: "request_failed", url: safeUrl(request.url()),
    error_code: String(request.failure()?.errorText || "").match(/(?:net::)?ERR_[A-Z0-9_]+/)?.[0] || "REQUEST_FAILED" });
  const response = value => { if (value.status() >= 400) push({ kind: "http_error", url: safeUrl(value.url()), status: value.status() }); };
  const pageError = error => push({ kind: "page_error", error_name: ["TypeError", "ReferenceError", "SyntaxError", "RangeError"].includes(error.name) ? error.name : "Error" });
  page.on("requestfailed", failed); page.on("response", response); page.on("pageerror", pageError);
  const timer = setTimeout(stop, lifetimeMs); timer.unref?.();
  function stop() {
    clearTimeout(timer);
    page.off("requestfailed", failed); page.off("response", response); page.off("pageerror", pageError);
    return events.slice();
  }
  return { stop };
}
