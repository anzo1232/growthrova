"""Synthetic HTTP transport + real SQLite/media. No external auth requests."""
import copy
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import requests
from requests import Response as HttpResponse
from business_growthrova_preview import create_growthrova_preview
from business_website_analysis import extract_website, WebsiteSafetyError
from tests.test_business_marketing_drafts import document
from business_marketing_offline import OfflineDocumentAccessError

USER='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
OTHER='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
ORG='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
PROJECT='https://synthetic-growthrova.supabase.co'


class Response:
    def __init__(self, data, status=200): self.data=data; self.status_code=status
    def json(self): return self.data


class Transport:
    def __init__(self): self.owner=USER; self.allowed=True; self.status=200; self.calls=[]
    def get(self,url,**options):
        self.calls.append((url, options))
        if self.status==503: raise requests.ConnectionError('synthetic outage')
        token=options['headers']['Authorization']
        if token!='Bearer synthetic-valid': return Response({},401)
        if url.endswith('/auth/v1/user'): return Response({'id':self.owner}, self.status)
        return Response([{'id':ORG,'owner_id':self.owner,'name':'Synthetic business',
                          'website':'https://example.org/','primary_goal':'enquiries'}] if self.allowed else [])


class GrowthrovaPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=str(Path(self.tmp.name)/'preview.db'); self.transport=Transport()
        self.app=self.create(); self.client=self.app.test_client()
        self.root=f'/api/growthrova/organisations/{ORG}/marketing-documents'
        self.headers={'Authorization':'Bearer synthetic-valid'}
        self.payload={'id':'1'*32,'mutationId':'2'*32,'expectedRevision':0,'document':document()}
    def create(self,**changes):
        return create_growthrova_preview(**dict(database_path=self.path, project_url=PROJECT,
            auth_url=PROJECT,anon_key='sb_publishable_synthetic',http=self.transport,**changes))
    def save(self,payload=None):return self.client.post(self.root,json=payload or self.payload,headers=self.headers)

    def test_website_preview_precedes_business_creation_and_rechecks_identity(self):
        endpoint='/api/growthrova/website-preview'
        self.assertEqual(self.client.post(endpoint,json={'website':'https://example.org/'}).status_code,401)
        # Authenticated users need no placeholder organisation for this read.
        self.transport.allowed=False
        html=b'<title>Orchard Workshop</title><meta name="description" content="Bicycle servicing and repairs at Orchard Workshop."><h1>Bicycle servicing</h1><p>Ask our workshop about brake servicing and bicycle repairs before booking.</p>'
        report=extract_website('https://example.org/',fetch=lambda *a:html,
            resolve=lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
        with patch('business_growthrova_preview.extract_website',return_value=report) as reader:
            result=self.client.post(endpoint,json={'website':'https://example.org/'},headers=self.headers)
            self.assertEqual(result.status_code,200,result.json)
            reader.assert_called_once_with('https://example.org/')
            self.assertEqual(self.client.post(endpoint,json={'website':'https://example.org/','ownerId':OTHER},headers=self.headers).status_code,400)
            self.assertEqual(reader.call_count,1)
        self.assertEqual(result.headers['Cache-Control'],'no-store')
        self.assertFalse(any('/rest/' in url for url,_ in self.transport.calls))
        # Exercise actual pipeline/document conversion: evidence is retained but
        # nothing is confirmed or saved merely by reading the website.
        script="""import fs from 'node:fs';import assert from 'node:assert/strict';
          import {prepareUrlCampaign} from './src/lib/businessUrlCampaignPipeline.mjs';
          import {createMarketingDocument} from './src/lib/businessMarketingDocument.mjs';
          const c=prepareUrlCampaign(JSON.parse(fs.readFileSync(0,'utf8')),{objective:'bookings'});
          const d=createMarketingDocument({...c,business:'Reviewed Orchard name'});
          assert.equal(d.business,'Reviewed Orchard name');assert.equal(d.goal,'bookings');
          assert.equal(d.sourceUrl,'https://example.org/');assert.ok(d.observedFacts.length);
          assert.equal(d.ownerStrategy.confirmedContext,null);assert.equal(d.canSpend,false);
          assert.equal(d.canPublish,false);"""
        subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(result.json),
                       text=True,capture_output=True,timeout=15,check=True)
        def changed_identity(_):
            self.transport.owner=OTHER
            return report
        with patch('business_growthrova_preview.extract_website',side_effect=changed_identity):
            self.assertEqual(self.client.post(endpoint,json={'website':'https://example.org/'},headers=self.headers).status_code,401)
        self.transport.owner=USER
        self.assertEqual(self.client.post(endpoint,json={'website':'https://127.0.0.1/'},headers=self.headers).status_code,400)

    def test_onboarding_research_durable_recovery_and_scope_fencing(self):
        import business_growthrova_research as snapshots
        endpoint = '/api/growthrova/website-preview'
        saved_endpoint = f'/api/growthrova/organisations/{ORG}/research'
        report = {'source_url': 'https://example.org/', 'status': 'extracted_unconfirmed',
                  'evidence': {'status': 'sufficient_unconfirmed'},
                  'observations': {'headings': ['Exact original evidence']}}
        def submit(value=report):
            with patch('business_growthrova_preview.extract_website',
                       side_effect=value if isinstance(value, Exception) else None,
                       return_value=value), patch('business_growthrova_preview.expand_business_audit',
                                                  side_effect=lambda value, **kw: value):
                return self.client.post(endpoint, json={'website': 'https://example.org/'}, headers=self.headers)
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        self.assertEqual(self.client.get(endpoint, headers=self.headers).status_code, 404)
        # No accessible organisation is needed, and no business is created.
        self.transport.allowed = False
        self.assertEqual(submit().json, report)
        client = self.create().test_client()
        with patch('business_growthrova_preview.extract_website') as reader:
            saved = client.get(endpoint, headers=self.headers)
            reader.assert_not_called()
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json['report'], report)
        self.assertEqual(saved.json['status'], 'unconfirmed')
        self.assertEqual(saved.json['website'], 'https://example.org/')
        self.assertEqual(saved.headers['Cache-Control'], 'no-store')
        self.assertFalse(any('/rest/' in url for url, _ in self.transport.calls))
        for failure in (WebsiteSafetyError('Synthetic failure'),
                        {**report, 'evidence': {'status': 'insufficient'}}):
            self.assertEqual(submit(failure).status_code, 400)
            self.assertEqual(client.get(endpoint, headers=self.headers).json, saved.json)
        self.transport.owner = OTHER
        self.assertEqual(client.get(endpoint, headers=self.headers).status_code, 404)
        self.transport.owner = USER
        self.transport.allowed = True
        self.assertEqual(client.get(saved_endpoint, headers=self.headers).status_code, 404)
        self.assertEqual(client.get(self.root, headers=self.headers).json['documents'], [])
        # Re-entrant real requests complete in the opposite order. The later
        # successful request must remain the recoverable result after restart.
        newer = {**report, 'observations': {'headings': ['Later request evidence']}}
        def overlap(_):
            self.assertEqual(submit(newer).status_code, 200)
            return report
        with patch('business_growthrova_preview.extract_website', side_effect=overlap), \
                patch('business_growthrova_preview.expand_business_audit', side_effect=lambda value, **kw: value):
            superseded = self.client.post(endpoint, json={'website': 'https://example.org/'},
                                          headers=self.headers)
            self.assertEqual(superseded.status_code, 409)
            self.assertEqual(superseded.json['code'], 'research_superseded')
        saved = self.create().test_client().get(endpoint, headers=self.headers)
        self.assertEqual(saved.json['report'], newer)
        original_retain = snapshots.retain
        def change_owner_after_write(*args):
            original_retain(*args)
            self.transport.owner = OTHER
        with patch.object(snapshots, 'retain', side_effect=change_owner_after_write):
            result = submit()
        self.assertEqual(result.status_code, 401)
        self.assertNotIn('report', result.json)
        self.transport.owner = USER
        self.assertEqual(client.get(endpoint, headers=self.headers).json, saved.json)
        original_latest = snapshots.latest
        def expire_after_read(*args):
            result = original_latest(*args)
            self.transport.status = 503
            return result
        with patch.object(snapshots, 'latest', side_effect=expire_after_read):
            denied = client.get(endpoint, headers=self.headers)
        self.assertEqual(denied.status_code, 503)
        self.assertNotIn('report', denied.json)
        self.transport.status = 200
        self.assertEqual(client.get(endpoint, headers=self.headers).json, saved.json)

    def test_website_preview_rechecks_session_for_extraction_and_enrichment_outcomes(self):
        endpoint = '/api/growthrova/website-preview'
        # Onboarding needs no business yet; organisation denial is immaterial.
        self.transport.allowed = False
        for stage in ('extraction', 'enrichment'):
            for outcome in ('success', 'insufficient', 'failure'):
                for change, expected in (('expired', 403), ('identity', 401),
                                         ('outage', 503), ('unchanged', 200)):
                    with self.subTest(stage=stage, outcome=outcome, change=change):
                        self.transport.owner = USER
                        self.transport.status = 200
                        report = {'source_url': 'https://example.org/',
                                  'evidence': {'status': 'sufficient'},
                                  'observations': {'name': 'Private findings'}}

                        def complete(*args, **kwargs):
                            if change == 'expired': self.transport.status = 401
                            if change == 'identity': self.transport.owner = OTHER
                            if change == 'outage': self.transport.status = 503
                            if outcome == 'failure': raise WebsiteSafetyError('Private failure details')
                            if outcome == 'insufficient': report['evidence']['status'] = 'insufficient'
                            return report

                        with patch('business_growthrova_preview.extract_website',
                                   side_effect=complete if stage == 'extraction' else None,
                                   return_value=report) as reader, \
                                patch('business_growthrova_preview.expand_business_audit',
                                      side_effect=complete if stage == 'enrichment' else lambda value, **kw: value):
                            response = self.client.post(endpoint,
                                json={'website': 'https://example.org/'}, headers=self.headers)
                        reader.assert_called_once_with('https://example.org/')
                        status = 400 if change == 'unchanged' and outcome != 'success' else expected
                        self.assertEqual(response.status_code, status, response.json)
                        self.assertEqual(response.headers['Cache-Control'], 'no-store')
                        if change != 'unchanged':
                            self.assertNotIn('observations', response.json)
                            self.assertNotIn('evidence', response.json)
                            self.assertNotIn('Private failure details', response.get_data(as_text=True))
                        elif outcome == 'success':
                            self.assertEqual(response.json, report)
                        else:
                            self.assertEqual(response.json['code'], 'research_unavailable')
                            if outcome == 'failure':
                                self.assertEqual(response.json['error'], 'Private failure details')
        self.transport.status = 200
        self.transport.owner = USER
        self.transport.allowed = True
        self.assertEqual(self.client.get(self.root, headers=self.headers).json['documents'], [])

    def test_copy_readiness_matches_editor_and_preserves_legacy_drafts_on_save_reopen(self):
        from business_marketing_drafts import marketing_copy_issue
        cases = [
            ('Example restaurant', 'Explore the menu'),
            ('  DRAFT DIRECTION: Explain the service.', 'Explore the menu'),
            ('Explore dining.\nWebsite excerpt (unconfirmed): “Seasonal dining.”', 'Explore the menu'),
            ('Ready to visit? What matters to you?', 'Explore the menu'),
            ('“Viewings are by appointment.”', 'Explore the menu'),
            ('Planning a visit? Talk to our team about a viewing.', 'Enquire about a viewing'),
            ('Read our menu', 'Explore the menu'),
            ('Discuss a viewing with the club.', ' '),
        ]
        items = [{'copyDraft':words,'callToAction':cta} for words,cta in cases]
        script = """import fs from 'node:fs';
          import {marketingCopyIssue} from './src/lib/businessCopyReadiness.mjs';
          const items=JSON.parse(fs.readFileSync(0,'utf8'));
          process.stdout.write(JSON.stringify(items.map(item=>marketingCopyIssue(item,'Example restaurant'))));"""
        client_issues = subprocess.run(['node','--input-type=module','-e',script],
            input=json.dumps(items),text=True,capture_output=True,timeout=15,check=True)
        issues = [marketing_copy_issue(item,'Example restaurant') for item in items]
        self.assertEqual(json.loads(client_issues.stdout),issues)
        self.assertEqual([bool(issue) for issue in issues],[True,True,True,True,True,False,False,True])
        doc = self.payload['document']
        for post,item in zip(doc['posts'],items):
            post.update(item,status='copy_reviewed')
        doc['creatives'][0].update(copyDraft=cases[1][0],status='copy_reviewed')
        original = copy.deepcopy(doc)
        saved = self.save()
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertTrue(self.save().json['replayed'])
        reopened = self.create().test_client().get(self.root+'/'+'1'*32,headers=self.headers).json['document']
        self.assertEqual([post['status'] for post in reopened['posts'][:8]],
                         ['draft']*5+['copy_reviewed','copy_reviewed','draft'])
        self.assertEqual(reopened['creatives'][0]['status'],'draft')
        for kind in ('posts','creatives'):
            for old,new in zip(original[kind],reopened[kind]):
                for key in ('copyDraft','callToAction'):
                    self.assertEqual(new[key],old[key])
        self.assertFalse(reopened['canSpend'])
        self.assertFalse(reopened['canPublish'])

    def test_picture_only_revision_keeps_word_review_across_save_retry_and_reopen(self):
        from business_marketing_drafts import normalise_document
        doc=self.payload['document']
        doc['creatives'][0]['status']='copy_reviewed'
        first=self.save()
        self.assertEqual(first.status_code,200,first.json)
        original=copy.deepcopy(first.json['document'])
        script="""import fs from 'node:fs';
          import {editMarketingCreative} from './src/lib/businessMarketingDocument.mjs';
          const doc=JSON.parse(fs.readFileSync(0,'utf8'));
          process.stdout.write(JSON.stringify(editMarketingCreative(doc,'creative-1',
            {brief:'Keep the authorised logo clear of the frame edge.'})));"""
        result=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(original),
                              text=True,capture_output=True,timeout=15,check=True)
        revised=json.loads(result.stdout)
        payload={**self.payload,'expectedRevision':1,'mutationId':'3'*32,'document':revised}
        saved=self.save(payload)
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertTrue(self.save(payload).json['replayed'])
        reopened=self.create().test_client().get(self.root+'/'+'1'*32,headers=self.headers).json['document']
        self.assertEqual(reopened['creatives'][0]['status'],'copy_reviewed')
        self.assertEqual(reopened['creatives'][0]['brief'],revised['creatives'][0]['brief'])
        self.assertEqual(reopened['posts'],original['posts'])
        for key in ('copyDraft','callToAction'):
            self.assertEqual(reopened['creatives'][0][key],original['creatives'][0][key])
        self.assertFalse(reopened['creatives'][0]['approved'])
        self.assertFalse(reopened['canPublish'])
        self.assertFalse(reopened['canSpend'])
        # Server independently rejects stale review for changed words/context,
        # even if a client attempts to retain copy_reviewed.
        for key,value in [('copyDraft','Explore dining with our team.'),('callToAction','Enquire about dining'),
                          ('title','Changed creative context'),('ratio','9:16'),('format','video_ad')]:
            with self.subTest(key=key):
                changed=copy.deepcopy(reopened)
                changed['creatives'][0][key]=value
                self.assertEqual(normalise_document(changed,reopened)['creatives'][0]['status'],'draft')

    def test_persist_reopen_retry_conflict_and_media_bytes(self):
        self.assertEqual(self.save().status_code,200)
        self.assertTrue(self.save().json['replayed'])
        client=self.create().test_client()
        restored=client.get(self.root,headers=self.headers) # list after restart
        self.assertEqual(restored.json['documents'][0]['document']['posts'][7]['copyDraft'],'Original copy')
        edited=copy.deepcopy(self.payload)
        edited.update(expectedRevision=1,mutationId='3'*32)
        edited['document']['posts'][7]['copyDraft']='Owner edited day eight'
        self.assertEqual(self.save(edited).json['revision'],2)
        self.assertEqual(self.save().status_code,409)
        png=io.BytesIO(); Image.new('RGB',(64,48),'#225533').save(png,format='PNG'); content=png.getvalue()
        media=self.root+'/'+'1'*32+'/media'
        def upload():
            return self.client.post(media,data={'file':(io.BytesIO(content),'owned.png','image/png'),
                'rightsStatement':'Synthetic test declaration for this original media.',
                'consentStatus':'owner_asserted'},headers={**self.headers,'Idempotency-Key':'4'*32})
        result=upload();self.assertEqual(result.status_code,201,result.json)
        self.assertTrue(upload().json['replayed'])
        asset=result.json['assets'][0]
        original=self.client.get(media+'/'+asset['assetId']+'/original',headers=self.headers)
        self.assertEqual(original.data,content)
        library=client.get(media,headers=self.headers)
        self.assertEqual(len(library.json['assets']),1)
        self.assertEqual(library.json['posts'][7]['copyDraft'],'Owner edited day eight')
        self.assertFalse(library.json['hostedStorageVerified'])
        self.assertFalse(library.json['canPublish']);self.assertFalse(library.json['canSpend'])
        self.assertEqual(original.headers['Cache-Control'],'no-store')
        selection={'revision':2,'selectionVersion':0,'assetIds':[asset['assetId']],
                   'postAssignments':[{'day':8,'assetIds':[asset['assetId']]}]}
        self.assertEqual(self.client.put(media+'/selection',json=selection,headers=self.headers).status_code,200)
        self.transport.allowed=False
        self.assertEqual(self.client.get(media+'/'+asset['assetId']+'/original',headers=self.headers).status_code,403)
        self.assertEqual(self.client.put(media+'/selection',json=selection,headers=self.headers).status_code,403)
        self.transport.allowed=True
        self.assertEqual(client.get(media,headers=self.headers).json['selection']['postAssignments'][0]['day'],8)

    def test_static_draft_uses_authenticated_preview_scope_before_any_render(self):
        from business_brand_render import compose_static_post
        import base64
        self.payload['document']['brandKit']=dict(name='Synthetic Workshop',primary_color='#123456',
            secondary_color='#FFFFFF',font_style='modern')
        self.assertEqual(self.save().status_code,200)
        root=self.root+'/'+self.payload['id']+'/media'
        pixels=io.BytesIO();Image.new('RGB',(64,48),'#225533').save(pixels,format='PNG')
        uploaded=self.client.post(root,headers=self.headers,data=dict(
            file=(io.BytesIO(pixels.getvalue()),'qa.png','image/png'),consentStatus='owner_asserted',
            rightsStatement='Synthetic QA pixels; permission for this local layout test.'),content_type='multipart/form-data')
        self.assertEqual(uploaded.status_code,201,uploaded.json)
        asset=uploaded.json['asset']['assetId']
        selected=self.client.put(root+'/selection',headers=self.headers,json=dict(revision=1,
            selectionVersion=0,assetIds=[asset],postAssignments=[dict(day=1,assetIds=[asset])]))
        self.assertEqual(selected.status_code,200,selected.json)
        preview=self.client.get(root+f'/posts/1/{asset}/original-review?revision=1&selectionVersion=1',headers=self.headers).json
        noted=self.client.put(root+f'/posts/1/{asset}/review-note',headers=self.headers,json=dict(revision=1,
            selectionVersion=1,reviewVersion=0,receipt=preview['reviewReceipt'],outcome='usable_candidate',
            note='Synthetic QA photo is fully visible in the saved source.'))
        self.assertEqual(noted.status_code,200,noted.json)
        url=root+'/posts/1/static-preview?revision=1&selectionVersion=1&reviewVersion=1'
        response=self.client.get(url,headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        with Image.open(io.BytesIO(base64.b64decode(response.json['previewBase64']))) as image:
            self.assertEqual(image.size,(1080,1350))
        for headers,owner,allowed in [({},USER,True),(self.headers,OTHER,True),(self.headers,USER,False)]:
            self.transport.owner=owner;self.transport.allowed=allowed
            with patch('business_brand_render.compose_static_post',wraps=compose_static_post) as render:
                denied=self.client.get(url,headers=headers)
                self.assertIn(denied.status_code,(401,403))
                render.assert_not_called()

    def test_saved_audio_draft_uses_scoped_preview_and_denies_revoked_access(self):
        self._saved_audio_draft()

    def test_silent_excerpt_of_delayed_audio_downloads_through_scoped_preview(self):
        self._saved_audio_draft(silent_excerpt=True)

    def test_excerpt_with_earlier_audio_downloads_through_scoped_preview(self):
        self._saved_audio_draft(earlier_audio=True)

    def _saved_audio_draft(self, *, silent_excerpt=False, earlier_audio=False):
        self.assertEqual(self.save().status_code,200)
        media=self.root+'/'+'1'*32+'/media'
        source=Path(self.tmp.name)/'tone.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error',
            *(['-itsoffset','0.5'] if earlier_audio else []),'-f','lavfi','-i',
            'color=c=blue:s=160x160:r=24:d='+('2' if silent_excerpt else '1' if earlier_audio else '0.5'),
            *(['-itsoffset','0.75'] if silent_excerpt else []),'-f','lavfi','-i',
            'sine=frequency=440:duration='+('0.25' if earlier_audio else '0.5'),
            '-fps_mode','passthrough','-c:v','libx264','-threads','1',
            '-pix_fmt','yuv420p','-c:a','aac','-y',str(source)],check=True,timeout=15)
        content=source.read_bytes()
        imported=self.client.post(media,data={'file':(io.BytesIO(content),'tone.mp4','video/mp4'),
            'rightsStatement':'Synthetic authored tone and pixels for local verification.',
            'consentStatus':'owner_asserted'},headers=self.headers)
        self.assertEqual(imported.status_code,201,imported.json)
        ident=imported.json['asset']['assetId']
        selection={'revision':1,'selectionVersion':0,'assetIds':[ident],
            'postAssignments':[{'day':1,'assetIds':[ident],
                'videoEdits':[{'assetId':ident,'startMs':0,'endMs':500,'muted':False}]}]}
        self.assertEqual(self.client.put(media+'/selection',json=selection,headers=self.headers).status_code,200)
        preview=self.client.get(media+f'/posts/1/{ident}/video-preview?revision=1&selectionVersion=1',headers=self.headers)
        self.assertEqual(preview.status_code,200,preview.json)
        note={'revision':1,'selectionVersion':1,'reviewVersion':0,
            'receipt':preview.json['reviewReceipt'],'outcome':'usable_candidate',
            'note':'Synthetic tone and pixels inspected for sequence testing only.'}
        self.assertEqual(self.client.put(media+f'/posts/1/{ident}/review-note',json=note,headers=self.headers).status_code,200)
        before=self.client.get(media,headers=self.headers).json
        url=media+'/posts/1/composition-preview?revision=1&selectionVersion=1&reviewVersion=1&audioPolicy=saved_candidate_audio'
        result=self.client.get(url,headers=self.headers)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.headers['Cache-Control'],'no-store')
        self.assertTrue(result.json['manifest']['timeline'][0]['hasAudio'])
        if silent_excerpt or earlier_audio:
            import base64,array
            target=Path(self.tmp.name)/'silent-excerpt-draft.mp4'
            target.write_bytes(base64.b64decode(result.json['previewBase64']))
            raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(target),
                '-ss','0.1','-t','0.2','-map','0:a:0','-ac','1','-ar','48000',
                '-f','s16le','-'],capture_output=True,check=True,timeout=10).stdout
            samples=array.array('h',raw)
            self.assertGreater(len(samples),8000)
            self.assertLess(max(abs(v) for v in samples),10)
        script="""import {loadSavedPostComposition} from './src/lib/businessOriginalReview.mjs';
          import fs from 'node:fs';const d=JSON.parse(fs.readFileSync(0,'utf8'));
          const r=await loadSavedPostComposition(d.library,1,async p=>p?d.result:d.library,()=>true,'saved_candidate_audio');
          if(r.blob.size!==d.result.manifest.previewBytes)throw Error('Download bytes differ');"""
        subprocess.run(['node','--input-type=module','-e',script],input=json.dumps({
            'library':before,'result':result.json}),text=True,capture_output=True,check=True,timeout=15)
        self.assertEqual(self.client.get(media,headers=self.headers).json,before)
        self.assertEqual(self.client.get(media+'/'+ident+'/original',headers=self.headers).data,content)
        with patch('business_reel_workbench._render_cut') as render:
            self.transport.allowed=False
            self.assertEqual(self.client.get(url,headers=self.headers).status_code,403)
            self.transport.allowed=True;self.transport.owner=OTHER
            self.assertEqual(self.client.get(url,headers=self.headers).status_code,403)
            self.transport.owner=USER
            self.assertEqual(self.client.get(url).status_code,401)
            render.assert_not_called()

    def test_deep_club_strategy_source_survives_save_reopen_and_invalidates_on_change(self):
        htmls=[b'<title>Synthetic Country Club</title><meta name="description" content="Dining at our country club."><p>Our restaurant is a welcoming place to spend time together and enjoy the day.</p><p>Our Orchard restaurant serves vegetable plates and offers a separate lunch menu.</p><a href="/membership">Membership</a><a href="/spa">Spa</a><a href="/fitness">Fitness</a>',
          ('<p>'+'Discover our club and the spaces where you can spend your day. '*9+
           'Membership options include a guided tour by appointment. Start the year with a club visit.</p>').encode(),
          b'<p>Our spa treatment descriptions explain the consultation process.</p>',
          ('<p>Fitness classes '+('provide guided sessions for different interests and routines '*9)+'</p>').encode()]
        urls=['https://example.org/','https://example.org/membership','https://example.org/spa','https://example.org/fitness']
        reports=[extract_website(url,fetch=lambda *a,body=body:body,
          resolve=lambda *a,**k:[(2,1,6,"",("93.184.216.34",443))]) for url,body in zip(urls,htmls)]
        with patch('business_growthrova_preview.extract_website',side_effect=reports):
            result=self.client.post(f'/api/growthrova/organisations/{ORG}/research',json={},headers=self.headers)
        self.assertEqual(result.status_code,200)
        script=r"""import fs from 'node:fs';import assert from 'node:assert/strict';
          import {prepareUrlCampaign} from './src/lib/businessUrlCampaignPipeline.mjs';
          import {createMarketingDocument,marketingPlanCsv,usePostWordsForCreative} from './src/lib/businessMarketingDocument.mjs';
          import * as s from './src/lib/businessOwnerStrategy.mjs';
          let doc=createMarketingDocument(prepareUrlCampaign(JSON.parse(fs.readFileSync(0,'utf8'))));
          assert.ok(marketingPlanCsv(doc).includes('https://example.org/membership'));
          assert.ok(marketingPlanCsv(doc).includes('Membership options include a guided tour by appointment.'));
          const membership=doc.posts.find(post=>post.copyDraft.includes('Source (unconfirmed): https://example.org/membership'));
          assert.ok(membership.copyDraft.includes('Date-sensitive source: current dates and availability are unknown.'));
          assert.ok(marketingPlanCsv(doc).includes('Date-sensitive source:'));
          assert.ok(doc.editorialShortlist.candidates.find(item=>item.evidence.kind==='membership').direction.includes('Date-sensitive source:'));
          const dining=doc.editorialShortlist.candidates.find(item=>item.evidence.kind==='dining');
          assert.ok(dining.hook.includes('Orchard'));
          assert.equal(dining.evidence.sourceUrl,'https://example.org/');
          assert.equal(dining.evidence.quote,'Our Orchard restaurant serves vegetable plates and offers a separate lunch menu.');
          assert.ok(marketingPlanCsv(doc).includes(dining.evidence.quote));
          const fitness=doc.posts.find(post=>post.copyDraft.includes('Source (unconfirmed): https://example.org/fitness'));
          assert.ok(fitness.copyDraft.includes('Website excerpt (unconfirmed; shortened): “Fitness classes'));
          assert.ok(fitness.copyDraft.includes('”\nSource (unconfirmed): https://example.org/fitness\n'));
          assert.ok(marketingPlanCsv(doc).includes('Website excerpt (unconfirmed; shortened): “Fitness classes'));
          for(let i=0;i<doc.observedFacts.length;i++)doc=s.reviewBusinessFact(doc,i,'excluded');
          for(const key of Object.keys(s.strategyFields))doc=s.editOwnerStrategy(doc,key,'Synthetic owner planning '+key);
          const item=s.strategyEvidence(doc).find(e=>e.sourceUrl==='https://example.org/membership');
          assert.ok(item);doc=s.linkStrategyEvidence(doc,'offer',item.id);doc=s.confirmOwnerStrategy(doc);
          const originalPosts=JSON.stringify(doc.posts),otherCreatives=JSON.stringify(doc.creatives.slice(1));
          const brief=doc.creatives[0].brief,cta=doc.creatives[0].callToAction;
          doc=usePostWordsForCreative(doc,'creative-1',membership.day);
          assert.equal(doc.creatives[0].copyDraft,membership.copyDraft);
          assert.equal(doc.creatives[0].brief,brief);assert.equal(doc.creatives[0].callToAction,cta);
          assert.equal(JSON.stringify(doc.posts),originalPosts);
          assert.equal(JSON.stringify(doc.creatives.slice(1)),otherCreatives);
          process.stdout.write(JSON.stringify(doc));"""
        run=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(result.json),text=True,capture_output=True,timeout=15,check=True)
        payload={**self.payload,'document':json.loads(run.stdout)}
        saved=self.save(payload)
        self.assertEqual(saved.status_code,200,saved.json)
        doc=self.create().test_client().get(self.root+'/'+'1'*32,headers=self.headers).json['document']
        # Server stores source-linked planning fields, dropping client-only
        # rendering hints and resetting authority flags by design.
        for field in ('evidence','hook','direction'):
            self.assertEqual([c[field] for c in doc['editorialShortlist']['candidates']],
              [c[field] for c in payload['document']['editorialShortlist']['candidates']])
        self.assertEqual(doc['ownerStrategy']['confirmedContext'],payload['document']['ownerStrategy']['confirmedContext'])
        self.assertEqual(doc['posts'],payload['document']['posts'])
        self.assertEqual(doc['creatives'],payload['document']['creatives'])
        self.assertIn('Source (unconfirmed): https://example.org/membership',doc['creatives'][0]['copyDraft'])
        self.assertIn('Date-sensitive source:',doc['creatives'][0]['copyDraft'])
        self.assertFalse(doc['canPublish'])
        self.assertFalse(doc['canSpend'])
        changed=copy.deepcopy(doc)
        changed['editorialShortlist']['candidates'][0]['evidence']['sourceUrl']='https://example.org/changed'
        from business_marketing_drafts import normalise_document, MarketingDraftError
        self.assertIsNone(normalise_document(changed)['ownerStrategy']['confirmedContext'])
        for bad in ['https://foreign.example.org/spa','http://example.org/spa','https://user@example.org/spa']:
            changed['editorialShortlist']['candidates'][0]['evidence']['sourceUrl']=bad
            with self.assertRaises(MarketingDraftError):normalise_document(changed)

    def test_service_evidence_after_consent_survives_research_save_reopen_export(self):
        notices=['We use cookies on our website to deliver you the best online experience.',
          'Necessary cookies enable core functionality such as security and accessibility.']
        filler=[f'Find our workshop information and team introduction in section {i}.' for i in range(10)]
        plumbing='Plumbing inspections cover visible leaks; ask the team about the inspection scope.'
        heating='Boiler servicing is available by appointment; discuss heating requirements with the team.'
        html=('<title>Example Plumbing</title><meta name="description" content="Plumbing and heating services.">'+
          ''.join('<p>'+value+'</p>' for value in notices+filler+[plumbing,heating])+
          '<a href="/contact">Book now</a><a href="/about">About us</a>'+
          '<a href="/services/plumbing">Plumbing</a><a href="/services/heating">Heating</a>').encode()
        report=extract_website('https://example.org/',fetch=lambda *a:html,
          resolve=lambda *a,**k:[(2,1,6,"",("93.184.216.34",443))])
        plumbing_detail=('Plumbing inspections cover pipe joints and visible leaks; describe the affected fixture before enquiring. '
                         'Request a written quotation before agreeing work.')
        heating_detail='Boiler servicing includes a discussion of the heating system; ask which service checks are included.'
        details={'https://example.org/services/plumbing':plumbing_detail,
                 'https://example.org/services/heating':heating_detail,
                 'https://example.org/contact':'Contact the team to discuss your requirements.'}
        reports={url:extract_website(url,fetch=lambda *a,quote=quote:('<p>'+quote+'</p>').encode(),
          resolve=lambda *a,**k:[(2,1,6,"",("93.184.216.34",443))]) for url,quote in details.items()}
        reports[report['source_url']]=report
        with patch('business_growthrova_preview.extract_website',side_effect=lambda url:reports[url]):
            result=self.client.post(f'/api/growthrova/organisations/{ORG}/research',json={},headers=self.headers)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['coverage']['attempted_urls'],list(details))
        self.assertIn(plumbing,report['observations']['visible_paragraphs'])
        self.assertIn(heating,report['observations']['visible_paragraphs'])
        script=r"""import fs from 'node:fs';import assert from 'node:assert/strict';
          import {prepareUrlCampaign} from './src/lib/businessUrlCampaignPipeline.mjs';
          import {createMarketingDocument,marketingPlanCsv} from './src/lib/businessMarketingDocument.mjs';
          const campaign=prepareUrlCampaign(JSON.parse(fs.readFileSync(0,'utf8')));
          const directions=campaign.siteSpecificStory.differentiators;
          assert.equal(directions.find(x=>x.key==='repairs').evidence,'Plumbing inspections cover pipe joints and visible leaks; describe the affected fixture before enquiring.');
          assert.equal(directions.find(x=>x.key==='repairs').sourceUrl,'https://example.org/services/plumbing');
          assert.equal(directions.find(x=>x.key==='heating').evidence,'Boiler servicing includes a discussion of the heating system; ask which service checks are included.');
          assert.equal(directions.find(x=>x.key==='heating').sourceUrl,'https://example.org/services/heating');
          const scope=directions.find(x=>x.key==='scope');
          assert.equal(scope.evidence,'Request a written quotation before agreeing work.');
          assert.equal(scope.sourceUrl,'https://example.org/services/plumbing');
          assert.equal(scope.hook,'“written quotation”: what should you ask?');
          assert.equal(directions.find(x=>x.key==='repairs').hook,'“Plumbing inspections”: what should you ask?');
          assert.equal(directions.find(x=>x.key==='heating').hook,'“Boiler servicing”: what should you ask?');
          const doc=createMarketingDocument(campaign);
          assert.ok(marketingPlanCsv(doc).includes('Boiler servicing includes a discussion'));
          assert.ok(!doc.posts.some(post=>post.copyDraft.includes('Necessary cookies')));
          assert.equal(doc.canPublish,false);assert.equal(doc.canSpend,false);
          process.stdout.write(JSON.stringify(doc));"""
        prepared=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(result.json),
          text=True,capture_output=True,timeout=15,check=True)
        payload={**self.payload,'document':json.loads(prepared.stdout)}
        saved=self.save(payload)
        self.assertEqual(saved.status_code,200,saved.json)
        reopened=self.create().test_client().get(self.root+'/'+'1'*32,headers=self.headers).json['document']
        self.assertEqual(reopened['posts'],payload['document']['posts'])
        verify=r"""import fs from 'node:fs';import assert from 'node:assert/strict';
          import {marketingPlanCsv} from './src/lib/businessMarketingDocument.mjs';
          const doc=JSON.parse(fs.readFileSync(0,'utf8'));
          assert.ok(marketingPlanCsv(doc).includes('Boiler servicing includes a discussion'));
          assert.ok(marketingPlanCsv(doc).includes('Plumbing inspections cover pipe joints'));
          assert.ok(marketingPlanCsv(doc).includes('“written quotation”: what should you ask?'));
          assert.ok(marketingPlanCsv(doc).includes('Request a written quotation before agreeing work.'));
          for(const path of ['plumbing','heating'])assert.ok(doc.posts.some(post=>post.copyDraft.includes('Source (unconfirmed): https://example.org/services/'+path+'\n')));
          assert.equal(doc.canPublish,false);assert.equal(doc.canSpend,false);"""
        subprocess.run(['node','--input-type=module','-e',verify],input=json.dumps(reopened),
          text=True,capture_output=True,timeout=15,check=True)

    def test_research_actual_js_confirmation_calendar_save_reload_and_csv(self):
        html=b'''<title>Synthetic business</title><meta name="description" content="Bicycle servicing and brake adjustments in our local workshop.">
        <h1>Bicycle workshop</h1><p>We offer bicycle servicing and brake adjustments. Contact the workshop to discuss your bicycle.</p><a href="/services/">Bicycle servicing</a>'''
        report=extract_website('https://example.org/',fetch=lambda url,ip:html,
            resolve=lambda *args,**kwargs:[(2,1,6,'',('93.184.216.34',443))])
        detail=extract_website('https://example.org/services/',fetch=lambda *a:b'<title>Workshop services</title><h1>Brake servicing</h1><p>Ask about winter servicing availability before booking your bicycle.</p>',
            resolve=lambda *args,**kwargs:[(2,1,6,'',('93.184.216.34',443))])
        with patch('business_growthrova_preview.extract_website',side_effect=[report,detail]) as reader:
            result=self.client.post(f'/api/growthrova/organisations/{ORG}/research',json={},headers=self.headers)
        self.assertEqual(reader.call_count,2)
        self.assertEqual(result.json['audited_page_urls'],['https://example.org/','https://example.org/services/'])
        self.assertEqual(result.json['page_reports'][1],detail)
        script=r'''import fs from 'node:fs';
          import {prepareUrlCampaign} from './src/lib/businessUrlCampaignPipeline.mjs';
          import {createMarketingDocument,editMarketingCreative,reviewMarketingCopy} from './src/lib/businessMarketingDocument.mjs';
          import {strategyFields,reviewBusinessFact,editOwnerStrategy,confirmOwnerStrategy,completeStrategyCalendar,appendReviewedBusinessDetail,appendReviewedCreativeDetail,useConfirmedBriefForPost} from './src/lib/businessOwnerStrategy.mjs';
          let doc=createMarketingDocument(prepareUrlCampaign(JSON.parse(fs.readFileSync(0,'utf8')),{objective:'enquiries'}));
          for(const [key,value] of Object.entries({audience:'Local bicycle owners',offer:'Bicycle servicing',positioning:'Owner supplied workshop details',callToAction:'Contact the workshop',constraints:'No invented discounts, reviews or outcomes'}))doc=editOwnerStrategy(doc,key,value.padEnd(strategyFields[key]-8,'x')+' ENDNOTE');
          for(let i=0;i<doc.observedFacts.length;i++)doc=reviewBusinessFact(doc,i,i===0?'corrected':'excluded',i===0?'Bicycle servicing by appointment':'');
          doc=confirmOwnerStrategy(doc);doc.calendarStartDate='2026-11-01';
          doc=completeStrategyCalendar({...doc,posts:[]});
          const otherDays=JSON.stringify(doc.posts.slice(1)),original=doc.posts[0].copyDraft;
          doc=appendReviewedBusinessDetail(doc,1,0);
          if(doc.posts[0].copyDraft!==original+'\n\nBicycle servicing by appointment'||JSON.stringify(doc.posts.slice(1))!==otherDays)throw Error('Owner work changed');
          if(appendReviewedBusinessDetail(doc,1,0)!==doc)throw Error('Repeated action duplicated copy');
          doc=useConfirmedBriefForPost(doc,2);
          doc=editMarketingCreative(doc,doc.creatives[0].id,{copyDraft:'Talk to our workshop about bicycle servicing.'});
          doc=reviewMarketingCopy(doc,'creative',doc.creatives[0].id);
          const posts=JSON.stringify(doc.posts),others=JSON.stringify(doc.creatives.slice(1)),cta=doc.creatives[0].callToAction;
          doc=editMarketingCreative(doc,doc.creatives[0].id,{copyDraft:'Discuss your bicycle with our workshop',brief:'Use an authorised workshop photo without invented customers or outcomes.'});
          doc=reviewMarketingCopy(doc,'creative',doc.creatives[0].id);
          doc=appendReviewedCreativeDetail(doc,doc.creatives[0].id,0);
          if(appendReviewedCreativeDetail(doc,doc.creatives[0].id,0)!==doc)throw Error('Repeated creative addition duplicated copy');
          if(doc.creatives[0].status!=='draft'||doc.creatives[0].callToAction!==cta||JSON.stringify(doc.posts)!==posts||JSON.stringify(doc.creatives.slice(1))!==others)throw Error('Creative revision lost owner work or retained stale copy review');
          process.stdout.write(JSON.stringify(doc));'''
        prepared=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(result.json),
            text=True,capture_output=True,timeout=15,check=True)
        payload={**self.payload,'document':json.loads(prepared.stdout)}
        self.assertEqual(self.save(payload).status_code,200)
        saved=self.create().test_client().get(self.root+'/'+'1'*32,headers=self.headers).json
        self.assertEqual(saved['document']['creatives'],payload['document']['creatives'])
        self.assertEqual(saved['document']['websiteAuditText'],payload['document']['websiteAuditText'])
        self.assertIn('Unconfirmed page excerpt: https://example.org/services/',saved['document']['websiteAuditText'])
        self.assertIn('winter servicing availability',saved['document']['websiteAuditText'])
        self.assertIn('current validity is unknown',saved['document']['websiteAuditText'])
        verify=r'''import fs from 'node:fs';import assert from 'node:assert/strict';
          import {strategyConfirmed} from './src/lib/businessOwnerStrategy.mjs';
          import {marketingPlanCsv,marketingCreativeText} from './src/lib/businessMarketingDocument.mjs';
          import {createPublicationCalendar,publicationCalendarIcs} from './src/lib/businessPublicationCalendar.mjs';
          const record=JSON.parse(fs.readFileSync(0,'utf8')),doc=record.document;
          assert.equal(strategyConfirmed(doc),true);assert.equal(doc.posts.length,30);
          assert.equal(doc.ownerStrategy.factDecisions[0].statement,'Bicycle servicing by appointment');
          assert.equal(doc.ownerStrategy.factDecisions[0].decision,'corrected');
          assert.notEqual(doc.observedFacts[0],'Bicycle servicing by appointment');
          assert.ok(doc.posts[0].copyDraft.endsWith('\n\nBicycle servicing by appointment'));
          assert.equal(doc.posts[0].status,'draft');
          assert.equal(doc.posts[1].copyDraft,[doc.business,doc.ownerStrategy.offer,doc.ownerStrategy.positioning].join('\n\n'));
          assert.equal(doc.posts[1].callToAction,doc.ownerStrategy.callToAction);
          assert.equal(doc.creatives[0].copyDraft,'Discuss your bicycle with our workshop\n\nBicycle servicing by appointment');
          assert.equal(doc.creatives[0].brief,'Use an authorised workshop photo without invented customers or outcomes.');
          assert.equal(doc.creatives[0].status,'draft');
          assert.equal(doc.creatives[0].assetUrl,null);
          const readable=marketingCreativeText(doc,'creative-1');
          assert.ok(readable.includes('Words\n'+doc.creatives[0].copyDraft+'\n\nCall to action\n'+doc.creatives[0].callToAction));
          assert.ok(readable.includes('Picture instructions\n'+doc.creatives[0].brief));
          assert.ok(readable.includes('Source website: '+doc.sourceUrl));
          assert.ok(readable.includes('Copy review: Not checked.'));
          assert.ok(!doc.posts[1].copyDraft.endsWith('\n\nBicycle servicing by appointment'));
          assert.match(marketingPlanCsv(doc),/Synthetic business/);
          const ics=publicationCalendarIcs(createPublicationCalendar(doc.posts,doc.calendarStartDate),{business:doc.business,sourceUrl:doc.sourceUrl,campaignId:record.id,revision:record.revision,updated:record.updated}).replace(/\r\n /g,'').replace(/\\([,;])/g,'$1');
          for(const key of ['audience','offer','positioning','constraints']){
            assert.ok(doc.posts.filter(post=>post.day!==2).every(post=>post.copyDraft.includes(doc.ownerStrategy[key])));
            assert.equal(doc.posts[1].copyDraft.includes(doc.ownerStrategy[key]),['offer','positioning'].includes(key));
            assert.ok(ics.includes(doc.ownerStrategy[key]));
          }
          assert.ok(ics.includes(doc.ownerStrategy.callToAction));assert.ok(ics.includes(doc.sourceUrl));
          assert.ok(ics.includes('\\n\\nBicycle servicing by appointment'));
          assert.equal(doc.canPublish,false);assert.equal(doc.canSpend,false);'''
        subprocess.run(['node','--input-type=module','-e',verify],input=json.dumps(saved),
            text=True,capture_output=True,timeout=15,check=True)
        changed=copy.deepcopy(saved['document'])
        changed['ownerStrategy']['factDecisions'][0]['statement']='Contact us to confirm current availability'
        revised={**payload,'document':changed,'expectedRevision':1,'mutationId':'3'*32}
        updated=self.save(revised)
        self.assertEqual(updated.status_code,200)
        self.assertIsNone(updated.json['document']['ownerStrategy']['confirmedContext'])
        self.assertTrue(self.save(revised).json['replayed'])
        reopened=self.create().test_client().get(self.root+'/'+'1'*32,headers=self.headers).json['document']
        self.assertEqual(reopened['observedFacts'],saved['document']['observedFacts'])
        self.assertEqual(reopened['posts'],saved['document']['posts'])
        self.assertEqual(reopened['creatives'],saved['document']['creatives'])
        self.assertEqual(reopened['ownerStrategy']['factDecisions'][0]['statement'],changed['ownerStrategy']['factDecisions'][0]['statement'])
        self.assertIsNone(reopened['ownerStrategy']['confirmedContext'])

    def test_identity_org_revocation_and_unavailable_fail_closed(self):
        self.assertEqual(self.client.post(self.root,json={**self.payload,'owner_id':USER},headers={'X-Clippr-Pilot':'local-only'}).status_code,401)
        self.assertEqual(self.client.get(self.root,headers={'Authorization':'Bearer forged'}).status_code,403)
        self.assertEqual(self.save().status_code,200)
        self.transport.owner=OTHER
        self.assertEqual(self.client.get(self.root+'/'+'1'*32,headers=self.headers).status_code,403)
        self.assertEqual(self.save().status_code,403)
        self.transport.owner=USER;self.transport.allowed=False
        self.assertEqual(self.client.get(self.root,headers=self.headers).status_code,403)
        self.transport.allowed=True;self.transport.status=503
        self.assertEqual(self.save().status_code,503)
        self.transport.status=200
        self.assertEqual(self.save().status_code,200)
        for url,options in self.transport.calls:
            self.assertTrue(url.startswith(PROJECT+'/'))
            self.assertFalse(options['allow_redirects'])
            self.assertEqual(options['headers']['Authorization'],'Bearer '+('forged' if options['headers']['Authorization'].endswith('forged') else 'synthetic-valid'))
        # Creator/offline routes are not mounted.
        self.assertEqual(self.client.get('/offline/organisations/x/marketing-documents',headers=self.headers).status_code,404)
        self.assertEqual(self.client.post('/api/pilot/render',headers=self.headers).status_code,404)

    def test_research_uses_rls_org_website_and_preserves_failure(self):
        endpoint=f'/api/growthrova/organisations/{ORG}/research'
        with patch('business_growthrova_preview.extract_website',return_value={'source_url':'https://example.org/','status':'extracted_unconfirmed','observations':{}}) as reader:
            self.assertEqual(self.client.post(endpoint,json={},headers=self.headers).status_code,200)
            reader.assert_called_once_with('https://example.org/')
            self.assertEqual(self.client.post(endpoint,json={'url':'https://foreign.example'},headers=self.headers).status_code,400)
        self.transport.allowed=False
        with patch('business_growthrova_preview.extract_website') as reader:
            self.assertEqual(self.client.post(endpoint,json={},headers=self.headers).status_code,403)
            reader.assert_not_called()

    def test_saved_research_rechecks_access_identity_and_website_after_slow_read(self):
        endpoint = f'/api/growthrova/organisations/{ORG}/research'
        saved = self.save().json
        report = {'source_url': 'https://example.org/',
                  'evidence': {'status': 'sufficient'}, 'observations': {'name': 'Private findings'}}
        original_get = self.transport.get
        for outcome in ('success', 'insufficient', 'failure'):
            for change, expected in (('revoked', 403), ('identity', 401),
                                     ('website', 409), ('outage', 503), ('unchanged', 200)):
                with self.subTest(outcome=outcome, change=change):
                    self.transport.owner = USER
                    self.transport.allowed = True
                    self.transport.status = 200
                    changed = False

                    def get(url, **options):
                        result = original_get(url, **options)
                        if changed and change == 'website' and '/rest/' in url:
                            result.data[0]['website'] = 'https://changed.example/'
                        return result

                    def read(website):
                        nonlocal changed
                        self.assertEqual(website, 'https://example.org/')
                        changed = True
                        if change == 'revoked': self.transport.allowed = False
                        if change == 'identity': self.transport.owner = OTHER
                        if change == 'outage': self.transport.status = 503
                        if outcome == 'failure': raise WebsiteSafetyError('Private failure details')
                        result = copy.deepcopy(report)
                        if outcome == 'insufficient': result['evidence']['status'] = 'insufficient'
                        return result

                    with patch.object(self.transport, 'get', side_effect=get), \
                            patch('business_growthrova_preview.extract_website', side_effect=read), \
                            patch('business_growthrova_preview.expand_business_audit', side_effect=lambda value, **kw: value):
                        response = self.client.post(endpoint, json={}, headers=self.headers)
                    status = 400 if change == 'unchanged' and outcome != 'success' else expected
                    self.assertEqual(response.status_code, status, response.json)
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    if change != 'unchanged':
                        self.assertNotIn('observations', response.json)
                        self.assertNotIn('evidence', response.json)
                        self.assertNotIn('Private failure details', response.get_data(as_text=True))
                    if change == 'website':
                        self.assertEqual(response.json['code'], 'research_website_changed')
        self.transport.status = 200
        self.transport.owner = USER
        self.transport.allowed = True
        reopened = self.create().test_client().get(self.root + '/' + self.payload['id'], headers=self.headers)
        self.assertEqual(reopened.json['document'], saved['document'])
        self.assertEqual(reopened.json['revision'], saved['revision'])

    def test_saved_research_recovers_without_fetch_after_restart_and_failed_retry(self):
        endpoint = f'/api/growthrova/organisations/{ORG}/research'
        report = {'source_url': 'https://example.org/', 'status': 'extracted_unconfirmed',
                  'evidence': {'status': 'sufficient_unconfirmed'},
                  'observations': {'headings': ['Synthetic source evidence']}}
        self.assertEqual(self.client.get(endpoint, headers=self.headers).status_code, 404)
        with patch('business_growthrova_preview.extract_website', return_value=report), \
                patch('business_growthrova_preview.expand_business_audit', side_effect=lambda value, **kw: value):
            self.assertEqual(self.client.post(endpoint, json={}, headers=self.headers).json, report)
        client = self.create().test_client()
        with patch('business_growthrova_preview.extract_website') as reader:
            saved = client.get(endpoint, headers=self.headers)
            reader.assert_not_called()
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json['report'], report)
        self.assertEqual(saved.json['status'], 'unconfirmed')
        for failure in (WebsiteSafetyError('Synthetic fetch failure'),
                        {**report, 'evidence': {'status': 'insufficient'}}):
            with patch('business_growthrova_preview.extract_website',
                       side_effect=failure if isinstance(failure, Exception) else None,
                       return_value=failure), \
                    patch('business_growthrova_preview.expand_business_audit', side_effect=lambda value, **kw: value):
                self.assertEqual(client.post(endpoint, json={}, headers=self.headers).status_code, 400)
            self.assertEqual(client.get(endpoint, headers=self.headers).json, saved.json)
        self.transport.owner = OTHER
        self.assertEqual(client.get(endpoint, headers=self.headers).status_code, 404)
        self.transport.owner = USER
        original_get = self.transport.get
        def changed_website(url, **kwargs):
            result = original_get(url, **kwargs)
            if '/rest/' in url: result.data[0]['website'] = 'https://changed.example/'
            return result
        with patch.object(self.transport, 'get', side_effect=changed_website):
            stale = client.get(endpoint, headers=self.headers)
            self.assertEqual(stale.status_code, 409)
            self.assertNotIn('report', stale.json)
        self.assertEqual(client.get(endpoint).status_code, 401)

    def test_saved_research_orders_results_and_rolls_back_after_final_access_loss(self):
        import business_growthrova_research as snapshots
        from contextlib import closing
        import sqlite3
        endpoint = f'/api/growthrova/organisations/{ORG}/research'
        scope = (USER, ORG)
        newer = {'marker': 'newer', 'source_url': 'https://example.org/'}
        with closing(sqlite3.connect(self.path)) as con:
            con.row_factory = sqlite3.Row
            earlier = snapshots.reserve(con, scope)
            later = snapshots.reserve(con, scope)
            snapshots.retain(con, scope, 'https://example.org/', later, newer)
            snapshots.retain(con, scope, 'https://example.org/', earlier, {'marker': 'older'})
            con.commit()
        saved = self.client.get(endpoint, headers=self.headers).json
        self.assertEqual(saved['report'], newer)
        original_retain = snapshots.retain
        def revoke_after_write(*args):
            original_retain(*args)
            self.transport.allowed = False
        report = {'source_url': 'https://example.org/', 'status': 'extracted_unconfirmed',
                  'evidence': {'status': 'sufficient_unconfirmed'}}
        with patch('business_growthrova_preview.extract_website', return_value=report), \
                patch('business_growthrova_preview.expand_business_audit', side_effect=lambda value, **kw: value), \
                patch.object(snapshots, 'retain', side_effect=revoke_after_write):
            result = self.client.post(endpoint, json={}, headers=self.headers)
        self.assertEqual(result.status_code, 403)
        self.transport.allowed = True
        self.assertEqual(self.create().test_client().get(endpoint, headers=self.headers).json, saved)
        original_latest = snapshots.latest
        def revoke_after_read(*args):
            result = original_latest(*args)
            self.transport.allowed = False
            return result
        with patch.object(snapshots, 'latest', side_effect=revoke_after_read):
            result = self.client.get(endpoint, headers=self.headers)
        self.assertEqual(result.status_code, 403)
        self.assertNotIn('report', result.json)

    def test_configuration_private_volume_and_project_alignment(self):
        with self.assertRaises(ValueError):
            create_growthrova_preview(database_path=self.path,project_url=PROJECT,
                auth_url='https://other.supabase.co',anon_key='sb_publishable_synthetic')
        with self.assertRaises(ValueError):
            create_growthrova_preview(database_path=self.path,project_url=PROJECT,
                auth_url=PROJECT,anon_key='sb_secret_rejected')
        with self.assertRaises(OfflineDocumentAccessError):
            create_growthrova_preview(database_path=self.path,project_url='https://different.supabase.co',
                auth_url='https://different.supabase.co',anon_key='sb_publishable_synthetic')
        Path(self.path).chmod(0o644)
        with self.assertRaises(ValueError):self.create()
        Path(self.path).chmod(0o600)
        link=Path(self.tmp.name)/'link.db';link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            create_growthrova_preview(database_path=str(link),project_url=PROJECT,auth_url=PROJECT,anon_key='sb_publishable_synthetic')

    def test_default_http_uses_only_explicit_caller_auth_and_transport(self):
        # Exercise real Requests preparation without sockets, files or credentials.
        # Ambient netrc auth would replace an explicit Authorization header.
        calls=[]
        def send(adapter, prepared, **options):
            calls.append((prepared, options))
            response=HttpResponse(); response.status_code=200
            response.url=prepared.url
            data=({'id':USER} if prepared.url.endswith('/auth/v1/user') else
                  [{'id':ORG,'owner_id':USER,'website':'https://example.org/'}])
            response._content=json.dumps(data).encode()
            response.headers['Content-Type']='application/json'
            return response
        with patch.dict('os.environ', {'HTTPS_PROXY':'http://synthetic-proxy.invalid:8080',
                                      'REQUESTS_CA_BUNDLE':'/synthetic-ca-do-not-read'}, clear=True), \
             patch('requests.sessions.get_netrc_auth', return_value=('synthetic-ambient','synthetic-password')) as netrc, \
             patch('requests.adapters.HTTPAdapter.send', new=send):
            app=create_growthrova_preview(database_path=self.path,project_url=PROJECT,
                auth_url=PROJECT,anon_key='sb_publishable_synthetic')
            result=app.test_client().get(self.root,headers=self.headers)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['documents'],[])
        self.assertEqual(len(calls),2)
        for prepared, options in calls:
            self.assertTrue(prepared.url.startswith(PROJECT+'/'))
            self.assertEqual(prepared.headers['Authorization'],'Bearer synthetic-valid')
            self.assertEqual(prepared.headers['apikey'],'sb_publishable_synthetic')
            self.assertNotIn('Cookie',prepared.headers)
            self.assertFalse(options['proxies'])
            self.assertIs(options['verify'],True)
            self.assertEqual(options['timeout'],7)
        netrc.assert_not_called()


if __name__=='__main__':unittest.main()
