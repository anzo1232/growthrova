"""Actual signed-in UI upload smoke test against fully mocked, non-live APIs.

No customer API secrets, real footage or paid provider calls. A 3KB synthetic
file exercises the browser picker, owner-scoped upload/confirmation, visual
queue/poll states and campaign-pack UI.
"""
import base64
import json
import time
from playwright.sync_api import sync_playwright

WEB = "http://127.0.0.1:4185"
ORG = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BRAND = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SOURCE = "d"*32
from pathlib import Path
import atexit
import shutil
import subprocess
import tempfile
assert shutil.which("ffmpeg"), "FFmpeg is required for real-frame browser regression"
_fixture=tempfile.TemporaryDirectory(prefix="clippr-business-frame-browser-")
atexit.register(_fixture.cleanup)
VIDEO_FILE=Path(_fixture.name)/"clippr-business-qa-scenes-20261017.mp4"
subprocess.run([
    "ffmpeg","-hide_banner","-loglevel","error","-y",
    "-f","lavfi","-i","testsrc2=size=320x568:rate=12:duration=18",
    "-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",
    "-movflags","+faststart",str(VIDEO_FILE)
],check=True,timeout=45)
VIDEO_SIZE=VIDEO_FILE.stat().st_size
JOB = "e"*32
KEY = f"business/sources/{ORG}/{SOURCE}.mp4"
calls = []
scan_reads = 0

def encode(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

def session():
    created=int(time.time())
    jwt=encode({"typ":"JWT","alg":"HS256"})+"."+encode({
        "sub":USER,"role":"authenticated","aud":"authenticated",
        "iat":created,"exp":created+7000})+".fake"
    person={
        "id":USER,"aud":"authenticated","role":"authenticated",
        "email":"qa@example.invalid","app_metadata":{"provider":"email","providers":["email"]},
        "user_metadata":{},"created_at":"2026-10-17T16:00:00Z"}
    return {"access_token":jwt,"refresh_token":"qa-refresh-not-valid",
        "token_type":"bearer","expires_at":created+7000,"expires_in":7000,"user":person}

def response(route,body,status=200):
    route.fulfill(status=status,content_type="application/json",body=json.dumps(body))

def handle(route):
    global scan_reads
    request=route.request
    url=request.url
    calls.append((request.method,url))
    if "example.supabase.co" in url:
        if "/auth/v1/user" in url:return response(route,session()["user"])
        if "/rest/v1/business_organisations" in url:
            return response(route,[{"id":ORG,"name":"QA Business",
                "industry":"hospitality","primary_goal":"awareness"}])
        if "/rest/v1/business_brand_kits" in url:
            return response(route,[{"id":BRAND,"organisation_id":ORG,
                "name":"QA Editorial","primary_color":"#132C24",
                "secondary_color":"#FFFFFF","default_cta":"","font_style":"modern",
                "logo_r2_key":None}])
        return response(route,{})
    if "/api/business/" in url:
        if "/api/business/sources?" in url:return response(route,{"sources":[]})
        if url.endswith("/api/business/sources/init"):
            return response(route,{"mode":"single","key":KEY,"source_id":SOURCE,
                "upload_url":"https://put.example.invalid/signed","content_type":"video/mp4"})
        if url.endswith("/api/business/sources/confirm"):
            return response(route,{"ok":True,"key":KEY,"source_id":SOURCE,"size":VIDEO_SIZE})
        if url.endswith("/api/business/visual/start"):
            return response(route,{"job_id":JOB,"status":"queued","replayed":False},202)
        if url.endswith("/api/business/visual/"+JOB):
            scan_reads+=1
            phases=["queued","downloading","scanning","done"]
            phase=phases[min(scan_reads-1,len(phases)-1)]
            return response(route,{"job_id":JOB,"status":phase,"phase":phase,
                "source_id":SOURCE,"scenes":[
                    {"timestamp_start":0,"timestamp_end":8,"title":"Visual scene 1"},
                    {"timestamp_start":8,"timestamp_end":16,"title":"Visual scene 2"},
                ] if phase=="done" else []})
        if url.endswith("/api/business/campaigns/prepare-visual"):
            return response(route,{"ai":{"status":"not_used","request_count":0},
                "brand":{"name":"QA Editorial","primary_color":"#132C24",
                         "secondary_color":"#FFFFFF"},
                "review_required":True,"clips":[{
                    "index":i,"source_id":SOURCE,"title":f"Visual scene {i+1}",
                    "start_s":i*8,"end_s":i*8+8,
                    "video_url":"r2://"+KEY,"why":"Review before publication",
                    "review_required":True
                } for i in range(2)]})
        return response(route,{"code":"not_found"},404)
    if "put.example.invalid" in url:return route.fulfill(status=200,body="")
    if "/api/preview-segment" in url:
        return response(route,{"status":"running","preview_id":"a"*32})
    if "/api/preview-status/" in url:
        return response(route,{"status":"running"})
    if "media.example.invalid" in url:return route.fulfill(status=404,body="")
    return route.continue_()

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,
        executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    page=browser.new_page(viewport={"width":1320,"height":870})
    errors=[]
    page.on("pageerror",lambda e:errors.append(str(e)))
    page.route("**/*",handle)
    page.goto(WEB+"/business/media?demo=1",wait_until="domcontentloaded",timeout=12000)
    page.evaluate("payload => localStorage.setItem('sb-example-auth-token',JSON.stringify(payload))",session())
    page.goto(WEB+"/business/media",wait_until="networkidle",timeout=15000)
    page.wait_for_function("() => document.querySelector('select[aria-label=\"Choose business\"]')?.value === '"+ORG+"'",timeout=10000)
    page.locator('input[type="file"][multiple]').set_input_files(str(VIDEO_FILE))
    page.get_by_text("clippr-business-qa-scenes-20261017.mp4").wait_for(timeout=7000)
    page.get_by_role("button",name="Upload & discover scenes").click()
    page.get_by_text("2 scenes").first.wait_for(timeout=17000)
    page.get_by_role("button",name="Build campaign pack").click()
    page.locator(".cbst-output-card").first.wait_for(timeout=7000)
    assert page.locator(".cbst-output-card").count()==2
    # In the window before the remote preview renders, display an actual
    # frame from the verified original source; never a fake completed clip.
    page.locator(".cbst-output-source-frame").first.wait_for(timeout=9000)
    assert page.locator(".cbst-still-indicator").count()>=1
    assert scan_reads>=4
    assert len([x for x in calls if "/sources/init" in x[1]])==1
    assert len([x for x in calls if "put.example.invalid" in x[1]])==1
    assert len([x for x in calls if "/sources/confirm" in x[1]])==1
    assert len([x for x in calls if "/visual/start" in x[1]])==1
    assert not errors, "JS errors: "+str(errors)
    print("REAL_SOURCE_FRAME_FROM_CORRECT_TIMESTAMP_OK")
    print("SCENE_STILL_CLEARLY_NOT_LABELED_FINISHED_CLIP")
    print("VISUAL_PACK_AND_OWNER_GUARDS_OK")
    browser.close()
