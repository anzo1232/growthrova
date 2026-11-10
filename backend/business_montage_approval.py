"""Human review gate before Business montage rendering.

A completed scene scan only supplies candidates. A montage must additionally
cite the exact saved and owner-owned campaign revision with approved scenes.
"""
from __future__ import annotations
import math
from business_campaign_supabase import CampaignSupabase,CampaignForbidden,CampaignStorageUnavailable

class MontageApprovalError(ValueError):
    def __init__(self,code,message):
        super().__init__(message)
        self.code=code

def verify_approved_draft(deps,bearer,owner,org,brand_id,
                          draft_id,draft_revision,requested,*,repo_class=CampaignSupabase):
    if not isinstance(draft_id,str) or not isinstance(draft_revision,int) or isinstance(draft_revision,bool) or draft_revision<1:
        raise MontageApprovalError("draft_required","A saved approved campaign revision is required.")
    if not bearer:
        raise MontageApprovalError("auth_required","Sign in before exporting approved footage.")
    repo=repo_class(deps.supabase_url,deps.supabase_anon_key,bearer)
    record=repo.get(owner,draft_id)
    if not record or record.get("organisation_id")!=org:
        raise MontageApprovalError("not_found","Campaign not found.")
    if record.get("revision")!=draft_revision:
        raise MontageApprovalError("revision_conflict","Campaign changed. Refresh and approve the latest version.")
    if record.get("brand_id")!=brand_id:
        raise MontageApprovalError("brand_mismatch","Campaign Brand Kit differs from export Brand Kit.")
    original=record.get("scenes")
    if not isinstance(original,list) or not 2<=len(requested)<=6:
        raise MontageApprovalError("scenes_unapproved","Choose two to six approved scenes.")
    approved=set()
    for scene in original:
        if not isinstance(scene,dict) or scene.get("review_status")!="approved":
            continue
        try:
            start=float(scene["start_s"]);end=float(scene["end_s"])
        except (TypeError,ValueError,KeyError):
            continue
        if not math.isfinite(start) or not math.isfinite(end) or start<0 or end<=start:
            continue
        approved.add((scene.get("source_id"),round(start,2),round(end,2)))
    seen=set()
    for scene in requested:
        try:
            key=(scene["source_id"],round(float(scene["start_s"]),2),
                 round(float(scene["end_s"]),2))
        except (KeyError,TypeError,ValueError):
            raise MontageApprovalError("scenes_unapproved","Scene selection is invalid.") from None
        if key not in approved or key in seen:
            raise MontageApprovalError("scenes_unapproved","Every chosen scene must be reviewed and approved in the saved campaign.")
        seen.add(key)
    return {"id":record["id"],"revision":draft_revision}
