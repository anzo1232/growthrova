"""Conservative deterministic spend preflight, not a substitute for human visual QC."""
import re

POLICY_VERSION=4
HUMANS=r"(?:roofers?|tradespeople|tradesperson|workers?|persons?|people|humans?|hands?|faces?|gloves?|silhouettes?|chauffeurs?|men|man|women|woman|crew|technicians?|engineers?|installers?)"

def positive_mentions(text, pattern):
    """Conservative lexical prompt guard, including logical-negation scope.

    Suppress only clearly excluded mentions. Double negatives like
    'not without workers' and positive activities after a negative noun
    must remain detectable. This does not verify real visual content.
    """
    if not isinstance(text,str):
        return False
    modifiers=r"(?:(?:any|visible|synthetic|ai-generated|fake|fabricated|real|other)\s+){0,3}"
    item=modifiers+pattern+r"\b"
    negative=re.compile(
        r"\b(?:no|without|avoid|exclude|never\s+(?:show|depict)|"
        r"do\s+not\s+(?:show|depict|include))\s+"+item,re.I)
    continuation=re.compile(
        r"\s*(?:,|and\b|or\b)\s*(?:(?P<explicit>no|without)\s+)?"+item,re.I)
    next_noun=re.compile(
        r"^\s*(?:,|and\b|or\b)\s*(?:(?:no|without)\s+)?"+item,re.I)
    locative=re.compile(
        r"^\s*(?:$|[.,;!?]|(?:in|on|at|inside|outside|within|throughout|around|anywhere)\b)",re.I)
    direct_meta=re.compile(
        r"\b(?:not|never|no|do\s+not|don.t|should\s+not|must\s+not|"
        r"cannot|can.t|is\s+not|was\s+not)\s*$",re.I)
    indirect_meta=re.compile(
        r"\b(?:do\s+not|don.t|never|not)\s+(?:want|need|accept|approve|"
        r"request|prefer|like)\b[^.!?;]{0,80}$",re.I)
    masked=list(text)
    for match in negative.finditer(text):
        prior=re.split(r"[.!?;]",text[max(0,match.start()-100):match.start()])[-1]
        if direct_meta.search(prior) or indirect_meta.search(prior):
            continue
        end=match.end()
        while True:
            part=continuation.match(text,end)
            if not part:
                break
            following=text[part.end():]
            if not (part.group("explicit") or locative.match(following)
                    or next_noun.match(following)):
                break
            end=part.end()
        for index in range(match.start(),end):
            masked[index]=" "
    return bool(re.search(r"\b"+pattern+r"\b","".join(masked),re.I))

class CreativePreflightError(ValueError):
    def __init__(self,issues):
        self.issues=tuple(issues)
        super().__init__('Paid creative blocked: '+', '.join(issues))

def inspect(sector,prompt,*,evidence='',shot_purpose='',estimated_credits=0,cap=0):
    text=' '.join(str(prompt or '').lower().split())
    proof=' '.join(str(evidence or '').lower().split())
    issues=[]
    if len(text)<100: issues.append('insufficient_scene_direction')
    if not shot_purpose or len(str(shot_purpose).strip())<12: issues.append('missing_shot_purpose')
    if len(proof)<20: issues.append('missing_business_evidence')
    if type(estimated_credits) is not int or estimated_credits<=0 or type(cap) is not int or cap<estimated_credits:
        issues.append('spend_cap_not_approved')
    if sector=='roofing':
        # The preflight is intentionally stricter than possible postprocessing.
        # AI-generated human labour undermines trust; real customer footage is separate.
        if positive_mentions(re.sub(r'\bhuman[- ]scale\b','natural scale',text),HUMANS):
            issues.append('synthetic_worker_or_hands')
        if 'interior' in text or 'ceiling' in text or 'living room' in text:
            if not ('normal' in text and ('ceiling height' in text or '2.4m' in text) and 'camera' in text):
                issues.append('interior_geometry_uncontrolled')
        if positive_mentions(text,r'before(?:[- ]and[- ]|[- ])after'):
            issues.append('fabricated_job_proof_risk')
        if not any(x in text for x in ('gutter','flashing','tile','slate','leak','roof')):
            issues.append('no_roofing_subject')
    return {'ready':not issues,'issues':issues,'estimatedCredits':estimated_credits,'maximumCredits':cap,'requiresHumanVisualReview':True,'policyVersion':POLICY_VERSION,'automaticVisualApproval':False}

def require(**kwargs):
    result=inspect(**kwargs)
    if not result['ready']: raise CreativePreflightError(result['issues'])
    return result
