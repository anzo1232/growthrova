"""Product-assembled briefs; synthetic HTTP proves assembly, never art quality."""
import copy
import json
import unittest

from tests import test_business_creative_plans as plans
from tests import test_business_complete_advert as adverts


class PlanningArtDirectionTests(unittest.TestCase):
    setUp = plans.CreativePlanTests.setUp
    create = plans.CreativePlanTests.create
    write = plans.CreativePlanTests.write

    def test_confirmed_business_shapes_brief_without_unreviewed_research_claims(self):
        self.provider.sample = plans.concepts()
        response = self.write(creativePlan=dict(mode='initial', parentOperationId='', conceptId=''))
        self.assertEqual(response.status_code, 200, response.json)
        sent = json.loads(self.provider.calls[0][1]['json']['input'][0]['content'])
        brief = sent.get('artDirectionBrief')
        self.assertIsInstance(brief, dict, 'Actual concept request needs a product-assembled art brief')
        self.assertEqual(brief['business'], self.doc['business'])
        self.assertEqual(brief['goal']['value'], self.doc['goal'])
        self.assertEqual(brief['audience']['value'], self.doc['ownerStrategy']['audience'])
        self.assertEqual(brief['proposition']['quote'], self.doc['ownerStrategy']['offer'])
        self.assertEqual(brief['proposition']['id'], 'brief-offer')
        self.assertEqual(brief['artworkMode'], 'complete_advert')
        self.assertEqual(brief['brand'], None, 'No invented palette or logo for an unsaved brand')
        self.assertEqual(brief['creativeProfile']['identity']['businessName'], self.doc['business'])
        self.assertEqual(brief['creativeProfile']['identity']['palette'], [])
        self.assertTrue(any('unrelated company' in rule for rule in brief['creativeProfile']['creativeRules']))
        self.assertNotIn('exactLogoRegionPercent', brief['brandTreatment'])
        self.assertEqual(brief['diversityDimensions'], ['buyer_motivation', 'visual_subject', 'composition', 'type_hierarchy'])
        self.assertEqual(self.write(creativePlan=dict(mode='initial', parentOperationId='', conceptId='')).json, response.json)
        self.assertEqual(len(self.provider.calls), 1)

    def test_brief_uses_only_eligible_proposition_and_does_not_mutate_material(self):
        from business_growthrova_writer import provider_payload, source_material
        material = source_material(self.doc)
        material['evidence'] = [item for item in material['evidence'] if item['id'] != 'brief-offer']
        material['evidence'].append(dict(id='brief-offer', quote='Unreviewed free lifetime service.',
                                         status='website_claim_unconfirmed', sourceUrl='https://example.org'))
        before = copy.deepcopy(material)
        payload, _ = provider_payload(self.config, material, 'warm and informative',
            plan=dict(mode='initial', parentOperationId='', conceptId=''))
        sent = json.loads(payload['input'][0]['content'])
        brief = sent.get('artDirectionBrief')
        self.assertIsInstance(brief, dict)
        self.assertIsNone(brief['proposition'], 'An unreviewed offer cannot become the supporting proposition')
        self.assertNotIn('Unreviewed free lifetime service', json.dumps(brief))
        self.assertEqual(material, before)

    def test_contrasting_businesses_keep_their_own_offer_goal_and_brand(self):
        from business_growthrova_writer import provider_payload, source_material
        for name, offer, goal, audience, colour in (
                ('Harbour Plumbing', 'Plumbing enquiries for local homes.', 'Generate service enquiries',
                 'Local homeowners', '#123456'),
                ('SignalNest AI', 'Prelaunch assistant drafts replies from help articles for human review.',
                 'Request early access', 'Small support teams', '#654321')):
            with self.subTest(business=name):
                material = source_material(self.doc)
                material.update(business=name, goal=dict(value=goal, status='owner_planning_input'),
                                audience=dict(value=audience, status='owner_planning_input'))
                for item in material['evidence']:
                    if item['id'] == 'brief-offer':
                        item['quote'] = offer
                brand = dict(name=name, primary_color=colour, secondary_color='#FFFFFF', font_style='modern')
                payload, _ = provider_payload(self.config, material, 'warm and informative',
                    plan=dict(mode='initial', parentOperationId='', conceptId=''), brand=brand)
                brief = json.loads(payload['input'][0]['content'])['artDirectionBrief']
                self.assertEqual(brief['business'], name)
                self.assertEqual(brief['proposition']['quote'], offer)
                self.assertEqual(brief['goal']['value'], goal)
                self.assertEqual(brief['audience']['value'], audience)
                self.assertEqual(brief['brand'], brand)
                self.assertEqual(brief['creativeProfile']['identity']['businessName'], name)
                self.assertEqual(brief['creativeProfile']['identity']['palette'], [colour, '#FFFFFF'])
                self.assertEqual(brief['creativeProfile']['commercialCore']['offer']['quote'], offer)
                self.assertTrue(any('generic' in rule.lower() or 'default' in rule.lower()
                                    for rule in brief['creativeProfile']['antiGeneric']))
                self.assertNotIn('bookkeeping', json.dumps(brief).lower())


class AdvertArtDirectionTests(unittest.TestCase):
    setUp = adverts.CompleteAdvertTests.setUp
    generate = adverts.CompleteAdvertTests.generate

    def test_missing_advert_headline_is_actionable_before_estimate_or_generation(self):
        doc = self.flow.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json['document']
        doc['posts'][0].pop('graphicText', None)
        self.base.save_document(doc, 2, '8')
        result = self.generate(expectedRevision=3)
        self.assertEqual(result.status_code, 400, result.json)
        self.assertIn('headline', result.json['error'].lower())
        self.assertEqual(len(self.flow.provider.calls), 0)
        estimate = self.flow.client.post(self.base.url+'/estimate', headers=self.base.headers,
            json={**self.base.data, 'expectedRevision': 3, 'renderingMode': 'complete_advert',
                  'size': 'portrait_2k', 'quality': 'standard'})
        self.assertEqual(estimate.status_code, 400, estimate.json)
        self.assertIn('headline', estimate.json['error'].lower())
        self.assertEqual(len(self.flow.provider.calls), 0)
        self.assertNotIn('graphicText', self.flow.client.get(self.base.root+'/'+self.base.ident,
                          headers=self.base.headers).json['document']['posts'][0])

    def test_advert_reserves_the_same_logo_space_used_by_exact_asset_export(self):
        import math
        from PIL import Image, ImageChops
        from business_brand_render import compose_static_post

        response = self.generate()
        self.assertEqual(response.status_code, 200, response.json)
        prompt = self.flow.provider.calls[0][1]['json']['contents'][0]['parts'][0]['text']
        source = json.loads(prompt.split('SOURCE DATA:\n', 1)[1])
        # Real provider output reproduced these internal percentages and boxes.
        # The model gets natural-language spacing; exact coordinates stay local.
        self.assertNotIn('exactLogoRegionPercent', source['artworkLayout'])
        self.assertNotIn('textSafeInsetPercent', source['artworkLayout'])
        self.assertNotIn('exactLogoRegionPercent', source['artDirectionBrief']['brandTreatment'])
        self.assertEqual(source['channelCreativeBrief']['requestedFrame'], 'square_2k')
        self.assertEqual(source['channelCreativeBrief']['funnelStage'], 'attention')
        self.assertEqual(len(source['channelCreativeBrief']['qualityBar']), 5)
        self.assertIn('phone', source['channelCreativeBrief']['qualityBar'][3])
        from business_brand_render import EXACT_LOGO_REGION_PERCENT
        region = EXACT_LOGO_REGION_PERCENT
        self.assertEqual(region, dict(left=72, top=8, width=20, height=12))
        for size in ((1792, 2400), (2048, 2048), (1536, 2752)):
            for logo_size in ((600, 60), (60, 600)):
                with self.subTest(size=size, logo=logo_size), Image.new('RGB', size, '#123456') as photo, Image.new('RGBA', logo_size, '#ffaa33') as logo:
                    output, layout = compose_static_post(photo, source['brandKit'],
                        source['advertCopy']['headline'], source['advertCopy']['callToAction'],
                        logo=logo, frame='original', layout='logo-only')
                    with output:
                        x, y, w, h = layout['logoBox']
                        self.assertGreaterEqual(x, math.floor(size[0]*region['left']/100))
                        self.assertEqual(y, round(size[1]*region['top']/100))
                        self.assertLessEqual(x+w, size[0]-round(size[0]*.08))
                        self.assertLessEqual(h, round(size[1]*region['height']/100))
                        self.assertEqual(ImageChops.difference(photo, output).getbbox(), (x,y,x+w,y+h))
        self.assertEqual(self.generate().json, response.json)
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_final_advert_receives_same_context_exact_copy_and_destination_separately(self):
        doc = self.flow.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json['document']
        doc['posts'][0].update(supportingLine='Bicycle servicing and brake adjustments.',
                               destinationUrl='https://example.org/service-enquiry')
        self.base.save_document(doc, 2, '8')
        response = self.generate(expectedRevision=3)
        self.assertEqual(response.status_code, 200, response.json)
        prompt = self.flow.provider.calls[0][1]['json']['contents'][0]['parts'][0]['text']
        source = json.loads(prompt.split('SOURCE DATA:\n', 1)[1])
        brief = source.get('artDirectionBrief')
        self.assertIsInstance(brief, dict, 'Paid adapter must consume product art direction too')
        self.assertEqual(brief['proposition']['quote'], doc['ownerStrategy']['offer'])
        self.assertEqual(brief['brand'], source['brandKit'])
        for key, value in doc['brandKit'].items():
            self.assertEqual(brief['brand'][key], value)
        self.assertEqual(source['advertCopy']['supportingLine'], doc['posts'][0]['supportingLine'])
        self.assertEqual(source['artworkLayout']['destinationUrl'], doc['posts'][0]['destinationUrl'])
        self.assertEqual(source['artworkLayout']['destinationTreatment'], 'context_only_not_generated_wording')
        self.assertNotIn(doc['posts'][0]['copyDraft'], prompt)
        self.assertEqual(self.generate(expectedRevision=3).json, response.json)
        self.assertEqual(len(self.flow.provider.calls), 1)

    def test_background_mode_keeps_existing_no_lettering_contract(self):
        response = self.flow.generate(expectedRevision=2)
        self.assertEqual(response.status_code, 200, response.json)
        prompt = self.flow.provider.calls[0][1]['json']['contents'][0]['parts'][0]['text']
        source = json.loads(prompt.split('SOURCE DATA:\n', 1)[1])
        self.assertNotIn('artDirectionBrief', source)
        self.assertNotIn('advertCopy', source)


if __name__ == '__main__':
    unittest.main()
