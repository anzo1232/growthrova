"""Hermetic Build 6 browser contracts: real React, video playback and caption UI.

Uses synthetic local media and an in-page API fixture. No model, billing, auth,
production database, social account or external network is available.
"""
from __future__ import annotations
import json
import hashlib
from PIL import Image, ImageDraw, ImageFont
import os
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
REPORT=Path(os.environ.get('CLIPPR_FINISHING_REPORT_DIR','/tmp/clippr-business-build6-qa/finishing-browser'))
REPORT.mkdir(parents=True,exist_ok=True)
checks={}

def main():
    with tempfile.TemporaryDirectory(prefix='clippr-finishing-browser-') as folder:
        temp=Path(folder)
        media=temp/'synthetic-six-seconds.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i',
            'testsrc2=size=270x480:rate=12:duration=6','-an','-c:v','libx264',
            '-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart',str(media)],
            check=True,timeout=30,capture_output=True)
        # A visibly captioned synthetic rendition proves the browser uses the
        # rendered MP4 instead of drawing a second DOM subtitle over it.
        plate=temp/'synthetic-caption-plate.png'
        overlay=Image.new('RGBA',(270,480),(0,0,0,0));draw=ImageDraw.Draw(overlay)
        font=None
        for candidate in ('/System/Library/Fonts/Supplemental/Arial Bold.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
            if Path(candidate).exists():font=ImageFont.truetype(candidate,16);break
        if font is None:font=ImageFont.load_default()
        draw.rounded_rectangle((24,318,246,388),radius=8,fill=(18,24,22,242))
        for text,y in [('Synthetic QA captions',331),('in this video',354)]:
            box=draw.textbbox((0,0),text,font=font)
            draw.text(((270-(box[2]-box[0]))/2,y),text,font=font,fill='white')
        draw.line((40,381,230,381),fill=(216,179,122,255),width=2);overlay.save(plate)
        captioned=temp/'synthetic-captioned-six-seconds.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-i',str(media),
            '-loop','1','-i',str(plate),'-filter_complex',
            "[0:v][1:v]overlay=enable='between(t,0.2,4)':shortest=1[v]",
            '-map','[v]','-t','6','-an','-c:v','libx264','-preset','ultrafast',
            '-pix_fmt','yuv420p','-movflags','+faststart',str(captioned)],
            check=True,timeout=30,capture_output=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        front='http://127.0.0.1:'+str(port)
        ready=temp/'vite-ready'
        script="""
import {createServer} from 'vite';
import react from '@vitejs/plugin-react';
import {readFileSync,writeFileSync} from 'node:fs';
const media=readFileSync(process.env.TEST_FINISHING_MEDIA);
const captioned=readFileSync(process.env.TEST_FINISHING_CAPTIONED);
const fixture={name:'local-finishing-media',configureServer(server){
 server.middlewares.use((req,res,next)=>{
  const file=req.url==='/__business-finishing-fixture.mp4'?media:req.url==='/__business-finishing-captioned.mp4'?captioned:null;
  if(!file)return next();
  res.statusCode=200;res.setHeader('Content-Type','video/mp4');res.setHeader('Content-Length',file.length);res.end(file);
 });
}};
const server=await createServer({root:process.cwd(),configFile:false,
 envDir:process.env.TEST_FINISHING_TEMP,cacheDir:process.env.TEST_FINISHING_TEMP+'/vite-cache',
 plugins:[fixture,react()],logLevel:'error',
 server:{host:'127.0.0.1',port:Number(process.env.TEST_FINISHING_PORT),strictPort:true,hmr:false}});
await server.listen();writeFileSync(process.env.TEST_FINISHING_READY,'ready');
"""
        env={**os.environ,'TEST_FINISHING_MEDIA':str(media),'TEST_FINISHING_CAPTIONED':str(captioned),'TEST_FINISHING_TEMP':str(temp),
             'TEST_FINISHING_PORT':str(port),'TEST_FINISHING_READY':str(ready)}
        log=(REPORT/'vite.log').open('w')
        vite=subprocess.Popen(['node','--input-type=module','-e',script],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+20
            while not ready.exists() and time.monotonic()<deadline:
                if vite.poll() is not None:raise RuntimeError('Fixture Vite failed; inspect finishing-browser/vite.log')
                time.sleep(.1)
            assert ready.exists(),'Fixture Vite startup timed out'
            with sync_playwright() as pw:
                chrome=os.environ.get('CLIPPR_TEST_BROWSER')
                default='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
                if not chrome and Path(default).exists():chrome=default
                browser=pw.chromium.launch(**({'executable_path':chrome} if chrome else {}),headless=True)
                context=browser.new_context(viewport={'width':1365,'height':1000},accept_downloads=True,service_workers='block')
                errors=[];external=[]
                def guard(route):
                    if route.request.url.startswith(front+'/'):return route.continue_()
                    external.append(route.request.url);route.abort('blockedbyclient')
                context.route('**/*',guard)
                page=context.new_page()
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.set_default_timeout(12000)
                url=front+'/tests/fixtures/business-reel-finishing.html'
                page.goto(url,wait_until='domcontentloaded')
                expect(page.get_by_role('heading',name='Finish your Reel',exact=True)).to_be_visible()
                video=page.get_by_label('Private Reel preview',exact=True)
                overlay=page.get_by_label('Current caption',exact=True)
                toggle=page.get_by_label('Show saved captions in preview',exact=True)
                cues=page.get_by_label(re.compile('^Editable caption cues'))
                def seek():
                    expect(video).to_be_visible()
                    page.wait_for_function("document.querySelector('video')?.readyState >= 1")
                    video.evaluate('(el)=>{el.pause();el.currentTime=1;}')
                seek()
                expect(toggle).to_be_checked()
                expect(overlay).to_have_text('The owner’s actual opening hook')
                expect(cues).to_have_value('0.2 | 4 | The owner’s actual opening hook')
                assert overlay.evaluate("el=>getComputedStyle(el).fontFamily").startswith('Georgia')
                assert overlay.evaluate("el=>getComputedStyle(el).borderBottomColor")=='rgb(216, 179, 122)'
                frame=page.locator('.brw-player').bounding_box();text_box=overlay.bounding_box()
                assert abs(frame['width']/frame['height']-9/16)<.002
                assert abs((text_box['y']+text_box['height']/2)-(frame['y']+frame['height']/2))<2
                expect(page.get_by_role('combobox',name='Caption placement',exact=True)).to_have_value('middle_safe')
                checks['saved_captions_visible_with_exact_brand_accent_and_typeface']=True
                checks['middle_safe_caption_is_centred_on_exact_portrait_frame']=True
                toggle.uncheck();expect(overlay).to_have_count(0)
                assert video.evaluate('el=>el.currentTime')>=.9,'Caption toggle must not restart the video'
                toggle.check();expect(overlay).to_be_visible()
                page.get_by_role('button',name='Cinematic · 6s',exact=True).click();seek()
                expect(toggle).to_be_checked();expect(overlay).to_have_text('A distinct cinematic caption')
                page.get_by_role('combobox',name='Caption edit',exact=True).select_option('b')
                expect(cues).to_have_value('0.2 | 4 | A distinct cinematic caption')
                checks['switch_cut_restores_saved_captions_and_editable_cues']=True

                preferred=page.get_by_role('combobox',name='Preferred complete Reel',exact=True)
                preferred.select_option('b')
                owner_reference=page.get_by_label('Owner reference',exact=True)
                owner_note=page.get_by_label('Approval and feedback note',exact=True)
                owner_confirm=page.get_by_label('I have reviewed both complete cuts and select this version for approval.',exact=True)
                owner_submit=page.get_by_role('button',name='Record private owner choice',exact=True)
                expect(owner_confirm).to_be_enabled()
                owner_reference.fill('Fixture owner')
                owner_note.fill('I reviewed the picture, captions and timing of both cuts.')
                owner_confirm.check();expect(owner_submit).to_be_enabled()
                page.evaluate('window.__finishingFixture.bumpPair()')
                page.get_by_label('Tell the editor what should change (free feedback, no regeneration)',exact=True).fill('Return the current fixture pair for review.')
                page.get_by_role('button',name='Save edit feedback',exact=True).click()
                expect(owner_note).to_have_value('')
                expect(owner_confirm).not_to_be_checked()
                expect(owner_submit).to_be_disabled()
                assert page.evaluate("window.__finishingFixture.requests.filter(x=>x.path.endsWith('/owner-choice')).length")==0
                checks['changed_pair_clears_owner_note_confirmation_and_old_readiness']=True
                expect(owner_confirm).to_be_enabled()
                owner_note.fill('I have rechecked the updated pair and choose the cinematic edit.')
                owner_confirm.check();owner_submit.click()
                expect(page.get_by_text('Local selection saved:',exact=False)).to_be_visible()
                choice=page.evaluate("window.__finishingFixture.requests.findLast(x=>x.path.endsWith('/owner-choice')).data")
                assert choice['variant']=='b'
                assert choice['expectedContentSha256']=='e'*64
                assert choice['expectedReviewSetSha256']=='9'*64
                checks['owner_choice_binds_exact_loaded_cut_and_pair']=True

                cues.fill('0.2 | 3 | First cue\n2 | 4 | Overlapping cue')
                verified=page.get_by_label('I have verified every word and time.',exact=True)
                verified.check();page.get_by_role('button',name='Save separate captions · free',exact=True).click()
                expect(page.get_by_role('alert').filter(has_text='without overlaps')).to_be_visible()
                assert page.evaluate("window.__finishingFixture.requests.filter(x=>x.method==='POST'&&x.path.endsWith('/captions')).length")==0
                cues.fill('0.2 | 4 | Owner-edited wording with checked timing')
                verified.check();page.get_by_role('button',name='Save separate captions · free',exact=True).click()
                expect(page.get_by_text('Caption sidecar saved.',exact=False)).to_be_visible()
                save=page.evaluate("window.__finishingFixture.requests.findLast(x=>x.method==='POST'&&x.path.endsWith('/captions')).data")
                assert save['expectedEditRevision']==2 and save['expectedCaptionRevision']==1
                assert save['style']=={'typeface':'editorial','weight':'bold','placement':'bottom_safe'}
                expect(page.get_by_text('Awaiting complete internal quality checks',exact=True)).to_be_visible()
                expect(page.get_by_text('Local selection saved:',exact=False)).to_have_count(0)
                expect(owner_submit).to_have_count(0)
                seek();expect(overlay).to_have_text('Owner-edited wording with checked timing')
                with page.expect_download() as downloaded:
                    page.get_by_role('link',name='Download editable captions (.vtt)',exact=True).click()
                sidecar=temp/'captions.vtt';downloaded.value.save_as(sidecar)
                assert sidecar.read_text().startswith('WEBVTT')
                assert 'Owner-edited wording with checked timing' in sidecar.read_text()
                checks['caption_save_versions_sidecar_and_returns_owner_flow_to_QC']=True
                requests=page.evaluate('window.__finishingFixture.requests')
                asset_requests=[r for r in requests if r['method']=='GET' and ('/previews/' in r['path'] or '/captions/' in r['path'])]
                assert asset_requests
                for request in asset_requests:
                    query=parse_qs(urlsplit(request['path']).query)
                    assert re.fullmatch('[a-f0-9]{64}',query['contentSha256'][0])
                    assert int(query['revision'][0])>=1
                    if '/captions/' in request['path']:assert int(query['captionRevision'][0])>=1
                assert not any(re.search('runway|reel-shot-quotes|publish|schedule',r['path']) for r in requests)
                checks['every_preview_and_sidecar_request_carries_exact_versions']=True
                page.screenshot(path=str(REPORT/'finishing-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth-innerWidth')<=2
                frame=page.locator('.brw-player').bounding_box()
                assert abs(frame['width']/frame['height']-9/16)<.002
                widths=page.locator('input[type=checkbox]').evaluate_all('els=>els.map(el=>el.getBoundingClientRect().width)')
                assert widths and all(10<=width<=20 for width in widths),widths
                page.screenshot(path=str(REPORT/'finishing-mobile.png'),full_page=True)
                checks['mobile_no_horizontal_overflow_and_contained_checkboxes']=True

                page.set_viewport_size({'width':1365,'height':1000})
                page.goto(url+'?case=delivery',wait_until='domcontentloaded')
                expect(page.get_by_role('heading',name='Finish your Reel',exact=True)).to_be_visible()
                render_button=page.get_by_role('button',name='Render captions into video',exact=True)
                expect(render_button).to_be_enabled()
                cues.fill('0.2 | 4 | Unsaved words must not be rendered')
                expect(render_button).to_be_disabled()
                expect(page.get_by_text('Save your caption changes before rendering or downloading the video.',exact=True)).to_be_visible()
                cues.fill('0.2 | 4 | Synthetic QA captions in this video')
                expect(render_button).to_be_enabled();render_button.click()
                expect(page.get_by_text('Captions included in this MP4',exact=True)).to_be_visible()
                seek();expect(overlay).to_have_count(0);expect(toggle).to_have_count(0)
                assert page.locator('video track').count()==0
                expect(render_button).to_be_disabled()
                render_request=page.evaluate("window.__finishingFixture.requests.findLast(x=>x.path.endsWith('/render-captions')).data")
                assert render_request=={'variant':'a','expectedContentSha256':'a'*64,'expectedEditRevision':1,'expectedCaptionRevision':1}
                expect(page.get_by_role('button',name='Download approved Reel',exact=True)).to_have_count(0)
                expect(page.get_by_role('link',name='Download editable captions (.vtt)',exact=True)).to_be_visible()
                checks['render_pins_saved_cut_and_caption_versions_and_suppresses_double_subtitles']=True
                page.get_by_role('combobox',name='Caption edit',exact=True).select_option('b')
                expect(render_button).to_be_enabled();render_button.click()
                expect(page.get_by_text('Captions included in this MP4',exact=True)).to_be_visible();seek()
                page.evaluate('window.__finishingFixture.reviewPair()')
                page.get_by_label('Tell the editor what should change (free feedback, no regeneration)',exact=True).fill('Refresh the reviewed synthetic captioned pair.')
                page.get_by_role('button',name='Save edit feedback',exact=True).click()
                preferred.select_option('b')
                expect(owner_confirm).to_be_enabled()
                owner_reference.fill('Synthetic fixture owner')
                owner_note.fill('Reviewed both synthetic captioned cuts for a browser contract test.')
                owner_confirm.check();owner_submit.click()
                download=page.get_by_role('button',name='Download approved Reel',exact=True)
                expect(download).to_be_enabled()
                with page.expect_download() as received:download.click()
                output=temp/'approved-fixture.mp4';received.value.save_as(output)
                assert output.read_bytes()==captioned.read_bytes()
                assert received.value.suggested_filename=='fixture-studio-cinematic-approved.mp4'
                request=page.evaluate("window.__finishingFixture.requests.findLast(x=>x.path.includes('/deliveries/'))")
                assert request['method']=='GET' and '/deliveries/b?' in request['path']
                query=parse_qs(urlsplit(request['path']).query)
                assert query['contentSha256']==['3'*64] and query['reviewSetSha256']==['4'*64]
                checks['approved_selected_download_matches_exact_captioned_mp4_bytes']=True
                page.locator('.brw-previews').scroll_into_view_if_needed()
                page.screenshot(path=str(REPORT/'captioned-preview-desktop.jpg'),quality=78)
                page.locator('.brf-grid article').last.scroll_into_view_if_needed()
                page.screenshot(path=str(REPORT/'approved-download-desktop.jpg'),quality=78)
                page.set_viewport_size({'width':390,'height':844})
                page.locator('.brf-grid article').last.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth-innerWidth')<=2
                page.screenshot(path=str(REPORT/'approved-download-mobile.jpg'),quality=78)
                checks['captioned_download_controls_fit_mobile']=True
                page.evaluate('window.__finishingFixture.setUnreconciled(true)')
                page.get_by_label('Tell the editor what should change (free feedback, no regeneration)',exact=True).fill('Refresh the current provider reconciliation status.')
                page.get_by_role('button',name='Save edit feedback',exact=True).click()
                expect(download).to_have_count(0)
                expect(page.get_by_text('Complete the client delivery checks above before downloading the approved Reel.',exact=True)).to_be_visible()
                page.evaluate('window.__finishingFixture.setUnreconciled(false)')
                page.get_by_label('Tell the editor what should change (free feedback, no regeneration)',exact=True).fill('Refresh the reconciled delivery checks again.')
                page.get_by_role('button',name='Save edit feedback',exact=True).click()
                expect(download).to_be_enabled()
                checks['download_honours_backend_readiness_and_spend_reconciliation']=True
                late_downloads=[]
                page.on('download',lambda item:late_downloads.append(item))
                page.evaluate("window.__finishingFixture.deferNext('download')")
                download.click();page.wait_for_function('window.__finishingFixture.hasPending()')
                cues.fill('0.2 | 4 | Unsaved text while the download is pending')
                expect(download).to_have_count(0)
                page.evaluate('''async()=>{
                  window.__finishingFixture.releasePending();
                  await Promise.resolve();
                  await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
                }''')
                assert not late_downloads,'An in-flight download must not ignore newly edited words'
                cues.fill('0.2 | 4 | Synthetic QA captions in this video')
                expect(download).to_be_enabled()
                checks['inflight_download_is_discarded_when_caption_editor_changes']=True
                page.evaluate('window.__finishingFixture.tamperDelivery()')
                download.click()
                expect(page.get_by_role('alert').filter(has_text='does not match the approved Reel')).to_be_visible()
                checks['download_refuses_bytes_that_do_not_match_approved_hash']=True
                cues.fill('0.2 | 4 | Newly requested caption wording')
                expect(download).to_have_count(0);expect(render_button).to_be_disabled()
                expect(page.get_by_text('Save your caption changes before rendering or downloading the video.',exact=True)).to_be_visible()
                verified.check();page.get_by_role('button',name='Save separate captions · free',exact=True).click()
                expect(page.get_by_text('Caption sidecar saved.',exact=False)).to_be_visible()
                expect(page.get_by_text('Captions included in this MP4',exact=True)).to_have_count(0)
                seek();expect(overlay).to_have_text('Newly requested caption wording')
                expect(download).to_have_count(0);expect(owner_submit).to_have_count(0)
                checks['editing_rendered_captions_removes_download_and_requires_new_render_review']=True

                page.goto(url+'?case=media',wait_until='domcontentloaded')
                link=page.get_by_role('link',name='Open original video library ↗',exact=True)
                expect(link).to_have_attribute('href','/business-pilot.html')
                expect(page.get_by_role('combobox',name='Reel stage',exact=True)).to_have_value('craft')
                expect(page.get_by_role('heading',name='Client delivery checks · 2/13')).to_be_visible()
                expect(page.get_by_text('Manually check food accuracy and real brand details')).to_be_visible()
                expect(page.get_by_text('Supply actual owner-authorised footage and secure internal visual approval',exact=True)).to_be_visible()
                checks['build7_readiness_and_creative_triage_visible_on_live_editor']=True
                page.evaluate('window.__finishingFixture.provideSource()')
                page.get_by_role('button',name='Refresh footage',exact=True).click()
                page.get_by_role('combobox',name='Previously uploaded business video',exact=True).select_option('owner-source')
                page.get_by_label('Media permission / ownership note',exact=True).fill('I own this original footage and approve its commercial marketing use.')
                page.get_by_label('I confirm this video is ours or licensed for marketing use.',exact=True).check()
                page.get_by_role('button',name='Use this real clip · 0 AI credits',exact=True).click()
                expect(page.get_by_text('Real footage saved for visual review',exact=True)).to_be_visible()
                expect(page.get_by_role('combobox',name='Reel stage',exact=True)).to_have_value('experience')
                expect(page.get_by_role('option',name='My original footage.mp4',exact=True)).to_have_count(0)
                expect(page.get_by_role('button',name='Use this real clip · 0 AI credits',exact=True)).to_be_disabled()
                source=page.evaluate("window.__finishingFixture.requests.findLast(x=>x.path.endsWith('/owner-video')).data")
                assert source['slot']=='craft' and source['sourceId']=='owner-source'
                checks['library_refresh_selects_eligible_failed_stage_and_preserves_accepted_stage']=True

                page.goto(url+'?case=stale',wait_until='domcontentloaded')
                expect(page.get_by_role('alert').filter(has_text='Captions changed with this cut.')).to_be_visible()
                expect(page.get_by_label('I have reviewed both complete cuts and select this version for approval.',exact=True)).to_be_disabled()
                expect(page.get_by_role('button',name='Record private owner choice',exact=True)).to_be_disabled()
                checks['failed_exact_sidecar_blocks_owner_choice_even_if_video_loads']=True

                page.goto(url+'?case=typography',wait_until='domcontentloaded')
                expect(page.get_by_label(re.compile('^Editable caption cues'))).to_have_value('0.2 | 4 | The owner’s actual opening hook')
                expect(page.get_by_role('combobox',name='Caption typeface',exact=True)).to_have_value('editorial')
                page.get_by_label('I have verified every word and time.',exact=True).check()
                page.get_by_role('button',name='Save separate captions · free',exact=True).click()
                expect(page.get_by_text('Caption sidecar saved.',exact=False)).to_be_visible()
                saved=page.evaluate("window.__finishingFixture.requests.findLast(x=>x.method==='POST'&&x.path.endsWith('/captions')).data")
                assert saved['style']['typeface']=='editorial' and saved['cues'][0]['text']=='The owner’s actual opening hook'
                checks['brand_lock_updates_old_typeface_while_preserving_owner_words']=True
                page.goto(url,wait_until='domcontentloaded')
                expect(page.get_by_role('heading',name='Finish your Reel',exact=True)).to_be_visible()
                edit_select=page.get_by_role('combobox',name='Caption edit',exact=True)
                original_a='0.2 | 4 | The owner’s actual opening hook'
                draft_a='0.2 | 4 | The first requested social revision'
                newer_a='0.2 | 4 | Newer words typed while the save was pending'
                draft_b='0.2 | 4 | A separate unfinished cinematic revision'
                cues.fill(draft_a)
                edit_select.select_option('b')
                expect(cues).to_have_value('0.2 | 4 | A distinct cinematic caption')
                expect(page.get_by_role('status').filter(has_text='Unsaved caption changes: Social-first.')).to_be_visible()
                expect(owner_confirm).to_be_disabled()
                expect(page.get_by_role('button',name='Render captions into video',exact=True)).to_be_disabled()
                cues.fill(draft_b)
                edit_select.select_option('a');expect(cues).to_have_value(draft_a)
                page.get_by_label('Tell the editor what should change (free feedback, no regeneration)',exact=True).fill('An unrelated feedback refresh must not erase caption drafts.')
                page.get_by_role('button',name='Save edit feedback',exact=True).click()
                expect(cues).to_have_value(draft_a)
                page.evaluate("window.__finishingFixture.deferNext('captions')")
                verified.check();page.get_by_role('button',name='Save separate captions · free',exact=True).click()
                page.wait_for_function('window.__finishingFixture.hasPending()')
                cues.fill(newer_a)
                edit_select.select_option('b');expect(cues).to_have_value(draft_b)
                page.evaluate('''async()=>{
                  window.__finishingFixture.releasePending();
                  await Promise.resolve();
                  await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
                }''')
                edit_select.select_option('a');expect(cues).to_have_value(newer_a)
                expect(verified).not_to_be_checked()
                assert page.evaluate("window.__finishingFixture.project.captionTracks.a.cues[0].text")=='The first requested social revision'
                verified.check();page.get_by_role('button',name='Save separate captions · free',exact=True).click()
                page.wait_for_function("window.__finishingFixture.project.captionTracks.a.captionRevision===3")
                expect(cues).to_have_value(newer_a)
                save=page.evaluate("window.__finishingFixture.requests.findLast(x=>x.path.endsWith('/captions')&&x.method==='POST').data")
                assert save['expectedCaptionRevision']==2 and save['cues'][0]['text']=='Newer words typed while the save was pending'
                edit_select.select_option('b');expect(cues).to_have_value(draft_b)
                assert page.evaluate("(()=>{const e=new Event('beforeunload',{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented})()")
                page.get_by_role('button',name='Discard unsaved captions for this cut',exact=True).click()
                expect(cues).to_have_value('0.2 | 4 | A distinct cinematic caption')
                expect(page.get_by_role('status').filter(has_text='Unsaved caption changes:')).to_have_count(0)
                assert not page.evaluate("(()=>{const e=new Event('beforeunload',{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented})()")
                checks['cut_switch_and_unrelated_refresh_preserve_each_unsaved_caption_draft']=True
                checks['save_acknowledgement_preserves_newer_typing_and_rebases_next_save']=True
                checks['dirty_captions_warn_before_leaving_and_explicit_discard_clears_warning']=True
                edit_select.select_option('a')
                cues.fill(' 0.20|4.00| A pasted caption with valid alternate spacing  \n')
                verified.check();page.get_by_role('button',name='Save separate captions · free',exact=True).click()
                page.wait_for_function("window.__finishingFixture.project.captionTracks.a.captionRevision===4")
                expect(cues).to_have_value('0.2 | 4 | A pasted caption with valid alternate spacing')
                expect(page.get_by_role('status').filter(has_text='Unsaved caption changes:')).to_have_count(0)
                expect(page.get_by_role('button',name='Render captions into video',exact=True)).to_be_enabled()
                checks['canonical_save_acknowledgement_clears_equivalent_pasted_cue_formatting']=True

                for mutation,fail in [('feedback',False),('captions',False),('feedback',True),('render-captions',False),('render-captions',True)]:
                    page.goto(url,wait_until='domcontentloaded')
                    expect(page.get_by_role('heading',name='Finish your Reel',exact=True)).to_be_visible()
                    page.evaluate('(kind)=>window.__finishingFixture.deferNext(kind)',mutation)
                    if mutation=='feedback':
                        page.get_by_label('Tell the editor what should change (free feedback, no regeneration)',exact=True).fill('Deferred note for the first campaign only.')
                        page.get_by_role('button',name='Save edit feedback',exact=True).click()
                    elif mutation=='render-captions':
                        page.get_by_role('button',name='Render captions into video',exact=True).click()
                    else:
                        page.get_by_label('I have verified every word and time.',exact=True).check()
                        page.get_by_role('button',name='Save separate captions · free',exact=True).click()
                    page.wait_for_function('window.__finishingFixture.hasPending()')
                    page.evaluate('window.__finishingFixture.switchCampaign()')
                    expect(page.locator('.brf-locked strong')).to_have_text('Second fixture campaign')
                    page.evaluate('''async fail=>{
                      window.__finishingFixture.releasePending(fail);
                      await Promise.resolve();
                      await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);
                    }''',fail)
                    expect(page.locator('.brf-locked strong')).to_have_text('Second fixture campaign')
                    expect(page.get_by_role('alert')).to_have_count(0)
                    expect(page.locator('.brf-success')).to_have_count(0)
                checks['late_mutation_success_error_and_finally_do_not_replace_another_campaign']=True
                assert not errors,errors
                assert not external,external
                checks['browser_errors']=errors;checks['external_requests']=external
                browser.close()
        finally:
            vite.terminate()
            try:vite.wait(timeout=8)
            except subprocess.TimeoutExpired:vite.kill();vite.wait(timeout=5)
            log.close()

if __name__=='__main__':
    try:
        main()
        result={'passed':True,'checks':checks,'scope':'Isolated component browser contract with synthetic local video; no paid calls or publishing.'}
        (REPORT/'acceptance.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2),flush=True)
    except Exception as exc:
        result={'passed':False,'checks':checks,'error':str(exc)}
        (REPORT/'acceptance.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2),flush=True)
        raise
