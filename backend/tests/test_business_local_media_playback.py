"""Private local video preview with byte seek ranges and expiring signed URLs."""
import hashlib
import json
import tempfile
import threading
import time
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import business_local_pilot as pilot

ORIGIN="http://127.0.0.1:4185"
class SignedMediaTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="clippr-signed-media-")
        self.addCleanup(tmp.cleanup)
        self.old_root=pilot.BASE
        pilot.BASE=Path(tmp.name)
        self.addCleanup(setattr,pilot,"BASE",self.old_root)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),pilot.Handler)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        worker=threading.Thread(target=self.server.serve_forever,daemon=True)
        worker.start()
        self.base="http://127.0.0.1:"+str(self.server.server_port)
        self.source=uuid.uuid4().hex
        self.bytes=bytes(range(256))*16
        with pilot.session() as db:
            db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
               (self.source,"original.mp4","video/mp4",len(self.bytes),
                "done",json.dumps({"duration_s":12,"scenes":[]}),
                time.time(),time.time()))
        (pilot.BASE/"files"/(self.source+".mp4")).write_bytes(self.bytes)
    def request(self,path,*,method="GET",origin=ORIGIN,header=False,range_header=None):
        headers={"Origin":origin}
        if header:headers["X-Clippr-Pilot"]="local-only"
        if range_header:headers["Range"]=range_header
        req=Request(self.base+path,headers=headers,method=method)
        try:
            with urlopen(req,timeout=8) as r:
                return r.status,dict(r.headers.items()),r.read()
        except HTTPError as e:
            with e:return e.code,dict(e.headers.items()),e.read()
    def playback(self):
        status,headers,body=self.request(
            "/api/pilot/sources/"+self.source+"/playback",header=True)
        self.assertEqual(status,200,body)
        value=json.loads(body)
        self.assertTrue(value["url"].startswith("/api/pilot/stream/"+self.source))
        return value
    def test_safe_preview_replays_original_file_after_reload(self):
        value=self.playback()
        status,headers,body=self.request(value["url"],range_header="bytes=100-199")
        self.assertEqual(status,206)
        self.assertEqual(body,self.bytes[100:200])
        self.assertEqual(headers.get("Content-Range"),"bytes 100-199/4096")
        self.assertEqual(headers.get("Accept-Ranges"),"bytes")
        self.assertEqual(headers.get("Access-Control-Allow-Origin"),ORIGIN)
        self.assertEqual(headers.get("Content-Type"),"video/mp4")
        self.assertEqual(headers.get("Cache-Control"),"private,no-store")
    def test_suffix_range_and_head_are_bounded(self):
        link=self.playback()["url"]
        status,headers,body=self.request(link,range_header="bytes=-49")
        self.assertEqual((status,len(body)),(206,49))
        self.assertEqual(body,self.bytes[-49:])
        status,headers,body=self.request(link,method="HEAD")
        self.assertEqual((status,len(body)),(200,0))
        self.assertEqual(int(headers["Content-Length"]),len(self.bytes))
    def test_full_file_bytes_match_original(self):
        status,headers,body=self.request(self.playback()["url"])
        self.assertEqual(status,200)
        self.assertEqual(hashlib.sha256(body).digest(),
                         hashlib.sha256(self.bytes).digest())
    def test_forged_or_expired_media_url_never_leaks(self):
        value=self.playback()["url"]
        sep="&" if "?" in value else "?"
        for path in ("/api/pilot/stream/"+self.source,
                     value.replace("sig=","sig=evil"),
                     value+"&sig=duplicate",
                     "/api/pilot/stream/"+uuid.uuid4().hex+"?"+value.split("?",1)[1]):
            status,_,_=self.request(path)
            self.assertEqual(status,403,path)
        query=urlsplit(value).query
        self.assertFalse(pilot.verify_media_ticket(self.source,query,
            now=time.time()+pilot.MEDIA_TTL_SECONDS+2))
    def test_other_origins_and_missing_origin_cannot_embed(self):
        value=self.playback()["url"]
        for origin in ("https://evil.example","http://localhost:3000",""):
            code,_,body=self.request(value,origin=origin)
            self.assertEqual(code,403,(origin,body))
    def test_invalid_or_multiple_byte_ranges_rejected(self):
        url=self.playback()["url"]
        for value in ("bytes=5000-","bytes=5-4","bytes=0-2,4-8",
                      "items=0-9","bytes=-0"):
            status,headers,body=self.request(url,range_header=value)
            self.assertEqual(status,416,value)
            self.assertEqual(headers.get("Content-Range"),"bytes */4096")
    def test_signed_link_cannot_access_deleted_or_missing_source(self):
        link=self.playback()["url"]
        (pilot.BASE/"files"/(self.source+".mp4")).unlink()
        self.assertEqual(self.request(link)[0],404)
        # The metadata endpoint must not issue a URL for deleted data.
        self.assertEqual(self.request(
            "/api/pilot/sources/"+self.source+"/playback",header=True)[0],409)

if __name__=="__main__":unittest.main()
