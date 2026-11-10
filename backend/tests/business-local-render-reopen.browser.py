"""Actual media export survives page reload, without duplicate render.

Uses independent QA localhost 4194 test workspace. User pilot 4192 not touched.
"""
from pathlib import Path
import subprocess,tempfile,uuid
from playwright.sync_api import sync_playwright

with tempfile.TemporaryDirectory(prefix="clippr-render-reopen-") as folder:
    source=Path(folder)/("scene-"+uuid.uuid4().hex[:6]+".mp4")
    subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
       "-f","lavfi","-i","testsrc2=size=320x180:rate=12:duration=24",
       "-c:v","libx264","-preset","ultrafast","-movflags","+faststart",
       str(source)],check=True,timeout=40,capture_output=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        context=browser.new_context(viewport={"width":1280,"height":900},accept_downloads=True)
        page=context.new_page()
        external=[]
        render_posts=[]
        errors=[]
        def qa_server(route):
            target=route.request.url
            if "/api/pilot/renders" in target and route.request.method=="POST":
                render_posts.append(target)
            return route.continue_(url=target.replace("127.0.0.1:4192","127.0.0.1:4194"))
        page.route("http://127.0.0.1:4192/**",qa_server)
        page.on("pageerror",lambda e:errors.append(str(e)))
        page.on("request",lambda r:external.append(r.url)
                if r.url.startswith("http") and
                not r.url.startswith("http://127.0.0.1:4185/") and
                not r.url.startswith("http://127.0.0.1:4192/") else None)
        page.goto("http://127.0.0.1:4185/business-pilot.html",wait_until="domcontentloaded",timeout=18000)
        page.get_by_text("Local engine connected").wait_for(timeout=10000)
        page.locator("#blp-video").set_input_files(str(source))
        card=page.locator(".blp-source").filter(has_text=source.name)
        card.get_by_text("2 real review windows found",exact=False).wait_for(timeout=85000)
        scene_checks=page.locator(".blp-scene input[type=checkbox]")
        scene_checks.nth(0).check();scene_checks.nth(1).check()
        page.get_by_role("button",name="Approve selections and save campaign").click()
        page.get_by_text("Campaign and manual approvals saved locally",exact=False).wait_for(timeout=13000)
        page.get_by_role("button",name="Render approved scenes").click()
        page.get_by_role("button",name="Download rendered MP4").wait_for(timeout=140000)
        assert len(render_posts)==1,len(render_posts)
        print("QA_ONE_RENDER_COMPLETED",flush=True)
        page.reload(wait_until="domcontentloaded",timeout=17000)
        page.get_by_text("Local engine connected").wait_for(timeout=10000)
        rows=page.locator(".blp-render-list button")
        rows.first.wait_for(timeout=9000)
        assert rows.count()>=1,rows.count()
        assert "READY" in rows.first.inner_text(),rows.first.inner_text()
        rows.first.click()
        page.get_by_role("button",name="Download rendered MP4").wait_for(timeout=7000)
        print("QA_RENDER_REOPENED_AFTER_REFRESH",flush=True)
        with page.expect_download(timeout=18000) as received:
            page.get_by_role("button",name="Download rendered MP4").click()
        output=Path(received.value.path())
        ffprobe=subprocess.run(["ffprobe","-v","error","-show_entries",
               "format=duration","-of","default=nokey=1:noprint_wrappers=1",
               str(output)],check=True,capture_output=True,text=True,timeout=20)
        duration=float(ffprobe.stdout.strip())
        assert 18<=duration<=29,duration
        assert output.stat().st_size>1500
        assert len(render_posts)==1,"Reopening render must not start a second job"
        assert not errors,errors
        assert not external,external[:5]
        print("QA_SAME_REAL_MP4_REDOWNLOADED",round(duration,2),flush=True)
        print("QA_NO_DUPLICATE_RENDER_AND_NO_EXTERNAL_REQUESTS",flush=True)
        browser.close()
