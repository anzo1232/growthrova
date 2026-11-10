"""Evidence-first creative planning across industries, without a fixed niche list.

Planning and risk analysis only: never authorises credits, media claims or publishing.
Unknown niches remain supported through observed offers and business model.
"""
from __future__ import annotations
import hashlib,json,re
import business_creative_learning as learning

# These are operational traits, not an exhaustive list of industries.
TRAITS={
 'local_service':('repair','roof','plumb','electrician','builder','cleaner','landscap','pest','locksmith','hvac','carpet','gutter','garage','mechanic'),
 'bookable_service':('salon','barber','spa','clinic','dentist','massage','beauty','therapy','photograph','personal train','fitness'),
 'hospitality':('restaurant','cafe','café','bar','hotel','catering','takeaway','menu','chef','dining','food truck'),
 'retail_product':('shop','store','ecommerce','e-commerce','clothing','jewellery','apparel','skincare','product','delivery','shipping'),
 'professional_service':('accountant','solicitor','lawyer','mortgage','agency','consultant','architect','insurance','advisory','estate agent'),
 'training':('course','academy','training','workshop','qualification','certificate','coaching','tuition'),
 'software':('software','saas','platform','app','subscription','api','dashboard','automation'),
 'property':('property','estate','letting','commercial property','renovation','real estate'),
 'events':('event','entertainment','wedding','dj','festival','venue','ticket'),
}
NEEDS={
 'local_service':('problem','diagnosis','evidence_of_work','enquiry'),
 'bookable_service':('customer_need','service_process','verified_result','booking'),
 'hospitality':('specific_product','sensory_craft','authentic_experience','booking_or_order'),
 'retail_product':('product_problem','real_product_demo','feature_proof','purchase'),
 'professional_service':('client_problem','clear_process','verifiable_trust','consultation'),
 'training':('career_goal','course_contents','verifiable_eligibility','enrolment'),
 'software':('workflow_pain','screen_recording','actual_result','trial_or_signup'),
 'property':('buyer_need','verified_property','real_details','viewing'),
 'events':('occasion','actual_experience','verified_details','ticket_or_enquiry'),
 'other':('customer_problem','grounded_offer','credible_proof','next_step'),
}
HIGH_TRUST=('clinic','medical','patient','dentist','financial','mortgage','law','solicitor','insurance','therapy','qualification')
PHYSICAL=('roof','building','plumb','electric','property','repair','mechanic','construction','renovation','product')

def _normal(x,limit=2000):
 return ' '.join(str(x or '').lower().split())[:limit]

STEMS={
 'roof':r'roof(?:s|ing|er(?:s)?)?', 'plumb':r'plumb(?:ing|er(?:s)?)?',
 'landscap':r'landscap(?:e|es|ing|er(?:s)?)', 'electric':r'electric(?:al|ian(?:s)?)?',
 'photograph':r'photograph(?:y|er(?:s)?|s)?', 'personal train':r'personal train(?:ing|er(?:s)?)',
 'property':r'propert(?:y|ies)', 'repair':r'repair(?:s|ing)?',
}

def _matches(text,term):
 pattern=STEMS.get(term,re.escape(term)+r'(?:s|es)?')
 return bool(re.search(r'(?<!\w)'+pattern+r'(?!\w)',text))

def profile(business,observations,*,goal='enquiries',owner_media=None):
 """Returns editable research directions; observations are unverified website claims."""
 if not isinstance(observations,(tuple,list)) or not observations:raise ValueError('Business website evidence required')
 facts=[str(x).strip()[:500] for x in observations if isinstance(x,str) and len(x.strip())>=12][:30]
 if not facts:raise ValueError('Specific business evidence required')
 context=_normal(' '.join(facts),10000)
 matched={trait:[term for term in terms if _matches(context,term)] for trait,terms in TRAITS.items()}
 # Workshop as a place of repair is not evidence of a training business.
 if 'workshop' in matched['training'] and not any(_matches(context,t) for t in ('course','training','class','learn','tuition','academy')):
  matched['training'].remove('workshop')
 scores={trait:len(terms) for trait,terms in matched.items()}
 rank=sorted(scores,key=lambda x:(-scores[x],list(TRAITS).index(x)))
 primary=rank[0] if scores[rank[0]]>0 else 'other'
 secondary=[x for x in rank[1:] if scores[x]>0][:3]
 risk=[]
 if any(_matches(context,x) for x in HIGH_TRUST):risk+=['regulated_or_high_trust_claims','no_fabricated_clients_or_results']
 if any(_matches(context,x) for x in PHYSICAL):risk+=['physical_accuracy','no_synthetic_work_as_proof']
 if primary in ('hospitality','retail_product'):risk+=['product_identity','no_invented_offers_or_menu']
 if primary in ('property','events'):risk+=['location_or_event_identity','no_fictitious_availability']
 risk+=['reference_rights','synthetic_media_disclosure','human_visual_review']
 supplied=bool(owner_media)
 return {'business':str(business).strip()[:120], 'primaryTrait':primary,'secondaryTraits':secondary,
  'researchRequired':primary=='other' or sum(v==scores.get(primary,0) and v>0 for v in scores.values())>1,
  'matchedSignals':matched,'traitScores':scores,
  'confidence':'unknown_needs_research' if primary=='other' else 'inferred_needs_business_verification','customerJourney':list(NEEDS[primary]),
  'risks':list(dict.fromkeys(risk)), 'ownerMediaAvailable':supplied,
  'proofSource':'owner_supplied_media_requires_verification' if supplied else 'requires_authorised_business_media',
  'mediaRightsVerified':False,
  'groundedFacts':facts,'conversionGoal':goal if goal in ('enquiries','bookings','purchases','signups','awareness') else 'enquiries',
  'noAutomaticPaidGeneration':True,'noAutomaticPublishing':True}

def blueprint(profile,*,budget_credits=0):
 if not isinstance(profile,dict) or not profile.get('groundedFacts'):raise ValueError('Grounded niche profile required')
 if type(budget_credits) is not int or budget_credits<0:raise ValueError('Invalid budget')
 journey=profile['customerJourney'];shots=[]
 policy=learning.rubric(profile,' '.join(profile['groundedFacts']))
 for i,step in enumerate(journey):
  is_proof=step in ('evidence_of_work','verified_result','feature_proof','verifiable_trust','verifiable_eligibility','actual_result','verified_property','actual_experience','credible_proof')
  needs_real=is_proof or step in ('real_product_demo','specific_product','grounded_offer')
  shots.append({'order':i+1,'narrativeRole':step,'purpose':f'Advance customer from {journey[i-1] if i else "attention"} to {step}',
   'mediaPolicy':'owner_authorised_only' if needs_real else 'illustrative_allowed_after_review',
   'generationStatus':'not_authorised','sourceFact':profile['groundedFacts'][min(i,len(profile['groundedFacts'])-1)],
   'continuityGroup':'same_property_product_or_person' if i in (1,2) else None})
 return {'business':profile['business'],'trait':profile['primaryTrait'],'shots':shots,
  'creativeRisks':profile['risks'],'learningPolicy':policy,'creditLimit':budget_credits,'creditsReserved':0,
  'requiredPreflight':['accuracy','customer_value','reality','claim_support','continuity','rights','cost'],
  'requiresOwnerVerification':True,'requiresArtReview':True,'readyForProduction':False,
  'canPublish':False,'canSpend':False,
  'fingerprint':hashlib.sha256(json.dumps([profile['business'],profile['groundedFacts'],shots,budget_credits,policy['policyFingerprint']],sort_keys=True).encode()).hexdigest()}
