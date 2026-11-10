"""Saved campaign brand settings remain drafts, never media rights or approval."""
import copy, json, subprocess, tempfile, unittest
from pathlib import Path
from business_marketing_drafts import normalise_document, MarketingDraftError
from business_marketing_offline import OfflineMarketingDocuments
from tests.test_business_marketing_drafts import document


class CampaignBrandTests(unittest.TestCase):
    def test_exact_brand_survives_scoped_store_reopen_without_copy_changes(self):
        doc=document()
        doc['posts'][0]['status']='copy_reviewed'
        original=copy.deepcopy(doc)
        doc['brandKit']={'name':'Workshop & Co','primary_color':'#123abc',
                         'secondary_color':'#123abc','font_style':'classic'}
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'campaigns.sqlite3')
            def repo():
                return OfflineMarketingDocuments(path,lambda: ({'id':'synthetic-owner'},None),
                                                  lambda org,user: ({'id':org},None))
            saved=repo().save('synthetic-org',{'id':'b'*32,'mutationId':'c'*32,
                                             'expectedRevision':0,'document':doc})
            reopened=repo().read('synthetic-org',saved['id'])['document']
            self.assertEqual(reopened['brandKit'],doc['brandKit'])
            self.assertEqual(reopened['posts'],normalise_document(original)['posts'])
            self.assertFalse(reopened['canPublish'])
            self.assertFalse(reopened['canSpend'])
            doc['brandKit']['name']='Changed brand'
            repo().save('synthetic-org',{'id':saved['id'],'mutationId':'d'*32,
                                       'expectedRevision':1,'document':doc})
            self.assertEqual(repo().read('synthetic-org',saved['id'])['document']['brandKit']['name'],'Changed brand')

    def test_js_python_parity_for_incomplete_exact_and_invalid_brand_settings(self):
        valid=[{'name':'','primary_color':'','secondary_color':'','font_style':''},
               {'name':'Workshop','primary_color':'#000000','secondary_color':'#FFFFFF','font_style':'bold'}]
        invalid=[None,[],{},dict(valid[1],primary_color='red'),dict(valid[1],name='x'*39),
                 dict(valid[1],font_style='custom'),dict(valid[1],name='Line\nbreak'),
                 dict(valid[1],logo_path='/tmp/logo.png'),dict(valid[1],approved=True)]
        values=valid+invalid
        script="""import {normaliseCampaignBrand} from './src/lib/businessCampaignBrand.mjs';
          const values=JSON.parse(process.argv[1]);
          console.log(JSON.stringify(values.map(value=>{try{return normaliseCampaignBrand(value);}catch{return null;}})));"""
        run=subprocess.run(['node','--input-type=module','-e',script,json.dumps(values)],
                           capture_output=True,text=True,cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout),valid+[None]*len(invalid))
        for value in valid:
            with self.subTest(value=value):
                doc=document();doc['brandKit']=value
                self.assertEqual(normalise_document(doc)['brandKit'],value)
        for value in invalid:
            with self.subTest(value=value):
                doc=document();doc['brandKit']=value
                with self.assertRaises(MarketingDraftError):normalise_document(doc)
        self.assertNotIn('brandKit',normalise_document(document()),'Historical campaigns gain no inferred brand.')


    def test_source_bound_visual_identity_survives_without_becoming_approval(self):
        doc=document()
        doc['brandKit']={'name':'Workshop','primary_color':'#0C0C0F','secondary_color':'#02FFB2','font_style':'modern'}
        doc['brandIdentity']={'status':'website_observed_unconfirmed','sourceUrl':'https://example.org/',
          'capturedAt':'2026-11-09T20:00:00+00:00','method':'rendered_computed_styles',
          'roles':{'background':'#0C0C0F','text':'#FFFFFF','accent':'#02FFB2'},
          'colours':[{'hex':'#FFFFFF','count':20},{'hex':'#02FFB2','count':2}],
          'fontFamilies':[{'family':'Inter','count':12}],
          'logoCandidates':[{'kind':'image_url','url':'https://cdn.example.org/logo.png','description':'Organisation logo'}],
          'suggestedBrandKit':{'primary_color':'#0C0C0F','secondary_color':'#02FFB2','font_style':'modern'}}
        result=normalise_document(doc)
        self.assertEqual(result['brandIdentity'],doc['brandIdentity'])
        self.assertFalse(result['canPublish']);self.assertFalse(result['canSpend'])
        changed=copy.deepcopy(doc);changed['brandIdentity']['sourceUrl']='https://other.example/'
        with self.assertRaises(MarketingDraftError):normalise_document(changed)

    def test_graphic_words_are_optional_bounded_and_invalidate_only_changed_review(self):
        doc=document()
        old=normalise_document(doc)
        self.assertNotIn('graphicText',old['posts'][0])
        doc['posts'][0].update(graphicText='Bicycle servicing at our workshop.',status='copy_reviewed')
        cleaned=normalise_document(doc)
        self.assertEqual(cleaned['posts'][0]['graphicText'],doc['posts'][0]['graphicText'])
        self.assertEqual(cleaned['posts'][0]['status'],'copy_reviewed')
        changed=copy.deepcopy(cleaned)
        changed['posts'][0]['graphicText']='Make room for your next project.'
        result=normalise_document(changed,previous=cleaned)
        self.assertEqual(result['posts'][0]['status'],'draft')
        self.assertEqual(result['posts'][0]['copyDraft'],cleaned['posts'][0]['copyDraft'])
        self.assertEqual(result['posts'][1:],cleaned['posts'][1:])
        removed=copy.deepcopy(cleaned)
        del removed['posts'][0]['graphicText']
        self.assertEqual(normalise_document(removed,previous=cleaned)['posts'][0]['status'],'draft')
        for bad in (None,42,'x'*501):
            with self.subTest(bad=str(bad)[:20]), self.assertRaises(MarketingDraftError):
                changed['posts'][0]['graphicText']=bad
                normalise_document(changed)
