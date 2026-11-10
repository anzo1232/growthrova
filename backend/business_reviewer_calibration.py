"""Conservative offline reviewer calibration against separately sourced labels.

The supplied held-out labels must come from independent existing reviews.
They are not verified ground truth merely because this tool accepts them.
"""
from __future__ import annotations
import re
import hashlib
import json

class CalibrationError(ValueError): pass

SCHEMA={'id','sourceSha256','groundTruth','reviewDecision','labelOrigin','reviewOrigin','evidenceReference'}
LABELS={'approve','reject','unknown'}
DECISIONS={'approve','reject','abstain'}
ORIGINS={'independent_preexisting_review','separate_review_session','customer_recorded_rejection','expert_manual_review'}
IDENT=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{1,79}\Z')
HASH=re.compile(r'[0-9a-f]{64}\Z')

def evaluate(cases):
    """Evaluate *declared* held-out evidence, never authorize creative."""
    if not isinstance(cases,list) or not 1<=len(cases)<=100:
        raise CalibrationError('Bounded held-out evidence list required')
    ids=set(); media=set()
    stats={'falseApprovals':0,'falseRejections':0,'correctDecisions':0,
           'abstentions':0,'uncertainCases':0,'scoredCases':0}
    for item in cases:
        if not isinstance(item,dict) or set(item)!=SCHEMA:
            raise CalibrationError('Complete calibration provenance required')
        ident=item['id'];digest=item['sourceSha256']
        if not isinstance(ident,str) or not IDENT.fullmatch(ident) or ident in ids:
            raise CalibrationError('Invalid or repeated case identifier')
        if not isinstance(digest,str) or not HASH.fullmatch(digest) or digest in media:
            raise CalibrationError('Invalid or repeated underlying media')
        if item['groundTruth'] not in LABELS or item['reviewDecision'] not in DECISIONS:
            raise CalibrationError('Invalid labels')
        for key in ('labelOrigin','reviewOrigin'):
            if item[key] not in ORIGINS:
                raise CalibrationError('Unverified reviewer origin')
        if item['labelOrigin']==item['reviewOrigin']:
            raise CalibrationError('Review and reference label cannot be the same source')
        evidence=item['evidenceReference']
        if not isinstance(evidence,str) or not IDENT.fullmatch(evidence):
            raise CalibrationError('Missing evidence reference')
        ids.add(ident); media.add(digest)
        truth=item['groundTruth']; decision=item['reviewDecision']
        if truth=='unknown':
            stats['uncertainCases']+=1
            continue
        if decision=='abstain':
            stats['abstentions']+=1
            continue
        stats['scoredCases']+=1
        if truth==decision:stats['correctDecisions']+=1
        elif truth=='reject':stats['falseApprovals']+=1
        else:stats['falseRejections']+=1
    denominator=stats['scoredCases']
    result={'version':1,'totalCases':len(cases),**stats,
            'accuracy':stats['correctDecisions']/denominator if denominator else None,
            'calibrationStatus':'declared_labels_not_independently_audited',
            'labelAndDecisionSourcesMustBeIndependent':True,
            'creativeApproved':False,'canPublish':False,'canSpend':False,
            'providerCalls':0,'networkRequests':0,'fineTuningPerformed':False}
    result['inputFingerprint']=hashlib.sha256(json.dumps(cases,sort_keys=True).encode()).hexdigest()
    return result
