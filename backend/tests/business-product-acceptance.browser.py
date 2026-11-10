"""Hermetic Business browser acceptance: real UI + HTTP + SQLite + FFmpeg.

Website HTML is a deterministic fixture. No live auth, model, billing, social or
storage providers are contacted. Local ports and the database are per-run.
"""
from __future__ import annotations
import json
import io
import hashlib
import zipfile
import os
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright, expect
import business_local_pilot as pilot
from PIL import Image
from business_website_analysis import extract_website

ROOT=Path(__file__).resolve().parents[1]
REPORT=Path(os.environ.get('CLIPPR_ACCEPTANCE_REPORT_DIR','/tmp/clippr-business-architect-20261018'))
REPORT.mkdir(parents=True,exist_ok=True)
checks={}
slow_started=threading.Event()
slow_release=threading.Event()
HTML=b'<html><title>Fixture Restaurant</title><meta name="description" content="Seasonal restaurant dining with a menu and a table enquiry service"><meta property="og:image" content="/media/restaurant.jpg"><h1>Seasonal dining</h1><h2>Our menu</h2><p>Seasonal dishes served in a local restaurant with a table enquiry service and weekend brunch options.</p></html>'

def website_fixture(url):
    if url=='https://slow.example.org/':
        slow_started.set()
        if not slow_release.wait(8): raise RuntimeError('Fixture response was not released')
    return extract_website(url,resolve=lambda *a,**k:[(None,None,None,None,('93.184.215.14',443))],fetch=lambda *a:HTML)

def main():
    with tempfile.TemporaryDirectory(prefix='clippr-acceptance-') as folder:
        temp=Path(folder)
        pilot.BASE=temp/'database'
        pilot.extract_website=website_fixture
        # Provider responses and image bytes are fixtures. All HTTP, SQLite,
        # no-duplicate admission, authenticated asset retrieval and UI are real.
        provider_calls={'submissions':0,'task_reads':0}
        class FixtureRunway:
            def balance(self):return 1000
            def submit_image(self,payload):
                provider_calls['submissions']+=1
                assert payload['outputCount']==1
                return {'id':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'}
            def task(self,task_id):
                provider_calls['task_reads']+=1
                return {'id':task_id,'status':'SUCCEEDED','output':['https://fixture-output.example/concept.png'],'cost':{'credits':20}}
        def store_fixture_image(url,destination):
            assert url=='https://fixture-output.example/concept.png'
            destination.parent.mkdir(parents=True,exist_ok=True)
            Image.new('RGB',(640,800),(36,53,67)).save(destination,format='PNG')
            data=destination.read_bytes()
            return {'width':640,'height':800,'bytes':len(data),'mime':'image/png','sha256':hashlib.sha256(data).hexdigest()}
        pilot.runway.RunwayClient=FixtureRunway
        pilot.runway._store_output=store_fixture_image
        real_import=pilot.website_media.import_photo
        def fake_website_import(*args,**kwargs):
            image=io.BytesIO();Image.new('RGB',(1024,768),(87,132,163)).save(image,'JPEG')
            return real_import(*args,**{**kwargs,'fetch':lambda *a:(image.getvalue(),'image/jpeg'),
                'resolve':lambda *a,**k:[(None,None,None,None,('93.184.215.14',443))]})
        pilot.website_media.import_photo=fake_website_import
        os.environ['CLIPPR_BUSINESS_RUNWAY_TEST_CAP']='20'
        backend=ThreadingHTTPServer(('127.0.0.1',0),pilot.Handler)
        backend_url='http://127.0.0.1:'+str(backend.server_port)
        thread=threading.Thread(target=backend.serve_forever,daemon=True)
        thread.start()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); front_port=sock.getsockname()[1]
        front='http://127.0.0.1:'+str(front_port)
        pilot.VALID_ORIGINS=frozenset({front})
        ready=temp/'vite-ready.json'
        node_script="""
import {createServer} from 'vite';
import react from '@vitejs/plugin-react';
import {writeFileSync} from 'node:fs';
const server=await createServer({root:process.cwd(),configFile:false,
  envDir:process.env.TEST_ENV_DIR,cacheDir:process.env.TEST_CACHE_DIR,plugins:[react()],logLevel:'error',
  server:{host:'127.0.0.1',port:Number(process.env.TEST_FRONT_PORT),strictPort:true,hmr:false}});
await server.listen(); writeFileSync(process.env.TEST_READY_FILE,'ready');
"""
        env={**os.environ,'TEST_ENV_DIR':str(temp),'TEST_FRONT_PORT':str(front_port),'TEST_READY_FILE':str(ready),'TEST_CACHE_DIR':str(temp/'vite-cache')}
        log=(REPORT/'acceptance-vite.log').open('w')
        vite=subprocess.Popen(['node','--input-type=module','-e',node_script],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+15
            while not ready.exists() and time.monotonic()<deadline:
                if vite.poll() is not None: raise RuntimeError('Vite failed; see acceptance-vite.log')
                time.sleep(.1)
            assert ready.exists(),'Vite startup timed out'
            fixture=temp/'synthetic-24s.mp4'
            subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=12:duration=24',
                '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart',str(fixture)],check=True,timeout=30,capture_output=True)
            with sync_playwright() as pw:
                chrome=os.environ.get('CLIPPR_TEST_BROWSER')
                default='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
                if not chrome and Path(default).exists(): chrome=default
                browser=pw.chromium.launch(**({'executable_path':chrome} if chrome else {}),headless=True)
                context=browser.new_context(viewport={'width':1365,'height':1000},accept_downloads=True,service_workers='block')
                errors=[];external=[]
                def guard(route):
                    url=route.request.url
                    if url.startswith(front+'/'): return route.continue_()
                    if url.startswith('http://127.0.0.1:4192/api/pilot/'):
                        path=urlsplit(url)
                        return route.continue_(url=backend_url+path.path+('?' + path.query if path.query else ''))
                    external.append(urlsplit(url).netloc)
                    route.abort('blockedbyclient')
                context.route('**/*',guard)
                # Product-facing path: one URL, immediate campaign, saved automatically.
                agency=context.new_page()
                agency.on('pageerror',lambda error:errors.append(str(error)))
                agency.goto(front+'/business-agency.html',wait_until='domcontentloaded',timeout=20000)
                expect(agency.get_by_role('heading',name='Your marketing, sorted.')).to_be_visible(timeout=12000)
                agency.get_by_label('Business website URL',exact=True).fill('https://fresh-restaurant.example.org/')
                agency.get_by_role('button',name='Build my marketing').click()
                section=agency.get_by_role('region',name='Marketing campaign editor')
                expect(section).to_be_visible(timeout=12000)
                expect(section.get_by_text('Saved revision 1',exact=True)).to_be_visible(timeout=12000)
                new_id=agency.url.split('marketingDraft=')[-1]
                assert len(new_id)==32
                checks['agency_url_to_autosaved_campaign']=True
                # Real application navigation must preserve unsaved work when
                # the website form resolves another campaign or the current one.
                campaign_name=section.get_by_label('Name of your marketing',exact=True)
                original_name=campaign_name.input_value()
                campaign_name.fill('Unsaved name retained while choosing another website')
                agency.get_by_role('button',name='Build my marketing').click()
                expect(agency.get_by_text('Your current campaign is open. Save your changes when ready.',exact=True)).to_be_visible()
                expect(campaign_name).to_have_value('Unsaved name retained while choosing another website')
                navigation_dialogs=[]
                def cancel_navigation(dialog):
                    navigation_dialogs.append(dialog.message);dialog.dismiss()
                agency.once('dialog',cancel_navigation)
                agency.get_by_label('Business website URL',exact=True).fill('https://second-restaurant.example.org/')
                agency.get_by_role('button',name='Build my marketing').click()
                expect(agency.get_by_text('Your current unsaved edits are still open.',exact=True)).to_be_visible(timeout=15000)
                assert len(navigation_dialogs)==1 and 'unsaved campaign or Reel caption edits' in navigation_dialogs[0]
                assert agency.url.split('marketingDraft=')[-1]==new_id
                expect(campaign_name).to_have_value('Unsaved name retained while choosing another website')
                def accept_navigation(dialog):
                    navigation_dialogs.append(dialog.message);dialog.accept()
                agency.once('dialog',accept_navigation)
                agency.get_by_role('button',name='Build my marketing').click()
                expect(campaign_name).to_have_value(original_name,timeout=15000)
                second_id=agency.url.split('marketingDraft=')[-1]
                assert second_id!=new_id and len(navigation_dialogs)==2
                agency.get_by_label('Business website URL',exact=True).fill('https://fresh-restaurant.example.org/')
                agency.get_by_role('button',name='Build my marketing').click()
                expect(agency.get_by_text('Campaign saved — ready for review',exact=True)).to_be_visible()
                assert agency.url.split('marketingDraft=')[-1]==new_id
                expect(campaign_name).to_have_value(original_name)
                with pilot.session() as con:
                    assert pilot.marketing_drafts.read_draft(con,new_id)['document']['name']==original_name
                checks['website_form_keeps_dirty_current_campaign_and_honours_cancel_or_discard']=True
                # The Board's own selector may diverge from the outer form's
                # last campaign. Confirmed navigation must still remount the
                # requested campaign when it equals that earlier outer ID.
                saved_campaigns=section.get_by_label('Saved marketing campaigns',exact=True)
                saved_campaigns.select_option(second_id)
                expect(section.locator('.bmb-source')).to_contain_text('https://second-restaurant.example.org/')
                campaign_name.fill('Unsaved edit in the campaign opened inside the editor')
                agency.once('dialog',accept_navigation)
                agency.get_by_role('button',name='Build my marketing').click()
                expect(saved_campaigns).to_have_value(new_id,timeout=15000)
                expect(campaign_name).to_have_value(original_name)
                expect(section.locator('.bmb-source')).to_contain_text('https://fresh-restaurant.example.org/')
                assert agency.url.split('marketingDraft=')[-1]==new_id and len(navigation_dialogs)==3
                checks['website_form_switches_after_editor_navigated_independently']=True
                kit_section=agency.get_by_role('region',name='Complete marketing kit')
                expect(kit_section).to_be_visible(timeout=12000)
                expect(kit_section.get_by_text('Automatic bulk rendering paused.',exact=True)).to_be_visible(timeout=12000)
                with pilot.session() as con:
                    assert con.execute('SELECT COUNT(*) FROM marketing_pack_jobs WHERE draft_id=?',(new_id,)).fetchone()[0]==0
                    saved=pilot.marketing_drafts.read_draft(con,new_id)
                    legacy_document={**saved['document'],'editorialShortlist':None,
                        'name':'Fixture Restaurant — historical campaign QA'}
                    # One business-evidence-based candidate for the legacy exact
                    # post approval test; all other legacy mock-ups remain drafts.
                    legacy_document['posts'][0]['channel']='Instagram'
                    legacy_document['posts'][0]['format']='Image advert'
                    legacy_document['posts'][0]['theme']='Seasonal weekend brunch menu'
                    legacy_document['posts'][0]['copyDraft']=(
                      'Fixture Restaurant describes seasonal dishes and weekend brunch. '
                      'Please check the current menu and arrange a suitable table with the restaurant.')
                    legacy_document['posts'][0]['callToAction']='Ask about the current weekend brunch menu'
                    # A reviewed caption cannot make a PNG satisfy a Reel brief.
                    legacy_document['posts'][1]['format']='Reel concept'
                    legacy_document['posts'][1]['status']='copy_reviewed'
                    first_id=uuid.uuid4().hex
                    pilot.marketing_drafts.save_draft(con,{'id':first_id,'mutationId':uuid.uuid4().hex,
                        'expectedRevision':0,'document':legacy_document})
                checks['agency_new_campaign_blocks_generic_bulk_export']=True
                # Existing saved draft compatibility remains independently tested.
                agency.goto(front+'/business-agency.html?marketingDraft='+first_id,wait_until='domcontentloaded')
                expect(section.get_by_text('Saved revision 1',exact=True)).to_be_visible(timeout=15000)
                expect(section.get_by_text('30',exact=True).first).to_be_visible()
                expect(section.get_by_text('7',exact=True).first).to_be_visible()
                expect(kit_section.get_by_text('Draft creative held · brand and imagery need review',exact=True)).to_be_visible(timeout=35000)
                kit_section.get_by_role('checkbox',name='Show rejected/unapproved mock-ups for internal inspection only').check()
                expect(kit_section.get_by_role('button',name='02 5-page slideshow 5 pages')).to_be_visible(timeout=10000)
                kit_section.get_by_role('button',name='02 5-page slideshow 5 pages').click()
                expect(kit_section.get_by_role('img',name='Carousel slide 1')).to_be_visible(timeout=10000)
                with agency.expect_download(timeout=15000) as archived:
                    kit_section.get_by_role('button',name='Download all my marketing ↓').click()
                archive_file=temp/'full-agency-kit.zip';archived.value.save_as(archive_file)
                with zipfile.ZipFile(archive_file) as archive:
                    assert 'short-video-concept.mp4' in archive.namelist()
                    assert 'website-landing-page.html' in archive.namelist()
                    site_preview=archive.read('website-landing-page.html').decode('utf-8')
                    assert 'DRAFT PREVIEW' in site_preview and 'noindex, nofollow' in site_preview
                    assert '<form' not in site_preview and '<script' not in site_preview
                    assert 'email-sequence.md' in archive.namelist()
                    assert 'seo-opportunities.md' in archive.namelist()
                    assert 'lead-capture-plan.md' in archive.namelist()
                    assert len([n for n in archive.namelist() if n.startswith('carousel-')])==5
                    assert len([n for n in archive.namelist() if n.startswith('post-day-')])==30
                kit_section.get_by_role('button',name='06 Website page preview HTML draft').click()
                frame=kit_section.frame_locator('iframe[title="Website landing page draft"]')
                expect(frame.get_by_text('DRAFT PREVIEW',exact=False)).to_be_visible(timeout=15000)
                with agency.expect_download(timeout=15000) as website_download:
                    kit_section.get_by_role('button',name='Download this website draft ↓').click()
                exported=temp/'website-page.html';website_download.value.save_as(exported)
                assert 'noindex, nofollow' in exported.read_text()
                checks['downloadable_website_page_rendered_no_forms_or_scripts']=True
                kit_section.get_by_role('button',name='05 30 pictures for your posts 30 pictures').click()
                kit_section.get_by_role('button',name='30',exact=True).click()
                expect(kit_section.get_by_role('img',name='Social post day 30')).to_be_visible(timeout=12000)
                checks['agency_full_media_and_strategy_pack']=True
                # The generated plan must contain distinct actual copy rather than
                # the former seven rotating 'potential customers' placeholders.
                agency_posts=agency.evaluate('''async ()=>{
                  const id=new URL(location.href).searchParams.get('marketingDraft');
                  const response=await fetch('http://127.0.0.1:4192/api/pilot/marketing-drafts/'+id,{
                    headers:{'X-Clippr-Pilot':'local-only'}});
                  if(!response.ok)throw Error('Campaign read failed');
                  return (await response.json()).document.posts.map(p=>({theme:p.theme,copy:p.copyDraft}));
                }''')
                assert len(set(p['theme'] for p in agency_posts))==30
                assert len(set(p['copy'] for p in agency_posts))==30
                assert all(len(p['copy'])>65 and 'Potential customers' not in p['copy'] for p in agency_posts)
                checks['agency_produces_30_distinct_copy_drafts']=True
                media_refs=agency.evaluate('''async()=>{
                  const id=new URL(location.href).searchParams.get('marketingDraft');
                  const response=await fetch('http://127.0.0.1:4192/api/pilot/marketing-drafts/'+id,{headers:{'X-Clippr-Pilot':'local-only'}});
                  return (await response.json()).document.websiteImages;
                }''')
                assert media_refs==[{'url':'https://fresh-restaurant.example.org/media/restaurant.jpg','alt':'Site preview image','rights_confirmed':False,'authenticity_verified':False}],media_refs
                checks['website_image_candidates_persist_unverified']=True
                section.get_by_role('button',name='What we found',exact=True).click()
                section.get_by_text('Pictures found on your website (1)',exact=True).click()
                import_button=section.get_by_role('button',name='Use website pictures',exact=True)
                expect(import_button).to_be_disabled()
                section.get_by_role('checkbox',name='I confirm I can use these pictures for my business marketing').check()
                import_button.click()
                expect(section.get_by_text('1 website picture ready for your designs',exact=True)).to_be_visible(timeout=10000)
                expect(kit_section.get_by_text('Draft creative held · brand and imagery need review',exact=True)).to_be_visible(timeout=45000)
                kit_section.get_by_role('checkbox',name='Show rejected/unapproved mock-ups for internal inspection only').check()
                with agency.expect_download(timeout=12000) as new_kit:
                    kit_section.get_by_role('button',name='Download all my marketing ↓').click()
                refreshed=temp/'with-website-image.zip';new_kit.value.save_as(refreshed)
                with zipfile.ZipFile(refreshed) as archive:
                    manifest=json.loads(archive.read('manifest.json'))
                    assert manifest['websitePhotoCount']==1,manifest
                    assert manifest['assetOrigin']=='owner_declared_website_photos'
                assert provider_calls['submissions']==0
                checks['opt_in_website_photos_refresh_campaign_without_ai_spend']=True

                agency.reload(wait_until='domcontentloaded')
                expect(section.get_by_text('Saved revision 1',exact=True)).to_be_visible(timeout=12000)
                expect(section.get_by_role('button',name='Edit day 30',exact=True)).to_be_visible(timeout=12000)
                checks['agency_fresh_browser_restores_campaign']=True
                agency.get_by_label('Business website URL',exact=True).fill('https://fresh-restaurant.example.org/')
                agency.get_by_role('button',name='Build my marketing').click()
                expect(section.get_by_text('Saved revision 1',exact=True)).to_be_visible(timeout=12000)
                assert agency.url.split('marketingDraft=')[-1]==first_id,'Repeat URL must reuse saved campaign, not create a duplicate'
                assert provider_calls['submissions']==0,'Website analysis cannot automatically spend credits'
                checks['agency_same_url_idempotent_no_generation']=True
                # Owner-facing services: real dated calendar export and honest website audit.
                section.get_by_role('button',name='Your 30 posts',exact=True).click()
                section.get_by_label('First day',exact=True).fill('2026-11-02')
                calendar_button=section.get_by_role('button',name='Download calendar reminders',exact=True)
                expect(calendar_button).to_be_disabled()
                section.get_by_role('button',name='Save my changes',exact=True).click()
                expect(section.get_by_text('Saved revision 2',exact=True)).to_be_visible(timeout=12000)
                with agency.expect_download(timeout=12000) as calendar_download:
                    calendar_button.click()
                calendar_path=temp/'post-reminders.ics';calendar_download.value.save_as(calendar_path)
                calendar_bytes=calendar_path.read_bytes()
                assert calendar_bytes.count(b'BEGIN:VEVENT')==30
                assert b'DTSTART;VALUE=DATE:20261102' in calendar_bytes
                assert b'Draft only\\; NOT scheduled or published' in calendar_bytes
                checks['calendar_30_dated_drafts_exported_without_publishing']=True
                section.get_by_role('button',name='What we found',exact=True).click()
                website_section=section.get_by_role('region',name='Website improvements')
                expect(website_section).to_be_visible()
                expect(website_section.get_by_label('Suggested homepage title')).to_have_value('Fixture Restaurant | Dining')
                with agency.expect_download(timeout=12000) as audit_download:
                    website_section.get_by_role('button',name='Download suggestions',exact=True).click()
                audit_path=temp/'website-improvements.md';audit_download.value.save_as(audit_path)
                audit_text=audit_path.read_text()
                assert 'What has not been tested' in audit_text
                assert 'Google position' not in audit_text
                checks['website_audit_presented_as_actionable_non_ranked_tasks']=True
                agency.reload(wait_until='domcontentloaded')
                expect(section.get_by_text('Saved revision 2',exact=True)).to_be_visible(timeout=12000)
                section.get_by_role('button',name='Your 30 posts',exact=True).click()
                expect(section.get_by_label('First day',exact=True)).to_have_value('2026-11-02')
                checks['owner_date_saved_and_restored']=True
                # Real owner decision: exact copy + post image approval, not social publishing.
                section.get_by_role('button',name='Edit day 1',exact=True).click()
                section.get_by_role('button',name='I’ve checked this post',exact=True).click()
                section.get_by_role('button',name='Save my changes',exact=True).click()
                expect(section.get_by_text('Saved revision 3',exact=True)).to_be_visible(timeout=14000)
                expect(kit_section.get_by_text('Draft creative held · brand and imagery need review',exact=True)).to_be_visible(timeout=45000)
                kit_section.get_by_role('checkbox',name='Show rejected/unapproved mock-ups for internal inspection only').check()
                kit_section.get_by_role('button',name='05 30 pictures for your posts 30 pictures').click()
                final_approval=kit_section.locator('.bk-approval')
                confirmations=(
                    'I checked the caption and the business claims.',
                    'I checked the actual picture and it represents my business appropriately.',
                    'I confirm I have permission to use these pictures for my business.')
                kit_section.get_by_role('button',name='2',exact=True).click()
                expect(final_approval.get_by_text('Creative preflight rejected this draft:',exact=False)).to_be_visible(timeout=12000)
                for label in confirmations:final_approval.get_by_role('checkbox',name=label,exact=True).check()
                expect(final_approval.get_by_role('button',name='Approve this post for manual use',exact=True)).to_be_disabled()
                checks['rejected_reel_preview_cannot_be_approved_as_a_picture']=True
                # A missing report must remain blocked even with all owner checks.
                missing_quality=context.new_page()
                missing_quality.on('pageerror',lambda error:errors.append(str(error)))
                missing_quality.route('**/api/pilot/agency-packs/*/assets/creative-quality-report.json',
                    lambda route:route.fulfill(status=503,content_type='application/json',
                        body=json.dumps({'code':'quality_unavailable','error':'Quality review unavailable in this test'})))
                missing_quality.goto(agency.url,wait_until='domcontentloaded')
                missing_kit=missing_quality.get_by_role('region',name='Complete marketing kit')
                expect(missing_kit.get_by_text('Draft creative held · brand and imagery need review',exact=True)).to_be_visible(timeout=20000)
                missing_kit.get_by_role('checkbox',name='Show rejected/unapproved mock-ups for internal inspection only').check()
                missing_kit.get_by_role('button',name='05 30 pictures for your posts 30 pictures').click()
                expect(missing_kit.get_by_text('The saved quality review has not loaded. Approval stays unavailable until it can be checked.',exact=True)).to_be_visible(timeout=12000)
                for label in confirmations:missing_kit.get_by_role('checkbox',name=label,exact=True).check()
                expect(missing_kit.get_by_role('button',name='Approve this post for manual use',exact=True)).to_be_disabled()
                checks['missing_quality_report_blocks_approval_with_all_checks']=True
                missing_quality.close()
                kit_section.get_by_role('button',name='1',exact=True).click()
                expect(final_approval.get_by_text('Check the wording',exact=False)).to_have_count(0)
                approve_action=final_approval.get_by_role('button',name='Approve this post for manual use',exact=True)
                expect(approve_action).to_be_disabled()
                for label in confirmations:final_approval.get_by_role('checkbox',name=label,exact=True).check()
                expect(approve_action).to_be_enabled(timeout=12000)
                approve_action.click()
                expect(final_approval.get_by_text('Approved for manual use. This has not been posted or scheduled.')).to_be_visible(timeout=12000)
                checks['manual_exact_post_approval_requires_three_confirmations']=True
                agency.reload(wait_until='domcontentloaded')
                expect(section.get_by_text('Saved revision 3',exact=True)).to_be_visible(timeout=14000)
                expect(kit_section.get_by_text('Draft creative held · brand and imagery need review',exact=True)).to_be_visible(timeout=20000)
                kit_section.get_by_role('checkbox',name='Show rejected/unapproved mock-ups for internal inspection only').check()
                kit_section.get_by_role('button',name='05 30 pictures for your posts 30 pictures').click()
                expect(kit_section.get_by_text('Approved for manual use. This has not been posted or scheduled.')).to_be_visible(timeout=12000)
                checks['post_approval_persists_without_publishing']=True
                agency.set_viewport_size({'width':390,'height':844})
                agency.wait_for_timeout(100)
                assert agency.evaluate('document.documentElement.scrollWidth-innerWidth')<=2
                checks['agency_mobile_no_horizontal_overflow']=True
                agency.screenshot(path=str(REPORT/'agency-url-first-mobile.png'),full_page=True)
                agency.close()
                page=context.new_page()
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(front+'/business-pilot.html',wait_until='domcontentloaded',timeout=20000)
                expect(page.get_by_text('Local engine connected',exact=True)).to_be_visible(timeout=15000)
                checks['pilot_loads']=True
                field=page.get_by_label('Business website',exact=True)
                field.fill('https://fixture.example.org/')
                page.get_by_role('button',name='Analyse public website').click()
                expect(page.get_by_text('Page:',exact=True)).to_be_visible(timeout=10000)
                plan=page.locator('details').filter(has=page.locator('summary',has_text='Preview 30-day marketing plan'))
                expect(plan.locator('ol > li')).to_have_count(30)
                checks['url_to_30_day_draft']=True
                page.screenshot(path=str(REPORT/'url-campaign-browser.png'),full_page=True)

                board=page.get_by_role('region',name='Marketing campaign editor')
                expect(board).to_be_visible(timeout=10000)
                board.get_by_role('checkbox',name='Inspect legacy 30-day drafts for internal QA only').check()
                expect(board.get_by_role('button',name='Edit day 30',exact=True)).to_be_visible()
                board.get_by_role('button',name='Edit day 8',exact=True).click()
                board.get_by_label('Words for this post',exact=True).fill('A proper seasonal dining campaign, edited in the dashboard.')
                board.get_by_label('What should customers do next?',exact=True).fill('View the menu and enquire')
                board.get_by_role('button',name='Change the words',exact=True).click()
                board.get_by_label('Change the words',exact=True).fill('Make the evening memorable.')
                board.get_by_label('Creative call to action',exact=True).fill('Explore our seasonal menu')
                board.get_by_role('button',name='Save my changes',exact=True).click()
                expect(board.get_by_text('Saved revision 1',exact=True)).to_be_visible(timeout=10000)
                assert 'marketingDraft=' in page.url
                checks['full_marketing_document_saved']=True
                page.reload(wait_until='domcontentloaded')
                expect(page.get_by_text('Local engine connected',exact=True)).to_be_visible(timeout=15000)
                expect(board.get_by_text('Saved revision 1',exact=True)).to_be_visible(timeout=10000)
                board.get_by_role('checkbox',name='Inspect legacy 30-day drafts for internal QA only').check()
                board.get_by_role('button',name='Edit day 8',exact=True).click()
                expect(board.get_by_label('Words for this post',exact=True)).to_have_value('A proper seasonal dining campaign, edited in the dashboard.')
                board.get_by_role('button',name='Change the words',exact=True).click()
                expect(board.get_by_label('Change the words',exact=True)).to_have_value('Make the evening memorable.')
                expect(board.get_by_label('Creative call to action',exact=True)).to_have_value('Explore our seasonal menu')
                checks['plan_and_creative_edits_survive_reload']=True
                # Copy-review status is explicitly separate from generated-media approval.
                board.get_by_role('button',name='I’ve checked these words',exact=True).click()
                board.get_by_role('button',name='Save my changes',exact=True).click()
                expect(board.get_by_text('Saved revision 2',exact=True)).to_be_visible(timeout=10000)
                expect(board.get_by_text('Words checked. Please check the picture before using it.',exact=True)).to_be_visible()
                with page.expect_download(timeout=10000) as exported:
                    board.get_by_role('button',name='Download post list',exact=True).click()
                csv_path=temp/'campaign.csv';exported.value.save_as(csv_path)
                assert 'A proper seasonal dining campaign' in csv_path.read_text()
                checks['editable_plan_export']=True
                board.screenshot(path=str(REPORT/'marketing-editor-browser.png'))
                board.get_by_role('button',name='Make this picture · 20 credits',exact=True).click()
                expect(board.get_by_text('Reviewed scene contract required before generation',exact=True)).to_be_visible(timeout=10000)
                assert provider_calls['submissions']==0
                checks['unreviewed_scene_blocks_generation_before_provider']=True
                # Explicit internal test preparation; the UI does not approve
                # its own creative, and provider responses remain entirely fake.
                from tests.business_scene_fixture import seed_image
                draft_id=parse_qs(urlsplit(page.url).query)['marketingDraft'][0]
                with pilot.session() as con:seed_image(con,draft_id)
                board.get_by_role('button',name='Make this picture · 20 credits',exact=True).click()
                image=board.get_by_role('img',name='Runway-generated concept',exact=True)
                expect(image).to_be_visible(timeout=20000)
                assert image.evaluate('(el)=>el.complete&&el.naturalWidth===640')
                expect(board.get_by_text('20 credits used',exact=True)).to_be_visible()
                assert provider_calls['submissions']==1
                checks['runway_ui_pipeline_with_mock_provider']=True
                page.reload(wait_until='domcontentloaded')
                expect(board.get_by_text('Saved revision 2',exact=True)).to_be_visible(timeout=15000)
                board.get_by_role('checkbox',name='Inspect legacy 30-day drafts for internal QA only').check()
                board.get_by_role('button',name='Change the words',exact=True).click()
                expect(image).to_be_visible(timeout=15000)
                assert provider_calls['submissions']==1,'Reload must not resubmit a generation'
                checks['generated_asset_survives_reload_no_resubmit']=True
                with page.expect_download(timeout=10000) as generated:
                    board.get_by_role('button',name='Download generated image',exact=True).click()
                image_path=temp/'generated.png';generated.value.save_as(image_path)
                assert Image.open(image_path).size==(640,800)
                checks['local_guarded_generated_asset_download']=True
                board.get_by_label('Picture instructions',exact=True).fill('A changed artistic direction with sufficient detail to form a valid saved image brief.')
                board.get_by_role('button',name='Save my changes',exact=True).click()
                expect(board.get_by_text('Saved revision 3',exact=True)).to_be_visible(timeout=10000)
                expect(board.get_by_text('Generated for an earlier brief',exact=True)).to_be_visible(timeout=15000)
                expect(board.get_by_role('button',name='Make this picture · 20 credits',exact=True)).to_have_count(0)
                assert provider_calls['submissions']==1
                checks['edited_brief_stales_image_without_paid_retry']=True
                board.screenshot(path=str(REPORT/'runway-editor-fixture.png'))

                # A response for an old URL must not appear under the new URL.
                field.fill('https://slow.example.org/')
                page.get_by_role('button',name='Analyse public website').click()
                assert slow_started.wait(5),'Website fixture request did not start'
                with page.expect_response(lambda r:'/api/pilot/website-audit' in r.url,timeout=10000):
                    field.fill('https://different.example.org/')
                    slow_release.set()
                page.wait_for_timeout(200)
                expect(page.get_by_text('Page:',exact=True)).to_have_count(0)
                expect(field).to_have_value('https://different.example.org/')
                checks['stale_website_result_discarded']=True

                page.locator('#blp-video').set_input_files(str(fixture))
                expect(page.get_by_text('2 real review windows found',exact=False).first).to_be_visible(timeout=45000)
                picks=page.locator('.blp-scene input[type=checkbox]')
                picks.nth(0).check();picks.nth(1).check()
                page.get_by_role('button',name='Approve selections and save campaign').click()
                expect(page.get_by_text('Campaign and manual approvals saved locally',exact=False)).to_be_visible(timeout=10000)
                checks['video_upload_scan_approval']=True
                page.get_by_role('button',name='Render approved scenes').click()
                button=page.get_by_role('button',name='Download rendered MP4')
                expect(button).to_be_visible(timeout=90000)
                with page.expect_download(timeout=20000) as info:button.click()
                output=temp/'render.mp4';info.value.save_as(output)
                media=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration,size:stream=codec_type,width,height','-of','json',str(output)],text=True,timeout=15))
                video=next(s for s in media['streams'] if s['codec_type']=='video')
                assert (video['width'],video['height'])==(360,640),media
                assert 20<=float(media['format']['duration'])<=26,media
                assert int(media['format']['size'])>2000
                checks['real_ffmpeg_export']=media
                page.set_viewport_size({'width':390,'height':844})
                page.wait_for_timeout(150)
                overflow=page.evaluate('document.documentElement.scrollWidth-window.innerWidth')
                assert overflow<=2,f'Mobile overflow: {overflow}px'
                checks['mobile_overflow_pixels']=overflow
                assert not errors,errors
                assert not external,external
                checks['browser_errors']=errors;checks['external_requests']=external
                browser.close()
        finally:
            slow_release.set()
            backend.shutdown();backend.server_close()
            pilot.EXEC.shutdown(wait=True,cancel_futures=True)
            vite.terminate()
            try:vite.wait(timeout=8)
            except subprocess.TimeoutExpired:vite.kill();vite.wait(timeout=5)
            log.close()

if __name__=='__main__':
    try:
        main()
        result={'passed':True,'checks':checks,'scope':'Isolated browser, fixture website HTML, real local HTTP/SQLite/FFmpeg. No production or paid providers.'}
        print(json.dumps(result,indent=2),flush=True)
        (REPORT/'acceptance.json').write_text(json.dumps(result,indent=2))
    except Exception as exc:
        result={'passed':False,'checks':checks,'error':str(exc)}
        (REPORT/'acceptance.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2),flush=True)
        raise
