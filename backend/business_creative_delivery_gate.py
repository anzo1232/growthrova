"""Creative-delivery hard gate. Media conversion success is NOT advertising approval.

Check declared image/video provenance, identity, composition and typography before
a paid campaign can be offered. This cannot assess beauty or truthfulness of pixels:
those always require a creative director and permissioned business asset review.
"""
from collections import Counter
from pathlib import Path
import hashlib, re

ALLOWED_LOGO_SOURCES={'approved_vector','approved_transparent_raster','none'}
UNSUITABLE_VISUAL_TAGS={'steakhouse','generic_restaurant','unrelated_brand','other_business_logo',
                         'unknown_subject','unlicensed', 'fake_before_after'}
REQUIRED_PHASES={'opening','experience','close'}
def _bounds(box):
 return isinstance(box,(list,tuple)) and len(box)==4 and all(type(n) in (int,float) for n in box)
def preflight(spec):
 if not isinstance(spec,dict):raise ValueError('Invalid creative review manifest')
 errors=[]
 width,height=spec.get('width'),spec.get('height')
 if type(width)!=int or type(height)!=int or width<500 or height<850 or width>=height:
  errors.append('invalid_vertical_canvas')
 idn=spec.get('identity') or {}
 if not idn.get('name') or not idn.get('expectedCity'):
  errors.append('unverified_business_identity')
 if idn.get('sourceBusinessMismatch'):
  errors.append('wrong_business_website')
 visual=spec.get('brand') or {}
 if visual.get('logoSource') not in ALLOWED_LOGO_SOURCES:
  errors.append('cropped_shop_sign_or_unapproved_logo')
 if not visual.get('brandingReviewedByOwner',False):
  errors.append('owner_brand_approval_missing')
 texts=spec.get('texts') or []
 if not texts:errors.append('missing_storytelling_copy')
 # 9:16 in 720x1280, accommodate Reels chrome (top 165, bottom ~230).
 # Headlines use y >= 225 and bottom <= 985, avoid bottom platform UI.
 safe={'left':round(width*.075),'right':round(width*.925),
       'top':round(height*.175),'bottom':round(height*.765)} if width and height else None
 for index,t in enumerate(texts):
  b=t.get('bbox')
  if not safe or not _bounds(b):
   errors.append('text_geometry_unmeasured:'+str(index));continue
  l,top,r,bottom=b
  if l<safe['left'] or r>safe['right'] or top<safe['top'] or bottom>safe['bottom'] or r<=l or bottom<=top:
   errors.append('mobile_text_overflow:'+str(index))
  if not t.get('contrastChecked',False):
   errors.append('text_contrast_unreviewed:'+str(index))
 shots=spec.get('shots') or []
 if len(shots)<5:errors.append('too_few_visual_beats')
 categories={s.get('phase') for s in shots}
 if not REQUIRED_PHASES.issubset(categories):
  errors.append('story_arc_incomplete')
 references=[s.get('sourceId') for s in shots if s.get('kind')=='video']
 if len(set(references))<4:errors.append('insufficient_shot_variety')
 if references and max(Counter(references).values())>2:errors.append('excessive_reused_stock_shot')
 if any(s.get('subjectTag') in UNSUITABLE_VISUAL_TAGS for s in shots):
  errors.append('off_brand_visual_source')
 if any(not s.get('licenseConfirmed') for s in shots):
  errors.append('source_usage_rights_unconfirmed')
 # "Stock" has a valid use but must never be represented as actual venue footage.
 if any(s.get('kind')=='video' and s.get('stock') and not s.get('illustrativeDisclosure') for s in shots):
  errors.append('stock_masquerading_as_business_footage')
 if any(s.get('artDirection')=='static_ken_burns' and s.get('phase')!='close' for s in shots):
  errors.append('unmotivated_still_slideshow')
 claims=spec.get('claims') or []
 for c in claims:
  if c.get('statedAsFact') and not c.get('verifiedOwner'):
   errors.append('unsupported_advertising_claim')
 video=spec.get('finalVideo') or {}
 if not video.get('actualVideoDecoded') or not video.get('technicalMotionPass'):
  errors.append('media_not_technically_verified')
 # Even a technically perfect video is never auto-approved by these checks.
 return {'technicalAndProvenancePass':len(errors)==0,'blockers':list(dict.fromkeys(errors)),
   'publishReady':False,'paidAdReady':False,'ownerApprovalRequired':True,
   'humanArtDirectorReviewRequired':True,
   'explanation':'Passing preflight only means known mechanical blockers were absent. It does not establish agency-quality creative or authentic business imagery.'}


def pack_delivery_status(doc, *, asset_origin, video_origin):
    '''All URL-generated kits are review packs unless provenance, ownership and
    creative approval are explicitly attested in a separate verified workflow.
    This is conservative: it never sets publishReady from scraped branding.
    '''
    if not isinstance(doc,dict):
        raise ValueError('Invalid saved campaign')
    reasons=['brand_identity_and_logo_not_owner_approved',
             'human_creative_director_review_missing',
             'business_claims_and_cta_require_verification']
    if 'owner_declared' not in str(asset_origin):
        reasons.append('authentic_business_media_not_provided')
    else:
        reasons.append('declared_website_media_rights_not_independently_confirmed')
    if video_origin not in ('runway_generated_scene_with_local_cta',):
        reasons.append('no_approved_genuine_short_form_video')
    else:
        reasons.append('generated_video_requires_subject_and_motion_review')
    return {
      'publishReady':False,'paidAdReady':False,'autoPublishBlocked':True,
      'source':'URL intake and saved campaign draft, not verified brand kit',
      'blockingReasons':reasons,'ownerBrandAssetsNeeded':True,
      'humanCreativeDirectorReviewRequired':True,
      'automaticPaidRetriesAllowed':False
    }
