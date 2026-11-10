/** Evidence-based launch readiness, never a substitute for real approval records. */
export function milestoneAReadiness({campaign, research, owner, assets, authenticated = false}={}) {
 const gaps=[];
 const posts=campaign?.calendarEntries;
 if(!authenticated)gaps.push('authenticated_owner_session_required');
 if(!campaign?.documentSha256 || !Number.isInteger(campaign.revision) || campaign.revision<1)
  gaps.push('saved_campaign_revision_required');
 if(!Array.isArray(posts) || posts.length!==30 ||
  new Set(posts.map(x=>x.day)).size!==30 ||
  posts.some(x=>!Number.isInteger(x.day)||x.day<1||x.day>30))
  gaps.push('complete_thirty_day_calendar_required');
 if(!research || research.state!=='captured_for_review' ||
    research.draftId!==campaign?.draftId || research.revision!==campaign?.revision)
  gaps.push('current_research_receipt_required');
 // A research receipt records excerpts, not independent verification.
 if(research?.claimsVerified!==true)
  gaps.push('independent_research_confirmation_required');
 if(!owner || owner.status!=='owner_brief_confirmed' ||
    owner.draftId!==campaign?.draftId || owner.revision!==campaign?.revision)
  gaps.push('current_owner_confirmation_required');
 if(!assets || assets.draftId!==campaign?.draftId ||
    assets.revision!==campaign?.revision ||
    assets.documentSha256!==campaign?.documentSha256)
  gaps.push('current_scoped_asset_inventory_required');
 // Uploaded material is only a candidate until an owner confirms actual usage rights.
 if(!assets || !Array.isArray(assets.assetCandidates) ||
    !assets.assetCandidates.some(x=>x.verifiedRights===true && x.authenticityVerified===true))
  gaps.push('verified_customer_asset_rights_required');
 return {milestone:'A', status:gaps.length?'blocked':'ready_for_supervised_review',
   gaps, canSpend:false, canPublish:false, productionApproved:false};
}
