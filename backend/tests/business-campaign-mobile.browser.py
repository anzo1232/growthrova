"""Actual signed-in UI upload smoke test against fully mocked, non-live APIs.

No customer API secrets, real footage or paid provider calls. A 3KB synthetic
file exercises the browser picker, owner-scoped upload/confirmation, visual
queue/poll states and campaign-pack UI.
"""
import base64
import json
import time
import uuid
from playwright.sync_api import sync_playwright

WEB = "http://127.0.0.1:4185"
ORG = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BRAND = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SOURCE = "d"*32
JOB = "e"*32
KEY = f"business/sources/{ORG}/{SOURCE}.mp4"
calls = []
scan_reads = 0
drafts={}
mock={"enable_montage":False,"saved":0,"montage_posts":0,"montage_reads":0,
      "drop_next_save_ack":False,"uncertain_id":None}

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
        path=url.split("/api/business/",1)[1].split("?",1)[0]
        if path=="drafts":
            if request.method=="GET":
                return response(route,{"campaigns":[{
                    "id":x["id"],"name":x["name"],"goal":x["goal"],
                    "brand_id":x["brand_id"],"revision":x["revision"],
                    "updated_at":x["updated_at"]
                } for x in drafts.values()]})
            if request.method=="POST":
                payload=json.loads(request.post_data)
                rid=payload.get("id") or payload.get("create_id")
                assert rid
                if rid in drafts:
                    old=drafts[rid]
                    if payload.get("revision")!=old["revision"]:
                        return response(route,{"code":"revision_conflict","error":"Campaign changed. Refresh before saving."},409)
                    current={**old,**{k:v for k,v in payload.items()
                        if k in ("name","goal","notes","scenes","brand_id")}}
                    current["revision"]=old["revision"]+1
                    current["updated_at"]="2026-10-18T12:00:00Z"
                else:
                    current={**payload,"id":rid,"revision":1,
                        "updated_at":"2026-10-18T12:00:00Z",
                        "created_at":"2026-10-18T12:00:00Z"}
                drafts[rid]=current
                mock["saved"]+=1
                if mock["drop_next_save_ack"]:
                    mock["drop_next_save_ack"]=False
                    mock["uncertain_id"]=rid
                    return route.abort("failed")
                return response(route,{"id":rid,"revision":current["revision"],
                    "updated":"2026-10-18T12:00:00Z"})
        if path.startswith("drafts/"):
            rid=path.split("/")[-1]
            if request.method=="GET":
                if rid not in drafts:return response(route,{"code":"not_found"},404)
                return response(route,drafts[rid])
            if request.method=="DELETE":
                drafts.pop(rid,None)
                return response(route,{"ok":True})
        if path=="montages":
            if request.method=="POST":
                mock["montage_posts"]+=1
                if not mock["enable_montage"]:
                    return response(route,{"code":"montage_unavailable","error":"Montage unavailable"},404)
                payload=json.loads(request.post_data)
                assert payload["draft_id"] in drafts
                assert payload["draft_revision"]==drafts[payload["draft_id"]]["revision"]
                assert all(x.get("review_status")=="approved" for x in drafts[payload["draft_id"]]["scenes"])
                assert len(payload["scenes"])==2
                return response(route,{"montage_id":"f"*32,"status":"queued","phase":"queued","replayed":False},202)
        if path=="montages/"+("f"*32):
            mock["montage_reads"]+=1
            if mock["montage_reads"]<2:
                return response(route,{"montage_id":"f"*32,"status":"running","phase":"rendering"})
            return response(route,{"montage_id":"f"*32,"status":"done",
                "url":"https://media.example.invalid/secure-render.mp4"})
        if "/api/business/sources?" in url:return response(route,{"sources":[]})
        if url.endswith("/api/business/sources/init"):
            return response(route,{"mode":"single","key":KEY,"source_id":SOURCE,
                "upload_url":"https://put.example.invalid/signed","content_type":"video/mp4"})
        if url.endswith("/api/business/sources/confirm"):
            return response(route,{"ok":True,"key":KEY,"source_id":SOURCE,"size":3000})
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
        return response(route,{"preview_url":"https://media.example.invalid/test.mp4"})
    if "media.example.invalid" in url:return route.fulfill(status=404,body="")
    return route.continue_()

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,
        executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    page=browser.new_page(viewport={"width":390,"height":844})
    errors=[]
    page.on("pageerror",lambda e:errors.append(str(e)))
    page.route("**/*",handle)
    page.goto(WEB+"/business/media?demo=1",wait_until="domcontentloaded",timeout=12000)
    page.evaluate("payload => localStorage.setItem('sb-example-auth-token',JSON.stringify(payload))",session())
    page.goto(WEB+"/business/media",wait_until="networkidle",timeout=15000)
    consent=page.get_by_role("button",name="Reject",exact=True)
    if consent.count():consent.click()
    page.wait_for_function("() => document.querySelector('select[aria-label=\"Choose business\"]')?.value === '"+ORG+"'",timeout=10000)
    page.locator('input[type="file"][multiple]').set_input_files({
      "name":"QA synthetic.mp4","mimeType":"video/mp4",
      "buffer":b'\x00'*3000
    })
    page.get_by_text("QA synthetic.mp4").wait_for(timeout=7000)
    page.get_by_role("button",name="Upload & discover scenes").click()
    page.get_by_text("2 scenes").first.wait_for(timeout=17000)
    page.get_by_role("button",name="Build campaign pack").click()
    page.locator(".cbst-output-card").first.wait_for(timeout=7000)
    assert page.locator(".cbst-output-card").count()==2
    page.wait_for_timeout(350)
    overflow=page.evaluate("() => document.documentElement.scrollWidth-window.innerWidth")
    assert overflow<=2, "Mobile horizontal overflow: "+str(overflow)
    panel=page.locator(".biz-draft-panel")
    panel.get_by_role("button",name="Use current scene pack").click()
    panel.locator('input[name="business-campaign-name"]').fill("Autumn Brunch Launch")
    panel.get_by_role("checkbox",name="Human approved").first.check()
    panel.get_by_role("checkbox",name="Human approved").nth(1).check()
    panel.get_by_role("checkbox",name="Include in montage").first.check()
    panel.get_by_role("checkbox",name="Include in montage").nth(1).check()
    panel.get_by_role("button",name="Save campaign").click()
    panel.get_by_text("Campaign saved successfully.",exact=False).wait_for(timeout=6500)
    assert len(drafts)==1
    rid=next(iter(drafts))
    assert drafts[rid]["revision"]==1
    assert len(drafts[rid]["scenes"])==2
    assert all(x["review_status"]=="approved" for x in drafts[rid]["scenes"])
    assert "video_url" not in str(drafts[rid])
    panel.get_by_role("button",name="Request montage").click()
    panel.get_by_text("Montage exports are not active",exact=False).wait_for(timeout=6000)
    assert len(drafts)==1
    mock["enable_montage"]=True
    panel.get_by_role("button",name="Request montage").click()
    panel.get_by_text("Your montage is ready").wait_for(timeout=11000)
    assert panel.get_by_role("link",name="Open secure montage link").count()==1
    assert mock["montage_posts"]==2
    page.reload(wait_until="networkidle",timeout=15000)
    panel=page.locator(".biz-draft-panel")
    panel.get_by_role("button",name="Autumn Brunch Launch").click()
    panel.get_by_text("Campaign loaded.",exact=False).wait_for(timeout=7000)
    assert panel.get_by_role("checkbox",name="Human approved").count()==2
    assert panel.get_by_role("checkbox",name="Human approved").nth(0).is_checked()
    panel.locator('textarea').first.fill("Updated notes in editor")
    drafts[rid]["revision"]=2  # second editor changed the record
    panel.get_by_role("button",name="Save changes").click()
    panel.get_by_text("updated elsewhere",exact=False).wait_for(timeout=6000)
    assert drafts[rid]["notes"]!="Updated notes in editor"
    assert scan_reads>=4
    assert len([x for x in calls if "/sources/init" in x[1]])==1
    assert len([x for x in calls if "put.example.invalid" in x[1]])==1
    assert len([x for x in calls if "/sources/confirm" in x[1]])==1
    assert len([x for x in calls if "/visual/start" in x[1]])==1
    assert not errors, "JS errors: "+str(errors)
    print("MOBILE_CAMPAIGN_WORKSPACE_NO_OVERFLOW_OK")
    print("BRANDED_MONTAGE_FLAG_OFF_AND_POLLING_OK")
    print("STALE_REVISION_CONFLICT_BLOCKED_OK")
    browser.close()
