"""Browser smoke check with fully simulated credentials/data: NEVER touches live auth."""
import base64
import json
import time
from playwright.sync_api import sync_playwright

ROOT="http://127.0.0.1:4185"
AUTH="https://example.supabase.co"
API="https://api.clippr.org"
U_A="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
U_B="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
ORG_A="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ORG_B="ffffffff-ffff-4fff-8fff-ffffffffffff"
BRAND_A="cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SOURCE="d"*32
JOB="f"*32
state={"user":U_A,"calls":[],"owner_requests":[]}
def jwt(uid):
    def b(x):return base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip("=")
    return b({"typ":"JWT","alg":"HS256"})+"."+b({
        "iss":AUTH+"/auth/v1","sub":uid,"role":"authenticated","aud":"authenticated",
        "exp":int(time.time())+7200,"iat":int(time.time())})+".signed"
def user(uid):
    return {"id":uid,"aud":"authenticated","role":"authenticated",
       "email":"staging-"+uid[:3]+"@example.invalid",
       "app_metadata":{"provider":"email","providers":["email"]},
       "user_metadata":{},"created_at":"2026-10-17T16:00:00Z",
       "email_confirmed_at":"2026-10-17T16:00:00Z"}
def session(uid):
    return {"access_token":jwt(uid),"refresh_token":"not-a-real-refresh-token",
      "token_type":"bearer","expires_in":7200,"expires_at":int(time.time())+7200,
      "user":user(uid)}
def reply(route,body,status=200):
    route.fulfill(status=status,content_type="application/json",body=json.dumps(body))
def handle(route):
    req=route.request
    url=req.url
    state["calls"].append((req.method,url))
    if AUTH in url:
        if "/auth/v1/user" in url:return reply(route,user(state["user"]))
        if "/auth/v1/token" in url:return reply(route,{"error":"token refresh disabled for QA"},401)
        if "/rest/v1/business_organisations" in url:
            if state["user"]==U_A:return reply(route,[{"id":ORG_A,"name":"QA Hospitality","industry":"hospitality","primary_goal":"awareness"}])
            return reply(route,[{"id":ORG_B,"name":"QA Property","industry":"property","primary_goal":"education"}])
        if "/rest/v1/business_brand_kits" in url:
            if state["user"]==U_A:return reply(route,[{"id":BRAND_A,"organisation_id":ORG_A,
                "name":"Editorial","primary_color":"#17251C","secondary_color":"#FFFFFF",
                "font_style":"modern","default_cta":"Learn more","logo_r2_key":None}])
            return reply(route,[])
        return reply(route,{})
    if "/api/business/" in url:
        state["owner_requests"].append((state["user"],url))
        if "/api/business/sources?" in url:
            if state["user"]==U_A:
                return reply(route,{"sources":[{"source_id":SOURCE,"filename":"Brunch ambience.mp4",
                    "size":22000,"status":"confirmed"}]})
            return reply(route,{"sources":[]})
        if "/api/business/visual/source/" in url:
            if state["user"]!=U_A:return reply(route,{"code":"not_found"},404)
            return reply(route,{"status":"done","job_id":JOB,"source_id":SOURCE,"scene_count":2})
        if "/api/business/campaigns/prepare-visual" in url:
            if state["user"]!=U_A:return reply(route,{"code":"not_found"},404)
            return reply(route,{"brand":{"name":"Editorial","primary_color":"#17251C",
                "secondary_color":"#FFFFFF"},"review_required":True,
                "ai":{"status":"not_used","request_count":0},
                "clips":[{"index":i,"source_id":SOURCE,"title":"Visual scene "+str(i+1),
                    "start_s":i*10,"end_s":i*10+8,"review_required":True,
                    "video_url":"r2://business/sources/"+ORG_A+"/"+SOURCE+".mp4",
                    "why":"Review video footage"} for i in range(2)]})
        return reply(route,{"code":"not_found"},404)
    if "/api/preview-segment" in url:
        return reply(route,{"preview_url":"https://media.example.invalid/preview.mp4"})
    if "media.example.invalid" in url:
        return route.fulfill(status=404,content_type="text/plain",body="")
    return route.continue_()

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    page=browser.new_page(viewport={"width":1350,"height":900})
    def init_storage():
        page.goto(ROOT+"/business/media?demo=1",wait_until="domcontentloaded",timeout=15000)
        page.evaluate("""(payload) => {
          window.localStorage.setItem("sb-example-auth-token",JSON.stringify(payload));
        }""",session(state["user"]))
    page.route("**/*",handle)
    init_storage()
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)))
    page.goto(ROOT+"/business/media",wait_until="networkidle",timeout=16000)
    page.wait_for_function("() => document.querySelector('select[aria-label=\"Choose business\"]')?.value === '"+ORG_A+"'",timeout=10000)
    page.get_by_text("Brunch ambience.mp4").wait_for(timeout=9000)
    assert page.get_by_text("2 scenes").count()>=1
    page.get_by_role("button",name="Build campaign pack").click()
    page.locator(".cbst-output-card").first.wait_for(timeout=9000)
    assert page.locator(".cbst-output-card").count()==2
    assert "QA Hospitality" in page.locator("main").inner_text()
    assert not errors,"Page errors: "+str(errors)
    print("ACCOUNT_A_SESSION_FLOW_OK")
    state["user"]=U_B
    page.evaluate("""(payload) => {
        window.localStorage.setItem("sb-example-auth-token",JSON.stringify(payload));
    }""",session(U_B))
    page.reload(wait_until="networkidle",timeout=16000)
    page.wait_for_function("() => document.querySelector('select[aria-label=\"Choose business\"]')?.value === '"+ORG_B+"'",timeout=10000)
    assert page.get_by_text("Brunch ambience.mp4").count()==0,"Account A source leaked into B"
    assert page.locator(".cbst-output-card").count()==0,"Account A scene pack leaked"
    assert not errors,"Page errors: "+str(errors)
    print("ACCOUNT_SWITCH_ISOLATION_OK")
    browser.close()
