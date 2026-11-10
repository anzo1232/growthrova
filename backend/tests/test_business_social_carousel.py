"""Frozen carousel through real local media/draft/approval/worker boundaries; no network."""
import base64
import hashlib
import io
import unittest
from PIL import Image

from tests.test_business_photo_intake import PhotoIntakeTests
from business_marketing_offline import OfflineMarketingDocuments
from business_social_drafts import register_social_draft_routes
from business_social_delivery import register_social_delivery_routes, SocialDeliveryConfig


class SocialCarouselTests(unittest.TestCase):
    def test_frozen_order_reopen_explicit_capability_and_worker_bytes(self):
        f = PhotoIntakeTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        _, first, _ = f.static_post_setup('Bicycle servicing at our workshop.')
        buf = io.BytesIO()
        Image.new('RGB', (64, 64), (220, 120, 60)).save(buf, format='PNG')
        second = f.upload(file=(io.BytesIO(buf.getvalue()), 'second.png', 'image/png')).json['asset']['assetId']
        ids = [second, first]
        assignment = dict(day=1, assetIds=ids, carouselSlides=[dict(assetId=i,
            graphicText='Bicycle servicing', callToAction='Ask about servicing') for i in ids])
        self.assertEqual(f.select(ids, revision=2, version=1, postAssignments=[assignment]).status_code, 200)
        for ident in ids:
            selection = f.client.get(f.root).json['selection']
            observation = f.client.get(f.root+f'/posts/1/{ident}/original-review?revision=2&selectionVersion=2').json
            self.assertEqual(f.note(ident, dict(revision=2, selectionVersion=2, reviewVersion=selection['reviewVersion'],
                receipt=observation['reviewReceipt'], outcome='usable_candidate',
                note='Synthetic fixture for carousel delivery boundary.')).status_code, 200)
        version = f.client.get(f.root).json['selection']['reviewVersion']
        package = f.client.get(f.root+'/posts/1/carousel-preview', query_string=dict(
            revision=2, selectionVersion=2, reviewVersion=version, package='1')).json
        manifest = package['manifest']
        now = [1800000000.0]
        calls = []

        class Adapter:
            def check(self, snapshot): return True  # Insufficient for carousel.
            def deliver(self, *args, **kwargs): raise AssertionError('Single-image transport must never receive carousel')
            def reconcile(self, snapshot, **kwargs): return None

        adapter = Adapter()
        def app():
            app = f.app()
            repo = OfflineMarketingDocuments(f.path, lambda: (f.user, None),
                lambda ident, user: ({'id':ident}, None))
            root = '/offline/organisations/<organisation_id>/marketing-documents'
            account = dict(id='fixture-page', name='Fixture', accountType='page')
            register_social_draft_routes(app, repo, root, lambda *args: self.fail('No single-image compose'),
                social_accounts=lambda org: [dict(channel='facebook', state='reported', destination=account)])
            register_social_delivery_routes(app, repo, root, config=SocialDeliveryConfig(adapter=adapter,
                authorised=lambda owner, org: owner == 'owner-a' and org == 'org-a', clock=lambda:now[0]))
            return app

        client = app().test_client()
        url = f.docs+'/'+f.ident+'/social-drafts'
        payload = dict(draftId='9'*32, expectedRevision=2, operationId=f.ident, frame='carousel', format='carousel',
            day=1, selectionVersion=2, reviewVersion=version, artworkSha256=package['packageSha256'],
            channels=['facebook'], channelCaptions={'facebook':'Ask about bicycle servicing.'},
            destinationAccounts={'facebook':'fixture-page'}, localTime='2027-03-28T09:30',
            timezone='Europe/London', utcOffsetMinutes=60)
        response = client.post(url, json=payload)
        self.assertEqual(response.status_code, 201, response.json)
        self.assertEqual(client.post(url, json=payload).status_code, 200)
        self.assertEqual(client.post(url, json=dict(payload, day=2)).status_code, 409)
        application = app()  # Restart instance, same authoritative database.
        client = application.test_client()
        draft = client.get(url).json['drafts'][0]
        self.assertEqual([s['assetId'] for s in draft['manifest']['slides']], ids)
        artwork_url = url+'/'+draft['draftId']+'/artwork'
        self.assertEqual(client.get(artwork_url).data, base64.b64decode(package['packageBase64']))
        for i, slide in enumerate(manifest['slides'], 1):
            self.assertEqual(hashlib.sha256(client.get(artwork_url+'?slide='+str(i)).data).hexdigest(), slide['sha256'])
        approval = url+'/'+draft['draftId']+'/delivery/approve'
        approved = dict(expectedRevision=2, artworkSha256=draft['artworkSha256'])
        self.assertEqual(client.post(approval, json=approved).status_code, 409)
        adapter.check_carousel = lambda snapshot: snapshot['channel'] == 'facebook' and len(snapshot['slides']) == 2
        def deliver(snapshot, files, *, idempotency_key):
            calls.append((snapshot, files, idempotency_key))
            return dict(id='synthetic-receipt', outcome='simulated')
        adapter.deliver_carousel = deliver
        self.assertEqual(client.post(approval, json=approved).status_code, 201)
        self.assertEqual(client.post(approval, json=approved).status_code, 200)
        now[0] = 1816853401.0
        worker = application.extensions['growthrova_social_delivery']
        self.assertTrue(worker.run_one())
        self.assertFalse(worker.run_one())
        self.assertEqual(len(calls), 1)
        snapshot, files, _ = calls[0]
        self.assertEqual([hashlib.sha256(b).hexdigest() for b in files], [s['sha256'] for s in manifest['slides']])
        self.assertEqual(snapshot['caption'], payload['channelCaptions']['facebook'])
        f.user = {'id':'foreign-owner'}
        self.assertEqual(client.get(artwork_url+'?slide=1').status_code, 403)
