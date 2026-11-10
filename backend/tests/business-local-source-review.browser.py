"""Actual real-video preview, Range seek, and source reopening after refresh.

Uses distinct QA pilot on 4193; the owner's normal local 4192 workspace is
unmodified. Chrome routes backend requests to the isolated QA server.
"""
import subprocess
import uuid
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

URL="http://127.0.0.1:4185/business-pilot.html"
with tempfile.TemporaryDirectory(prefix="clippr-real-review-browser-") as tmp:
    clip=Path(tmp)/("review-source-"+uuid.uuid4().hex[:8]+".mp4")
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
        "-f","lavfi","-i","testsrc2=size=320x180:rate=12:duration=24",
        "-c:v","libx264","-preset","ultrafast","-movflags","+faststart",
        str(clip)],check=True,capture_output=True,timeout=40)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,
            executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        context=browser.new_context(viewport={"width":1250,"height":900})
        page=context.new_page()
        errors=[]
        intercepted=[]
        page.on("pageerror",lambda error:errors.append(str(error)))
        def qa_only(route):
            requested=route.request.url
            intercepted.append(requested)
            return route.continue_(url=requested.replace("127.0.0.1:4192","127.0.0.1:4193"))
        page.route("http://127.0.0.1:4192/**",qa_only)
        page.goto(URL,wait_until="domcontentloaded",timeout=15000)
        page.get_by_text("Local engine connected").wait_for(timeout=9000)
        page.locator("#blp-video").set_input_files(str(clip))
        current_source=page.locator(".blp-source").filter(has_text=clip.name)
        current_source.get_by_text("2 real review windows found",exact=False).wait_for(timeout=80000)
        print("QA_REAL_SCENE_SCAN_READY",flush=True)
        watches=page.get_by_role("button",name="Watch this window")
        assert watches.count()>=2
        watches.nth(1).click()
        page.get_by_text("Source is ready. Play the highlighted window",exact=False).wait_for(timeout=10000)
        player=page.locator(".blp-player")
        player.wait_for(timeout=10000)
        page.wait_for_function("() => {const v=document.querySelector('.blp-player');return v&&v.readyState>=1}",timeout=20000)
        page.wait_for_timeout(1800)
        print("QA_VIDEO_STATE",page.locator(".blp-player").evaluate("""v=>({
          currentTime:v.currentTime,duration:v.duration,networkState:v.networkState,
          readyState:v.readyState,error:v.error?.code,seekable:v.seekable.length,
          source:v.currentSrc.split("?")[0]})"""),flush=True)
        print("QA_UI_ERROR",page.locator(".blp-alert").all_text_contents(),flush=True)
        page.wait_for_function("() => {const v=document.querySelector('.blp-player');return v&&v.currentTime>=11.0}",timeout=7000)
        print("QA_SEEKS_SECOND_SCENE_TIMESTAMP",round(player.evaluate("(v)=>v.currentTime"),2),flush=True)
        assert player.evaluate("(v)=>v.videoWidth")>0
        assert "stream/" in player.get_attribute("src")
        page.reload(wait_until="domcontentloaded",timeout=14000)
        page.get_by_text("Local engine connected").wait_for(timeout=12000)
        originals=page.get_by_role("button",name="Watch original source")
        assert originals.count()>=1
        originals.first.click()
        page.wait_for_function("() => {const v=document.querySelector('.blp-player');return v&&v.readyState>=1}",timeout=18000)
        print("QA_ORIGINAL_FOOTAGE_AVAILABLE_AFTER_REFRESH",flush=True)
        page.get_by_role("button",name="Watch this window").nth(1).click()
        page.wait_for_timeout(1800)
        print("QA_VIDEO_STATE",page.locator(".blp-player").evaluate("""v=>({
          currentTime:v.currentTime,duration:v.duration,networkState:v.networkState,
          readyState:v.readyState,error:v.error?.code,seekable:v.seekable.length,
          source:v.currentSrc.split("?")[0]})"""),flush=True)
        print("QA_UI_ERROR",page.locator(".blp-alert").all_text_contents(),flush=True)
        page.wait_for_function("() => {const v=document.querySelector('.blp-player');return v&&v.currentTime>=11.0}",timeout=7000)
        print("QA_SCENE_SEEK_AVAILABLE_AFTER_REFRESH",flush=True)
        assert not errors,errors
        assert any("/api/pilot/stream/" in url for url in intercepted)
        print("QA_PRIVATE_RANGE_STREAM_REQUESTS",sum("/api/pilot/stream/" in url for url in intercepted),flush=True)
        browser.close()
