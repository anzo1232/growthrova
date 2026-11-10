/** Client review state only. Server-side ownership and revision checks remain mandatory.
 * Editing never carries an earlier approval or claims verification forward.
 */
function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function validAssetUrl(value) {
  if (typeof value !== "string" || value.length > 4096) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && Boolean(url.hostname) && !url.username && !url.password;
  } catch { return false; }
}
function invalidateApproval(item) {
  return {...item, approved:false, approvedAt:null, approvedBy:null,
    approvedRevision:null, claimsVerified:false, published:false};
}
export function reviewCreative(item, change) {
  if (!isRecord(item) || !isRecord(change)) throw new TypeError("Review details required");
  if (change.type === "edit") {
    // Permit in-progress typing, deletion and trailing spaces. Validation of
    // publishable copy belongs to approval, not each input keystroke.
    if (typeof change.copy !== "string" || change.copy.length > 400)
      throw new TypeError("Invalid draft copy");
    return {...invalidateApproval(item), copyDraft:change.copy, reviewStatus:"needs_review"};
  }
  if (change.type === "regenerate") {
    return {...invalidateApproval(item), regenerationRequested:true, reviewStatus:"needs_generation"};
  }
  if (change.type === "approve") {
    if (!validAssetUrl(item.assetUrl) || item.brandVerified !== true || item.claimsVerified !== true ||
        item.regenerationRequested === true ||
        (typeof item.copyDraft === "string" && item.copyDraft.trim().length < 3))
      throw new TypeError("Review a real asset, brand and claims before approval");
    return {...item, reviewStatus:"approved_for_manual_export", approved:true, published:false};
  }
  throw new TypeError("Unknown review action");
}
