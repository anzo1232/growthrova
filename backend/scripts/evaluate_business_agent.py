#!/usr/bin/env python3
"""Reproducible offline decision regression, not a claim of model/creative quality."""
from __future__ import annotations
import argparse,datetime,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import business_niche_strategy as strategy

NETWORK=[]
def deny_network(event,args):
    if event in ('socket.connect','socket.getaddrinfo'):
        NETWORK.append(event)
        raise RuntimeError('This evaluation forbids network and paid provider calls')

def evaluate(path):
    data=path.read_bytes()
    if len(data)>500_000:raise ValueError('Fixture data too large')
    corpus=json.loads(data);cases=corpus['cases']
    if corpus.get('schemaVersion')!=1 or not isinstance(cases,list) or not 1<=len(cases)<=500:
        raise ValueError('Invalid evaluation fixtures')
    results=[];seen=set();authorisations=0
    for case in cases:
        if not isinstance(case,dict) or not isinstance(case.get('id'),str) or case['id'] in seen:
            raise ValueError('Invalid or duplicate evaluation case')
        seen.add(case['id'])
        expected=case.get('expectedTraits')
        if not isinstance(expected,list) or not expected or any(x not in strategy.NEEDS for x in expected):
            raise ValueError('Invalid expected trait')
        p=strategy.profile(case['business'],case['observations'])
        b=strategy.blueprint(p,budget_credits=192)
        authorisations+=int(b['canSpend'] is True)
        lessons={x['id'] for x in b['learningPolicy']['checks']}
        issues=[]
        if p['primaryTrait'] not in expected:issues.append('incorrect_primary_trait')
        if case.get('researchRequired') is True and not p['researchRequired']:issues.append('unknown_not_escalated')
        if b['canSpend'] or b['canPublish'] or b['readyForProduction']:issues.append('planning_granted_authority')
        if not {'source_truth','continuity','marketing_purpose','finished_asset'} <= lessons:issues.append('missing_universal_review')
        if not any(s['mediaPolicy']=='owner_authorised_only' for s in b['shots']):issues.append('no_proof_source_requirement')
        results.append({'id':case['id'],'trait':p['primaryTrait'],'expectedTraits':expected,
            'researchRequired':p['researchRequired'],'lessonIds':sorted(lessons),'passed':not issues,'issues':issues})
    failed=sum(not x['passed'] for x in results)
    source_paths=['business_niche_strategy.py','business_creative_learning.py','business_creative_preflight.py',
                  'data/business_creative_lessons.json','scripts/evaluate_business_agent.py']
    return {'schemaVersion':1,'recordedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope':'offline_decision_regression_not_media_quality','fixtureProvenance':corpus.get('provenance'),
        'fixtureSha256':hashlib.sha256(data).hexdigest(),'caseCount':len(results),'passed':len(results)-failed,
        'failed':failed,'networkAttempts':len(NETWORK),'generationAuthorisations':authorisations,
        'fineTuningPerformed':False,'actualMediaReviewed':False,'commercialQualityProven':False,
        'sourceSha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in source_paths},'cases':results}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cases',type=Path,default=ROOT/'data/business_niche_eval_cases.json');parser.add_argument('--output',type=Path)
    args=parser.parse_args();sys.addaudithook(deny_network)
    try:
        report=evaluate(args.cases)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        print(json.dumps({'error':type(exc).__name__,'message':str(exc),'scope':'offline_decision_regression_not_media_quality'}));return 2
    rendered=json.dumps(report,indent=2)+'\n'
    if args.output:args.output.write_text(rendered)
    print(rendered,end='')
    return int(report['failed']>0 or report['networkAttempts']>0 or report['generationAuthorisations']>0)
if __name__=='__main__':raise SystemExit(main())
