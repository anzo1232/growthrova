"""Real original bytes -> existing catalogue -> campaign selection, no sockets/cloud."""
import hashlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from business_marketing_offline import create_offline_document_app
from tests.test_business_marketing_drafts import document


class PhotoIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name)/'offline.db')
        self.user = {'id':'owner-a'}; self.memberships = {'org-a','org-b'}
        self.client = self.app().test_client()
        self.docs = '/offline/organisations/org-a/marketing-documents'
        self.ident = 'a'*32
        self.payload = dict(id=self.ident,mutationId='b'*32,expectedRevision=0,document=document())
        self.assertEqual(self.client.post(self.docs,json=self.payload).status_code,200)
        self.root = self.docs+'/'+self.ident+'/media'
        buf=io.BytesIO(); Image.new('RGB',(48,32),(17,82,91)).save(buf,format='PNG')
        self.content=buf.getvalue()

    def app(self):
        return create_offline_document_app(self.path,
            current_user=lambda:(self.user,None) if self.user else (None,'denied'),
            load_org=lambda ident,user:({'id':ident},None) if ident in self.memberships else (None,'denied'))

    def upload(self,**changes):
        data=dict(file=(io.BytesIO(self.content),'product.png','image/png'),
                  rightsStatement='Authored test image with permission for marketing.',consentStatus='owner_asserted')
        data.update(changes)
        return self.client.post(self.root,data=data,content_type='multipart/form-data')

    def test_library_thumbnails_real_pixels_preserve_selection_originals_and_documents(self):
        import base64
        photo,video=self.batch().json['assets']
        before=self.client.get(self.root).json
        doc=self.client.get(self.docs+'/'+self.ident).json
        for asset,coverage in [(photo,'whole_photo_scaled'),(video,'first_frame_only')]:
            result=self.client.get(self.root+'/'+asset['assetId']+'/thumbnail')
            self.assertEqual(result.status_code,200,result.json)
            self.assertEqual(result.headers['Cache-Control'],'no-store')
            data=result.json;pixels=base64.b64decode(data['previewBase64'])
            self.assertEqual(data['sourceSha256'],asset['sourceSha256'])
            self.assertEqual(data['previewSha256'],hashlib.sha256(pixels).hexdigest())
            self.assertEqual(data['coverage'],coverage)
            self.assertFalse(data['approved']);self.assertFalse(data['canPublish'])
            with Image.open(io.BytesIO(pixels)) as image:
                self.assertEqual(image.size,(data['width'],data['height']))
                self.assertLessEqual(max(image.size),320)
                r,g,b=image.getpixel((0,0))
                if asset==photo:self.assertEqual((r,g,b),(17,82,91))
                else:self.assertTrue(b>200 and r<20 and g<20)
        self.assertEqual(self.client.get(self.root).json,before)
        self.assertEqual(self.client.get(self.docs+'/'+self.ident).json,doc)
        self.assertEqual(self.client.get(self.root+'/'+photo['assetId']+'/original').data,self.content)
        self.client=self.app().test_client()
        self.assertEqual(self.client.get(self.root+'/'+video['assetId']+'/thumbnail').status_code,200)

    def test_library_thumbnail_scope_integrity_withdrawal_and_permission_holds(self):
        asset=self.upload(consentStatus='not_confirmed').json['asset'];ident=asset['assetId']
        url=self.root+'/'+ident+'/thumbnail'
        response=self.client.get(url)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['consentStatus'],'not_confirmed')
        self.assertEqual(self.select([ident]).status_code,400)
        for user,memberships in [(None,{'org-a'}),({'id':'owner-b'},{'org-a'}),
                                  ({'id':'owner-a'},set())]:
            self.user=user;self.memberships=memberships
            denial=self.client.get(url,headers={'X-Clippr-Pilot':'local'})
            self.assertEqual(denial.status_code,403)
            self.assertNotIn('previewBase64',denial.json)
        self.user={'id':'owner-a'};self.memberships={'org-a','org-b'}
        self.assertEqual(self.client.get(url.replace('org-a','org-b')).status_code,403)
        self.assertEqual(self.client.get(self.root+'/missing-original/thumbnail').status_code,403)
        withdrawn=self.client.post(self.root+'/'+ident+'/withdraw-permission',json=dict(
            reason='Permission withdrawn for this authored test original.'))
        self.assertEqual(withdrawn.status_code,200)
        held=self.client.get(url)
        self.assertEqual(held.status_code,400);self.assertNotIn('previewBase64',held.json)
        other=self.upload(file=(io.BytesIO(self.content+b'x'),'different.png','image/png')).json['asset']['assetId']
        with sqlite3.connect(self.path) as con:
            con.execute('UPDATE business_asset_originals SET original_bytes=? WHERE asset_id=?',(b'changed',other))
        tampered=self.client.get(self.root+'/'+other+'/thumbnail')
        self.assertEqual(tampered.status_code,400);self.assertNotIn('previewBase64',tampered.json)

    def test_library_thumbnail_decode_failure_and_busy_render_fail_closed(self):
        from unittest.mock import patch
        import subprocess,business_campaign_assets as assets
        ident=self.video_upload().json['asset']['assetId'];url=self.root+'/'+ident+'/thumbnail'
        assets._video_preview_lock.acquire()
        try:
            busy=self.client.get(url)
            self.assertEqual(busy.status_code,400);self.assertNotIn('previewBase64',busy.json)
        finally:assets._video_preview_lock.release()
        with patch('business_asset_catalog.subprocess.run',side_effect=subprocess.TimeoutExpired('ffmpeg',5)):
            failed=self.client.get(url)
        self.assertEqual(failed.status_code,400);self.assertNotIn('previewBase64',failed.json)
        self.assertEqual(self.client.get(url).status_code,200)

    def test_library_photo_thumbnail_uses_display_orientation_without_copying_metadata(self):
        import base64
        original=io.BytesIO();exif=Image.Exif();exif[274]=6;exif[270]='Authored private fixture metadata'
        Image.new('RGB',(800,400),(100,50,20)).save(original,format='JPEG',exif=exif)
        content=original.getvalue()
        asset=self.upload(file=(io.BytesIO(content),'portrait.jpg','image/jpeg')).json['asset']
        result=self.client.get(self.root+'/'+asset['assetId']+'/thumbnail')
        self.assertEqual(result.status_code,200,result.json)
        with Image.open(io.BytesIO(base64.b64decode(result.json['previewBase64']))) as image:
            self.assertEqual(image.size,(160,320))
            self.assertFalse(image.getexif());self.assertNotIn('exif',image.info)
            self.assertTrue(all(abs(a-b)<4 for a,b in zip(image.getpixel((0,0)),(100,50,20))))
        self.assertEqual(self.client.get(self.root+'/'+asset['assetId']+'/original').data,content)

    def batch(self, files=None, **changes):
        data=dict(file=files if files is not None else [
            (io.BytesIO(self.content),'product.png','image/png'),
            (io.BytesIO(self.video_bytes),'studio.mp4','video/mp4')],
            rightsStatement='Authored test media; permission covers every file and subject.',
            consentStatus='owner_asserted')
        data.update(changes)
        return self.client.post(self.root,data=data,content_type='multipart/form-data')

    def test_batch_mixed_originals_reload_assign_edit_and_withdraw(self):
        before=self.client.get(self.docs+'/'+self.ident).json
        result=self.batch()
        self.assertEqual(result.status_code,201,result.json)
        self.assertFalse(result.json['hostedStorageVerified'])
        self.assertEqual(result.headers['Cache-Control'],'no-store')
        photo,video=result.json['assets']; ids=[photo['assetId'],video['assetId']]
        for asset,content in zip([photo,video],[self.content,self.video_bytes]):
            self.assertEqual(asset['sourceSha256'],hashlib.sha256(content).hexdigest())
            self.assertEqual(asset['sourceBytes'],len(content))
            self.assertFalse(asset['canPublish']);self.assertFalse(asset['verifiedRights'])
            self.assertEqual(self.client.get(self.root+'/'+asset['assetId']+'/original').data,content)
        self.client=self.app().test_client()
        self.assertEqual({a['assetId'] for a in self.client.get(self.root).json['assets']},set(ids))
        self.assertEqual(self.select(ids,postAssignments=[dict(day=1,assetIds=ids,
            photoCrops=[self.crop(ids[0])],videoEdits=[dict(assetId=ids[1],startMs=0,endMs=500,muted=True)])]).status_code,200)
        self.assertEqual(self.crop_preview(ids[0]).status_code,200)
        self.assertEqual(self.video_preview(ids[1]).status_code,200)
        self.assertEqual(self.client.get(self.docs+'/'+self.ident).json,before)
        self.client.post(self.root+'/'+ids[0]+'/withdraw-permission',json=dict(
            reason='Permission withdrawn for this authored test original.'))
        self.assertTrue(self.client.get(self.root).json['selection']['stale'])
        # Reimporting held bytes cannot reinstate permission under a fresh ID.
        held=self.batch().json['assets'][0]
        self.assertTrue(held['permissionWithdrawn'])
        self.assertEqual(self.select([held['assetId']],version=1).status_code,400)

    def retry_intake(self, key='c'*32, contents=None, **changes):
        data=dict(file=[(io.BytesIO(content),name,mime) for content,name,mime in
            (contents or [(self.content,'product.png','image/png'),
                          (self.video_bytes,'studio.mp4','video/mp4')])],
            rightsStatement='Authored test media; permission covers every file and subject.',
            consentStatus='owner_asserted')
        data.update(changes)
        return self.client.post(self.root,data=data,headers={'Idempotency-Key':key},
                                content_type='multipart/form-data')

    def test_retry_recovers_lost_response_after_restart_without_duplicates_or_selection_changes(self):
        ident,note=self.prepared_note()
        self.assertEqual(self.note(ident,note).status_code,200)
        before=self.client.get(self.root).json['selection']
        first=self.retry_intake()
        self.assertEqual(first.status_code,201,first.json)
        self.assertFalse(first.json['replayed'])
        self.client=self.app().test_client()
        retry=self.retry_intake()
        self.assertEqual(retry.status_code,200,retry.json)
        self.assertTrue(retry.json['replayed'])
        self.assertEqual(first.json['assets'],retry.json['assets'])
        library=self.client.get(self.root).json
        self.assertEqual(len(library['assets']),3)
        self.assertEqual(library['selection'],before)
        for asset,content in zip(retry.json['assets'],[self.content,self.video_bytes]):
            self.assertEqual(self.client.get(self.root+'/'+asset['assetId']+'/original').data,content)
        self.assertEqual(retry.headers['Cache-Control'],'no-store')

    def test_retry_conflicts_on_changed_bytes_order_name_mime_or_permission(self):
        first=self.retry_intake()
        self.assertEqual(first.status_code,201,first.json)
        photo=(self.content,'product.png','image/png');video=(self.video_bytes,'studio.mp4','video/mp4')
        for changes in [dict(contents=[video,photo]),
            dict(contents=[(self.content+b'x','product.png','image/png'),video]),
            dict(contents=[(self.content,'renamed.png','image/png'),video]),
            dict(contents=[(self.content,'product.png','image/jpeg'),video]),
            dict(rightsStatement='Different permission covering all of these originals.'),
            dict(consentStatus='not_confirmed')]:
            response=self.retry_intake(**changes)
            self.assertEqual(response.status_code,409,response.json)
            self.assertEqual(response.json['code'],'intake_conflict')
        self.assertEqual(len(self.client.get(self.root).json['assets']),2)

    def test_retry_rechecks_access_current_withdrawal_and_original_integrity(self):
        asset=self.retry_intake().json['assets'][0]
        self.client.post(self.root+'/'+asset['assetId']+'/withdraw-permission',json=dict(
            reason='Permission withdrawn for this authored test original.'))
        replay=self.retry_intake()
        self.assertEqual(replay.status_code,200,replay.json)
        self.assertTrue(replay.json['assets'][0]['permissionWithdrawn'])
        self.assertEqual(self.select([asset['assetId']]).status_code,400)
        for user,memberships in [(None,{'org-a'}),({'id':'owner-b'},{'org-a'}),
                                 ({'id':'owner-a'},set())]:
            self.user=user;self.memberships=memberships
            self.assertEqual(self.retry_intake().status_code,403)
        self.user={'id':'owner-a'};self.memberships={'org-a'}
        with sqlite3.connect(self.path) as con:
            con.execute('UPDATE business_asset_originals SET original_bytes=? WHERE asset_id=?',
                        (b'changed',asset['assetId']))
        self.assertEqual(self.retry_intake().status_code,400)

    def test_retry_failure_leaves_no_receipt_and_same_identity_can_be_corrected(self):
        files=[(self.content,'product.png','image/png'),(b'bad','studio.mp4','video/mp4')]
        self.assertEqual(self.retry_intake(contents=files).status_code,400)
        with sqlite3.connect(self.path) as con:
            for table in ['business_asset_intake_receipts','business_asset_originals','business_asset_catalog']:
                self.assertEqual(con.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(self.retry_intake().status_code,201)
        self.assertEqual(self.retry_intake(key='invalid').status_code,400)
        self.assertEqual(len(self.client.get(self.root).json['assets']),2)

    def test_retry_receipt_failure_rolls_back_originals_then_recovers_at_library_quota(self):
        with sqlite3.connect(self.path) as con:
            con.execute('''CREATE TRIGGER fail_receipt BEFORE INSERT ON business_asset_intake_receipts
                BEGIN SELECT RAISE(ABORT,'test receipt write failed'); END''')
        self.assertEqual(self.retry_intake().status_code,503)
        self.assertEqual(self.client.get(self.root).json['assets'],[])
        with sqlite3.connect(self.path) as con:
            con.execute('DROP TRIGGER fail_receipt')
        first=self.retry_intake()
        self.assertEqual(first.status_code,201,first.json)
        with sqlite3.connect(self.path) as con:
            con.executemany('INSERT INTO business_asset_originals VALUES(?,?,?,?,?)',
                [('org-a','org-a',f'quota-{i}','owner-a',self.content) for i in range(98)])
        replay=self.retry_intake()
        self.assertEqual(replay.status_code,200,replay.json)
        self.assertEqual(replay.json['assets'],first.json['assets'])
        self.assertEqual(self.retry_intake(key='d'*32).status_code,409)

    def test_retry_identity_is_document_scoped_and_unconfirmed_permission_stays_held(self):
        first=self.retry_intake(consentStatus='not_confirmed')
        self.assertEqual(first.status_code,201,first.json)
        replay=self.retry_intake(consentStatus='not_confirmed')
        self.assertEqual(replay.status_code,200,replay.json)
        ids=[a['assetId'] for a in replay.json['assets']]
        self.assertEqual(self.select(ids).status_code,400)
        self.assertTrue(all(a['usageStatus']=='held_rights_unconfirmed' for a in replay.json['assets']))
        other='e'*32
        payload={**self.payload,'id':other,'mutationId':'f'*32}
        self.assertEqual(self.client.post(self.docs,json=payload).status_code,200)
        self.root=self.docs+'/'+other+'/media'
        separate=self.retry_intake(consentStatus='not_confirmed')
        self.assertEqual(separate.status_code,201,separate.json)
        self.assertTrue(set(ids).isdisjoint(a['assetId'] for a in separate.json['assets']))

    def test_retry_substituted_or_invalid_receipt_is_held(self):
        import json
        first=self.retry_intake().json['assets']
        other=self.upload(file=(io.BytesIO(self.content),'different.png','image/png')).json['asset']
        for ids in [[other['assetId'],first[1]['assetId']],[],[first[0]['assetId']]*2,{'bad':'ids'}]:
            with sqlite3.connect(self.path) as con:
                con.execute('UPDATE business_asset_intake_receipts SET asset_ids=?',(json.dumps(ids),))
            self.assertEqual(self.retry_intake().status_code,400)
        self.assertEqual(len(self.client.get(self.root).json['assets']),3)

    def test_batch_five_photos_keep_order_and_existing_observation_current(self):
        ident,payload=self.prepared_note()
        self.assertEqual(self.note(ident,payload).status_code,200)
        before=self.client.get(self.root).json['selection']
        files=[];contents=[]
        for i in range(5):
            buf=io.BytesIO();Image.new('RGB',(48,32),(i*40,82,91)).save(buf,format='PNG')
            contents.append(buf.getvalue())
            files.append((io.BytesIO(contents[-1]),f'product-{i}.png','image/png'))
        result=self.batch(files=files)
        self.assertEqual(result.status_code,201,result.json)
        self.assertEqual([a['originalName'] for a in result.json['assets']],
                         [f'product-{i}.png' for i in range(5)])
        for asset,content in zip(result.json['assets'],contents):
            self.assertEqual(self.client.get(self.root+'/'+asset['assetId']+'/original').data,content)
        self.client=self.app().test_client()
        self.assertEqual(self.client.get(self.root).json['selection'],before)
        self.assertFalse(before['reviewNotes'][0]['stale'])
        self.assertEqual(self.crop_preview(ident).status_code,200)

    def test_batch_invalid_last_file_rolls_back_all_originals_and_metadata(self):
        first=self.upload().json['asset'];before=self.client.get(self.root).json
        result=self.batch(files=[(io.BytesIO(self.content),'valid.png','image/png'),
            (io.BytesIO(b'not an image'),'invalid.png','image/png')])
        self.assertEqual(result.status_code,400,result.json)
        self.assertIn('Original 2:',result.json['error'])
        self.assertEqual(self.client.get(self.root).json,before)
        with sqlite3.connect(self.path) as con:
            for table in ['business_asset_originals','business_asset_catalog']:
                self.assertEqual(con.execute('SELECT count(*) FROM '+table).fetchone()[0],1)
        self.assertEqual(self.client.get(self.root+'/'+first['assetId']+'/original').data,self.content)

    def test_batch_bounds_and_ambiguous_declarations_are_rejected_atomically(self):
        for changes in [dict(files=[(io.BytesIO(self.content),f'photo-{i}.png','image/png') for i in range(6)]),
                        dict(rightsStatement=['First declaration covers all originals.','Different permission declaration.']),
                        dict(consentStatus=['owner_asserted','not_confirmed']),
                        dict(ownerId='owner-a'),dict(organisationId='org-a')]:
            result=self.batch(**changes)
            self.assertEqual(result.status_code,400,result.json)
            self.assertEqual(self.client.get(self.root).json['assets'],[])
        # Below the HTTP envelope cap but above the aggregate original-byte cap.
        content=self.content+b'\0'*(7*1024*1024-200000-len(self.content))
        result=self.batch(files=[(io.BytesIO(content),f'large-{i}.png','image/png') for i in range(3)])
        self.assertEqual(result.status_code,400,result.json)
        self.assertEqual(self.client.get(self.root).json['assets'],[])

    def test_batch_denies_missing_auth_membership_foreign_owner_and_org(self):
        for user,memberships,path in [(None,{'org-a'},self.root),
            ({'id':'owner-b'},{'org-a'},self.root),
            ({'id':'owner-a'},set(),self.root),
            ({'id':'owner-a'},{'org-a','org-b'},self.root.replace('org-a','org-b'))]:
            self.user=user;self.memberships=memberships
            response=self.client.post(path,data=dict(file=[
                (io.BytesIO(self.content),'first.png','image/png'),
                (io.BytesIO(self.content),'second.png','image/png')],
                rightsStatement='Authored media with permission for all subjects.',consentStatus='owner_asserted'),
                headers={'X-Clippr-Pilot':'local-only'},content_type='multipart/form-data')
            self.assertEqual(response.status_code,403,response.json)
        self.user={'id':'owner-a'};self.memberships={'org-a'}
        self.assertEqual(self.client.get(self.root).json['assets'],[])

    def test_batch_quota_is_for_complete_set_and_unconfirmed_rights_stay_held(self):
        asset=self.upload().json['asset']
        with sqlite3.connect(self.path) as con:
            con.executemany('INSERT INTO business_asset_originals VALUES(?,?,?,?,?)',
                [('org-a','org-a',f'quota-{i}','owner-a',self.content) for i in range(98)])
        result=self.batch()
        self.assertEqual(result.status_code,409,result.json)
        self.assertEqual(result.json['code'],'storage_limit')
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM business_asset_originals').fetchone()[0],99)
            con.execute("DELETE FROM business_asset_originals WHERE asset_id LIKE 'quota-%'")
        result=self.batch(consentStatus='not_confirmed')
        self.assertEqual(result.status_code,201,result.json)
        ids=[a['assetId'] for a in result.json['assets']]
        self.assertTrue(all(a['usageStatus']=='held_rights_unconfirmed' for a in result.json['assets']))
        self.assertEqual(self.select(ids).status_code,400)
        self.assertEqual(self.client.get(self.root+'/'+asset['assetId']+'/original').data,self.content)

    def select(self,ids,revision=1,version=0,**extra):
        return self.client.put(self.root+'/selection',json=dict(revision=revision,selectionVersion=version,assetIds=ids,**extra))

    def crop(self,ident,**changes):
        return dict(assetId=ident,left=8,top=4,width=24,height=20,**changes)

    def crop_preview(self,ident,day=1,revision=1,version=1):
        return self.client.get(self.root+f'/posts/{day}/{ident}/photo-preview?revision={revision}&selectionVersion={version}')

    def video_preview(self,ident,day=1,revision=1,version=1):
        return self.client.get(self.root+f'/posts/{day}/{ident}/video-preview?revision={revision}&selectionVersion={version}')

    def whole_review(self,ident,day=1,version=1):
        return self.client.get(self.root+f'/posts/{day}/{ident}/original-review?revision=1&selectionVersion={version}')

    def test_whole_original_photo_video_notes_survive_recreation_without_edits(self):
        import base64
        for upload,content in [(self.upload,self.content),(self.video_upload,self.video_bytes)]:
            with self.subTest(media=upload.__name__):
                asset=upload().json['asset'];ident=asset['assetId']
                version=self.client.get(self.root).json['selection']['selectionVersion']
                self.assertEqual(self.select([ident],version=version,postAssignments=[
                    dict(day=1,assetIds=[ident]),dict(day=9,assetIds=[ident])]).status_code,200)
                result=self.whole_review(ident,version=version+1)
                self.assertEqual(result.status_code,200,result.json)
                self.assertEqual(result.headers['Cache-Control'],'no-store')
                preview=result.json
                self.assertEqual(base64.b64decode(preview['originalBase64']),content)
                self.assertEqual(preview['previewSha256'],asset['sourceSha256'])
                self.assertTrue(preview['wholeOriginal'])
                review_version=self.client.get(self.root).json['selection']['reviewVersion']
                payload=dict(revision=1,selectionVersion=version+1,reviewVersion=review_version,
                    receipt=preview['reviewReceipt'],outcome='needs_changes',
                    note='The whole original contains unrelated background; revise framing before use.')
                self.assertEqual(self.note(ident,payload,day=9).status_code,400)
                result=self.note(ident,payload)
                self.assertEqual(result.status_code,200,result.json)
                note=next(n for n in result.json['selection']['reviewNotes'] if n['assetId']==ident)
                self.assertEqual(note['candidateEdit'],dict(assetId=ident,wholeOriginal=True))
                self.assertFalse(note['approved']);self.assertFalse(note['canPublish']);self.assertFalse(note['stale'])
                self.client=self.app().test_client()
                loaded=self.client.get(self.root).json['selection']
                self.assertIn(note,loaded['reviewNotes'])
                self.assertEqual(loaded['postAssignments'][0],dict(day=1,assetIds=[ident]))
                self.assertEqual(self.client.get(self.root+'/'+ident+'/original').data,content)

    def test_whole_original_review_holds_edits_staleness_withdrawal_and_unassigned(self):
        ident=self.upload().json['asset']['assetId']
        self.assertEqual(self.whole_review(ident).status_code,409)
        self.select([ident],postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[self.crop(ident)])])
        self.assertEqual(self.whole_review(ident).status_code,400)
        self.assertEqual(self.select([ident],version=1,postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[])]).status_code,200)
        preview=self.whole_review(ident,version=2)
        self.assertEqual(preview.status_code,200,preview.json)
        self.assertEqual(self.whole_review(ident).status_code,409)
        self.assertEqual(self.whole_review(ident,day=9,version=2).status_code,400)
        payload=dict(revision=1,selectionVersion=2,reviewVersion=0,receipt=preview.json['reviewReceipt'],
            outcome='usable_candidate',note='The entire original is relevant but independent QC remains required.')
        self.assertEqual(self.note(ident,payload).status_code,200)
        self.client.post(self.root+'/'+ident+'/withdraw-permission',json=dict(reason='Permission withdrawn for this authored test original.'))
        self.assertEqual(self.whole_review(ident,version=2).status_code,409)
        self.assertEqual(self.note(ident,{**payload,'reviewVersion':1}).status_code,409)
        self.assertTrue(self.client.get(self.root).json['selection']['reviewNotes'][0]['stale'])

    def test_whole_original_review_denies_owner_membership_and_tampering(self):
        ident=self.upload().json['asset']['assetId']
        self.select([ident],postAssignments=[dict(day=1,assetIds=[ident])])
        before=self.client.get(self.root).json
        self.user={'id':'another-owner'}
        self.assertEqual(self.whole_review(ident).status_code,403)
        self.user=None
        self.assertEqual(self.whole_review(ident).status_code,403)
        self.user={'id':'owner-a'};self.memberships.clear()
        self.assertEqual(self.whole_review(ident).status_code,403)
        self.memberships={'org-a','org-b'}
        path=self.root.replace('org-a','org-b')+f'/posts/1/{ident}/original-review?revision=1&selectionVersion=1'
        self.assertEqual(self.client.get(path,headers={'X-Clippr-Pilot':'local'}).status_code,403)
        self.assertEqual(self.client.get(self.root).json,before)
        with sqlite3.connect(self.path) as con:
            con.execute('UPDATE business_asset_originals SET original_bytes=? WHERE asset_id=?',(b'tampered',ident))
        result=self.whole_review(ident)
        self.assertEqual(result.status_code,400);self.assertNotIn('originalBase64',result.json)

    def test_whole_original_receipt_rejects_changed_selection_calendar_and_signature(self):
        ident=self.upload().json['asset']['assetId']
        self.select([ident],postAssignments=[dict(day=1,assetIds=[ident])])
        preview=self.whole_review(ident).json
        payload=dict(revision=1,selectionVersion=1,reviewVersion=0,receipt=preview['reviewReceipt'],
            outcome='needs_changes',note='Remove unrelated background from the entire original before use.')
        self.assertEqual(self.note(ident,{**payload,'receipt':preview['reviewReceipt']+'forged'}).status_code,400)
        self.select([ident],version=1,postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[self.crop(ident)])])
        self.assertEqual(self.note(ident,payload).status_code,409)
        self.assertEqual(self.note(ident,{**payload,'selectionVersion':2}).status_code,400)
        self.assertEqual(self.client.get(self.root).json['selection']['reviewNotes'],[])
        edited=document();edited['posts'][0]['copyDraft']='Updated campaign copy requires a new media review.'
        self.assertEqual(self.client.post(self.docs,json=dict(id=self.ident,
            mutationId='c'*32,expectedRevision=1,document=edited)).status_code,200)
        self.assertEqual(self.whole_review(ident,version=2).status_code,409)

    def test_whole_video_review_rejects_saved_excerpt_without_rendering(self):
        ident=self.video_upload().json['asset']['assetId']
        self.assertEqual(self.select([ident],postAssignments=[dict(day=1,assetIds=[ident],videoEdits=[
            dict(assetId=ident,startMs=0,endMs=500,muted=True)])]).status_code,200)
        from unittest.mock import patch
        with patch('business_campaign_assets.video_excerpt_preview',side_effect=AssertionError('must not render')):
            self.assertEqual(self.whole_review(ident).status_code,400)

    def test_whole_original_request_can_be_answered_by_crop_and_reset(self):
        # Nonuniform pixels distinguish actual changed framing from a uniform crop.
        image=Image.new('RGB',(48,32),(17,82,91));image.putpixel((0,0),(240,0,0))
        buf=io.BytesIO();image.save(buf,format='PNG');self.content=buf.getvalue()
        ident=self.upload().json['asset']['assetId']
        self.select([ident],postAssignments=[dict(day=1,assetIds=[ident])])
        preview=self.whole_review(ident).json
        payload=dict(revision=1,selectionVersion=1,reviewVersion=0,receipt=preview['reviewReceipt'],
            outcome='needs_changes',note='Remove the unrelated left edge of the original before using this photo.')
        self.assertEqual(self.note(ident,payload).status_code,200)
        prior=self.client.get(self.root).json['selection']['reviewNotes'][0]
        self.select([ident],version=1,postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[self.crop(ident)])])
        crop=self.crop_preview(ident,version=2).json
        response=dict(observationSha256=prior['observationSha256'],changeSummary='Cropped away the left edge while retaining the subject.')
        result=self.note(ident,{**payload,'selectionVersion':2,'reviewVersion':1,'receipt':crop['reviewReceipt'],'revisionResponse':response})
        self.assertEqual(result.status_code,200,result.json)
        prior=result.json['selection']['reviewNotes'][0]
        self.select([ident],version=2,postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[])])
        whole=self.whole_review(ident,version=3).json
        response=dict(observationSha256=prior['observationSha256'],changeSummary='Reset to the whole original to restore the complete subject.')
        result=self.note(ident,{**payload,'selectionVersion':3,'reviewVersion':2,'receipt':whole['reviewReceipt'],'revisionResponse':response})
        self.assertEqual(result.status_code,200,result.json)
        self.assertTrue(result.json['selection']['reviewNotes'][0]['candidateEdit']['wholeOriginal'])

    def prepared_note(self):
        ident=self.upload().json['asset']['assetId']
        self.assertEqual(self.select([ident],postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[self.crop(ident)])]).status_code,200)
        preview=self.crop_preview(ident).json
        return ident,dict(revision=1,selectionVersion=1,reviewVersion=0,
            receipt=preview['reviewReceipt'],outcome='needs_changes',
            note='The product is visible; crop out the unrelated background before use.')

    def note(self,ident,payload,day=1):
        return self.client.put(self.root+f'/posts/{day}/{ident}/review-note',json=payload)

    def package(self,ident,day=1,**changes):
        selection=self.client.get(self.root).json['selection']
        note=next(n for n in selection['reviewNotes'] if n['assetId']==ident)
        query=dict(revision=1,selectionVersion=selection['selectionVersion'],
                   reviewVersion=selection['reviewVersion'],observationSha256=note['observationSha256'])
        query.update(changes)
        return self.client.get(self.root+f'/posts/{day}/{ident}/review-package',query_string=query)

    def unpack_package(self,result):
        import base64,json,zipfile
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.headers['Cache-Control'],'no-store')
        envelope=result.json;content=base64.b64decode(envelope['packageBase64'])
        self.assertEqual(len(content),envelope['packageBytes'])
        self.assertEqual(hashlib.sha256(content).hexdigest(),envelope['packageSha256'])
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest,envelope['manifest'])
            self.assertEqual(set(archive.namelist()),{manifest['candidateFile'],'manifest.json','REVIEW-NOT-APPROVED.txt'})
            candidate=archive.read(manifest['candidateFile'])
            self.assertIn(b'UNAPPROVED QC REVIEW COPY',archive.read('REVIEW-NOT-APPROVED.txt'))
        self.assertEqual(len(candidate),manifest['candidateBytes'])
        self.assertEqual(hashlib.sha256(candidate).hexdigest(),manifest['previewSha256'])
        for item in (envelope,manifest):
            for flag in ('approved','canSpend','canPublish','hostedStorageVerified'):self.assertIs(item[flag],False)
        self.assertTrue(manifest['requiresIndependentQC']);self.assertTrue(manifest['requiresOwnerApproval'])
        return manifest,candidate

    def test_qc_package_contains_exact_saved_crop_observation_context_and_no_mutations(self):
        ident,payload=self.prepared_note()
        self.assertEqual(self.note(ident,payload).status_code,200)
        before=self.client.get(self.root).json
        self.client=self.app().test_client()  # No ephemeral receipt required after saving the observation.
        response=self.package(ident)
        manifest,candidate=self.unpack_package(response)
        self.assertEqual(manifest['ownerObservation'],before['selection']['reviewNotes'][0])
        self.assertEqual(manifest['post'],before['posts'][0])
        self.assertEqual(manifest['candidateEdit'],self.crop(ident))
        self.assertEqual(manifest['rightsDeclaration']['statement'],before['assets'][0]['rightsStatement'])
        self.assertFalse(manifest['rightsDeclaration']['independentlyVerified'])
        self.assertFalse(manifest['containsOriginalMetadata'])
        with Image.open(io.BytesIO(candidate)) as image,Image.open(io.BytesIO(self.content)) as original:
            self.assertEqual(image.convert('RGB').tobytes(),original.crop((8,4,32,24)).tobytes())
        self.assertEqual(self.package(ident).json['packageSha256'],response.json['packageSha256'])
        self.assertEqual(self.client.get(self.root).json,before)
        self.assertEqual(self.client.get(self.root+'/'+ident+'/original').data,self.content)

    def test_qc_package_whole_original_and_revision_response_preserve_identity(self):
        # Nonuniform authored pixels make the changed crop an actual byte change.
        image=Image.new('RGB',(48,32),'red');image.paste('blue',(24,0,48,32))
        buf=io.BytesIO();image.save(buf,format='PNG');self.content=buf.getvalue()
        ident,previous,payload=self.revised_candidate()
        self.assertEqual(self.note(ident,payload).status_code,200)
        manifest,_=self.unpack_package(self.package(ident))
        self.assertEqual(manifest['ownerObservation']['revisionResponse']['previousObservation']['note'],previous['note'])
        self.assertEqual(manifest['ownerObservation']['revisionResponse']['changeSummary'],payload['revisionResponse']['changeSummary'])
        self.select([ident],version=2,postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[])])
        self.assertEqual(self.package(ident).status_code,409)
        preview=self.whole_review(ident,version=3).json
        self.assertEqual(self.note(ident,{k:v for k,v in dict(payload,selectionVersion=3,reviewVersion=2,
            receipt=preview['reviewReceipt']).items() if k!='revisionResponse'}).status_code,200)
        manifest,candidate=self.unpack_package(self.package(ident))
        self.assertEqual(candidate,self.content);self.assertTrue(manifest['containsOriginalMetadata'])

    def test_qc_package_rejects_missing_stale_wrong_day_versions_and_render_substitution(self):
        from unittest.mock import patch
        import business_campaign_assets as assets
        ident,payload=self.prepared_note()
        url=self.root+f'/posts/1/{ident}/review-package'
        self.assertEqual(self.client.get(url,query_string=dict(revision=1,selectionVersion=1,reviewVersion=0)).status_code,409)
        self.note(ident,payload)
        before=self.client.get(self.root).json
        for changes in [dict(revision=2),dict(selectionVersion=2),dict(reviewVersion=0),dict(observationSha256='f'*64),dict(day=9)]:
            self.assertIn(self.package(ident,**changes).status_code,(400,409))
        with patch.object(assets,'photo_crop_preview',return_value=(b'substituted',dict(previewSha256=before['selection']['reviewNotes'][0]['previewSha256']))):
            result=self.package(ident);self.assertEqual(result.status_code,400)
            self.assertNotIn('packageBase64',result.json)
        self.assertEqual(self.client.get(self.root).json,before)
        self.note(ident,{**payload,'reviewVersion':1,'note':'A replaced observation needs another independent review.'})
        self.assertEqual(self.package(ident,reviewVersion=1,
            observationSha256=before['selection']['reviewNotes'][0]['observationSha256']).status_code,409)
        changed={**self.payload,'expectedRevision':1,'mutationId':'c'*32,
                 'document':{**self.payload['document'],'goal':'bookings'}}
        self.assertEqual(self.client.post(self.docs,json=changed).status_code,200)
        self.assertEqual(self.package(ident,revision=2).status_code,409)

    def test_qc_package_denies_auth_membership_foreign_owner_withdrawal_and_tampering(self):
        ident,payload=self.prepared_note();self.note(ident,payload)
        selection=self.client.get(self.root).json['selection']
        query=dict(revision=1,selectionVersion=1,reviewVersion=1,
                   observationSha256=selection['reviewNotes'][0]['observationSha256'])
        url=self.root+f'/posts/1/{ident}/review-package'
        for user,root in [(None,self.root),({'id':'owner-b'},self.root),
                          ({'id':'owner-a'},self.root.replace('org-a','org-b'))]:
            self.user=user
            response=self.client.get(root+f'/posts/1/{ident}/review-package',query_string=query,
                                     headers={'X-Clippr-Pilot':'local-only'})
            self.assertEqual(response.status_code,403)
        self.user={'id':'owner-a'};self.memberships.clear()
        self.assertEqual(self.client.get(url,query_string=query).status_code,403)
        self.memberships={'org-a'}
        self.client.post(self.root+'/'+ident+'/withdraw-permission',json={'reason':'Owner withdrew this authored fixture from marketing use.'})
        response=self.client.get(url,query_string=query)
        self.assertIn(response.status_code,(400,409));self.assertNotIn('packageBase64',response.json)
        with sqlite3.connect(self.path) as con:
            con.execute('UPDATE business_asset_originals SET original_bytes=?',(b'tampered',))
        self.assertEqual(self.client.get(url,query_string=query).status_code,400)

    def test_qc_video_package_reuses_exact_rendered_interval_and_mute(self):
        ident=self.video_upload().json['asset']['assetId']
        edit=dict(assetId=ident,startMs=250,endMs=750,muted=True)
        self.assertEqual(self.select([ident],postAssignments=[dict(day=1,assetIds=[ident],videoEdits=[edit])]).status_code,200)
        preview=self.video_preview(ident).json
        payload=dict(revision=1,selectionVersion=1,reviewVersion=0,receipt=preview['reviewReceipt'],
            outcome='needs_changes',note='Review the saved interval and check framing before approving anything.')
        self.assertEqual(self.note(ident,payload).status_code,200)
        before=self.client.get(self.root).json
        manifest,candidate=self.unpack_package(self.package(ident))
        import base64
        self.assertEqual(candidate,base64.b64decode(preview['previewBase64']))
        self.assertEqual(manifest['candidateEdit'],edit);self.assertEqual(manifest['candidateFile'],'candidate.mp4')
        self.assertEqual(self.client.get(self.root).json,before)

    def post_package(self,day=1,**changes):
        selection=self.client.get(self.root).json['selection']
        query=dict(revision=1,selectionVersion=selection['selectionVersion'],reviewVersion=selection['reviewVersion'])
        return self.client.get(self.root+f'/posts/{day}/review-package',query_string={**query,**changes})

    def observed_post(self):
        photo=self.upload().json['asset']['assetId'];video=self.video_upload().json['asset']['assetId']
        edit=dict(assetId=video,startMs=250,endMs=750,muted=True)
        self.assertEqual(self.select([photo,video],postAssignments=[dict(day=1,assetIds=[video,photo],
            videoEdits=[edit]),dict(day=9,assetIds=[photo])]).status_code,200)
        previews=[self.video_preview(video).json,self.whole_review(photo).json]
        for version,(ident,preview) in enumerate(zip([video,photo],previews)):
            self.assertEqual(self.note(ident,dict(revision=1,selectionVersion=1,reviewVersion=version,
                receipt=preview['reviewReceipt'],outcome='needs_changes',
                note='Review this candidate in the context of the full post before approval.')).status_code,200)
        return photo,video,previews

    def static_post_setup(self,copy=None,graphic_text=None):
        doc=document()
        if copy is not None:doc['posts'][0]['copyDraft']=copy
        if graphic_text is not None:doc['posts'][0]['graphicText']=graphic_text
        doc['brandKit']=dict(name='Synthetic Workshop', primary_color='#123456',
            secondary_color='#FFFFFF',font_style='modern')
        self.assertEqual(self.client.post(self.docs,json=dict(self.payload,document=doc,
            expectedRevision=1,mutationId='c'*32)).status_code,200)
        asset=self.upload().json['asset']['assetId']
        self.assertEqual(self.select([asset],revision=2,postAssignments=[dict(day=1,assetIds=[asset])]).status_code,200)
        preview=self.client.get(self.root+f'/posts/1/{asset}/original-review?revision=2&selectionVersion=1').json
        self.assertEqual(self.note(asset,dict(revision=2,selectionVersion=1,reviewVersion=0,
            receipt=preview['reviewReceipt'],outcome='usable_candidate',
            note='Synthetic pixels are suitable for testing the static layout.')).status_code,200)
        query=dict(revision=2,selectionVersion=1,reviewVersion=1)
        return doc,asset,query

    def test_photo_carousel_saved_words_order_restart_and_exact_export(self):
        import base64, json, zipfile
        _,first,_=self.static_post_setup('Bicycle servicing at our workshop.')
        buffer=io.BytesIO();Image.new('RGB',(64,64),(220,120,60)).save(buffer,format='PNG')
        second=self.upload(file=(io.BytesIO(buffer.getvalue()),'second.png','image/png')).json['asset']['assetId']
        ids=[second,first]
        slides=[dict(assetId=ident,graphicText=words,callToAction='Ask about servicing')
            for ident,words in zip(ids,['Bicycle servicing','Plan your workshop visit'])]
        captions={'instagram':'Ask about bicycle servicing.\nContact our workshop.',
                  'linkedin':'Plan your next workshop visit.'}
        assignment=dict(day=1,assetIds=ids,carouselSlides=slides,carouselCaptions=captions)
        for invalid in ({'email':'No channel'}, {'instagram':''}, {'instagram':'x'*3001}, []):
            rejected=self.select(ids,revision=2,version=1,postAssignments=[dict(assignment,carouselCaptions=invalid)])
            self.assertEqual(rejected.status_code,400,rejected.json)
        result=self.select(ids,revision=2,version=1,postAssignments=[assignment])
        self.assertEqual(result.status_code,200,result.json)
        url=self.root+'/posts/1/carousel-preview'
        query=dict(revision=2,selectionVersion=2,reviewVersion=1)
        self.assertEqual(self.client.get(url,query_string=query).status_code,400)
        for ident in ids:
            selection=self.client.get(self.root).json['selection']
            observation=self.client.get(self.root+f'/posts/1/{ident}/original-review?revision=2&selectionVersion=2').json
            result=self.note(ident,dict(revision=2,selectionVersion=2,reviewVersion=selection['reviewVersion'],
                receipt=observation['reviewReceipt'],outcome='usable_candidate',note='Synthetic fixture for explicit carousel layout review.'))
            self.assertEqual(result.status_code,200,result.json)
        self.client=self.app().test_client()
        library=self.client.get(self.root).json
        self.assertEqual(library['selection']['postAssignments'][0],assignment)
        query['reviewVersion']=library['selection']['reviewVersion']
        response=self.client.get(url,query_string=query)
        self.assertEqual(response.status_code,200,response.json)
        data=response.json
        self.assertEqual([s['assetId'] for s in data['manifest']['slides']],ids)
        self.assertFalse(data['manifest']['canPublish'])
        package=self.client.get(url,query_string=dict(query,package='1'))
        self.assertEqual(package.status_code,200,package.json)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(package.json['packageBase64']))) as archive:
            self.assertEqual(json.loads(archive.read('manifest.json')),data['manifest'])
            self.assertEqual(data['manifest']['channelCaptions'],captions)
            handoff=archive.read('posting-handoff.txt').decode('utf-8')
            for caption in captions.values():self.assertIn(caption,handoff)
            self.assertIn('Nothing is scheduled or published.',handoff)
            self.assertLess(handoff.index('slide-01.png'),handoff.index('slide-02.png'))
            for slide,encoded in zip(data['manifest']['slides'],data['slidesBase64']):
                pixels=base64.b64decode(encoded)
                self.assertEqual(archive.read(slide['file']),pixels)
                self.assertEqual(hashlib.sha256(pixels).hexdigest(),slide['sha256'])
                with Image.open(io.BytesIO(pixels)) as image:self.assertEqual(image.size,(1080,1350))
        self.assertEqual(self.client.get(self.root).json,library)
        # A stale client cannot silently erase saved channel captions.
        missing=dict(assignment);missing.pop('carouselCaptions')
        self.assertEqual(self.select(ids,revision=2,version=2,postAssignments=[missing]).status_code,400)
        removed=self.select(ids,revision=2,version=2,postAssignments=[dict(assignment,carouselCaptions={})])
        self.assertEqual(removed.status_code,200,removed.json)
        self.assertEqual(removed.json['selection']['postAssignments'][0]['carouselCaptions'],{})
        self.assertEqual(self.client.get(self.root+'/'+first+'/original').data,self.content)
        self.assertEqual(self.client.get(url,query_string=dict(query,selectionVersion=1)).status_code,409)
        self.user={'id':'foreign-owner'}
        denied=self.client.get(url,query_string=query)
        self.assertEqual(denied.status_code,403)
        self.assertNotIn('slidesBase64',denied.json)

    def test_static_explicit_logo_survives_reopen_and_requires_current_observation(self):
        import base64
        _,photo,_=self.static_post_setup('Bicycle servicing at our workshop.')
        buffer=io.BytesIO();Image.new('RGBA',(200,100),(250,60,20,255)).save(buffer,format='PNG')
        logo=self.upload(file=(io.BytesIO(buffer.getvalue()),'logo.png','image/png')).json['asset']['assetId']
        assigned=dict(day=1,assetIds=[photo,logo],staticLogoAssetId=logo)
        result=self.select([photo,logo],revision=2,version=1,postAssignments=[assigned])
        self.assertEqual(result.status_code,200,result.json)
        query=dict(revision=2,selectionVersion=2,reviewVersion=1)
        url=self.root+'/posts/1/static-preview'
        self.assertEqual(self.client.get(url,query_string=query).status_code,400)
        for ident in (photo,logo):
            library=self.client.get(self.root).json
            preview=self.client.get(self.root+f'/posts/1/{ident}/original-review?revision=2&selectionVersion=2').json
            noted=self.note(ident,dict(revision=2,selectionVersion=2,
                reviewVersion=library['selection']['reviewVersion'],receipt=preview['reviewReceipt'],
                outcome='usable_candidate',note='Synthetic authorised pixels inspected for this exact role.'))
            self.assertEqual(noted.status_code,200,noted.json)
        query['reviewVersion']=self.client.get(self.root).json['selection']['reviewVersion']
        result=self.client.get(url,query_string=query)
        self.assertEqual(result.status_code,200,result.json)
        self.assertTrue(result.json['manifest']['logoIncluded'])
        self.assertEqual(result.json['manifest']['logoCandidate']['assetId'],logo)
        self.assertEqual(result.json['manifest']['candidates'][0]['assetId'],photo)
        self.client=self.app().test_client()
        self.assertEqual(self.client.get(self.root).json['selection']['postAssignments'],[assigned])
        self.assertEqual(self.client.get(url,query_string=query).json,result.json)
        self.client.post(self.root+'/'+logo+'/withdraw-permission',json=dict(reason='Withdraw synthetic logo permission.'))
        self.assertEqual(self.client.get(url,query_string=query).status_code,409)

    def test_static_logo_selection_rejects_unassigned_cropped_and_silent_removal(self):
        _,photo,_=self.static_post_setup('Bicycle servicing at our workshop.')
        buffer=io.BytesIO();Image.new('RGBA',(200,100),(250,60,20,255)).save(buffer,format='PNG')
        logo=self.upload(file=(io.BytesIO(buffer.getvalue()),'logo.png','image/png')).json['asset']['assetId']
        original=self.client.get(self.root).json
        for invalid in (None,[],42,'f'*32):
            result=self.select([photo,logo],revision=2,version=1,
                postAssignments=[dict(day=1,assetIds=[photo,logo],staticLogoAssetId=invalid)])
            self.assertEqual(result.status_code,400,result.json)
            self.assertEqual(self.client.get(self.root).json,original)
        cropped=dict(day=1,assetIds=[photo,logo],staticLogoAssetId=logo,
            photoCrops=[dict(assetId=logo,left=0,top=0,width=100,height=100)])
        self.assertEqual(self.select([photo,logo],revision=2,version=1,postAssignments=[cropped]).status_code,400)
        assigned=dict(day=1,assetIds=[photo,logo],staticLogoAssetId=logo)
        self.assertEqual(self.select([photo,logo],revision=2,version=1,postAssignments=[assigned]).status_code,200)
        before=self.client.get(self.root).json
        # An older client must not silently strip an owner’s saved role choice.
        self.assertEqual(self.select([photo,logo],revision=2,version=2,
            postAssignments=[dict(day=1,assetIds=[photo,logo])]).status_code,400)
        self.assertEqual(self.client.get(self.root).json,before)
        removed=self.select([photo,logo],revision=2,version=2,
            postAssignments=[dict(assigned,staticLogoAssetId='')])
        self.assertEqual(removed.status_code,200,removed.json)
        self.assertEqual(removed.json['selection']['postAssignments'][0]['staticLogoAssetId'],'')

    def test_static_saved_post_renders_reopens_and_keeps_source_and_holds(self):
        import base64
        doc,asset,query=self.static_post_setup()
        url=self.root+'/posts/1/static-preview'
        before=self.client.get(self.root).json
        result=self.client.get(url,query_string=query)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.headers['Cache-Control'],'no-store')
        data=result.json;m=data['manifest'];content=base64.b64decode(data['previewBase64'])
        self.assertEqual(m['previewSha256'],hashlib.sha256(content).hexdigest())
        self.assertEqual(m['brandKit'],doc['brandKit'])
        self.assertEqual(m['post']['copyDraft'],'Original copy')
        self.assertFalse(m['approved']);self.assertFalse(m['canPublish']);self.assertFalse(m['logoIncluded'])
        with Image.open(io.BytesIO(content)) as image:
            self.assertEqual(image.size,(1080,1350))
            self.assertEqual(image.getpixel((540,400))[:3],(17,82,91))
            self.assertFalse(image.getexif())
        self.client=self.app().test_client()
        self.assertEqual(self.client.get(url,query_string=query).json,data)
        self.assertEqual(self.client.get(self.root).json,before)
        self.assertEqual(self.client.get(self.root+'/'+asset+'/original').data,self.content)
        self.assertEqual(self.client.get(url,query_string=dict(query,revision=1)).status_code,409)
        self.user={'id':'owner-b'}
        self.assertEqual(self.client.get(url,query_string=query).status_code,403)
        self.user={'id':'owner-a'};self.memberships=set()
        self.assertEqual(self.client.get(url,query_string=query).status_code,403)
        self.memberships={'org-a'}
        self.client.post(self.root+'/'+asset+'/withdraw-permission',json=dict(reason='Withdraw the synthetic source permission.'))
        self.assertEqual(self.client.get(url,query_string=query).status_code,409)

    def test_static_graphic_words_preserve_long_caption_across_reopen_and_render(self):
        caption='Bring your bicycle to our workshop for servicing. '*40
        words='Bicycle servicing at our workshop.'
        doc,asset,query=self.static_post_setup(caption,graphic_text=words)
        url=self.root+'/posts/1/static-preview'
        result=self.client.get(url,query_string=query)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['manifest']['layout']['copy'],words)
        self.assertEqual(result.json['manifest']['post']['copyDraft'],caption)
        self.assertEqual(result.json['manifest']['post']['graphicText'],words)
        self.client=self.app().test_client()
        reopened=self.client.get(self.docs+'/'+self.ident).json['document']
        self.assertEqual(reopened['posts'][0]['copyDraft'],caption)
        self.assertEqual(reopened['posts'][0]['graphicText'],words)
        self.assertEqual(self.client.get(url,query_string=query).json,result.json)

    def test_static_graphic_planning_notes_are_held(self):
        _,_,query=self.static_post_setup('Bicycle servicing at our workshop.',
            graphic_text='Draft direction: Show bicycle servicing')
        result=self.client.get(self.root+'/posts/1/static-preview',query_string=query)
        self.assertEqual(result.status_code,400,result.json)
        self.assertNotIn('previewBase64',result.json)

    def test_static_post_holds_internal_notes_and_questions_before_rendering(self):
        from unittest.mock import patch
        from business_brand_render import compose_static_post
        self.static_post_setup('Draft direction: Explain bicycle servicing')
        with patch('business_brand_render.compose_static_post',wraps=compose_static_post) as render:
            result=self.client.get(self.root+'/posts/1/static-preview',query_string=dict(
                revision=2,selectionVersion=1,reviewVersion=1))
            self.assertEqual(result.status_code,400,result.json)
            self.assertIn('post words',result.json['error'].lower())
            render.assert_not_called()

    def composition(self,day=1,**changes):
        library=self.client.get(self.root).json
        query=dict(revision=library['revision'],selectionVersion=library['selection']['selectionVersion'],
                   reviewVersion=library['selection']['reviewVersion'])
        return self.client.get(self.root+f'/posts/{day}/composition-preview',query_string={**query,**changes})

    def test_composed_saved_post_actual_bytes_pixels_timeline_and_customer_loader(self):
        import base64,json,subprocess
        photo,video,_=self.observed_post()
        before=self.client.get(self.root).json;doc=self.client.get(self.docs+'/'+self.ident).json
        response=self.composition()
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        result=response.json;m=result['manifest'];content=base64.b64decode(result['previewBase64'])
        self.assertEqual(m['previewSha256'],hashlib.sha256(content).hexdigest())
        self.assertEqual(m['audioPolicy'],'silent_review');self.assertFalse(m['approved'])
        self.assertFalse(m['canSpend']);self.assertFalse(m['canPublish'])
        self.assertEqual(m['timeline'],[dict(assetId=video,startFrame=0,endFrame=12),
                                      dict(assetId=photo,startFrame=12,endFrame=84)])
        target=Path(self.tmp.name)/'composed.mp4';target.write_bytes(content)
        import business_asset_catalog as catalog
        info=catalog.probe_offline_video(target)
        self.assertEqual([s['codec_type'] for s in info['streams']],['video'])
        self.assertAlmostEqual(float(info['format']['duration']),3.5,places=2)
        # Inspect real encoded pixels at two distinct times, including the black
        # letterbox border. No creative-quality verdict is inferred.
        for seconds,expected in [(0.1,(0,0,255)),(1.0,(17,82,91))]:
            frame=subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-ss',str(seconds),
                '-i',str(target),'-frames:v','1','-threads','1','-f','image2pipe','-vcodec','png','-'],
                capture_output=True,check=True,timeout=15).stdout
            with Image.open(io.BytesIO(frame)) as pixels:
                self.assertEqual(pixels.size,(720,1280))
                self.assertTrue(all(abs(a-b)<12 for a,b in zip(pixels.getpixel((360,640)),expected)))
                self.assertTrue(max(pixels.getpixel((0,0)))<12)
        script="""import {loadSavedPostComposition} from './src/lib/businessOriginalReview.mjs';
          import {createHash} from 'node:crypto';import {readFileSync} from 'node:fs';
          const d=JSON.parse(readFileSync(0,'utf8'));
          const result=await loadSavedPostComposition(d.library,1,async p=>p?d.result:d.current);
          process.stdout.write(createHash('sha256').update(Buffer.from(await result.blob.arrayBuffer())).digest('hex'));"""
        loaded=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(dict(
            library=before,current=self.client.get(self.root).json,result=result)),text=True,capture_output=True,timeout=15)
        self.assertEqual(loaded.returncode,0,loaded.stderr);self.assertEqual(loaded.stdout,m['previewSha256'])
        self.assertEqual(self.client.get(self.root).json,before)
        self.assertEqual(self.client.get(self.docs+'/'+self.ident).json,doc)
        self.assertEqual(self.client.get(self.root+'/'+photo+'/original').data,self.content)
        self.assertEqual(self.client.get(self.root+'/'+video+'/original').data,self.video_bytes)
        self.client=self.app().test_client()
        self.assertEqual(self.composition().status_code,200)

    def test_saved_audio_composition_exact_excerpt_silence_and_customer_loader(self):
        import base64,json,subprocess,array,math
        photo=self.upload().json['asset']['assetId']
        video=self.video_upload().json['asset']['assetId']
        # Exercise saved audio and a mute revision; the same original is intact.
        for version,muted in enumerate((False,True),1):
            edit=dict(assetId=video,startMs=250,endMs=750,muted=muted)
            current=self.client.get(self.root).json['selection']
            self.assertEqual(self.select([photo,video],version=current['selectionVersion'],
                postAssignments=[dict(day=1,assetIds=[photo,video],videoEdits=[edit])]).status_code,200)
            previews=[self.whole_review(photo,version=version).json,self.video_preview(video,version=version).json]
            for ident,preview in zip((photo,video),previews):
                current=self.client.get(self.root).json['selection']
                self.assertEqual(self.note(ident,dict(revision=1,selectionVersion=version,
                    reviewVersion=current['reviewVersion'],receipt=preview['reviewReceipt'],
                    outcome='usable_candidate',note='Authored source is ready for complete sequence listening.')).status_code,200)
            before=self.client.get(self.root).json
            response=self.composition(audioPolicy='saved_candidate_audio')
            self.assertEqual(response.status_code,200,response.json)
            m=response.json['manifest']
            self.assertEqual(m['audioPolicy'],'saved_candidate_audio')
            self.assertEqual([t['hasAudio'] for t in m['timeline']],[False,not muted])
            target=Path(self.tmp.name)/'audio-composition.mp4'
            target.write_bytes(base64.b64decode(response.json['previewBase64']))
            import business_asset_catalog as catalog
            info=catalog.probe_offline_video(target)
            self.assertEqual(any(s['codec_type']=='audio' for s in info['streams']),not muted)
            self.assertAlmostEqual(float(info['format']['duration']),3.5,delta=.125)
            if not muted:
                # Real decoded samples prove the tone stays after the photo;
                # encoder padding must neither shift it nor leak into silence.
                for start,expected_tone in ((.2,False),(3.1,True)):
                    raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(target),
                        '-ss',str(start),'-t','0.2','-map','0:a:0','-ac','1','-ar','48000',
                        '-f','s16le','-'],capture_output=True,check=True,timeout=10).stdout
                    samples=array.array('h',raw)
                    rms=math.sqrt(sum(v*v for v in samples)/len(samples))
                    self.assertGreater(rms,1000) if expected_tone else self.assertLess(rms,10)
            script="""import {loadSavedPostComposition} from './src/lib/businessOriginalReview.mjs';
              import {readFileSync} from 'node:fs';const d=JSON.parse(readFileSync(0,'utf8'));
              const r=await loadSavedPostComposition(d.library,1,async p=>p?d.result:d.library,
                ()=>true,'saved_candidate_audio');process.stdout.write(String(r.blob.size));"""
            loaded=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(dict(
                library=before,result=response.json)),text=True,capture_output=True,timeout=15)
            self.assertEqual(loaded.returncode,0,loaded.stderr)
            self.assertEqual(int(loaded.stdout),m['previewBytes'])
            self.assertEqual(self.client.get(self.root).json,before)
            self.assertEqual(self.client.get(self.root+'/'+video+'/original').data,self.video_bytes)
        self.client=self.app().test_client()
        self.assertEqual(self.composition(audioPolicy='saved_candidate_audio').status_code,200)

    def test_saved_audio_mixed_muted_and_missing_tracks_do_not_shift_timeline(self):
        import subprocess,base64,array,math
        photo=self.upload().json['asset']['assetId']
        audible=self.video_upload().json['asset']['assetId']
        muted=self.video_upload().json['asset']['assetId']
        no_audio=Path(self.tmp.name)/'no-audio.mp4'
        source=Path(self.tmp.name)/'source.mp4';source.write_bytes(self.video_bytes)
        subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(source),'-map','0:v:0',
            '-c:v','copy','-an',str(no_audio)],capture_output=True,check=True,timeout=10)
        silent=self.video_upload(no_audio.read_bytes()).json['asset']['assetId']
        ids=[photo,audible,muted,silent]
        edits=[dict(assetId=ident,startMs=250,endMs=750,muted=ident==muted)
               for ident in ids[1:]]
        self.assertEqual(self.select(ids,postAssignments=[dict(day=1,assetIds=ids,videoEdits=edits)]).status_code,200)
        for version,ident in enumerate(ids):
            preview=(self.whole_review(ident) if ident==photo else self.video_preview(ident)).json
            self.assertEqual(self.note(ident,dict(revision=1,selectionVersion=1,reviewVersion=version,
                receipt=preview['reviewReceipt'],outcome='usable_candidate',
                note='Authored sequence retained for offline audio boundary verification.')).status_code,200)
        result=self.composition(audioPolicy='saved_candidate_audio')
        self.assertEqual(result.status_code,200,result.json)
        manifest=result.json['manifest']
        self.assertEqual([t['hasAudio'] for t in manifest['timeline']],[False,True,False,False])
        self.assertEqual([t['endFrame'] for t in manifest['timeline']],[72,84,96,108])
        target=Path(self.tmp.name)/'mixed.mp4';target.write_bytes(base64.b64decode(result.json['previewBase64']))
        for start,tone in ((.2,False),(3.1,True),(3.6,False),(4.1,False)):
            raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(target),'-ss',str(start),
                '-t','0.2','-map','0:a:0','-ac','1','-ar','48000','-f','s16le','-'],
                capture_output=True,check=True,timeout=10).stdout
            values=array.array('h',raw);rms=math.sqrt(sum(v*v for v in values)/len(values))
            self.assertGreater(rms,1000) if tone else self.assertLess(rms,10)
        self.assertEqual(self.client.get(self.root+'/'+silent+'/original').data,no_audio.read_bytes())

    def test_saved_audio_preserves_leading_silence_in_whole_original(self):
        import subprocess,base64,array,math
        photo=self.upload().json['asset']['assetId']
        source=Path(self.tmp.name)/'delayed-audio.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
            'color=c=blue:s=160x160:r=24:d=1.5','-itsoffset','0.75','-f','lavfi',
            '-i','sine=frequency=440:sample_rate=48000:duration=0.75',
            '-map','0:v:0','-map','1:a:0','-c:v','libx264','-threads','1',
            '-pix_fmt','yuv420p','-c:a','aac',str(source)],
            capture_output=True,check=True,timeout=15)
        original=source.read_bytes()
        video=self.video_upload(original).json['asset']['assetId']
        ids=[photo,video]
        self.assertEqual(self.select(ids,postAssignments=[dict(day=1,assetIds=ids)]).status_code,200)
        for version,ident in enumerate(ids):
            preview=self.whole_review(ident).json
            self.assertEqual(self.note(ident,dict(revision=1,selectionVersion=1,
                reviewVersion=version,receipt=preview['reviewReceipt'],outcome='usable_candidate',
                note='Synthetic source has intentional leading silence before its tone.')).status_code,200)
        before=self.client.get(self.root).json
        # Missing timestamps must produce a recoverable held render, never a
        # guessed offset or server error; the following real render can retry.
        from unittest.mock import patch
        import business_asset_catalog as catalog
        probe=catalog.probe_offline_video
        def missing_timestamp(path):
            info=probe(path)
            for stream in info['streams']:
                stream.pop('start_time',None)
            return info
        with patch.object(catalog,'probe_offline_video',side_effect=missing_timestamp):
            held=self.composition(audioPolicy='saved_candidate_audio')
            self.assertEqual(held.status_code,400,held.json)
            self.assertNotIn('previewBase64',held.json)
        result=self.composition(audioPolicy='saved_candidate_audio')
        self.assertEqual(result.status_code,200,result.json)
        target=Path(self.tmp.name)/'delayed-composed.mp4'
        target.write_bytes(base64.b64decode(result.json['previewBase64']))
        # Decode on the video timeline, filling a delayed audio stream's initial
        # gap. Resetting each audio stream to STARTPTS incorrectly advances tone.
        def rms_at(path,start):
            raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(path),
                '-af','aresample=48000:async=1:first_pts=0','-ss',str(start),'-t','0.15',
                '-map','0:a:0','-ac','1','-ar','48000','-f','s16le','-'],
                capture_output=True,check=True,timeout=10).stdout
            samples=array.array('h',raw)
            self.assertGreater(len(samples),6000)
            return math.sqrt(sum(v*v for v in samples)/len(samples))
        self.assertLess(rms_at(source,.15),10)
        self.assertGreater(rms_at(source,1.05),1000)
        self.assertLess(rms_at(target,3.15),10)
        self.assertGreater(rms_at(target,4.05),1000)
        self.assertEqual(result.json['manifest']['timeline'],[
            dict(assetId=photo,startFrame=0,endFrame=72,hasAudio=False),
            dict(assetId=video,startFrame=72,endFrame=108,hasAudio=True)])
        self.assertEqual(self.client.get(self.root).json,before)
        self.assertEqual(self.client.get(self.root+'/'+video+'/original').data,original)

    def test_saved_excerpts_preserve_silent_intervals_before_and_after_source_audio(self):
        import subprocess,base64,array,math
        source=Path(self.tmp.name)/'short-delayed-tone.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
            'color=c=blue:s=160x160:r=24:d=2','-itsoffset','0.75','-f','lavfi',
            '-i','sine=frequency=440:sample_rate=48000:duration=0.5',
            '-map','0:v:0','-map','1:a:0','-c:v','libx264','-threads','1',
            '-pix_fmt','yuv420p','-c:a','aac',str(source)],
            capture_output=True,check=True,timeout=15)
        original=source.read_bytes()
        video=self.video_upload(original).json['asset']['assetId']
        # Both silent regions and a region crossing the delayed tone must be
        # reviewable without changing the owner's saved mute/excerpt choices.
        for version,(start,end,checks) in enumerate([
                (0,500,[(.1,False)]),
                (500,1250,[(.05,False),(.4,True)]),
                (1500,2000,[(.1,False)])],1):
            with self.subTest(start=start,end=end):
                before=self.client.get(self.root).json
                edit=dict(assetId=video,startMs=start,endMs=end,muted=False)
                self.assertEqual(self.select([video],version=before['selection']['selectionVersion'],
                    postAssignments=[dict(day=1,assetIds=[video],videoEdits=[edit])]).status_code,200)
                preview=self.video_preview(video,version=version)
                self.assertEqual(preview.status_code,200,preview.json)
                data=preview.json
                self.assertEqual(data['edit'],edit)
                self.assertTrue(data['hasAudio'])
                target=Path(self.tmp.name)/f'excerpt-{start}.mp4'
                target.write_bytes(base64.b64decode(data['previewBase64']))
                selection=self.client.get(self.root).json['selection']
                self.assertEqual(self.note(video,dict(revision=1,selectionVersion=version,
                    reviewVersion=selection['reviewVersion'],receipt=data['reviewReceipt'],
                    outcome='usable_candidate',note='Synthetic silent interval and delayed tone for local review.')).status_code,200)
                library=self.client.get(self.root).json
                result=self.composition(audioPolicy='saved_candidate_audio')
                self.assertEqual(result.status_code,200,result.json)
                composed=Path(self.tmp.name)/f'composed-{start}.mp4'
                composed.write_bytes(base64.b64decode(result.json['previewBase64']))
                self.assertEqual(result.json['manifest']['timeline'],[
                    dict(assetId=video,startFrame=0,endFrame=round((end-start)*24/1000),hasAudio=True)])
                for output in (target,composed):
                    for offset,tone in checks:
                        raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(output),
                            '-ss',str(offset),'-t','0.1','-map','0:a:0','-ac','1',
                            '-ar','48000','-f','s16le','-'],
                            capture_output=True,check=True,timeout=10).stdout
                        samples=array.array('h',raw)
                        self.assertGreater(len(samples),4000)
                        rms=math.sqrt(sum(v*v for v in samples)/len(samples))
                        self.assertGreater(rms,1000) if tone else self.assertLess(rms,10)
                self.assertEqual(self.client.get(self.root).json,library)
                self.assertEqual(self.client.get(self.root+'/'+video+'/original').data,original)

    def test_excerpt_uses_first_video_frame_when_audio_starts_earlier(self):
        import subprocess,base64,array
        source=Path(self.tmp.name)/'early-audio.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-itsoffset','0.5',
            '-f','lavfi','-i','color=c=blue:s=160x160:r=24:d=1',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=0.25',
            '-map','0:v:0','-map','1:a:0','-fps_mode','passthrough',
            '-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-c:a','aac',str(source)],
            capture_output=True,check=True,timeout=15)
        import business_asset_catalog as catalog
        info=catalog.probe_offline_video(source)
        video_stream=next(s for s in info['streams'] if s['codec_type']=='video')
        self.assertAlmostEqual(float(video_stream['start_time']),.5,places=2)
        original=source.read_bytes()
        ident=self.video_upload(original).json['asset']['assetId']
        edit=dict(assetId=ident,startMs=0,endMs=500,muted=False)
        self.assertEqual(self.select([ident],postAssignments=[dict(day=1,
            assetIds=[ident],videoEdits=[edit])]).status_code,200)
        before=self.client.get(self.root).json
        from unittest.mock import patch
        probe=catalog.probe_offline_video
        def missing_timestamp(path):
            metadata=probe(path)
            metadata['format'].pop('start_time',None)
            return metadata
        with patch.object(catalog,'probe_offline_video',side_effect=missing_timestamp):
            held=self.video_preview(ident)
            self.assertEqual(held.status_code,400,held.json)
            self.assertNotIn('previewBase64',held.json)
        self.assertEqual(self.client.get(self.root).json,before)
        result=self.video_preview(ident)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['edit'],edit)
        self.assertAlmostEqual(result.json['durationMs'],500,delta=50)
        target=Path(self.tmp.name)/'video-origin-excerpt.mp4'
        target.write_bytes(base64.b64decode(result.json['previewBase64']))
        raw=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(target),
            '-ss','0.1','-t','0.2','-map','0:a:0','-ac','1','-ar','48000',
            '-f','s16le','-'],capture_output=True,check=True,timeout=10).stdout
        samples=array.array('h',raw)
        self.assertGreater(len(samples),8000)
        self.assertLess(max(abs(v) for v in samples),10)
        pixels=subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(target),
            '-ss','0.1','-frames:v','1','-f','image2pipe','-vcodec','png','-'],
            capture_output=True,check=True,timeout=10).stdout
        with Image.open(io.BytesIO(pixels)) as image:
            self.assertEqual(image.size,(160,160))
            r,g,b=image.getpixel((80,80))
            self.assertGreater(b,240);self.assertLess(r+g,15)
        self.assertEqual(self.client.get(self.root).json,before)
        self.assertEqual(self.client.get(self.root+'/'+ident+'/original').data,original)

    def test_saved_audio_policy_denied_before_render_and_mute_changes_stale_observations(self):
        from unittest.mock import patch
        photo,video,_=self.observed_post()
        with patch('business_reel_workbench._render_cut') as render:
            self.assertEqual(self.composition(audioPolicy='invented').status_code,400)
            self.user=None
            self.assertEqual(self.client.get(self.root+'/posts/1/composition-preview?audioPolicy=saved_candidate_audio').status_code,403)
            self.user={'id':'owner-a'}
            edit=dict(assetId=video,startMs=250,endMs=750,muted=False)
            self.assertEqual(self.select([photo,video],version=1,postAssignments=[dict(
                day=1,assetIds=[video,photo],videoEdits=[edit])]).status_code,200)
            self.assertEqual(self.composition(audioPolicy='saved_candidate_audio').status_code,400)
            render.assert_not_called()

    def test_composition_scope_stale_permission_observation_and_hash_holds(self):
        from unittest.mock import patch
        photo,video,_=self.observed_post()
        url=self.root+'/posts/1/composition-preview?revision=1&selectionVersion=1&reviewVersion=2'
        with patch('business_reel_workbench._render_cut') as render:
            for user,orgs in [(None,{'org-a'}),({'id':'owner-b'},{'org-a'}),({'id':'owner-a'},set())]:
                self.user=user;self.memberships=orgs
                denied=self.client.get(url,headers={'X-Clippr-Pilot':'local'})
                self.assertEqual(denied.status_code,403);self.assertNotIn('previewBase64',denied.json)
            self.user={'id':'owner-a'};self.memberships={'org-a','org-b'}
            self.assertEqual(self.client.get(url.replace('org-a','org-b')).status_code,403)
            self.assertEqual(self.composition(revision=2).status_code,409)
            self.assertEqual(self.composition(reviewVersion=1).status_code,409)
            self.assertEqual(self.composition(day=9).status_code,400) # no observation for this day
            self.client.post(self.root+'/'+photo+'/withdraw-permission',json=dict(reason='Withdraw this synthetic owned fixture.'))
            held=self.composition();self.assertEqual(held.status_code,409)
            render.assert_not_called()
        # Separate genuine byte-integrity hold, without a withdrawal masking it.
        with sqlite3.connect(self.path) as con:
            con.execute('DELETE FROM business_asset_withdrawals')
            con.execute('UPDATE business_asset_originals SET original_bytes=? WHERE asset_id=?',(b'changed',photo))
        held=self.client.get(url)
        self.assertEqual(held.status_code,400);self.assertNotIn('previewBase64',held.json)

    def test_composition_crop_requires_fresh_observations_and_render_failure_releases_lock(self):
        import subprocess
        from unittest.mock import patch
        import business_campaign_assets as assets
        import business_reel_workbench as reel
        photo,video,_=self.observed_post()
        assignment=self.client.get(self.root).json['selection']['postAssignments'][0]
        assignment['photoCrops']=[self.crop(photo)]
        self.assertEqual(self.select([photo,video],version=1,postAssignments=[assignment]).status_code,200)
        self.assertEqual(self.composition().status_code,400)
        for rv,(ident,preview) in enumerate([(video,self.video_preview(video,version=2).json),
                (photo,self.crop_preview(photo,version=2).json)],2):
            self.assertEqual(self.note(ident,dict(revision=1,selectionVersion=2,reviewVersion=rv,
                receipt=preview['reviewReceipt'],outcome='needs_changes',
                note='Check the revised framing in the complete silent sequence.')).status_code,200)
        before=self.client.get(self.root).json
        with patch('business_reel_workbench._render_cut',side_effect=reel.ReelError('failed')):
            failed=self.composition();self.assertEqual(failed.status_code,400)
            self.assertNotIn('previewBase64',failed.json)
        self.assertFalse(assets._video_preview_lock.locked())
        rendered=self.composition();self.assertEqual(rendered.status_code,200,rendered.json)
        self.assertEqual(rendered.json['manifest']['candidates'][1]['candidateEdit'],self.crop(photo))
        self.assertEqual(self.client.get(self.root).json,before)

    def test_composition_whole_video_duration_and_unsuitable_holds_before_renderer(self):
        import subprocess
        from unittest.mock import patch
        target=Path(self.tmp.name)/'long.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
            'color=c=green:s=160x160:r=2:d=31','-c:v','libx264','-threads','1',
            '-pix_fmt','yuv420p',str(target)],check=True,capture_output=True,timeout=15)
        ident=self.video_upload(content=target.read_bytes()).json['asset']['assetId']
        self.assertEqual(self.select([ident],postAssignments=[dict(day=1,assetIds=[ident])]).status_code,200)
        preview=self.whole_review(ident).json
        payload=dict(revision=1,selectionVersion=1,reviewVersion=0,receipt=preview['reviewReceipt'],
            outcome='needs_changes',note='Choose a shorter saved excerpt before composing the complete post.')
        self.assertEqual(self.note(ident,payload).status_code,200)
        before=self.client.get(self.root).json
        with patch('business_reel_workbench._render_cut') as render:
            held=self.composition();self.assertEqual(held.status_code,400)
            self.assertIn('30 seconds',held.json['error']);render.assert_not_called()
        payload.update(reviewVersion=1,outcome='unsuitable')
        self.assertEqual(self.note(ident,payload).status_code,200)
        with patch('business_reel_workbench._render_cut') as render:
            held=self.composition();self.assertEqual(held.status_code,400);render.assert_not_called()
        self.assertEqual(self.client.get(self.docs+'/'+self.ident).json['revision'],1)

    def test_composition_five_photos_preserves_alpha_and_busy_lock_holds(self):
        import base64
        from unittest.mock import patch
        import business_campaign_assets as assets
        import business_reel_workbench as reel
        originals=[]
        for index in range(5):
            buf=io.BytesIO()
            with Image.new('RGBA',(48,32),(255,0,0,0) if index==0 else (17,82,91,255)) as image:
                image.save(buf,format='PNG')
            originals.append(self.upload(file=(io.BytesIO(buf.getvalue()),f'photo-{index}.png','image/png')).json['asset']['assetId'])
        self.assertEqual(self.select(originals,postAssignments=[dict(day=1,assetIds=originals)]).status_code,200)
        for rv,ident in enumerate(originals):
            preview=self.whole_review(ident).json
            self.assertEqual(self.note(ident,dict(revision=1,selectionVersion=1,reviewVersion=rv,
                receipt=preview['reviewReceipt'],outcome='needs_changes',
                note='Review these authored photos together before a final creative decision.')).status_code,200)
        before=self.client.get(self.root).json
        assets._video_preview_lock.acquire()
        try:
            held=self.composition();self.assertEqual(held.status_code,400)
            self.assertNotIn('previewBase64',held.json)
        finally:assets._video_preview_lock.release()
        render=reel._render_cut
        def checked(paths,output,**kwargs):
            self.assertEqual(len(paths),5);self.assertTrue(kwargs['catalogue_review'])
            with Image.open(paths[0][1]) as pixels:
                self.assertEqual(pixels.getpixel((24,16)),(0,0,0))
                self.assertEqual(pixels.info,{})
            return render(paths,output,**kwargs)
        with patch('business_reel_workbench._render_cut',side_effect=checked):
            response=self.composition();self.assertEqual(response.status_code,200,response.json)
        m=response.json['manifest']
        self.assertEqual(m['durationMs'],15000)
        self.assertEqual([t['assetId'] for t in m['timeline']],originals)
        self.assertEqual([t['endFrame'] for t in m['timeline']],[72,144,216,288,360])
        self.assertEqual(self.client.get(self.root).json,before)

    def test_saved_post_editor_loads_actual_ordered_crops_excerpts_notes_and_whole_original(self):
        import json,subprocess
        photo,video,_=self.observed_post()
        original_document=self.client.get(self.docs+'/'+self.ident).json
        assignments=self.client.get(self.root).json['selection']['postAssignments']
        assignments[0]['photoCrops']=[self.crop(photo)]
        self.assertEqual(self.select([photo,video],version=1,postAssignments=assignments).status_code,200)
        self.client=self.app().test_client()
        library=self.client.get(self.root).json
        responses={}
        for day,ident,kind in [(1,video,'video-preview'),(1,photo,'photo-preview'),(9,photo,'original-review')]:
            path=f'/posts/{day}/{ident}/{kind}?revision=1&selectionVersion=2'
            response=self.client.get(self.root+path)
            self.assertEqual(response.status_code,200,response.json)
            responses[path]=response.json
        # Run the exact customer loader on responses from actual scoped routes;
        # no socket server, duplicate renderer or forged authentication contract.
        script="""import {loadSavedPostReview} from './src/lib/businessOriginalReview.mjs';
          import {createHash} from 'node:crypto';
          import {readFileSync} from 'node:fs';
          const data=JSON.parse(readFileSync(0,'utf8')),calls=[];
          const request=async path=>{calls.push(path);return path?data.responses[path]:data.current;};
          const result=await loadSavedPostReview(data.library,data.day,request);
          const candidates=await Promise.all(result.candidates.map(async c=>({
            assetId:c.asset.assetId,mimeType:c.blob.type,
            hash:createHash('sha256').update(Buffer.from(await c.blob.arrayBuffer())).digest('hex'),
            previewSha256:c.previewSha256,observation:c.observation,crop:c.crop,edit:c.edit})));
          process.stdout.write(JSON.stringify({post:result.post,candidates,calls}));"""
        def load(day,current):
            return subprocess.run(['node','--input-type=module','-e',script],
                input=json.dumps(dict(library=library,responses=responses,current=current,day=day)),
                cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=15)
        result=load(1,library)
        self.assertEqual(result.returncode,0,result.stderr)
        rendered=json.loads(result.stdout)
        self.assertEqual([c['assetId'] for c in rendered['candidates']],[video,photo])
        self.assertEqual([c['mimeType'] for c in rendered['candidates']],['video/mp4','image/png'])
        self.assertEqual(rendered['post'],library['posts'][0])
        self.assertEqual(rendered['calls'][-1],'')
        for candidate in rendered['candidates']:
            self.assertEqual(candidate['hash'],candidate['previewSha256'])
            self.assertEqual(candidate['observation']['outcome'],'needs_changes')
            self.assertTrue(candidate['observation']['stale'])
        self.assertEqual(rendered['candidates'][1]['crop'],self.crop(photo))
        whole=load(9,library)
        self.assertEqual(whole.returncode,0,whole.stderr)
        self.assertEqual(json.loads(whole.stdout)['candidates'][0]['hash'],hashlib.sha256(self.content).hexdigest())
        self.assertEqual(self.client.get(self.root).json,library)
        self.assertEqual(self.client.get(self.docs+'/'+self.ident).json,original_document)
        self.assertEqual(self.client.get(self.root+'/'+photo+'/original').data,self.content)
        self.assertEqual(self.client.get(self.root+'/'+video+'/original').data,self.video_bytes)
        # Withdrawal between the individual reads and final recheck holds the
        # whole screen, even when all previously fetched bytes still hash.
        self.client.post(self.root+'/'+photo+'/withdraw-permission',json=dict(
            reason='Permission withdrawn for this authored review fixture.'))
        rejected=load(1,self.client.get(self.root).json)
        self.assertNotEqual(rejected.returncode,0)
        self.assertIn('Saved post changed or media permission is held',rejected.stderr)

    def test_customer_sequence_edit_reload_invalidates_observations_and_packages_new_order(self):
        import base64,json,subprocess,zipfile
        photo,video,previews=self.observed_post()
        before=self.client.get(self.root).json
        document_before=self.client.get(self.docs+'/'+self.ident).json
        assignments=before['selection']['postAssignments']
        # Exercise the customer editor helper, then the existing authenticated
        # save/reload/observe/package path. No parallel persistence contract.
        script="""import {movePostMedia} from './src/lib/businessOriginalReview.mjs';
          const [ids,id]=JSON.parse(process.argv[1]);
          process.stdout.write(JSON.stringify(movePostMedia(ids,id,-1)));"""
        result=subprocess.run(['node','--input-type=module','-e',script,json.dumps([[video,photo],photo])],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10,check=True)
        assignments[0]['assetIds']=json.loads(result.stdout)
        response=self.select([photo,video],version=1,postAssignments=assignments)
        self.assertEqual(response.status_code,200,response.json)
        self.client=self.app().test_client()
        saved=self.client.get(self.root).json['selection']
        self.assertEqual(saved['postAssignments'],assignments)
        self.assertTrue(all(n['stale'] for n in saved['reviewNotes']))
        self.assertEqual(self.post_package(selectionVersion=2).status_code,400)
        # An old preview receipt cannot bless the rearranged sequence.
        old_note=dict(revision=1,selectionVersion=2,reviewVersion=2,
            receipt=previews[1]['reviewReceipt'],outcome='usable_candidate',
            note='Inspect the subject in the new sequence before independent QC.')
        self.assertNotEqual(self.note(photo,old_note).status_code,200)
        self.assertEqual(self.select([photo,video],version=1,postAssignments=assignments).status_code,409)
        for review_version,ident in enumerate([photo,video],2):
            preview=(self.whole_review(ident,version=2) if ident==photo else
                self.video_preview(ident,version=2)).json
            response=self.note(ident,dict(old_note,receipt=preview['reviewReceipt'],reviewVersion=review_version))
            self.assertEqual(response.status_code,200,response.json)
        package=self.post_package(selectionVersion=2,reviewVersion=4)
        self.assertEqual(package.status_code,200,package.json)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(package.json['packageBase64']))) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual([c['assetId'] for c in manifest['candidates']],[photo,video])
            self.assertEqual(archive.read('media/01/candidate.png'),self.content)
            self.assertEqual(archive.read('media/02/candidate.mp4'),base64.b64decode(previews[0]['previewBase64']))
            self.assertFalse(manifest['approved']);self.assertFalse(manifest['canPublish'])
            self.assertNotEqual(manifest['assignmentSha256'],before['selection']['reviewNotes'][0]['assignmentSha256'])
        self.assertEqual(self.client.get(self.docs+'/'+self.ident).json,document_before)
        self.assertEqual(self.client.get(self.root+'/'+photo+'/original').data,self.content)
        self.assertEqual(self.client.get(self.root+'/'+video+'/original').data,self.video_bytes)

    def test_post_qc_package_all_media_in_order_exact_bytes_reload_and_no_writes(self):
        import base64,json,zipfile
        photo,video,previews=self.observed_post()
        before=self.client.get(self.root).json
        self.client=self.app().test_client()
        result=self.post_package();self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.headers['Cache-Control'],'no-store')
        raw=base64.b64decode(result.json['packageBase64'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(),result.json['packageSha256'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest=json.loads(archive.read('manifest.json'));self.assertEqual(manifest,result.json['manifest'])
            self.assertEqual(manifest['post'],before['posts'][0])
            self.assertEqual([c['assetId'] for c in manifest['candidates']],[video,photo])
            self.assertEqual(set(archive.namelist()),{'manifest.json','REVIEW-NOT-APPROVED.txt','REVIEW.html',
                'media/01/candidate.mp4','media/02/candidate.png'})
            page=archive.read('REVIEW.html')
            self.assertEqual(manifest['reviewPage'],dict(file='REVIEW.html',bytes=len(page),sha256=hashlib.sha256(page).hexdigest()))
            self.assertIn(b'<video controls preload="none" src="media/01/candidate.mp4">',page)
            self.assertIn(b'<img src="media/02/candidate.png"',page)
            self.assertLess(page.index(b'id="candidate-1"'),page.index(b'id="candidate-2"'))
            self.assertIn(b'original metadata is retained',page)
            self.assertEqual(archive.read('media/01/candidate.mp4'),base64.b64decode(previews[0]['previewBase64']))
            self.assertEqual(archive.read('media/02/candidate.png'),self.content)
            for candidate in manifest['candidates']:
                self.assertEqual(hashlib.sha256(archive.read(candidate['candidateFile'])).hexdigest(),candidate['previewSha256'])
                self.assertEqual(candidate['ownerObservation']['outcome'],'needs_changes')
                self.assertFalse(candidate['approved']);self.assertFalse(candidate['canPublish'])
            self.assertTrue(manifest['containsOriginalMetadata'])
            self.assertTrue(manifest['requiresIndependentQC']);self.assertTrue(manifest['requiresOwnerApproval'])
            self.assertFalse(manifest['approved']);self.assertFalse(manifest['canPublish'])
        self.assertEqual(self.client.get(self.root).json,before)
        self.assertEqual(self.client.get(self.root+'/'+photo+'/original').data,self.content)
        self.assertEqual(self.client.get(self.root+'/'+video+'/original').data,self.video_bytes)
        # Day 9 has no observation; day 1 observations cannot be replayed for it.
        self.assertEqual(self.post_package(day=9).status_code,400)

    def test_post_qc_package_five_cropped_photos_and_resaving_stales_entire_handoff(self):
        import base64,json,zipfile
        ids=[]
        for color in ['red','green','blue','yellow','purple']:
            image=Image.new('RGB',(48,32),color);buf=io.BytesIO();image.save(buf,format='PNG')
            self.content=buf.getvalue();ids.append(self.upload().json['asset']['assetId'])
        assignment=dict(day=1,assetIds=ids,photoCrops=[self.crop(ident) for ident in ids])
        self.assertEqual(self.select(ids,postAssignments=[assignment]).status_code,200)
        for version,ident in enumerate(ids):
            preview=self.crop_preview(ident).json
            self.assertEqual(self.note(ident,dict(revision=1,selectionVersion=1,reviewVersion=version,
                receipt=preview['reviewReceipt'],outcome='usable_candidate',
                note='The saved framing keeps the subject visible; independent QC remains required.')).status_code,200)
        result=self.post_package();self.assertEqual(result.status_code,200,result.json)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result.json['packageBase64']))) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(len(archive.namelist()),8);self.assertFalse(manifest['containsOriginalMetadata'])
            for ident,candidate in zip(ids,manifest['candidates']):
                self.assertEqual(candidate['assetId'],ident)
                self.assertEqual(candidate['candidateEdit'],self.crop(ident))
                with Image.open(io.BytesIO(archive.read(candidate['candidateFile']))) as image:
                    self.assertEqual(image.size,(24,20))
        self.assertEqual(self.select(ids,version=1,postAssignments=[assignment]).status_code,200)
        self.assertEqual(self.post_package().status_code,400)  # Resave requires new observations.

    def test_post_review_page_owner_text_is_inert_and_only_packaged_media_loads(self):
        import base64,html,json,zipfile
        from html.parser import HTMLParser
        class Page(HTMLParser):
            def __init__(self):
                super().__init__();self.tags=[];self.text=[]
            def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))
            def handle_data(self,data):self.text.append(data)
        attack='Inspect <script>alert(1)</script><img src="https://example.org/leak" onerror="alert(2)"> & the actual framing.'
        ident,payload=self.prepared_note()
        self.assertEqual(self.note(ident,{**payload,'note':attack}).status_code,200)
        before=self.client.get(self.root).json
        result=self.post_package();self.assertEqual(result.status_code,200,result.json)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result.json['packageBase64']))) as archive:
            manifest=json.loads(archive.read('manifest.json'));page=archive.read('REVIEW.html').decode()
            parsed=Page();parsed.feed(page)
            self.assertIn(attack,''.join(parsed.text))
            self.assertNotIn('script',[tag for tag,_ in parsed.tags])
            self.assertNotIn('form',[tag for tag,_ in parsed.tags])
            self.assertEqual([attrs['src'] for _,attrs in parsed.tags if 'src' in attrs],['media/01/candidate.png'])
            self.assertTrue(all(value.startswith('#candidate-') for _,attrs in parsed.tags for key,value in attrs.items() if key=='href'))
            policy=next(attrs['content'] for tag,attrs in parsed.tags if tag=='meta' and attrs.get('http-equiv')=='Content-Security-Policy')
            for rule in ["default-src 'none'","script-src 'none'","connect-src 'none'","form-action 'none'","base-uri 'none'"]:
                self.assertIn(rule,policy)
            self.assertIn('This page records no decisions.',page)
            self.assertIn(manifest['candidates'][0]['previewSha256'],page)
            # Other owner-controlled fields, including URLs, also stay inert.
            from business_campaign_assets import _post_review_page,CampaignAssetError
            manifest['post']['copyDraft']=attack;manifest['candidates'][0]['rightsDeclaration']['statement']=attack
            escaped=_post_review_page(manifest).decode()
            self.assertEqual(escaped.count(html.escape(attack,quote=True)),3)
            for path in ['https://example.org/file','../candidate.png','media/01/candidate.svg']:
                manifest['candidates'][0]['candidateFile']=path
                with self.assertRaises(CampaignAssetError):_post_review_page(manifest)
        self.assertEqual(self.client.get(self.root).json,before)

    def test_post_review_page_includes_current_edit_and_immediate_revision_request(self):
        import base64,html,zipfile
        image=Image.new('RGB',(48,32),'red');image.paste('blue',(24,0,48,32))
        buf=io.BytesIO();image.save(buf,format='PNG');self.content=buf.getvalue()
        ident,previous,payload=self.revised_candidate()
        self.assertEqual(self.note(ident,payload).status_code,200)
        result=self.post_package();self.assertEqual(result.status_code,200,result.json)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result.json['packageBase64']))) as archive:
            page=archive.read('REVIEW.html').decode()
            for text in [previous['note'],payload['note'],payload['revisionResponse']['changeSummary'],
                         previous['previewSha256'],'previous media is not included']:
                self.assertIn(html.escape(text,quote=True),page)
            self.assertIn('Independent assessment still needed',page)
            self.assertFalse(result.json['approved'])

    def test_post_qc_package_requires_every_observation_before_any_render(self):
        from unittest.mock import patch
        ident,payload=self.prepared_note()
        other=self.upload().json['asset']['assetId']
        self.select([ident,other],version=1,postAssignments=[dict(day=1,assetIds=[ident,other],photoCrops=[self.crop(ident)])])
        preview=self.crop_preview(ident,version=2).json
        self.assertEqual(self.note(ident,{**payload,'selectionVersion':2,'receipt':preview['reviewReceipt']}).status_code,200)
        with patch('business_campaign_assets._review_candidate',side_effect=AssertionError('must preflight complete set')):
            result=self.post_package();self.assertEqual(result.status_code,400,result.json)
        self.assertNotIn('packageBase64',result.json)

    def test_post_qc_package_rejects_stale_versions_calendar_selection_and_observation(self):
        photo,video,_=self.observed_post()
        for changes in [dict(revision=2),dict(selectionVersion=0),dict(reviewVersion=1)]:
            self.assertEqual(self.post_package(**changes).status_code,409)
        self.assertEqual(self.post_package(day=30).status_code,400)
        # A replacement observation changes the review version even with identical media.
        preview=self.whole_review(photo).json
        self.note(photo,dict(revision=1,selectionVersion=1,reviewVersion=2,receipt=preview['reviewReceipt'],
            outcome='unsuitable',note='This original does not support the intended post and needs replacement.'))
        self.assertEqual(self.post_package(reviewVersion=2).status_code,409)
        self.assertEqual(self.post_package().status_code,200)
        changed=document();changed['posts'][0]['copyDraft']='Revised context requires another observation.'
        self.assertEqual(self.client.post(self.docs,json=dict(id=self.ident,mutationId='c'*32,
            expectedRevision=1,document=changed)).status_code,200)
        self.assertEqual(self.post_package(revision=2).status_code,409)

    def test_post_qc_package_denies_scope_membership_permission_and_tampering(self):
        photo,_,_=self.observed_post();url=self.root+'/posts/1/review-package'
        query=dict(revision=1,selectionVersion=1,reviewVersion=2)
        for user,root in [(None,self.root),({'id':'other-owner'},self.root),
                          ({'id':'owner-a'},self.root.replace('org-a','org-b'))]:
            self.user=user
            result=self.client.get(root+'/posts/1/review-package',query_string=query,headers={'X-Clippr-Pilot':'local'})
            self.assertEqual(result.status_code,403);self.assertNotIn('packageBase64',result.json)
        self.user={'id':'owner-a'};self.memberships.clear()
        self.assertEqual(self.client.get(url,query_string=query).status_code,403)
        self.memberships={'org-a'}
        self.client.post(self.root+'/'+photo+'/withdraw-permission',json=dict(reason='Withdraw permission for the entire saved photo.'))
        result=self.client.get(url,query_string=query);self.assertEqual(result.status_code,409)
        with sqlite3.connect(self.path) as con:
            con.execute('UPDATE business_asset_originals SET original_bytes=? WHERE asset_id=?',(b'tampered',photo))
        self.assertEqual(self.client.get(url,query_string=query).status_code,400)

    def test_post_qc_package_render_substitution_or_oversize_never_returns_partial_zip(self):
        from unittest.mock import patch
        import business_campaign_assets as assets
        self.observed_post();before=self.client.get(self.root).json
        with patch.object(assets,'video_excerpt_preview',return_value=(b'substituted',dict(previewSha256='a'*64))):
            result=self.post_package();self.assertEqual(result.status_code,400)
            self.assertNotIn('packageBase64',result.json)
        with patch.object(assets,'POST_REVIEW_LIMIT',10):
            result=self.post_package();self.assertEqual(result.status_code,400)
            self.assertNotIn('packageBase64',result.json)
        self.assertEqual(self.client.get(self.root).json,before)

    def revised_candidate(self):
        ident,payload=self.prepared_note()
        self.assertEqual(self.note(ident,payload).status_code,200)
        previous=self.client.get(self.root).json['selection']['reviewNotes'][0]
        crop={**self.crop(ident),'left':12,'width':20}
        self.assertEqual(self.select([ident],version=1,postAssignments=[
            dict(day=1,assetIds=[ident],photoCrops=[crop])]).status_code,200)
        preview=self.crop_preview(ident,version=2).json
        response={**payload,'selectionVersion':2,'reviewVersion':1,'receipt':preview['reviewReceipt'],
            'outcome':'usable_candidate','note':'The revised framing retains the product; independent QC is still needed.',
            'revisionResponse':dict(observationSha256=previous['observationSha256'],
                changeSummary='Moved the left edge inward and reduced width to exclude the background.')}
        return ident,previous,response

    def test_targeted_revision_retains_request_and_new_preview_without_approval(self):
        ident,previous,payload=self.revised_candidate()
        result=self.note(ident,payload)
        self.assertEqual(result.status_code,200,result.json)
        note=result.json['selection']['reviewNotes'][0]
        response=note['revisionResponse']
        self.assertEqual(response['observationSha256'],previous['observationSha256'])
        self.assertEqual(response['previousObservation']['note'],previous['note'])
        self.assertEqual(response['previousObservation']['previewSha256'],previous['previewSha256'])
        self.assertEqual(response['previousObservation']['candidateEdit'],self.crop(ident))
        self.assertEqual(note['candidateEdit']['width'],20)
        self.assertNotEqual(note['assignmentSha256'],previous['assignmentSha256'])
        self.assertNotEqual(note['previewSha256'],previous['previewSha256'])
        self.assertEqual(note['sourceSha256'],previous['sourceSha256'])
        self.assertFalse(note['stale']);self.assertFalse(note['approved'])
        self.assertFalse(note['canSpend']);self.assertFalse(note['canPublish'])
        self.client=self.app().test_client()
        self.assertEqual(self.client.get(self.root).json['selection']['reviewNotes'][0],note)
        self.assertEqual(self.client.get(self.root+'/'+ident+'/original').data,self.content)
        self.assertEqual(self.select([ident],version=2,postAssignments=[
            dict(day=1,assetIds=[ident],photoCrops=[])]).status_code,200)
        stale=self.client.get(self.root).json['selection']['reviewNotes'][0]
        self.assertTrue(stale['stale']);self.assertEqual(stale['revisionResponse'],response)

    def test_revision_response_denies_forged_requests_identity_and_malformed_changes(self):
        ident,previous,payload=self.revised_candidate()
        before=self.client.get(self.root).json
        for value in [None,{},dict(observationSha256='f'*64,changeSummary='Changed the crop boundaries for review.'),
                      {**payload['revisionResponse'],'changeSummary':'done'},
                      {**payload['revisionResponse'],'changeSummary':'x'*1001},
                      {**payload['revisionResponse'],'changeSummary':'x'*25+'\x00'},
                      {**payload['revisionResponse'],'approved':True}]:
            self.assertEqual(self.note(ident,{**payload,'revisionResponse':value}).status_code,400)
        self.assertEqual(self.note(ident,payload,day=9).status_code,400)
        self.user={'id':'other-owner'}
        self.assertEqual(self.note(ident,payload).status_code,403)
        self.user=None
        self.assertEqual(self.note(ident,payload).status_code,403)
        self.user={'id':'owner-a'};self.memberships.clear()
        self.assertEqual(self.note(ident,payload).status_code,403)
        self.memberships={'org-a','org-b'}
        self.assertEqual(self.client.put(self.root.replace('org-a','org-b')+f'/posts/1/{ident}/review-note',json=payload).status_code,403)
        self.assertEqual(self.client.get(self.root).json,before)
        # A concurrent replacement cannot be answered using the earlier request hash.
        replacement={k:v for k,v in payload.items() if k!='revisionResponse'}
        self.assertEqual(self.note(ident,replacement).status_code,200)
        self.assertEqual(self.note(ident,{**payload,'reviewVersion':2}).status_code,400)

    def test_revision_requires_changed_assignment_and_pixels_not_just_resaving(self):
        ident,payload=self.prepared_note()
        self.assertEqual(self.note(ident,payload).status_code,200)
        previous=self.client.get(self.root).json['selection']['reviewNotes'][0]
        response=dict(observationSha256=previous['observationSha256'],changeSummary='Claimed change without a different saved edit.')
        self.assertEqual(self.note(ident,{**payload,'reviewVersion':1,'revisionResponse':response}).status_code,400)
        for version,crop in [(1,self.crop(ident)),(2,{**self.crop(ident),'left':10})]:
            # Uniform fixture pixels: shifting alone changes instructions but not rendered bytes.
            self.assertEqual(self.select([ident],version=version,postAssignments=[
                dict(day=1,assetIds=[ident],photoCrops=[crop])]).status_code,200)
            preview=self.crop_preview(ident,version=version+1).json
            candidate={**payload,'reviewVersion':1,'selectionVersion':version+1,
                       'receipt':preview['reviewReceipt'],'revisionResponse':response}
            self.assertEqual(self.note(ident,candidate).status_code,400)

    def test_revision_response_rolls_back_and_withdrawal_holds(self):
        from unittest.mock import patch
        import business_campaign_assets as assets
        ident,previous,payload=self.revised_candidate()
        original=assets.saved_selection;calls=0
        def fail_response(*args):
            nonlocal calls
            calls+=1
            if calls==3:raise assets.CampaignAssetError('Response failed')
            return original(*args)
        with patch.object(assets,'saved_selection',side_effect=fail_response):
            self.assertEqual(self.note(ident,payload).status_code,400)
        self.assertEqual(self.client.get(self.root).json['selection']['reviewVersion'],1)
        self.assertEqual(self.client.post(self.root+'/'+ident+'/withdraw-permission',json={
            'reason':'Permission withdrawn for the authored revision fixture.'}).status_code,200)
        self.assertEqual(self.note(ident,payload).status_code,409)

    def test_revision_response_cannot_carry_request_across_changed_calendar(self):
        ident,previous,payload=self.revised_candidate()
        updated={**self.payload,'mutationId':'c'*32,'expectedRevision':1,
                 'document':{**self.payload['document'],'goal':'bookings'}}
        self.assertEqual(self.client.post(self.docs,json=updated).status_code,200)
        crop={**self.crop(ident),'left':12,'width':20}
        self.assertEqual(self.select([ident],revision=2,version=2,postAssignments=[
            dict(day=1,assetIds=[ident],photoCrops=[crop])]).status_code,200)
        preview=self.crop_preview(ident,revision=2,version=3).json
        payload.update(revision=2,selectionVersion=3,receipt=preview['reviewReceipt'])
        self.assertEqual(self.note(ident,payload).status_code,400)
        self.assertEqual(self.client.get(self.root).json['selection']['reviewVersion'],1)

    def test_video_revision_response_preserves_exact_old_and_new_excerpt(self):
        ident=self.video_upload().json['asset']['assetId']
        edit=dict(assetId=ident,startMs=0,endMs=500,muted=False)
        assignments=[dict(day=1,assetIds=[ident],videoEdits=[edit]),dict(day=9,assetIds=[ident],videoEdits=[edit])]
        self.assertEqual(self.select([ident],postAssignments=assignments).status_code,200)
        preview=self.video_preview(ident).json
        payload=dict(revision=1,selectionVersion=1,reviewVersion=0,receipt=preview['reviewReceipt'],
            outcome='needs_changes',note='Shorten the interval and remove audio before further assessment.')
        self.assertEqual(self.note(ident,payload).status_code,200)
        previous=self.client.get(self.root).json['selection']['reviewNotes'][0]
        changed={**edit,'endMs':250,'muted':True}
        assignments[0]['videoEdits']=[changed]
        self.assertEqual(self.select([ident],version=1,postAssignments=assignments).status_code,200)
        preview=self.video_preview(ident,version=2).json
        response=self.note(ident,{**payload,'selectionVersion':2,'reviewVersion':1,'receipt':preview['reviewReceipt'],
            'outcome':'usable_candidate','note':'The shorter muted interval is ready for independent assessment.',
            'revisionResponse':dict(observationSha256=previous['observationSha256'],
                changeSummary='Reduced the out point to 250 milliseconds and muted the excerpt.')})
        self.assertEqual(response.status_code,200,response.json)
        note=response.json['selection']['reviewNotes'][0]
        self.assertEqual(note['candidateEdit'],changed)
        self.assertEqual(note['revisionResponse']['previousObservation']['candidateEdit'],edit)
        self.assertEqual(response.json['selection']['postAssignments'][1],assignments[1])
        self.assertFalse(note['approved']);self.assertFalse(response.json['canPublish'])

    def test_review_note_persists_exact_preview_and_stales_after_selection_change(self):
        ident,payload=self.prepared_note()
        before=self.client.get(self.root).json
        response=self.note(ident,payload);self.assertEqual(response.status_code,200,response.json)
        selection=response.json['selection'];note=selection['reviewNotes'][0]
        self.assertEqual(note['reviewedBy'],'owner-a');self.assertEqual(note['note'],payload['note'])
        self.assertEqual(note['outcome'],'needs_changes');self.assertFalse(note['stale'])
        self.assertEqual(note['previewSha256'],self.crop_preview(ident).json['previewSha256'])
        self.assertEqual(note['sourceSha256'],hashlib.sha256(self.content).hexdigest())
        self.assertFalse(note['approved']);self.assertFalse(response.json['canPublish'])
        self.assertEqual(selection['postAssignments'],before['selection']['postAssignments'])
        self.assertEqual(selection['selectionVersion'],1);self.assertEqual(selection['reviewVersion'],1)
        self.assertEqual(self.note(ident,payload).status_code,409)
        self.client=self.app().test_client()
        self.assertEqual(self.client.get(self.root).json['selection'],selection)
        # Receipts expire on factory restart, while notes remain readable.
        self.assertEqual(self.note(ident,{**payload,'reviewVersion':1}).status_code,400)
        self.assertEqual(self.select([ident],version=1,postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[])]).status_code,200)
        result=self.client.get(self.root).json['selection']
        self.assertTrue(result['reviewNotes'][0]['stale']);self.assertEqual(result['reviewVersion'],1)
        self.assertEqual(result['reviewNotes'][0]['note'],payload['note'])
        self.assertEqual(self.client.get(self.root+'/'+ident+'/original').data,self.content)

    def test_review_receipt_rejects_forgery_wrong_day_scope_and_invalid_notes(self):
        ident,payload=self.prepared_note();before=self.client.get(self.root).json
        for changes in [dict(receipt='invented evidence'),dict(receipt=payload['receipt']+'0'),
                        dict(outcome='approved'),dict(outcome=True),dict(note='pass'),dict(note='x'*1001),
                        dict(note='a'*22+'\x00'),dict(reviewVersion=True),dict(ownerId='owner-a'),
                        dict(revision=True),dict(selectionVersion=True)]:
            response=self.note(ident,{**payload,**changes})
            self.assertIn(response.status_code,(400,409),response.json)
        self.assertEqual(self.note(ident,payload,day=9).status_code,400)
        other_doc='d'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other_doc}).status_code,200)
        other_root=self.docs+'/'+other_doc+'/media'
        assignment=dict(day=1,assetIds=[ident],photoCrops=[self.crop(ident)])
        self.assertEqual(self.client.put(other_root+'/selection',json=dict(revision=1,selectionVersion=0,
            assetIds=[ident],postAssignments=[assignment])).status_code,200)
        self.assertEqual(self.client.put(other_root+f'/posts/1/{ident}/review-note',json=payload).status_code,400)
        self.user={'id':'other-owner'}
        self.assertEqual(self.note(ident,payload).status_code,403)
        self.user=None
        self.assertEqual(self.note(ident,payload).status_code,403)
        self.user={'id':'owner-a'};self.memberships.clear()
        self.assertEqual(self.note(ident,payload).status_code,403)
        self.memberships={'org-a','org-b'}
        other=self.root.replace('org-a','org-b')
        self.assertEqual(self.client.put(other+f'/posts/1/{ident}/review-note',json=payload).status_code,403)
        self.assertEqual(self.client.get(self.root).json,before)

    def test_review_note_rechecks_calendar_withdrawal_receipt_expiry_and_bytes(self):
        from unittest.mock import patch
        import time
        ident,payload=self.prepared_note()
        with patch('time.time',return_value=time.time()+3601):
            self.assertEqual(self.note(ident,payload).status_code,400)
        # Calendar changes invalidate a receipt even when selection was not saved again.
        updated={**self.payload,'mutationId':'c'*32,'expectedRevision':1,
                 'document':{**self.payload['document'],'goal':'bookings'}}
        self.assertEqual(self.client.post(self.docs,json=updated).status_code,200)
        self.assertEqual(self.note(ident,payload).status_code,409)
        self.assertEqual(self.select([ident],revision=2,version=1,postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[self.crop(ident)])]).status_code,200)
        preview=self.crop_preview(ident,revision=2,version=2).json
        payload.update(revision=2,selectionVersion=2,receipt=preview['reviewReceipt'])
        withdrawal=self.client.post(self.root+'/'+ident+'/withdraw-permission',json={'reason':'The subject has withdrawn permission for this authored fixture.'})
        self.assertEqual(withdrawal.status_code,200)
        self.assertEqual(self.note(ident,payload).status_code,409)
        self.assertEqual(self.client.get(self.root).json['selection']['reviewNotes'],[])

    def test_review_note_replacement_and_response_failure_roll_back(self):
        from unittest.mock import patch
        import business_campaign_assets as assets
        ident,payload=self.prepared_note()
        self.assertEqual(self.note(ident,payload).status_code,200)
        replacement={**payload,'reviewVersion':1,'outcome':'unsuitable',
                     'note':'The saved crop excludes the important product label; choose a different crop.'}
        original=assets.saved_selection;calls=0
        def fail_response(*args):
            nonlocal calls
            calls+=1
            if calls==3:raise assets.CampaignAssetError('Response construction failed')
            return original(*args)
        with patch.object(assets,'saved_selection',side_effect=fail_response):
            self.assertEqual(self.note(ident,replacement).status_code,400)
        selection=self.client.get(self.root).json['selection']
        self.assertEqual(selection['reviewVersion'],1);self.assertEqual(selection['reviewNotes'][0]['note'],payload['note'])
        self.assertEqual(self.note(ident,replacement).status_code,200)
        selection=self.client.get(self.root).json['selection']
        self.assertEqual(selection['reviewVersion'],2);self.assertEqual(len(selection['reviewNotes']),1)
        self.assertEqual(selection['reviewNotes'][0]['outcome'],'unsuitable')

    def test_review_note_rejects_tampered_original_before_persistence(self):
        ident,payload=self.prepared_note()
        with sqlite3.connect(self.path) as con:
            con.execute('UPDATE business_asset_originals SET original_bytes=? WHERE asset_id=?',(b'changed',ident))
        self.assertEqual(self.note(ident,payload).status_code,400)
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute('SELECT review_notes,review_version FROM business_campaign_asset_selections').fetchone(),('[]',0))

    def test_rendered_video_excerpt_has_saved_pixels_interval_audio_and_no_mutations(self):
        import base64, json, subprocess
        # Authored temporal fixture: first half red, second half blue, with tone.
        path=Path(self.tmp.name)/'colours.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
            'color=c=red:s=160x160:r=24:d=0.5','-f','lavfi','-i',
            'color=c=blue:s=160x160:r=24:d=0.5','-f','lavfi','-i','sine=frequency=440:duration=1',
            '-filter_complex_threads','1','-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]',
            '-map','[v]','-map','2:a','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',
            '-c:a','aac','-movflags','+faststart',str(path)],check=True,timeout=15)
        original=path.read_bytes();asset=self.video_upload(original).json['asset'];ident=asset['assetId']
        edits=[dict(assetId=ident,startMs=500,endMs=1000,muted=True),
               dict(assetId=ident,startMs=0,endMs=500,muted=False)]
        assignments=[dict(day=day,assetIds=[ident],videoEdits=[edit]) for day,edit in zip([1,9],edits)]
        self.assertEqual(self.select([ident],postAssignments=assignments).status_code,200)
        before=self.client.get(self.root).json
        self.client=self.app().test_client()
        for day,edit in zip([1,9],edits):
            result=self.video_preview(ident,day=day)
            self.assertEqual(result.status_code,200,result.json)
            self.assertEqual(result.headers['Cache-Control'],'no-store')
            data=result.json;raw=base64.b64decode(data['previewBase64'],validate=True)
            self.assertEqual(data['sourceSha256'],hashlib.sha256(original).hexdigest())
            self.assertEqual(data['previewSha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(data['previewBytes'],len(raw));self.assertEqual(data['edit'],edit)
            self.assertFalse(data['approved']);self.assertFalse(data['canPublish']);self.assertFalse(data['canSpend'])
            self.assertIn('reviewReceipt',data)
            review=Path(self.tmp.name)/f'review-{day}.mp4';review.write_bytes(raw)
            probe=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(review)],
                check=True,capture_output=True,text=True,timeout=8).stdout)
            self.assertAlmostEqual(float(probe['format']['duration']),0.5,delta=0.125)
            self.assertEqual(any(s['codec_type']=='audio' for s in probe['streams']),not edit['muted'])
            # Decode every output frame: the saved in point must exclude the other colour.
            frames=subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(review),
                '-map','0:v:0','-threads','1','-f','rawvideo','-pix_fmt','rgb24','-'],
                check=True,capture_output=True,timeout=10).stdout
            frame_bytes=160*160*3;self.assertGreaterEqual(len(frames),frame_bytes*10)
            for offset in range(0,len(frames),frame_bytes):
                rgb=frames[offset:offset+3]
                self.assertGreater(rgb[2] if day==1 else rgb[0],200)
                self.assertLess(rgb[0] if day==1 else rgb[2],20)
        self.assertEqual(self.client.get(self.root).json,before)
        self.assertEqual(self.client.get(self.root+'/'+ident+'/original').data,original)
        # Save an observation on the exact final rendered video, without rerendering.
        response=self.note(ident,dict(revision=1,selectionVersion=1,reviewVersion=0,
            receipt=data['reviewReceipt'],outcome='usable_candidate',
            note='The authored red interval and retained audio match this saved excerpt.'),day=9)
        self.assertEqual(response.status_code,200,response.json)
        observation=response.json['selection']['reviewNotes'][0]
        self.assertEqual(observation['previewSha256'],data['previewSha256'])
        self.assertFalse(observation['stale']);self.assertFalse(observation['approved'])
        assignments[0]['videoEdits']=[]
        self.assertEqual(self.select([ident],version=1,postAssignments=assignments).status_code,200)
        self.assertEqual(self.video_preview(ident,version=2).status_code,400)
        self.assertTrue(self.client.get(self.root).json['selection']['reviewNotes'][0]['stale'])

    def test_video_render_rejects_unauthorised_stale_and_unsaved_before_renderer(self):
        from unittest.mock import patch
        ident=self.video_upload().json['asset']['assetId']
        assignment=dict(day=1,assetIds=[ident],videoEdits=[dict(assetId=ident,startMs=0,endMs=500,muted=True)])
        self.assertEqual(self.select([ident],postAssignments=[assignment]).status_code,200)
        with patch('business_asset_catalog.probe_offline_video',side_effect=AssertionError('No render for denied requests')):
            self.assertEqual(self.video_preview(ident,version=0).status_code,409)
            self.assertEqual(self.video_preview(ident,day=9).status_code,400)
            self.assertEqual(self.video_preview('f'*32).status_code,403)
            self.assertEqual(self.client.get(self.root.replace('org-a','org-b')+
                f'/posts/1/{ident}/video-preview?revision=1&selectionVersion=1').status_code,403)
            self.user={'id':'another-owner'}
            self.assertEqual(self.video_preview(ident).status_code,403)
            self.user=None
            self.assertEqual(self.client.get(self.root+f'/posts/1/{ident}/video-preview',headers={'X-Clippr-Pilot':'1'}).status_code,403)
            self.user={'id':'owner-a'};self.memberships=set()
            self.assertEqual(self.video_preview(ident).status_code,403)
            self.memberships={'org-a'}
            withdrawn=self.client.post(self.root+'/'+ident+'/withdraw-permission',json={'reason':'Permission withdrawn for this authored video fixture.'})
            self.assertEqual(withdrawn.status_code,200)
            self.assertEqual(self.video_preview(ident).status_code,409)

    def test_video_render_failure_busy_and_tampering_preserve_selection(self):
        from unittest.mock import patch
        import business_campaign_assets as assets
        ident=self.video_upload().json['asset']['assetId']
        assignment=dict(day=1,assetIds=[ident],videoEdits=[dict(assetId=ident,startMs=0,endMs=500,muted=True)])
        self.assertEqual(self.select([ident],postAssignments=[assignment]).status_code,200)
        before=self.client.get(self.root).json
        assets._video_preview_lock.acquire()
        try:self.assertEqual(self.video_preview(ident).status_code,400)
        finally:assets._video_preview_lock.release()
        with patch('business_campaign_assets.catalog.probe_offline_video',side_effect=OSError('private path')):
            result=self.video_preview(ident)
            self.assertEqual(result.status_code,400);self.assertNotIn('private path',result.json['error'])
            self.assertNotIn('previewBase64',result.json)
        self.assertFalse(assets._video_preview_lock.locked())
        self.assertEqual(self.client.get(self.root).json,before)
        with sqlite3.connect(self.path) as con:
            con.execute('UPDATE business_asset_originals SET original_bytes=? WHERE asset_id=?',(b'changed',ident))
        with patch('business_asset_catalog.probe_offline_video',side_effect=AssertionError('No decode after tampering')):
            self.assertEqual(self.video_preview(ident).status_code,400)

    def test_static_presets_save_reopen_and_render_exact_owned_pixels(self):
        import base64, json, subprocess
        image=Image.new('RGB',(48,32))
        image.putdata([(x*5,y*7,(x+y)*3) for y in range(32) for x in range(48)])
        buf=io.BytesIO();image.save(buf,format='PNG');self.content=buf.getvalue()
        ident=self.upload().json['asset']['assetId']
        script="""
import {centeredPhotoCrop} from './src/lib/businessOriginalReview.mjs';
const crop=centeredPhotoCrop({photoWidth:48,photoHeight:32},process.argv[1]);
process.stdout.write(JSON.stringify(crop));
"""
        for version,ratio,expected in [(1,'4:5',(12,1,36,31)),(2,'1:1',(8,0,40,32))]:
            result=subprocess.run(['node','--input-type=module','-e',script,ratio],
                cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,check=True)
            framing=json.loads(result.stdout)
            crop={key:framing[key] for key in ('left','top','width','height')}
            crop['assetId']=ident
            assignments=[dict(day=1,assetIds=[ident],photoCrops=[crop]),dict(day=9,assetIds=[ident])]
            saved=self.select([ident],version=version-1,postAssignments=assignments)
            self.assertEqual(saved.status_code,200,saved.json)
            self.client=self.app().test_client()
            self.assertEqual(self.client.get(self.root).json['selection']['postAssignments'],assignments)
            response=self.crop_preview(ident,version=version)
            self.assertEqual(response.status_code,200,response.json)
            raw=base64.b64decode(response.json['previewBase64'],validate=True)
            with Image.open(io.BytesIO(raw)) as preview:
                self.assertEqual(preview.convert('RGB').tobytes(),image.crop(expected).tobytes())
                self.assertEqual(preview.size,(expected[2]-expected[0],expected[3]-expected[1]))
            self.assertFalse(response.json['approved']);self.assertFalse(response.json['canPublish'])
            self.assertEqual(self.client.get(self.root+'/'+ident+'/original').data,self.content)

    def test_photo_crops_render_exact_pixels_reopen_and_reset_per_day(self):
        import base64
        # Synthetic owned image with a different value at every coordinate.
        image=Image.new('RGB',(48,32))
        image.putdata([(x*5,y*7,(x+y)*3) for y in range(32) for x in range(48)])
        buf=io.BytesIO();image.save(buf,format='PNG');self.content=buf.getvalue()
        ident=self.upload().json['asset']['assetId'];crop=self.crop(ident)
        assignments=[dict(day=1,assetIds=[ident],photoCrops=[crop]),dict(day=9,assetIds=[ident])]
        self.assertEqual(self.select([ident],postAssignments=assignments).status_code,200)
        self.client=self.app().test_client()
        self.assertEqual(self.client.get(self.root).json['selection']['postAssignments'],assignments)
        response=self.crop_preview(ident);self.assertEqual(response.status_code,200,response.json)
        result=response.json;raw=base64.b64decode(result['previewBase64'],validate=True)
        with Image.open(io.BytesIO(raw)) as preview:
            self.assertEqual(preview.size,(24,20))
            self.assertEqual(preview.convert('RGB').tobytes(),image.crop((8,4,32,24)).tobytes())
        self.assertEqual(result['previewSha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['sourceSha256'],hashlib.sha256(self.content).hexdigest())
        self.assertEqual(result['crop'],crop);self.assertEqual(result['day'],1)
        self.assertFalse(result['approved']);self.assertFalse(result['canPublish']);self.assertFalse(result['canSpend'])
        self.assertFalse(result['hostedStorageVerified'])
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
        self.assertEqual(self.client.get(self.root+'/'+ident+'/original').data,self.content)
        self.assertEqual(self.crop_preview(ident,day=9).status_code,400)
        self.assertEqual(self.crop_preview(ident,version=0).status_code,409)
        assignments[0].pop('photoCrops')
        self.assertEqual(self.select([ident],version=1,postAssignments=assignments).status_code,400)
        assignments[0]['photoCrops']=[]
        self.assertEqual(self.select([ident],version=1,postAssignments=assignments).status_code,200)
        self.assertEqual(self.crop_preview(ident,version=2).status_code,400)
        self.assertEqual(self.client.get(self.root).json['selection']['postAssignments'][1],assignments[1])

    def test_photo_crop_bounds_types_substitution_and_tamper_fail_without_writes(self):
        ident=self.upload().json['asset']['assetId'];video=self.video_upload().json['asset']['assetId']
        good=self.crop(ident)
        invalid=[None,{}, {**good,'left':True},{**good,'left':-1},{**good,'left':0.5},
                 {**good,'top':'4'},{**good,'width':15},{**good,'height':0},
                 {**good,'width':1000000000},{**good,'top':32},{**good,'extra':1},
                 {**good,'assetId':video},{**good,'assetId':'f'*32},{**good,'assetId':[]}]
        for crop in invalid:
            with self.subTest(crop=crop):
                response=self.select([ident,video],postAssignments=[dict(day=1,assetIds=[ident,video],photoCrops=[crop])])
                self.assertEqual(response.status_code,400,response.json)
        self.assertEqual(self.select([ident],postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[good,good])]).status_code,400)
        self.assertEqual(self.client.get(self.root).json['selection']['selectionVersion'],0)
        self.assertEqual(self.select([ident],postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[good])]).status_code,200)
        with sqlite3.connect(self.path) as con:
            con.execute('UPDATE business_asset_originals SET original_bytes=? WHERE asset_id=?',(b'tampered',ident))
        result=self.crop_preview(ident)
        self.assertEqual(result.status_code,400);self.assertNotIn('previewBase64',result.json)

    def test_photo_crops_follow_exif_display_orientation_and_bound_preview_size(self):
        image=Image.new('RGB',(1800,1200),(20,80,140));exif=Image.Exif();exif[274]=6
        buf=io.BytesIO();image.save(buf,format='JPEG',exif=exif)
        self.content=buf.getvalue()
        ident=self.upload(file=(io.BytesIO(self.content),'portrait.jpg','image/jpeg')).json['asset']['assetId']
        bounds=self.client.get(self.root+'/'+ident+'/original?photo_edit_bounds=1',headers={'Accept':'application/json'}).json
        self.assertEqual((bounds['photoWidth'],bounds['photoHeight']),(1200,1800))
        crop=dict(assetId=ident,left=0,top=0,width=1200,height=1800)
        self.assertEqual(self.select([ident],postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[crop])]).status_code,200)
        result=self.crop_preview(ident);self.assertEqual(result.status_code,200,result.json)
        self.assertEqual((result.json['width'],result.json['height']),(800,1200))
        self.assertEqual(self.client.get(self.root+'/'+ident+'/original').data,self.content)

    def test_photo_crop_preview_requires_owner_membership_and_never_accepts_pilot_header(self):
        ident=self.upload().json['asset']['assetId']
        self.assertEqual(self.select([ident],postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[self.crop(ident)])]).status_code,200)
        self.user={'id':'owner-b'}
        self.assertEqual(self.crop_preview(ident).status_code,403)
        other='e'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other}).status_code,200)
        suffix=f'/posts/1/{ident}/photo-preview?revision=1&selectionVersion=1'
        response=self.client.get(self.root.replace(self.ident,other)+suffix,headers={'X-Clippr-Pilot':'local-only'})
        missing=self.client.get(self.root.replace(self.ident,other)+suffix.replace(ident,'f'*32))
        self.assertEqual(response.status_code,403);self.assertEqual(response.json,missing.json)
        self.user={'id':'owner-a'};self.memberships.clear()
        self.assertEqual(self.crop_preview(ident).status_code,403)
        self.memberships={'org-a'};self.user=None
        self.assertEqual(self.crop_preview(ident).status_code,403)

    def test_photo_crop_editing_checks_permission_before_decode(self):
        from unittest.mock import patch
        ident=self.upload(consentStatus='not_confirmed').json['asset']['assetId']
        with patch('PIL.Image.open',side_effect=AssertionError('Permission must precede decode')):
            result=self.client.get(self.root+'/'+ident+'/original?photo_edit_bounds=1',headers={'Accept':'application/json'})
            self.assertEqual(result.status_code,400,result.json)
            result=self.select([ident],postAssignments=[dict(day=1,assetIds=[ident],photoCrops=[self.crop(ident)])])
            self.assertEqual(result.status_code,400,result.json)

    def test_photo_crops_stale_calendar_withdrawal_and_explicit_removal(self):
        ident=self.upload().json['asset']['assetId'];assignment=dict(day=1,assetIds=[ident],photoCrops=[self.crop(ident)])
        self.assertEqual(self.select([ident],postAssignments=[assignment]).status_code,200)
        saved=self.client.get(self.docs+'/'+self.ident).json
        saved['document']['posts'][0]['copyDraft']='Changed post requiring another review.'
        result=self.client.post(self.docs,json={**self.payload,'expectedRevision':1,'mutationId':'c'*32,'document':saved['document']})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(self.crop_preview(ident,revision=2).status_code,409)
        self.assertEqual(self.select([ident],revision=2,version=1,postAssignments=[assignment]).status_code,200)
        self.assertEqual(self.crop_preview(ident,revision=2,version=2).status_code,200)
        self.assertEqual(self.client.post(self.root+'/'+ident+'/withdraw-permission',json={'reason':'Owner withdraws marketing permission for this photo.'}).status_code,200)
        self.assertEqual(self.crop_preview(ident,revision=2,version=2).status_code,409)
        self.assertEqual(self.select([ident],revision=2,version=2,postAssignments=[assignment]).status_code,400)
        self.assertEqual(self.select([],revision=2,version=2,postAssignments=[]).status_code,200)
        self.assertEqual(self.client.get(self.root).json['selection']['postAssignments'],[])

    def test_saved_original_inspection_preserves_bytes_rights_and_assignments(self):
        import base64
        for upload,content in [(self.upload,self.content),(self.video_upload,self.video_bytes)]:
            asset=upload().json['asset'];ident=asset['assetId']
            path=self.root+'/'+ident+'/original'
            self.client=self.app().test_client()
            response=self.client.get(path,headers={'Accept':'application/json'})
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(base64.b64decode(response.json['originalBase64'],validate=True),content)
            self.assertEqual(response.json['asset'],asset)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
            self.assertFalse(response.json['hostedStorageVerified'])
            self.assertFalse(response.json['canPublish']);self.assertFalse(response.json['canSpend'])
            self.assertEqual(self.client.get(path).data,content)
            self.assertEqual(self.client.get(path,headers={'Accept':'*/*'}).data,content)
        # Viewing does not select, approve, assign or mutate the campaign.
        library=self.client.get(self.root).json
        self.assertEqual(library['revision'],1)
        self.assertEqual(library['selection']['selectionVersion'],0)
        self.assertEqual(library['selection']['postAssignments'],[])
        self.assertFalse(library['selection']['approved'])

    def test_saved_inspection_uses_current_consent_and_never_grants_permission(self):
        ident=self.upload(consentStatus='not_confirmed').json['asset']['assetId']
        path=self.root+'/'+ident+'/original'
        response=self.client.get(path,headers={'Accept':'application/json'})
        self.assertEqual(response.json['asset']['consentStatus'],'not_confirmed')
        self.assertEqual(self.select([ident]).status_code,400)
        reason='Subject has withdrawn permission for marketing use.'
        self.assertEqual(self.client.post(self.root+'/'+ident+'/withdraw-permission',json={'reason':reason}).status_code,200)
        response=self.client.get(path,headers={'Accept':'application/json'})
        self.assertTrue(response.json['asset']['permissionWithdrawn'])
        self.assertEqual(response.json['asset']['withdrawalReason'],reason)
        self.assertEqual(self.select([ident]).status_code,400)

    def test_saved_inspection_denies_foreign_scopes_and_rechecks_membership(self):
        ident=self.upload().json['asset']['assetId']
        path=self.root+'/'+ident+'/original';headers={'Accept':'application/json','X-Clippr-Pilot':'local-only'}
        self.user={'id':'owner-b'}
        other='e'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other}).status_code,200)
        own_path=path.replace(self.ident,other)
        foreign=self.client.get(own_path,headers=headers)
        missing=self.client.get(own_path.replace(ident,'f'*32),headers=headers)
        self.assertEqual(foreign.status_code,403);self.assertEqual(foreign.json,missing.json)
        self.assertEqual(self.client.get(path,headers=headers).status_code,403)
        self.user={'id':'owner-a'}
        org_docs=self.docs.replace('org-a','org-b')
        org_ident='d'*32
        self.assertEqual(self.client.post(org_docs,json={**self.payload,'id':org_ident}).status_code,200)
        self.assertEqual(self.client.get(path.replace('org-a','org-b').replace(self.ident,org_ident),headers=headers).status_code,403)
        self.memberships.clear()
        self.assertEqual(self.client.get(path,headers=headers).status_code,403)
        self.memberships={'org-a'};self.user=None
        self.assertEqual(self.client.get(path,headers=headers).status_code,403)

    def test_saved_inspection_refuses_tampered_original(self):
        ident=self.upload().json['asset']['assetId']
        with sqlite3.connect(self.path) as con:
            con.execute('UPDATE business_asset_originals SET original_bytes=? WHERE asset_id=?',(b'changed',ident))
        result=self.client.get(self.root+'/'+ident+'/original',headers={'Accept':'application/json'})
        self.assertEqual(result.status_code,400)
        self.assertNotIn('originalBase64',result.json)

    @classmethod
    def setUpClass(cls):
        import subprocess
        cls.video_tmp=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.video_tmp.cleanup)
        path=Path(cls.video_tmp.name)/'studio.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
            'color=c=blue:s=160x160:r=2:d=1','-f','lavfi','-i','sine=frequency=440:duration=1',
            '-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-c:a','aac',
            '-movflags','+faststart','-y',str(path)],check=True,timeout=15)
        cls.video_bytes=path.read_bytes()

    def video_upload(self,content=None,**changes):
        return self.upload(file=(io.BytesIO(self.video_bytes if content is None else content),
                                 'studio.mp4','video/mp4'),**changes)

    def test_post_video_edits_persist_independently_and_preserve_original(self):
        asset=self.video_upload().json['asset'];ident=asset['assetId']
        photo=self.upload().json['asset']['assetId']
        preview=self.client.get(self.root+'/'+ident+'/original?video_edit_bounds=1',headers={'Accept':'application/json'})
        self.assertEqual(preview.status_code,200,preview.json)
        self.assertEqual(preview.json['videoDurationMs'],1000)
        self.assertEqual(preview.json['asset'],asset)
        self.assertEqual(self.client.get(self.root+'/'+photo+'/original?video_edit_bounds=1',
            headers={'Accept':'application/json'}).status_code,400)
        edits=[{'assetId':ident,'startMs':100,'endMs':800,'muted':True}]
        assignments=[{'day':1,'assetIds':[ident,photo],'videoEdits':edits},
                     {'day':9,'assetIds':[ident],'videoEdits':[]}]
        result=self.select([ident,photo],postAssignments=assignments)
        self.assertEqual(result.status_code,200,result.json)
        self.client=self.app().test_client()
        selection=self.client.get(self.root).json['selection']
        self.assertEqual(selection['postAssignments'],assignments)
        self.assertFalse(selection['approved']);self.assertFalse(selection['canSpend'])
        original=self.client.get(self.root+'/'+ident+'/original')
        self.assertEqual(original.data,self.video_bytes)
        self.assertEqual(original.headers['X-Content-SHA256'],asset['sourceSha256'])
        # Older writers cannot erase a reviewed edit by silently omitting its field.
        legacy=[{'day':1,'assetIds':[ident,photo]},{'day':9,'assetIds':[ident]}]
        self.assertEqual(self.select([ident,photo],version=1,postAssignments=legacy).status_code,400)
        self.assertEqual(self.select([ident,photo],version=0,postAssignments=assignments).status_code,409)
        assignments[0]['videoEdits']=[]  # Explicitly restore whole original/audio.
        result=self.select([ident,photo],version=1,postAssignments=assignments)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['selection']['postAssignments'],assignments)
        self.assertEqual(len(self.client.get(self.docs+'/'+self.ident).json['document']['posts']),30)

    def test_video_edit_bounds_and_media_substitution_fail_without_writes(self):
        ident=self.video_upload().json['asset']['assetId']
        photo=self.upload().json['asset']['assetId']
        edit={'assetId':ident,'startMs':100,'endMs':800,'muted':False}
        invalid=[{**edit,'startMs':True},{**edit,'startMs':-1},{**edit,'startMs':100.5},
                 {**edit,'endMs':349},{**edit,'endMs':1001},{**edit,'endMs':60001},
                 {**edit,'endMs':'800'},{**edit,'muted':1},{**edit,'assetId':photo},
                 {**edit,'assetId':'f'*32},{**edit,'sourceDurationMs':999999}]
        for candidate in invalid:
            result=self.select([ident,photo],postAssignments=[{'day':1,'assetIds':[ident,photo],'videoEdits':[candidate]}])
            self.assertEqual(result.status_code,400,result.json)
        for invalid_edits in (None,{},[edit,edit]):
            result=self.select([ident,photo],postAssignments=[{'day':1,'assetIds':[ident,photo],'videoEdits':invalid_edits}])
            self.assertEqual(result.status_code,400,result.json)
        self.assertEqual(self.client.get(self.root).json['selection']['selectionVersion'],0)

    def test_video_edits_stale_after_calendar_changes_and_held_after_withdrawal(self):
        ident=self.video_upload().json['asset']['assetId']
        assignments=[{'day':1,'assetIds':[ident],'videoEdits':[
            {'assetId':ident,'startMs':0,'endMs':1000,'muted':False}]}]
        self.assertEqual(self.select([ident],postAssignments=assignments).status_code,200)
        saved=self.client.get(self.docs+'/'+self.ident).json
        saved['document']['posts'][0]['copyDraft']='Updated owner copy needs media review'
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'expectedRevision':1,
            'mutationId':'c'*32,'document':saved['document']}).status_code,200)
        library=self.client.get(self.root).json
        self.assertTrue(library['selection']['stale'])
        self.assertEqual(library['selection']['postAssignments'],assignments)
        self.assertEqual(self.select([ident],version=1,postAssignments=assignments).status_code,409)
        self.assertEqual(self.select([ident],revision=2,version=1,postAssignments=assignments).status_code,200)
        self.assertEqual(self.client.post(self.root+'/'+ident+'/withdraw-permission',json={
            'reason':'Subject no longer permits marketing use of this video.'}).status_code,200)
        self.assertTrue(self.client.get(self.root).json['selection']['stale'])
        self.assertEqual(self.select([ident],revision=2,version=2,postAssignments=assignments).status_code,400)
        self.assertEqual(self.select([],revision=2,version=2,postAssignments=[]).status_code,200)

    def test_video_edit_ownership_missing_decoder_and_transaction_rollback(self):
        from unittest.mock import patch
        import business_asset_catalog as catalog
        import business_campaign_assets as assets
        ident=self.video_upload().json['asset']['assetId']
        assignments=[{'day':1,'assetIds':[ident],'videoEdits':[
            {'assetId':ident,'startMs':100,'endMs':800,'muted':True}]}]
        with patch.object(catalog.subprocess,'run',side_effect=FileNotFoundError('private path')):
            result=self.select([ident],postAssignments=assignments)
            # Missing edit capability must not break ordinary original inspection.
            path=self.root+'/'+ident+'/original'
            self.assertEqual(self.client.get(path,headers={'Accept':'application/json'}).status_code,200)
            self.assertEqual(self.client.get(path+'?video_edit_bounds=1',headers={'Accept':'application/json'}).status_code,400)
        self.assertEqual(result.status_code,400)
        self.assertNotIn('private path',result.get_data(as_text=True))
        real=assets.saved_selection;calls=[]
        def fail_after_write(*args):
            calls.append(True)
            if len(calls)==2:raise sqlite3.OperationalError('private table')
            return real(*args)
        with patch.object(assets,'saved_selection',side_effect=fail_after_write):
            result=self.select([ident],postAssignments=assignments)
        self.assertEqual(result.status_code,503)
        self.assertEqual(self.client.get(self.root).json['selection']['selectionVersion'],0)
        self.user={'id':'owner-b'};other='e'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other}).status_code,200)
        for root in (self.root,self.root.replace(self.ident,other),self.root.replace('org-a','org-b')):
            response=self.client.put(root+'/selection',json=dict(revision=1,selectionVersion=0,
                assetIds=[ident],postAssignments=assignments),headers={'X-Clippr-Pilot':'local-only'})
            self.assertIn(response.status_code,(400,403))
        self.user=None
        self.assertEqual(self.select([ident],postAssignments=assignments).status_code,403)

    def test_video_edit_duration_probe_reused_and_missing_duration_held(self):
        from unittest.mock import patch
        import business_asset_catalog as catalog
        ident=self.video_upload().json['asset']['assetId']
        assignments=[{'day':day,'assetIds':[ident],'videoEdits':[
            {'assetId':ident,'startMs':100,'endMs':800,'muted':True}]} for day in (1,9,30)]
        with patch.object(catalog,'probe_offline_video',wraps=catalog.probe_offline_video) as probe:
            result=self.select([ident],postAssignments=assignments)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(probe.call_count,1)
        for duration in (None,'NaN','Infinity',0):
            stream={'codec_type':'video'}
            if duration is not None:stream['duration']=duration
            with patch.object(catalog,'probe_offline_video',return_value={
                'format':{'duration':'1.0'},'streams':[stream]}):
                result=self.select([ident],version=1,postAssignments=assignments)
            self.assertEqual(result.status_code,400,result.json)
        selection=self.client.get(self.root).json['selection']
        self.assertEqual(selection['selectionVersion'],1)
        self.assertEqual(selection['postAssignments'],assignments)
        self.assertEqual(self.client.post(self.root+'/'+ident+'/withdraw-permission',json={
            'reason':'Owner requests a permanent hold on this video.'}).status_code,200)
        with patch.object(catalog,'original_video_duration_ms') as probe:
            result=self.select([ident],version=1,postAssignments=assignments)
        self.assertEqual(result.status_code,400)
        probe.assert_not_called()

    def test_video_original_mixed_post_assignment_reopen_and_withdrawal(self):
        response=self.video_upload()
        self.assertEqual(response.status_code,201,response.json)
        asset=response.json['asset'];ident=asset['assetId']
        self.assertEqual(asset['mediaKind'],'video')
        self.assertEqual(asset['sourceSha256'],hashlib.sha256(self.video_bytes).hexdigest())
        original=self.client.get(self.root+'/'+ident+'/original')
        self.assertEqual(original.data,self.video_bytes)
        self.assertEqual(original.mimetype,'video/mp4')
        self.assertEqual(original.headers['Cache-Control'],'no-store')
        self.assertEqual(original.headers['X-Content-Type-Options'],'nosniff')
        photo=self.upload().json['asset']['assetId']
        assignment=[{'day':2,'assetIds':[photo,ident]}]
        self.assertEqual(self.select([ident,photo],postAssignments=assignment).status_code,200)
        self.client=self.app().test_client()
        saved=self.client.get(self.root).json
        self.assertEqual(saved['selection']['postAssignments'],assignment)
        self.assertFalse(saved['selection']['approved']);self.assertFalse(saved['canPublish'])
        self.assertFalse(saved['hostedStorageVerified'])
        held=self.client.post(self.root+'/'+ident+'/withdraw-permission',json={
            'reason':'Subject withdrew permission for this recorded demonstration.'})
        self.assertEqual(held.status_code,200,held.json)
        self.assertTrue(held.json['selection']['stale'])
        duplicate=self.video_upload().json['asset']
        self.assertTrue(duplicate['permissionWithdrawn'])
        self.assertEqual(self.select([duplicate['assetId']],version=1,postAssignments=[]).status_code,400)
        self.assertEqual(self.select([photo],version=1,
            postAssignments=[{'day':2,'assetIds':[photo]}]).status_code,200)
        self.assertEqual(self.client.get(self.root+'/'+ident+'/original').data,self.video_bytes)

    def test_video_owner_consent_and_calendar_revision_boundaries(self):
        held=self.video_upload(consentStatus='not_confirmed').json['asset']['assetId']
        self.assertEqual(self.select([held]).status_code,400)
        ident=self.video_upload().json['asset']['assetId']
        self.assertEqual(self.select([ident],postAssignments=[{'day':9,'assetIds':[ident]}]).status_code,200)
        saved=self.client.get(self.docs+'/'+self.ident).json
        saved['document']['posts'][8]['copyDraft']='New copy needs a fresh review of the selected footage.'
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'expectedRevision':1,
            'mutationId':'c'*32,'document':saved['document']}).status_code,200)
        self.assertTrue(self.client.get(self.root).json['selection']['stale'])
        self.assertEqual(self.select([ident],version=1,postAssignments=[]).status_code,409)
        self.user={'id':'owner-b'}
        other='e'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other}).status_code,200)
        own_root=self.root.replace(self.ident,other)
        self.assertEqual(self.client.get(own_root).json['assets'],[])
        self.assertEqual(self.client.get(own_root+'/'+ident+'/original').status_code,403)
        self.assertEqual(self.client.put(own_root+'/selection',json=dict(revision=1,
            selectionVersion=0,assetIds=[ident],postAssignments=[])).status_code,400)
        self.memberships.clear()
        self.assertEqual(self.video_upload().status_code,403)

    def test_invalid_or_corrupt_video_never_persists(self):
        import json,subprocess
        path=Path(self.video_tmp.name)/'studio.mp4'
        packets=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','v:0',
            '-show_packets','-of','json',str(path)],capture_output=True,text=True,
            check=True,timeout=8).stdout)['packets']
        corrupt=bytearray(self.video_bytes)
        for packet in packets:
            start=int(packet['pos']);size=int(packet['size']);corrupt[start:start+size]=b'\0'*size
        for content in (self.content,b'not a video',self.video_bytes[:80],bytes(corrupt),
                        b'#EXTM3U\n#EXTINF:1,\nhttps://invalid.example/no-network.ts\n'):
            response=self.video_upload(content)
            self.assertEqual(response.status_code,400,response.json)
        self.assertEqual(self.client.get(self.root).json['assets'],[])
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM business_asset_originals').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT count(*) FROM business_asset_catalog').fetchone()[0],0)

    def test_video_container_codec_duration_and_decode_timeout_fail_closed(self):
        import subprocess
        from unittest.mock import patch
        for name,options in [('wrong-codec.mp4',['-c:v','mpeg4']),
                             ('quicktime.mov',['-c:v','libx264']),
                             ('long.mp4',['-c:v','libx264'])]:
            path=Path(self.video_tmp.name)/name
            duration=61 if name=='long.mp4' else 1
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
                f'color=c=blue:s=160x160:r=1:d={duration}',*options,'-threads','1',
                '-pix_fmt','yuv420p','-y',str(path)],check=True,timeout=15)
            response=self.video_upload(path.read_bytes())
            self.assertEqual(response.status_code,400,response.json)
        real=subprocess.run
        def timeout_decode(args,**kwargs):
            if args[0]=='ffmpeg':raise subprocess.TimeoutExpired('ffmpeg',20)
            return real(args,**kwargs)
        with patch('business_asset_catalog.subprocess.run',side_effect=timeout_decode):
            self.assertEqual(self.video_upload().status_code,400)
        self.assertEqual(self.client.get(self.root).json['assets'],[])

    def test_post_photo_assignments_persist_with_original_hash_and_calendar(self):
        asset=self.upload().json['asset']; ident=asset['assetId']
        assignments=[{'day':9,'assetIds':[ident]},{'day':1,'assetIds':[ident]}]
        response=self.select([ident],postAssignments=assignments)
        self.assertEqual(response.status_code,200,response.json)
        self.assertFalse(response.json['selection']['approved'])
        self.client=self.app().test_client()
        library=self.client.get(self.root).json
        self.assertEqual(len(library['posts']),30)
        self.assertEqual(library['selection']['postAssignments'],list(reversed(assignments)))
        self.assertEqual(library['selection']['assets'][0]['sourceSha256'],asset['sourceSha256'])
        # Legacy clients cannot silently erase a saved post assignment.
        self.assertEqual(self.select([ident],version=1).status_code,400)
        self.assertEqual(self.select([ident],version=0,postAssignments=[]).status_code,409)
        self.assertEqual(self.select([ident],version=1,postAssignments=[]).status_code,200)
        self.assertEqual(self.client.get(self.root).json['selection']['postAssignments'],[])
        self.assertEqual(self.client.get(self.docs+'/'+self.ident).json['document']['posts'],
                         library['posts'])

    def test_assignment_validation_is_atomic_and_requires_selected_authorised_bytes(self):
        ident=self.upload().json['asset']['assetId']
        held=self.upload(consentStatus='not_confirmed').json['asset']['assetId']
        invalid=[None,{},[{'day':True,'assetIds':[ident]}],
                 [{'day':31,'assetIds':[ident]}],[{'day':1,'assetIds':[]}],
                 [{'day':1,'assetIds':[ident,ident]}],
                 [{'day':1,'assetIds':['f'*32]}],
                 [{'day':1,'assetIds':[held]}],
                 [{'day':1,'assetIds':[ident],'approved':True}],
                 [{'day':1,'assetIds':[ident]}]*2]
        for assignments in invalid:
            result=self.select([ident],postAssignments=assignments)
            self.assertEqual(result.status_code,400,result.json)
            self.assertEqual(self.client.get(self.root).json['selection']['selectionVersion'],0)
        self.assertEqual(self.select([ident,held],postAssignments=[{'day':1,'assetIds':[held]}]).status_code,400)
        # An authorised second owner's original still cannot be assigned here.
        self.user={'id':'owner-b'}
        other='e'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other}).status_code,200)
        other_root=self.root.replace(self.ident,other)
        result=self.client.put(other_root+'/selection',json=dict(revision=1,selectionVersion=0,
            assetIds=[ident],postAssignments=[{'day':1,'assetIds':[ident]}]))
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.client.get(other_root).json['selection']['postAssignments'],[])
        self.memberships.clear()
        self.assertEqual(self.client.put(other_root+'/selection',json=dict(revision=1,
            selectionVersion=0,assetIds=[ident],postAssignments=[])).status_code,403)

    def test_assignment_calendar_edit_and_permission_withdrawal_require_review(self):
        ident=self.upload().json['asset']['assetId']
        assignments=[{'day':9,'assetIds':[ident]}]
        self.assertEqual(self.select([ident],postAssignments=assignments).status_code,200)
        saved=self.client.get(self.docs+'/'+self.ident).json
        saved['document']['posts']=[p for p in saved['document']['posts'] if p['day']!=9]
        response=self.client.post(self.docs,json={**self.payload,'expectedRevision':1,
            'mutationId':'c'*32,'document':saved['document']})
        self.assertEqual(response.status_code,200,response.json)
        selection=self.client.get(self.root).json['selection']
        self.assertTrue(selection['stale']);self.assertEqual(selection['orphanedDays'],[9])
        self.assertEqual(selection['postAssignments'],assignments)
        self.assertEqual(self.select([ident],revision=2,version=1,postAssignments=assignments).status_code,400)
        current=[{'day':10,'assetIds':[ident]}]
        self.assertEqual(self.select([ident],revision=1,version=1,postAssignments=current).status_code,409)
        self.assertEqual(self.select([ident],revision=2,version=1,postAssignments=current).status_code,200)
        held=self.client.post(self.root+'/'+ident+'/withdraw-permission',json={
            'reason':'Subject no longer permits use of this original photo.'})
        self.assertEqual(held.status_code,200)
        self.assertTrue(held.json['selection']['stale'])
        self.assertEqual(held.json['selection']['postAssignments'],current)
        self.assertEqual(self.select([ident],revision=2,version=2,postAssignments=current).status_code,400)
        self.assertEqual(self.select([],revision=2,version=2,postAssignments=[]).status_code,200)

    def test_existing_offline_selection_database_upgrades_without_losing_candidates(self):
        ident=self.upload().json['asset']['assetId']
        self.assertEqual(self.select([ident]).status_code,200)
        with sqlite3.connect(self.path) as con:
            con.execute('ALTER TABLE business_campaign_asset_selections DROP COLUMN post_assignments')
        self.client=self.app().test_client()
        result=self.client.get(self.root)
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['selection']['assetIds'],[ident])
        self.assertEqual(result.json['selection']['postAssignments'],[])
        self.assertEqual(result.json['selection']['selectionVersion'],1)
        self.assertFalse(result.json['selection']['stale'])
        self.assertEqual(self.select([ident],version=1,postAssignments=[{'day':30,'assetIds':[ident]}]).status_code,200)

    def test_post_assignment_bounds_cross_campaign_isolation_and_failed_write_rollback(self):
        from unittest.mock import patch
        import business_campaign_assets
        ids=[self.upload().json['asset']['assetId'] for _ in range(6)]
        self.assertEqual(self.select(ids,postAssignments=[{'day':1,'assetIds':ids}]).status_code,400)
        assignments=[{'day':1,'assetIds':ids[:5]}]
        self.assertEqual(self.select(ids,postAssignments=assignments).status_code,200)
        other='e'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other}).status_code,200)
        other_root=self.root.replace(self.ident,other)
        self.assertEqual(self.client.get(other_root).json['selection']['postAssignments'],[])
        self.assertEqual(self.client.put(other_root+'/selection',json=dict(revision=1,
            selectionVersion=0,assetIds=ids,postAssignments=[{'day':2,'assetIds':ids[1:]}])).status_code,200)
        self.assertEqual(self.client.get(self.root).json['selection']['postAssignments'],assignments)
        # Fail after SQL mutation but before commit: neither version nor assignments may change.
        real=business_campaign_assets.saved_selection
        calls=[]
        def fail_after_write(*args):
            calls.append(True)
            if len(calls)==2:raise sqlite3.OperationalError('private database detail')
            return real(*args)
        with patch.object(business_campaign_assets,'saved_selection',side_effect=fail_after_write):
            response=self.select(ids,version=1,postAssignments=[])
        self.assertEqual(len(calls),2)
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private database detail',response.get_data(as_text=True))
        selection=self.client.get(self.root).json['selection']
        self.assertEqual(selection['selectionVersion'],1)
        self.assertEqual(selection['postAssignments'],assignments)

    def test_original_intake_reopen_library_select_and_invalidate_on_calendar_edit(self):
        response=self.upload(); self.assertEqual(response.status_code,201,response.json)
        asset=response.json['asset']; ident=asset['assetId']
        self.assertEqual(asset['sourceSha256'],hashlib.sha256(self.content).hexdigest())
        self.assertFalse(asset['verifiedRights']);self.assertFalse(asset['generationApproved'])
        self.assertFalse(response.json['hostedStorageVerified'])
        original=self.client.get(self.root+'/'+ident+'/original')
        self.assertEqual(original.data,self.content)
        self.assertEqual(original.headers['X-Content-SHA256'],asset['sourceSha256'])
        self.assertEqual(original.headers['Cache-Control'],'no-store')
        self.assertEqual(original.headers['X-Content-Type-Options'],'nosniff')
        selected=self.select([ident]);self.assertEqual(selected.status_code,200,selected.json)
        self.assertFalse(selected.json['selection']['approved'])
        self.client=self.app().test_client()
        library=self.client.get(self.root).json
        self.assertEqual(library['selection']['assetIds'],[ident]);self.assertFalse(library['selection']['stale'])
        self.assertEqual(self.select([],version=0).status_code,409)
        saved=self.client.get(self.docs+'/'+self.ident).json
        saved['document']['posts'][8]['copyDraft']='Owner edits day nine after media selection'
        updated=self.client.post(self.docs,json={**self.payload,'document':saved['document'],
            'expectedRevision':1,'mutationId':'c'*32})
        self.assertEqual(updated.status_code,200)
        stale=self.client.get(self.root).json['selection']
        self.assertTrue(stale['stale']);self.assertFalse(stale['approved'])
        self.assertEqual(stale['assetIds'],[ident])
        self.assertEqual(self.select([ident],revision=1,version=1).status_code,409)
        self.assertEqual(self.select([ident],revision=2,version=1).status_code,200)
        restored=self.client.get(self.docs+'/'+self.ident).json['document']
        self.assertEqual(len(restored['posts']),30)
        self.assertEqual(restored['posts'][8]['copyDraft'],'Owner edits day nine after media selection')
        self.assertFalse(restored['canPublish'])

    def test_auth_org_document_and_original_ownership_enforced(self):
        ident=self.upload().json['asset']['assetId']
        for user,root in [(None,self.root),({'id':'owner-b'},self.root),
                          ({'id':'owner-a'},self.root.replace('org-a','org-b'))]:
            self.user=user
            for response in [self.client.get(root),self.client.get(root+'/'+ident+'/original'),
                             self.client.put(root+'/selection',json={'assetIds':[ident]}),
                             self.client.post(root,data={},headers={'X-Clippr-Pilot':'local-only'})]:
                self.assertEqual(response.status_code,403,response.json)
        # Even an authorised second owner with their own document cannot adopt originals.
        self.user={'id':'owner-b'}
        other='d'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other}).status_code,200)
        other_root=self.root.replace(self.ident,other)
        self.assertEqual(self.client.get(other_root).json['assets'],[])
        self.assertEqual(self.client.get(other_root+'/'+ident+'/original').status_code,403)
        response=self.client.put(other_root+'/selection',json=dict(revision=1,selectionVersion=0,assetIds=[ident]))
        self.assertEqual(response.status_code,400)
        self.memberships.clear()
        self.assertEqual(self.client.get(other_root).status_code,403)

    def test_bad_bytes_mime_animation_rights_and_forged_owner_never_persist(self):
        fake=io.BytesIO(b'not image data')
        jpeg=io.BytesIO();Image.new('RGB',(48,32)).save(jpeg,format='JPEG')
        animated=io.BytesIO();Image.new('RGB',(32,32),'red').save(animated,format='WEBP',save_all=True,
            append_images=[Image.new('RGB',(32,32),'blue')],duration=200,loop=0)
        for changes in [dict(file=(fake,'fake.png','image/png')),
                        dict(file=(io.BytesIO(jpeg.getvalue()[:-10]),'truncated.jpg','image/jpeg')),
                        dict(file=(io.BytesIO(self.content),'false.jpg','image/jpeg')),
                        dict(file=(io.BytesIO(animated.getvalue()),'animation.webp','image/webp')),
                        dict(rightsStatement=''),dict(consentStatus='verified'),dict(owner_id='owner-a')]:
            result=self.upload(**changes);self.assertEqual(result.status_code,400,result.json)
        self.assertEqual(self.client.get(self.root).json['assets'],[])
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM business_asset_catalog').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT count(*) FROM business_asset_originals').fetchone()[0],0)
        held=self.upload(consentStatus='not_confirmed').json['asset']
        self.assertEqual(self.select([held['assetId']]).status_code,400)

    def test_library_reuse_across_owned_campaigns_and_deselection(self):
        ident=self.upload().json['asset']['assetId']
        other='e'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other}).status_code,200)
        other_root=self.root.replace(self.ident,other)
        self.assertEqual(self.client.get(other_root).json['assets'][0]['assetId'],ident)
        result=self.client.put(other_root+'/selection',json=dict(revision=1,selectionVersion=0,assetIds=[ident]))
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.client.get(self.root).json['selection']['assetIds'],[])
        self.assertEqual(self.select([ident]).status_code,200)
        self.assertEqual(self.select([],version=1).status_code,200)
        self.assertEqual(self.client.get(other_root).json['selection']['assetIds'],[ident])

    def test_tampered_original_not_served_or_selected_and_hosted_apis_absent(self):
        ident=self.upload().json['asset']['assetId']
        self.assertEqual(self.select([ident,ident]).status_code,400)
        with sqlite3.connect(self.path) as con:
            con.execute('UPDATE business_asset_originals SET original_bytes=?',(b'changed',))
        for response in [self.client.get(self.root+'/'+ident+'/original'),
                         self.client.get(self.root),self.select([ident])]:
            self.assertEqual(response.status_code,400,response.json)
            self.assertNotEqual(response.data,b'changed')
        for url in ['/api/business/drafts','/api/business/photos','/api/pilot/marketing-drafts']:
            self.assertEqual(self.client.get(url).status_code,404)

    def test_request_size_and_storage_errors_are_bounded_and_private(self):
        self.assertEqual(self.client.post(self.root,data=b'x'*(11*1024*1024+1)).status_code,413)
        self.assertEqual(self.client.post(self.docs,data='x'*300001,content_type='application/json').status_code,413)
        with sqlite3.connect(self.path) as con:
            con.execute('DROP TABLE business_asset_originals')
        response=self.client.get(self.root)
        self.assertEqual(response.status_code,503)
        self.assertNotIn('business_asset_originals',response.get_data(as_text=True))

    def test_withdraw_permission_invalidates_all_campaigns_without_changing_original(self):
        asset=self.upload().json['asset']; ident=asset['assetId']
        other='e'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other}).status_code,200)
        other_root=self.root.replace(self.ident,other)
        self.assertEqual(self.select([ident]).status_code,200)
        self.assertEqual(self.client.put(other_root+'/selection',json=dict(
            revision=1,selectionVersion=0,assetIds=[ident])).status_code,200)
        reason='Subject withdrew their permission for marketing use.'
        url=self.root+'/'+ident+'/withdraw-permission'
        response=self.client.post(url,json={'reason':reason})
        self.assertEqual(response.status_code,200,response.json)
        held=response.json['asset']
        self.assertEqual(held['consentStatus'],'owner_asserted')  # original declaration is immutable
        self.assertTrue(held['permissionWithdrawn'])
        self.assertEqual(held['usageStatus'],'held_permission_withdrawn')
        self.assertEqual(held['sourceSha256'],asset['sourceSha256'])
        self.assertEqual(held['rightsStatement'],asset['rightsStatement'])
        retry=self.client.post(url,json={'reason':reason})
        self.assertEqual(retry.status_code,200)
        self.assertEqual(retry.json['asset']['withdrawnAt'],held['withdrawnAt'])
        self.assertEqual(self.client.post(url,json={'reason':'A different reason cannot replace the original.'}).status_code,400)
        self.client=self.app().test_client()
        for root in (self.root,other_root):
            selection=self.client.get(root).json['selection']
            self.assertTrue(selection['stale']);self.assertFalse(selection['approved'])
            self.assertEqual(selection['blockedAssetIds'],[ident])
            self.assertEqual(selection['assetIds'],[ident])
            # Even a client holding the pre-withdrawal version cannot reuse it.
            self.assertEqual(self.client.put(root+'/selection',json=dict(
                revision=1,selectionVersion=1,assetIds=[ident])).status_code,400)
        self.assertEqual(self.client.get(url.replace('/withdraw-permission','/original')).data,self.content)
        self.assertEqual(self.select([],version=1).status_code,200)
        self.assertFalse(self.client.get(self.root).json['selection']['stale'])
        self.assertTrue(self.client.get(other_root).json['selection']['stale'])
        from business_asset_planning import shortlist
        with sqlite3.connect(self.path) as con:
            con.row_factory=sqlite3.Row
            self.assertEqual(shortlist(con,'org-a','org-a')['assets'][0]['planningStatus'],
                             'held_permission_withdrawn')

    def test_withdrawal_requires_current_owner_org_and_document(self):
        ident=self.upload().json['asset']['assetId']
        suffix='/'+ident+'/withdraw-permission'
        reason={'reason':'Subject no longer permits this marketing use.'}
        for user,root in [(None,self.root),({'id':'owner-b'},self.root),
                          ({'id':'owner-a'},self.root.replace('org-a','org-b'))]:
            self.user=user
            response=self.client.post(root+suffix,json=reason,headers={'X-Clippr-Pilot':'local-only'})
            self.assertEqual(response.status_code,403)
        self.user={'id':'owner-b'}
        other='e'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other}).status_code,200)
        for target in (ident,'f'*32):
            response=self.client.post(self.root.replace(self.ident,other)+'/'+target+'/withdraw-permission',json=reason)
            self.assertEqual(response.status_code,403)
        self.user={'id':'owner-a'}
        for payload in ({'reason':'short'},{**reason,'owner_id':'owner-a'},{'reason':None}):
            self.assertEqual(self.client.post(self.root+suffix,json=payload).status_code,400)
        self.assertFalse(self.client.get(self.root).json['assets'][0]['permissionWithdrawn'])
        self.memberships.clear()
        self.assertEqual(self.client.post(self.root+suffix,json=reason).status_code,403)

    def test_withdrawal_failure_rolls_back_and_keeps_original_declaration(self):
        from unittest.mock import patch
        import business_campaign_assets
        ident=self.upload().json['asset']['assetId']
        self.assertEqual(self.select([ident]).status_code,200)
        with patch.object(business_campaign_assets,'saved_selection',side_effect=sqlite3.OperationalError('private table')):
            response=self.client.post(self.root+'/'+ident+'/withdraw-permission',json={
                'reason':'Owner requests a permanent hold on marketing use.'})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private table',response.get_data(as_text=True))
        library=self.client.get(self.root).json
        self.assertFalse(library['assets'][0]['permissionWithdrawn'])
        self.assertFalse(library['selection']['stale'])

    def test_identical_bytes_inherit_hold_only_within_authenticated_owner_scope(self):
        first=self.upload().json['asset']['assetId']
        duplicate=self.upload().json['asset']['assetId']
        self.assertEqual(self.select([duplicate]).status_code,200)
        response=self.client.post(self.root+'/'+first+'/withdraw-permission',json={
            'reason':'Owner withdraws permission for these exact photo bytes.'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['selection']['blockedAssetIds'],[duplicate])
        reuploaded=self.upload().json['asset']
        self.assertTrue(reuploaded['permissionWithdrawn'])
        self.assertEqual(self.select([reuploaded['assetId']],version=1).status_code,400)
        self.user={'id':'owner-b'}
        other='e'*32
        self.assertEqual(self.client.post(self.docs,json={**self.payload,'id':other}).status_code,200)
        self.root=self.root.replace(self.ident,other)
        own_copy=self.upload().json['asset']
        self.assertFalse(own_copy['permissionWithdrawn'])
        self.assertNotIn('withdrawalReason',own_copy)
        self.assertEqual(self.select([own_copy['assetId']]).status_code,200)
        self.user={'id':'owner-a'}
        org_docs=self.docs.replace('org-a','org-b')
        self.assertEqual(self.client.post(org_docs,json={**self.payload,'id':'f'*32}).status_code,200)
        self.root=org_docs+'/'+'f'*32+'/media'
        org_copy=self.upload().json['asset']
        self.assertFalse(org_copy['permissionWithdrawn'])
        self.assertNotIn('withdrawalReason',org_copy)

if __name__=='__main__':unittest.main()
