from playwright.sync_api import sync_playwright
from pathlib import Path
URL="http://127.0.0.1:4185/business/media?demo=1"
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    page=browser.new_page(viewport={"width":1330,"height":860},accept_downloads=True)
    requests=[]
    page.on("request",lambda r:requests.append(r.url) if "/api/business/" in r.url else None)
    page.goto(URL,wait_until="networkidle",timeout=16000)
    page.get_by_role("button",name="Add to shot list").first.click()
    page.get_by_text("1 ideas shortlisted").wait_for(timeout=4000)
    with page.expect_download(timeout=9000) as report:
        page.get_by_role("button",name="Download sample shot list (.csv)").click()
    file=report.value
    result=Path(file.path()).read_bytes().decode("utf-8-sig")
    assert "illustrative demo" in result
    assert "human approval required" in result
    assert "Visual scene 02" not in result
    assert not requests, "No private customer API should be used in demo"
    print("INTERACTIVE_DEMO_SHOTLIST_CSV_OK")
    print("DEMO_DID_NOT_USE_PRIVATE_BUSINESS_APIS")
    browser.close()
