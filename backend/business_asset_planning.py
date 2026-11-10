"""Read-only owner media shortlist for creative planning; no approval or generation."""
import business_asset_catalog as catalog

class PlanningError(ValueError):pass

def shortlist(con,organisation_id,business_id,*,kind=None):
    """Expose only scoped assets and explicit pending-review status.

    This does not register scene references; each source needs authenticated
    ownership, current byte inspection and independent scene relevance review.
    """
    if kind is not None and kind not in catalog.MIMES:
        raise PlanningError('Unknown media type')
    assets=catalog.list_assets(con,organisation_id,business_id)
    result=[]
    for asset in assets:
        if kind is not None and asset['mediaKind']!=kind:
            continue
        result.append({'assetId':asset['assetId'],
                       'mediaKind':asset['mediaKind'],
                       'sourceSha256':asset['sourceSha256'],
                       'originalName':asset['originalName'],
                       'rightsStatus':asset['consentStatus'],
                       'planningStatus':('held_permission_withdrawn' if asset.get('permissionWithdrawn') else
                                         'pending_rights_review' if asset['consentStatus']=='not_confirmed' else 'candidate_pending_scene_review'),
                       'referenceRegistered':False,
                       'sourceAvailableForGeneration':False,
                       'mayClaimRealBusinessProof':False,
                       'canSpend':False,'canPublish':False})
    return {'organisationId':organisation_id,'businessId':business_id,
            'assets':result,'readOnly':True,'requiresOwnerReview':True,
            'automaticGenerationEnabled':False,'publishingEnabled':False}
