"""Deterministic, conservative social creative-director screening.

This is a minimum evidence/format gate, NOT a machine's artistic endorsement.
Human review is mandatory and no rejection initiates paid regeneration.
"""
import re

SOCIAL={'Instagram','Facebook','TikTok'}
VIDEO_WORDS=('reel','video','tiktok')
GENERIC={
 'what the brand represents','our positioning in plain english','the decision before the decision',
 'a useful place to begin','what matters most','questions worth asking',
 'a detail that changes the experience','what the service covers','choosing with confidence',
 'common misconceptions','what good service looks like','where to start today',
 'your invitation to enquire','make a plan','planning somewhere to eat',
 'what is on the menu','find your kind of table','know before you go',
 'what happens next','what you need to know','a closer look','get in touch'
}
GENERIC_PATTERNS=(
 r'^our positioning\\b',r'^what matters\\b',r'^why choose us\\??$',
 r'^discover (more|what makes us different)\\b',r'^what to expect\\??$',
 r'^the best of (both|everything)\\b'
)

def screen(post, *, photo_available=False, authentic_photo=False, illustrative_photo=False):
 issues=[]
 channel=str(post.get('channel','')).strip()
 fmt=str(post.get('format','')).lower()
 hook=str(post.get('theme','')).strip()
 text=str(post.get('copyDraft','')).strip()
 cta=str(post.get('callToAction','')).strip()
 if channel not in SOCIAL:issues.append('not_a_target_social_channel')
 if any(word in fmt for word in VIDEO_WORDS):issues.append('real_video_required_not_a_static_graphic')
 if len(hook)<12 or hook.lower().rstrip('?.!') in {v.rstrip('?.!') for v in GENERIC} or any(re.search(p,hook.lower()) for p in GENERIC_PATTERNS):
  issues.append('weak_or_generic_hook')
 if len(text)<35 or len({w.lower() for w in re.findall(r"[a-zA-Z']+",text)})<9:issues.append('insufficient_customer_value')
 if len(cta)<4 or cta.lower() in ('click here','learn more'):issues.append('unclear_next_step')
 if not photo_available:issues.append('no_service_relevant_photo_or_approved_visual')
 elif not (authentic_photo or illustrative_photo):issues.append('photo_provenance_unconfirmed')
 # A bitmap is not a photograph of this business; visual fidelity is unproven.
 return {'day':post.get('day'),'channel':channel,'format':post.get('format'),
         'status':'rejected_by_preflight' if issues else 'awaiting_human_creative_review',
         'issues':issues,'publishApproved':False,'autoRetry':False,
         'humanVisualReviewRequired':True}

def campaign_report(posts, *, authentic_photo_count=0, illustrative_photo_count=0):
 available=authentic_photo_count+illustrative_photo_count>0
 rows=[screen(p,photo_available=available,authentic_photo=authentic_photo_count>0,
    illustrative_photo=illustrative_photo_count>0) for p in posts]
 return {'standard':'minimum_evidence_and_format_screen_not_artistic_scoring',
  'targetChannels':['Instagram','Facebook','TikTok'],
  'reviewed':len(rows),'rejected':sum(x['status']=='rejected_by_preflight' for x in rows),
  'humanReviewRequired':True,'noAutoRetry':True,'publishApproved':False,
  'posts':rows}
