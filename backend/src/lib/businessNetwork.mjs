/** Time-bounded network calls for Clippr Business.
 * Never retries a metered job. Caller decides whether an idempotent operation
 * may be retried; a timeout means the server might have completed it.
 */
export async function guardedFetch(url, options = {}, { timeoutMs = 16000 } = {}) {
  if (!Number.isFinite(timeoutMs) || timeoutMs < 1000 || timeoutMs > 240000)
    throw new TypeError("Invalid request timeout");
  const controller = new AbortController();
  const upstream = options.signal;
  if (upstream?.aborted) {
    throw Object.assign(new Error("This request was cancelled."), { code: "request_cancelled" });
  }
  const abortUpstream = () => controller.abort();
  upstream?.addEventListener?.("abort", abortUpstream, { once: true });
  let timedOut = false;
  const deadline = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (upstream?.aborted)
      throw Object.assign(new Error("This request was cancelled."), { code: "request_cancelled" });
    if (timedOut)
      throw Object.assign(new Error("The server took too long to respond. Your existing job may still be running; check its status before retrying."), {
        code: "request_timeout"
      });
    throw error;
  } finally {
    clearTimeout(deadline);
    upstream?.removeEventListener?.("abort", abortUpstream);
  }
}
