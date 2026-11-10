"""Real FFmpeg, business-style media e2e; isolated localhost, no customer footage."""
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from http.server import ThreadingHTTPServer
import requests
import business_local_pilot as pilot

def fixture(path, portrait, name):
    dimensions="360x640" if portrait else "640x360"
    # Distinct shots and hard cuts imitate typical vertical reels / landscape business B-roll.
    with tempfile.TemporaryDirectory(prefix="clippr-business-shots-") as folder:
        pieces=[]
        for index,(colour,caption) in enumerate([
            ("0x3d674e","VENUE EXTERIOR"),
            ("0x977357","PRODUCT DETAIL"),
            ("0x515b7c","SERVICE IN ACTION"),
        ]):
            out=Path(folder)/f"shot-{index}.mp4"
            filter_=f"drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:text='{caption}':fontcolor=white:fontsize=24:x=(w-text_w)/2:y=(h-text_h)/2"
            subprocess.run(["ffmpeg","-v","error","-nostdin","-y","-f","lavfi",
                "-i",f"color=c={colour}:s={dimensions}:r=12:d=6",
                "-c:v","libx264","-preset","ultrafast",
                "-pix_fmt","yuv420p",str(out)],check=True,timeout=35,capture_output=True)
            pieces.append(out)
        concat=Path(folder)/"playlist.txt"
        concat.write_text("".join(f"file '{p.name}'\n" for p in pieces))
        subprocess.run(["ffmpeg","-v","error","-nostdin","-y","-f","concat","-safe","1",
            "-i",str(concat),"-c","copy","-movflags","+faststart",str(path)],
            check=True,capture_output=True,timeout=35)

def main():
    with tempfile.TemporaryDirectory(prefix="clippr-business-hospitality-e2e-") as work:
        root=Path(work)
        prior=pilot.BASE
        pilot.BASE=root/"db"
        server=ThreadingHTTPServer(("127.0.0.1",0),pilot.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        url=f"http://127.0.0.1:{server.server_port}"
        headers={"Origin":"http://127.0.0.1:4185","X-Clippr-Pilot":"local-only"}
        def api(route, method="GET", data=None, binary=None, mime="application/json"):
            h={**headers}
            if binary is not None:
                h.update({"Content-Type":mime,"X-Clippr-Filename":"hospitality-broll.mp4"})
            else:h["Content-Type"]="application/json"
            response=requests.request(method,url+route,headers=h,
                data=binary if binary is not None else (json.dumps(data) if data is not None else None),
                timeout=40)
            if response.status_code>=400:raise AssertionError(f"{route} HTTP {response.status_code}: {response.text[:240]}")
            return response.json()
        try:
            windows=[]
            for portrait,label in [(True,"VERTICAL"),(False,"LANDSCAPE")]:
                path=root/f"{label.lower()}.mp4"
                fixture(path,portrait,label)
                uploaded=api("/api/pilot/uploads","POST",binary=path.read_bytes(),mime="video/mp4")
                sid=uploaded["id"]
                deadline=time.monotonic()+50
                while time.monotonic()<deadline:
                    source=api("/api/pilot/sources/"+sid)
                    if source["status"] in ("done","error"):break
                    time.sleep(.4)
                assert source["status"]=="done",(label,source["status"])
                scenes=source["result"]["scenes"]
                assert scenes,label
                # Pick verified source windows, trim nothing outside scan-validated segments.
                selected=next((x for x in scenes if 3<=float(x["timestamp_end"])-float(x["timestamp_start"])<=30),None)
                assert selected,(label,scenes)
                windows.append({"source_id":sid,"start_s":selected["timestamp_start"],
                                "end_s":selected["timestamp_end"],"review_status":"approved"})
                print(label+"_UPLOAD_SCAN_PASS",len(scenes),"windows",flush=True)
            campaign=api("/api/pilot/campaigns","POST",data={"name":"Hospitality venue reel",
                "brand_name":"Demo Cafe","goal":"bookings","scenes":windows})
            job=api("/api/pilot/renders","POST",
                    data={"campaign_id":campaign["id"],"revision":campaign["revision"]})
            deadline=time.monotonic()+150
            while time.monotonic()<deadline:
                result=api("/api/pilot/renders/"+job["id"])
                if result["status"] in ("done","error","unavailable"):break
                time.sleep(.8)
            assert result["status"]=="done",result
            downloaded=requests.get(url+"/api/pilot/download/"+job["id"],headers=headers,timeout=40)
            assert downloaded.status_code==200,downloaded.status_code
            output=root/"hospitality-montage.mp4"
            output.write_bytes(downloaded.content)
            probe=subprocess.run(["ffprobe","-v","error","-show_entries",
                "format=duration:stream=width,height,codec_type","-of","json",str(output)],
                capture_output=True,text=True,check=True,timeout=15)
            info=json.loads(probe.stdout)
            assert info["streams"][0]["width"]==360
            assert info["streams"][0]["height"]==640
            assert len(downloaded.content)>2500
            print("MULTI_SOURCE_BRANDED_VIDEO_PASS",round(float(info["format"]["duration"]),2),
                  "seconds",len(downloaded.content),"bytes",flush=True)
            assert api("/api/pilot/renders","POST",data={
                "campaign_id":campaign["id"],"revision":campaign["revision"]})["replayed"]
            print("IDEMPOTENT_EXPORT_PASS",flush=True)
        finally:
            server.shutdown()
            server.server_close()
            pilot.BASE=prior

if __name__=="__main__":main()
