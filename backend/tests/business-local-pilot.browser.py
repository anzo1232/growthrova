"""Real local-only end-to-end Business video processing browser test.

Exercises the actual FFmpeg scan and montage renderer, not mocked clip data.
Does not use external user auth, customer R2, paid APIs or Stripe.
"""
import os, subprocess,tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

FRONT="http://127.0.0.1:4185/business-pilot.html"

with tempfile.TemporaryDirectory(prefix="clippr-business-pilot-browser-") as tmp:
    video=Path(tmp)/"real-scene-test.mp4"
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
        "-f","lavfi","-i","testsrc2=size=320x180:rate=12:duration=24",
        "-c:v","libx264","-preset","ultrafast","-movflags","+faststart",
        str(video)],check=True,timeout=45,capture_output=True)
    print("GENERATED_REAL_SYNTHETIC_SOURCE_BYTES",video.stat().st_size,flush=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",headless=True)
        context=browser.new_context(viewport={"width":1365,"height":910},accept_downloads=True)
        page=context.new_page()
        errors=[]
        requests=[]
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.on("request",lambda request:requests.append(request.url))
        page.goto(FRONT,wait_until="domcontentloaded",timeout=15000)
        page.get_by_text("Local engine connected").wait_for(timeout=14000)
        print("LOCAL_PILOT_CONNECTED")
        page.locator("#blp-video").set_input_files(str(video))
        page.get_by_text("Video received and queued",exact=False).wait_for(timeout=15000)
        print("ACTUAL_VIDEO_UPLOADED",flush=True)
        page.get_by_text("2 real review windows found",exact=False).first.wait_for(timeout=95000)
        print("REAL_FFMPEG_SCENE_SCAN_READY",flush=True)
        scenes=page.locator(".blp-scene input[type=checkbox]")
        assert scenes.count()>=2,scenes.count()
        scenes.nth(0).check()
        scenes.nth(1).check()
        page.get_by_role("button",name="Approve selections and save campaign").click()
        page.get_by_text("Campaign and manual approvals saved locally",exact=False).wait_for(timeout=12000)
        print("MANUAL_APPROVAL_AND_DURABLE_CAMPAIGN_SAVED",flush=True)
        page.get_by_role("button",name="Render approved scenes").click()
        page.get_by_text("Real FFmpeg montage queued",exact=False).wait_for(timeout=12000)
        print("ACTUAL_MONTAGE_QUEUED",flush=True)
        page.get_by_role("button",name="Download rendered MP4").wait_for(timeout=150000)
        with page.expect_download(timeout=20000) as report:
            page.get_by_role("button",name="Download rendered MP4").click()
        download=report.value
        output=Path(download.path())
        assert output.stat().st_size>2000
        assert download.suggested_filename=="clippr-business-local-test.mp4"
        probe=subprocess.run(["ffprobe","-v","error","-show_entries",
           "format=duration","-of","default=nokey=1:noprint_wrappers=1",str(output)],
           capture_output=True,text=True,timeout=20,check=True)
        duration=float(probe.stdout.strip())
        assert 15<duration<35,duration
        assert not errors,errors
        print("REAL_FFMPEG_BRANDED_MP4_DOWNLOADED",output.stat().st_size,round(duration,2),flush=True)
        remote=[u for u in requests if u.startswith("http") and
            not u.startswith("http://127.0.0.1:4185/") and
            not u.startswith("http://127.0.0.1:4192/")]
        assert not remote, "Local pilot must not access outside services: "+str(remote[:4])
        print("NO_EXTERNAL_SERVICE_REQUESTS",True,flush=True)
        page.set_viewport_size({"width":390,"height":844})
        page.wait_for_timeout(200)
        overflow=page.evaluate("() => document.documentElement.scrollWidth-innerWidth")
        assert overflow<=2,"Mobile layout overflows by "+str(overflow)+"px"
        print("MOBILE_NO_HORIZONTAL_OVERFLOW",flush=True)
        browser.close()
