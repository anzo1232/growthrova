"""Actual leaked Clippr directions must be held before image spending, never rewritten."""
import copy
import json
import unittest
from pathlib import Path

from tests import test_business_art_direction as fixtures
from tests import test_business_image_batches as batches


class ImageSetInstructionRecoveryTests(unittest.TestCase):
    setUp = batches.ImageBatchTests.setUp
    prepare = batches.ImageBatchTests.prepare

    def test_saved_set_explains_direction_hold_without_claiming_model_changed(self):
        import sqlite3
        from contextlib import closing
        from dataclasses import replace
        from unittest.mock import patch
        f = self.f
        authority = patch('business_growthrova_images.AUTHORISED_IMAGE_CALL_MICROUSD', 300000)
        authority.start()
        self.addCleanup(authority.stop)
        f.config = replace(f.config, model='gemini-3-pro-image', output_cost_microusd=234000,
                           budget_microusd=1000000, call_cap_microusd=300000)
        self.assertTrue(f.config.available(), 'Synthetic funded provider is required to exercise preflight')
        f.client = f.create(image_config=f.config, image_http=f.provider).test_client()
        doc = copy.deepcopy(f.doc)
        doc['brandKit'] = dict(name='Synthetic Workshop', primary_color='#123456',
                              secondary_color='#FFFFFF', font_style='modern')
        f.save_document(doc, 1, '8')
        self.data['expectedRevision'] = 2
        self.plan['brandKit'] = doc['brandKit']
        before = f.client.get(f.root+'/'+f.ident, headers=f.headers).json
        actual = json.loads(Path('docs/evidence/real-clippr-content-20261104/concepts.json').read_text())['concepts']
        for concept, observed in zip(self.plan['concepts'], actual):
            concept['visualDirection'] = observed['visualDirection']
        with closing(sqlite3.connect(f.path)) as con:
            con.execute('UPDATE growthrova_writing_requests SET result_json=? WHERE operation_id=?',
                        (json.dumps(self.plan), self.plan_id))
            con.commit()
        result = self.prepare(renderingMode='complete_advert')
        self.assertEqual(result.status_code, 200, result.json)
        batch = result.json
        self.assertEqual(batch['funding']['state'], 'direction_held')
        self.assertTrue(all(s['funding']['state']=='direction_held' for s in batch['slots']))
        self.assertIsNone(batch['funding']['plannedReservationMicrousd'])
        self.assertEqual(batch['funding']['reservedMicrousd'], 0)
        reopened = f.create(image_config=f.config, image_http=f.provider).test_client().get(f.url, headers=f.headers).json['batches'][0]
        self.assertEqual(reopened, batch)
        denied = f.client.post(f.url+'/batches/'+self.data['batchId']+'/slots/0',
                               headers=f.headers, json={'expectedRevision':2})
        self.assertEqual(denied.status_code, 400, denied.json)
        self.assertEqual(denied.json['code'], 'artwork_instruction_conflict')
        self.assertEqual(f.provider.calls, [])
        self.assertEqual(f.client.get(f.root+'/'+f.ident, headers=f.headers).json, before)
        with closing(sqlite3.connect(f.path)) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM growthrova_image_requests').fetchone()[0], 0)
            saved = json.loads(con.execute('SELECT result_json FROM growthrova_writing_requests WHERE operation_id=?',
                                          (self.plan_id,)).fetchone()[0])
        self.assertEqual(saved, self.plan)


class ArtworkInstructionTests(unittest.TestCase):
    setUp = fixtures.AdvertArtDirectionTests.setUp
    generate = fixtures.AdvertArtDirectionTests.generate
    def test_actual_labelled_directions_are_rejected_before_dispatch_without_changing_saved_work(self):
        saved = self.flow.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json
        concepts = json.loads(Path('docs/evidence/real-clippr-content-20261104/concepts.json').read_text())['concepts']
        for concept in concepts:
            with self.subTest(headline=concept['headline']):
                response = self.generate(visualBrief=concept['visualDirection'])
                self.assertEqual(response.status_code, 400, response.json)
                self.assertEqual(response.json['code'], 'artwork_instruction_conflict')
        self.assertEqual(self.flow.provider.calls, [])
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(self.base.path)) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM growthrova_image_requests').fetchone()[0], 0)
        self.assertEqual(self.flow.client.get(self.base.root+'/'+self.base.ident, headers=self.base.headers).json, saved)

    def test_clean_photographic_direction_keeps_exact_copy_and_no_internal_review_metadata(self):
        response = self.generate(visualBrief='A photorealistic microphone and physical film strip, lime light on dark material. Keep clear margins.')
        self.assertEqual(response.status_code, 200, response.json)
        prompt = self.flow.provider.calls[0][1]['json']['contents'][0]['parts'][0]['text']
        source = json.loads(prompt.split('SOURCE DATA:\n')[1])
        self.assertNotIn('review', source['artDirectionBrief'])
        self.assertNotIn('exactLogoRegionPercent', source['artDirectionBrief']['brandTreatment'])


class PlanningInstructionTests(unittest.TestCase):
    setUp = fixtures.PlanningArtDirectionTests.setUp
    create = fixtures.PlanningArtDirectionTests.create

    def test_actual_six_concepts_are_held_for_review_with_originals_intact(self):
        from business_creative_plans import concept_issues
        result = json.loads(Path('docs/evidence/real-clippr-content-20261104/concepts.json').read_text())
        before = copy.deepcopy(result)
        issues = concept_issues(result['concepts'], result['material'])
        self.assertEqual(len([issue for issue in issues if 'internal illustrative' in issue]), 6)
        self.assertEqual(result, before)
    def test_planner_does_not_receive_local_export_coordinates_or_review_instructions(self):
        from business_growthrova_writer import provider_payload, source_material
        material = source_material(self.doc)
        before = copy.deepcopy(material)
        payload, _ = provider_payload(self.config, material, 'warm and informative',
            plan=dict(mode='initial', parentOperationId='', conceptId=''))
        brief = json.loads(payload['input'][0]['content'])['artDirectionBrief']
        self.assertNotIn('exactLogoRegionPercent', brief['brandTreatment'])
        self.assertNotIn('logoSpace', brief['brandTreatment'])
        self.assertNotIn('review', brief)
        self.assertEqual(material, before)

    def test_provenance_description_and_explicit_no_label_instruction_are_not_print_requests(self):
        from business_art_direction import artwork_instruction_issue
        for direction in ('An illustrative scene of a microphone; no actual customer is depicted.',
                          'Never add an Illustrative concept label. Keep the CTA legible.',
                          'Do not label the photograph Illustrative scene.'):
            with self.subTest(direction=direction):
                self.assertIsNone(artwork_instruction_issue(direction))
