#!/usr/bin/env python3
"""Replay authored cross-niche preparation decisions. Never calls a model."""
from __future__ import annotations
import base64,hashlib,io,json,socket,sqlite3,sys
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from PIL import Image
import business_marketing_drafts as drafts
import business_scene_contracts as contracts
import business_scene_preparation as planner
# Test-only document scaffold; production code never imports this evaluator.
from tests.test_business_marketing_drafts import document
DATA=ROOT/'data/business_preparation_eval_cases.json'

def evaluate():
    data=DATA.read_bytes();corpus=json.loads(data);cases=[];attempts=0
    def no_network(*args,**kwargs):
        nonlocal attempts
        attempts+=1
        raise AssertionError('No network in authored preparation evaluation')
    image=io.BytesIO();Image.new('RGB',(720,1280),(100,105,110)).save(image,'PNG')
    uri='data:image/png;base64,'+base64.b64encode(image.getvalue()).decode()
    with patch.object(socket,'socket',side_effect=no_network),patch.object(socket,'create_connection',side_effect=no_network):
        for case in corpus['cases']:
            con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
            try:
                drafts.initialise(con);contracts.initialise(con)
                did='a'*32;doc=document();doc.update(business='Offline '+case['id'],sourceUrl='https://'+case['id'].replace('_','-')+'.example/',observedFacts=case['facts'])
                drafts.save_draft(con,{'id':did,'expectedRevision':0,'mutationId':'b'*32,'document':doc})
                contracts.register_reference(con,did,'fixture-image',uri,origin=case['origin'],rights_reference='offline-synthetic-fixture-rights',reviewer_reference='offline-fixture-no-actual-image-approval')
                before=con.total_changes
                proposal=planner.prepare(con,did,1,case['intent'],reference_pool=[{'id':'fixture-image','sourceFactIndices':[0],'providerImage':uri}])
                issues=[]
                if proposal['mode']!=case['expectedMode']:issues.append('unexpected_mode')
                if not set(case['requiredBlockers']).issubset(proposal['blockers']):issues.append('missing_expected_blocker')
                if con.total_changes!=before:issues.append('preparation_wrote_data')
                if proposal['canSpend'] or proposal['approvedForPublishing'] or proposal['visualQualityVerified']:issues.append('false_authority')
                cases.append({'id':case['id'],'mode':proposal['mode'],'blockers':proposal['blockers'],
                    'estimatedCredits':proposal['estimatedCredits'],'reviewIds':[x['id'] for x in proposal['reviewChecks']],
                    'sourceSha256':proposal['sourceSha256'],'passed':not issues,'issues':issues})
            finally:con.close()
    return {'schemaVersion':1,'recordedAt':datetime.now(timezone.utc).isoformat(),'fixtureProvenance':corpus['provenance'],
        'fixtureSha256':hashlib.sha256(data).hexdigest(),'caseCount':len(cases),'passed':sum(x['passed'] for x in cases),
        'failed':sum(not x['passed'] for x in cases),'networkAttempts':attempts,'generationCalls':0,
        'fineTuningPerformed':False,'commercialQualityProven':False,'actualMediaQualityAssessed':False,'cases':cases}

if __name__=='__main__':
    report=evaluate();print(json.dumps(report,indent=2));raise SystemExit(1 if report['failed'] or report['networkAttempts'] else 0)
