"""End-to-end isolated owner review; no production accounts, APIs or vendor charges."""
import hashlib,io,os,socket,subprocess,tempfile,threading,time,uuid,shutil
from pathlib import Path
from http.server import ThreadingHTTPServer
from PIL import Image
from playwright.sync_api import sync_playwright,expect
import business_local_pilot as pilot
import business_marketing_drafts as drafts
from tests.test_business_marketing_drafts import document

ROOT=Path(__file__).resolve().parents[1]

def main():
 with tempfile.TemporaryDirectory(prefix='business-hero-browser-') as folder:
  temp=Path(folder)
  previous=pilot.BASE;previous_origins=pilot.VALID_ORIGINS
  pilot.BASE=temp/'private-db'
  api_server=ThreadingHTTPServer(('127.0.0.1',0),pilot.Handler)
  threading.Thread(target=api_server.serve_forever,daemon=True).start()
  with socket.socket() as sock:
   sock.bind(('127.0.0.1',0));frontend_port=sock.getsockname()[1]
  frontend=f'http://127.0.0.1:{frontend_port}'
  pilot.VALID_ORIGINS=frozenset({frontend})
  did='a'*32
  with pilot.session() as conn:
   doc=document();doc['business']='QA Restaurant'
   drafts.save_draft(conn,{'id':did,'expectedRevision':0,'mutationId':'b'*32,'document':doc})
   pic=Image.new('RGB',(1200,800),(91,127,144));target=pilot.BASE/'website_photos'/did;target.mkdir(parents=True,exist_ok=True)
   buffer=io.BytesIO();pic.save(buffer,format='JPEG');raw=buffer.getvalue();photo_id='f'*32
   (target/(photo_id+'.jpg')).write_bytes(raw)
   conn.execute('INSERT INTO marketing_website_media VALUES(?,?,?,?,?,?,?,?)',(
    photo_id,did,'https://example.org/owner-attested.jpg',hashlib.sha256(raw).hexdigest(),len(raw),1200,800,time.time()))
  vite_cmd='''import {createServer} from 'vite';import react from '@vitejs/plugin-react';
const server=await createServer({configFile:false,plugins:[react()],logLevel:'error',root:process.cwd(),
server:{host:'127.0.0.1',port:Number(process.env.QA_PORT),strictPort:true,hmr:false}});
await server.listen();'''
  env={**os.environ,'QA_PORT':str(frontend_port),'VITE_BUSINESS_PILOT_API':f'http://127.0.0.1:{api_server.server_port}'}
  out=(temp/'vite.log').open('w')
  proc=subprocess.Popen(['node','--input-type=module','-e',vite_cmd],cwd=ROOT,env=env,stdout=out,stderr=out)
  try:
   from urllib.request import urlopen
   deadline=time.monotonic()+15
   while time.monotonic()<deadline:
    if proc.poll() is not None:raise RuntimeError('Vite exited early')
    try:
     with urlopen(frontend+'/tests/business-hero-review.html',timeout=1) as response:
      if response.status==200:break
    except Exception:time.sleep(.15)
   else:raise RuntimeError('QA Vite server timeout')
   with sync_playwright() as pw:
    chrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    browser=pw.chromium.launch(**({'executable_path':chrome} if Path(chrome).exists() else {}),headless=True)
    page=browser.new_page(viewport={'width':1180,'height':950},device_scale_factor=1)
    errors=[];page.on('pageerror',lambda x:errors.append(str(x)))
    page.goto(frontend+'/tests/business-hero-review.html?draft='+did)
    expect(page.get_by_text('Make three posts worth publishing.')).to_be_visible()
    page.get_by_label('What this business actually offers').fill('Verified restaurant dining')
    page.get_by_label('Who should see these posts?').fill('Local diners in the city')
    page.get_by_role('checkbox').check()
    page.get_by_role('button',name='Save my first six directions').click()
    expect(page.get_by_text('Six creative directions safely saved.')).to_be_visible(timeout=12000)
    expect(page.get_by_text('Authorised website photos: 1')).to_be_visible()
    page.locator('.bh-source-picks button').first.click()
    expect(page.get_by_text('Instagram · 4:5 reference crop')).to_be_visible()
    expect(page.get_by_text('TikTok · 9:16 reference crop')).to_be_visible()
    editorial=page.get_by_role('article').filter(has_text='Editorial image')
    editorial.get_by_label('What should we improve?').fill('Keep the dining activity in the scene and use a more natural close-up.')
    editorial.get_by_role('button',name='Prepare two improved directions').click()
    expect(page.get_by_text('Two new alternatives were saved. No AI generation or credits used.')).to_be_visible()
    page.reload();expect(page.get_by_text('Version 2').first).to_be_visible()
    editorial=page.get_by_role('article').filter(has_text='Editorial image')
    editorial.get_by_label('Saved history for Editorial image').select_option('0')
    editorial.get_by_role('button',name='Restore as a new version').click()
    expect(page.get_by_text('An earlier direction was restored as a new version.')).to_be_visible()
    page.reload();expect(page.get_by_text('Version 3').first).to_be_visible()
    social=page.get_by_role('article').filter(has_text='Social-first short video')
    expect(social.get_by_text('Estimated cost')).to_be_visible()
    social.get_by_role('button',name='Prepare video proposal — no credits used').click()
    expect(social.get_by_text('Saved production proposal · Awaiting separate spend approval')).to_be_visible()
    expect(social.get_by_text('Nothing generated, billed, scheduled or published.')).to_be_visible()
    social.locator('.bvp').screenshot(path=str(temp/'hero-video-spend-proposal.png'))
    page.reload()
    social=page.get_by_role('article').filter(has_text='Social-first short video')
    expect(social.get_by_role('button',name='Video proposal already saved')).to_be_disabled()
    page.locator('.bh-source-picks button').first.click()
    expect(page.locator('.bh-mobile-comparison')).to_be_visible()
    print('QA_DOM',page.evaluate("({roots:document.querySelectorAll('.bh-root').length,sections:document.querySelectorAll('.bh-creative').length,intros:document.querySelectorAll('.bh-intro').length,bodyHeight:document.body.scrollHeight})"))
    page.screenshot(path=str(temp/'hero-review-desktop.png'),full_page=False)
    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(temp/'hero-review-mobile.png'),full_page=False)
    page.locator('.bh-mobile-comparison').screenshot(path=str(temp/'hero-review-crops.png'))
    page.get_by_role('article').first.screenshot(path=str(temp/'hero-review-editorial.png'))
    if not errors:
     evidence=Path.home()/'.clippr-business-build4-review-20261019'
     evidence.mkdir(mode=0o700,exist_ok=True)
     for name in ('hero-review-desktop.png','hero-review-mobile.png','hero-review-crops.png','hero-review-editorial.png','hero-video-spend-proposal.png'):
      shutil.copyfile(temp/name,evidence/name)
     print('QA_SCREENSHOTS_SAVED',evidence)
    print('BROWSER_HERO_WORKFLOW_PASS browser errors',errors,'shots bytes',
          (temp/'hero-review-desktop.png').stat().st_size,(temp/'hero-review-mobile.png').stat().st_size)
    assert not errors,errors
    browser.close()
  finally:
   proc.terminate()
   try:proc.wait(timeout=8)
   except subprocess.TimeoutExpired:proc.kill()
   out.close()
   api_server.shutdown();api_server.server_close()
   pilot.BASE=previous;pilot.VALID_ORIGINS=previous_origins

if __name__=='__main__':main()
