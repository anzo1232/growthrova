/** Safely join a Clippr preview that can outlive the browser or backend worker.
 * Never reuploads original footage. An expired in-memory preview ID may be
 * rejoined once through the backend's idempotent preview-cache endpoint.
 */
const expiredError = error => ["http_404", "preview_expired"].includes(error?.code) ||
  /\bpreview\b.{0,35}\bexpired\b/i.test(error?.message||"");

export async function resolveBusinessPreview({
  start, read, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
  isCurrent = () => true, intervalMs = 1800, maxChecks = 32
}) {
  if (typeof start !== "function" || typeof read !== "function")
    throw new TypeError("Preview start/read functions are required");
  if (!(maxChecks >= 1 && maxChecks <= 90) || !(intervalMs >= 0 && intervalMs <= 12000))
    throw new TypeError("Invalid preview polling limit");
  let rejoins = 0;
  let failures = 0;
  let checks = 0;
  let snapshot = await start();
  while (checks < maxChecks) {
    if (!isCurrent()) return {status:"cancelled"};
    if (snapshot?.preview_url) return {status:"ready",url:snapshot.preview_url};
    if (snapshot?.status === "error") {
      if (rejoins < 1 && expiredError({code:snapshot.code,message:snapshot.error})) {
        rejoins++;
        snapshot=await start();
        continue;
      }
      throw new Error(snapshot.error || "Preview rendering failed.");
    }
    if (!snapshot?.preview_id)
      throw new Error("Clippr did not confirm the preview job.");
    await sleep(intervalMs);
    if (!isCurrent()) return {status:"cancelled"};
    checks++;
    try {
      const response=await read(snapshot.preview_id);
      failures=0;
      snapshot={...response,preview_id:snapshot.preview_id};
    } catch(error) {
      if (rejoins < 1 && expiredError(error)) {
        rejoins++;
        snapshot=await start();
        failures=0;
        continue;
      }
      failures++;
      if (["auth_required","source_not_owned","forbidden"].includes(error?.code) ||
          failures >= 3) throw error;
    }
  }
  throw new Error("Preview is delayed. Try again in a moment; your original video is safe.");
}
