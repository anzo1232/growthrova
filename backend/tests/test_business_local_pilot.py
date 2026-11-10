"""Real localhost HTTP test of the isolated Business pilot; no live services."""
from __future__ import annotations
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import business_local_pilot as pilot

class LocalPilotTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="clippr-pilot-http-test-")
        self.addCleanup(tmp.cleanup)
        self.old_root=pilot.BASE
        pilot.BASE=Path(tmp.name)
        self.addCleanup(setattr,pilot,"BASE",self.old_root)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),pilot.Handler)
        self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url="http://127.0.0.1:"+str(self.port)
    def api(self,path,*,method="GET",body=None,origin="http://127.0.0.1:4185",
            pilot_header="local-only",content_type="application/json"):
        headers={"Origin":origin,"X-Clippr-Pilot":pilot_header,
                 "Content-Type":content_type}
        payload=json.dumps(body).encode() if body is not None else None
        request=Request(self.url+path,method=method,headers=headers,data=payload)
        try:
            with urlopen(request,timeout=8) as r:return r.status,json.loads(r.read())
        except HTTPError as e:
            try:return e.code,json.loads(e.read())
            finally:e.close()
    def test_only_allowed_local_origin_and_header(self):
        code,out=self.api("/api/pilot/health")
        self.assertEqual(code,200)
        self.assertTrue(out["real_ffmpeg"])
        self.assertFalse(out["external_services"])
        for origin,header in [("https://evil.example","local-only"),
                              ("http://127.0.0.1:4185",""),
                              ("https://clippr.org","local-only")]:
            status,result=self.api("/api/pilot/health",origin=origin,pilot_header=header)
            self.assertEqual(status,403)
    def test_website_audit_rejects_private_sites_and_requires_approval(self):
        code,out=self.api("/api/pilot/website-audit",method="POST",body={"website":"http://127.0.0.1/private"})
        self.assertEqual(code,422)
        with patch.object(pilot,'extract_website',return_value={'source_url':'https://example.org','status':'extracted_unconfirmed','confirmed':False,'observations':{'title':'Example','service_links':[]}}):
            code,out=self.api("/api/pilot/website-audit",method="POST",body={"website":"https://example.org"})
        self.assertEqual(code,200)
        self.assertFalse(out['audit']['confirmed'])
        self.assertTrue(out['approval_required'])

    def test_invalid_media_is_denied_without_storing_source(self):
        status,payload=self.api("/api/pilot/uploads",method="POST",body={"bad":"video"})
        self.assertEqual(status,415)
        with pilot.session() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sources").fetchone()[0],0)
    def test_save_retry_is_idempotent_and_mismatch_refused(self):
        sid="a"*32
        with pilot.session() as db:
            db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",(
                sid,"qa.mp4","video/mp4",4000,"done",
                json.dumps({"duration_s":20,"scenes":[
                    {"timestamp_start":0,"timestamp_end":10},
                    {"timestamp_start":10,"timestamp_end":20}]}),
                time.time(),time.time()))
        ident=uuid.uuid4().hex
        scene=lambda a,b:{"source_id":sid,"start_s":a,"end_s":b,"review_status":"approved"}
        content={"id":ident,"name":"My launch video","brand_name":"QA Brand",
                 "goal":"awareness","scenes":[scene(0,10),scene(10,20)]}
        a,b=self.api("/api/pilot/campaigns",method="POST",body=content)
        self.assertEqual(a,200)
        self.assertEqual(b["revision"],1)
        status,replayed=self.api("/api/pilot/campaigns",method="POST",body=content)
        self.assertEqual(status,200)
        self.assertTrue(replayed["replayed"])
        self.assertEqual(replayed["revision"],1)
        changed={**content,"name":"Different campaign"}
        status,problem=self.api("/api/pilot/campaigns",method="POST",body=changed)
        self.assertEqual(status,409)
        self.assertEqual(problem["code"],"create_id_conflict")
        with pilot.session() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM campaigns").fetchone()[0],1)
    def test_real_render_requires_explicit_approved_windows(self):
        sid="b"*32
        with pilot.session() as db:
            db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",(
                sid,"qa.mp4","video/mp4",4000,"done",
                json.dumps({"duration_s":20,"scenes":[
                    {"timestamp_start":0,"timestamp_end":10},
                    {"timestamp_start":10,"timestamp_end":20}]}),
                time.time(),time.time()))
        ident=uuid.uuid4().hex
        body={"id":ident,"name":"QA campaign","brand_name":"QA Brand",
              "goal":"bookings","scenes":[
                {"source_id":sid,"start_s":0,"end_s":10,"review_status":"draft"},
                {"source_id":sid,"start_s":10,"end_s":20,"review_status":"approved"}]}
        status,_=self.api("/api/pilot/campaigns",method="POST",body=body)
        self.assertEqual(status,200)
        status,denial=self.api("/api/pilot/renders",method="POST",
                               body={"campaign_id":ident,"revision":1})
        self.assertEqual(status,409)
        self.assertEqual(denial["code"],"approval_required")
    def test_recent_render_history_and_missing_output_fail_closed(self):
        stable=uuid.uuid4().hex
        missing=uuid.uuid4().hex
        now=time.time()
        with pilot.session() as db:
            db.execute("""INSERT INTO renders VALUES(?,?,?,?,?,?,?,?,?)""",
                       (stable,"c"*32,1,"f"*64,"done",22.0,None,now,now))
            db.execute("""INSERT INTO renders VALUES(?,?,?,?,?,?,?,?,?)""",
                       (missing,"d"*32,1,"e"*64,"done",14.0,None,now+1,now+1))
        output=pilot.BASE/"exports"/(stable+".mp4")
        output.write_bytes(b"real-synthetic-mp4-placeholder"*250)
        code,records=self.api("/api/pilot/renders")
        self.assertEqual(code,200)
        self.assertEqual(len(records["renders"]),2)
        statuses={r["id"]:r["status"] for r in records["renders"]}
        self.assertEqual(statuses[stable],"done")
        self.assertEqual(statuses[missing],"unavailable")
        code,record=self.api("/api/pilot/renders/"+stable)
        self.assertEqual((code,record["status"]),(200,"done"))
        self.assertEqual(record["url"],"/api/pilot/download/"+stable)
        code,record=self.api("/api/pilot/renders/"+missing)
        self.assertEqual((code,record["status"]),(200,"unavailable"))
        self.assertIsNone(record["url"])
        self.assertIn("missing",record["error"])
        code,record=self.api("/api/pilot/renders",origin="https://evil.example")
        self.assertEqual(code,403)

    def test_missing_render_never_claims_success_on_download_or_replay(self):
        sid="a"*32
        campaign_id="b"*32
        scenes=[{"source_id":sid,"start_s":0,"end_s":10,"review_status":"approved"},
                {"source_id":sid,"start_s":10,"end_s":20,"review_status":"approved"}]
        payload=json.dumps(scenes)
        revision=1
        fingerprint=__import__("hashlib").sha256(
            (campaign_id+":"+str(revision)+":"+payload).encode()).hexdigest()
        render_id="c"*32
        now=time.time()
        with pilot.session() as con:
            con.execute("INSERT INTO campaigns VALUES(?,?,?,?,?,?,?)",
                        (campaign_id,revision,"QA campaign","QA Brand","bookings",payload,now))
            con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
                        (sid,"qa.mp4","video/mp4",4000,"done",
                         json.dumps({"scenes":[{"timestamp_start":0,"timestamp_end":10},
                                                {"timestamp_start":10,"timestamp_end":20}]}),now,now))
            con.execute("INSERT INTO renders VALUES(?,?,?,?,?,?,?,?,?)",
                        (render_id,campaign_id,revision,fingerprint,"done",20,None,now,now))
        status,response=self.api("/api/pilot/download/"+render_id)
        self.assertEqual(status,409)
        self.assertEqual(response["code"],"render_unavailable")
        status,response=self.api("/api/pilot/renders",method="POST",
                                 body={"campaign_id":campaign_id,"revision":revision})
        self.assertEqual(status,409)
        self.assertEqual(response["code"],"render_retry_required")
        self.assertEqual(response["status"],"unavailable")
        self.assertEqual(response["id"],render_id)

    def test_interrupted_source_retry_reuses_original_and_deduplicates(self):
        from unittest.mock import patch
        sid="f"*32
        now=time.time()
        with pilot.session() as con:
            con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
                        (sid,"clip.mp4","video/mp4",4096,"interrupted",None,now,now))
        video=pilot.BASE/"files"/(sid+".mp4")
        video.write_bytes(b"x"*4096)
        with patch.object(pilot.EXEC,"submit") as submit:
            code,result=self.api("/api/pilot/sources/"+sid+"/retry",method="POST")
            self.assertEqual(code,202)
            self.assertFalse(result["replayed"])
            code,again=self.api("/api/pilot/sources/"+sid+"/retry",method="POST")
            self.assertEqual(code,200)
            self.assertTrue(again["replayed"])
            submit.assert_called_once_with(pilot.scan_source,sid)
        with pilot.session() as con:
            self.assertEqual(con.execute("SELECT status FROM sources WHERE id=?",(sid,)).fetchone()[0],"queued")
        self.assertEqual(video.read_bytes(),b"x"*4096)

    def test_interrupted_source_retry_missing_file_fails_closed(self):
        sid="e"*32
        now=time.time()
        with pilot.session() as con:
            con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
                        (sid,"clip.mp4","video/mp4",4096,"interrupted",None,now,now))
        with patch.object(pilot.EXEC,"submit") as submit:
            code,result=self.api("/api/pilot/sources/"+sid+"/retry",method="POST")
            self.assertEqual(code,409)
            self.assertEqual(result["code"],"source_missing")
            submit.assert_not_called()

    def test_failed_render_retry_is_explicit_bounded_and_idempotent(self):
        sid="a"*32
        campaign_id="b"*32
        old_id="c"*32
        scenes=[{"source_id":sid,"start_s":0,"end_s":10,"review_status":"approved"},
                {"source_id":sid,"start_s":10,"end_s":20,"review_status":"approved"}]
        import hashlib
        fingerprint=hashlib.sha256((campaign_id+":1:"+json.dumps(scenes)).encode()).hexdigest()
        now=time.time()
        with pilot.session() as con:
            con.execute("INSERT INTO campaigns VALUES(?,?,?,?,?,?,?)",
                 (campaign_id,1,"QA campaign","QA Brand","awareness",json.dumps(scenes),now))
            con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
                 (sid,"source.mp4","video/mp4",4096,"done",
                  json.dumps({"scenes":[{"timestamp_start":0,"timestamp_end":10},
                                         {"timestamp_start":10,"timestamp_end":20}]}),now,now))
            con.execute("INSERT INTO renders VALUES(?,?,?,?,?,?,?,?,?)",
                 (old_id,campaign_id,1,fingerprint,"interrupted",20,None,now,now))
        source=pilot.BASE/"files"/(sid+".mp4")
        source.write_bytes(b"a"*4096)
        with patch.object(pilot.EXEC,"submit") as submit:
            code,result=self.api("/api/pilot/renders/"+old_id+"/retry",method="POST")
            self.assertEqual(code,202,result)
            self.assertEqual(result["status"],"queued")
            code,repeated=self.api("/api/pilot/renders/"+old_id+"/retry",method="POST")
            self.assertEqual(code,200)
            self.assertTrue(repeated["replayed"])
            self.assertEqual(repeated["id"],result["id"])
            submit.assert_called_once()
            with pilot.session() as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM renders").fetchone()[0],2)
            code,denied=self.api("/api/pilot/renders/"+result["id"]+"/retry",method="POST")
            self.assertEqual(code,409)
            self.assertEqual(denied["code"],"retry_not_allowed")

    def test_render_retry_refuses_missing_original_footage(self):
        sid="d"*32
        campaign_id="e"*32
        old_id="f"*32
        scenes=[{"source_id":sid,"start_s":0,"end_s":10,"review_status":"approved"},
                {"source_id":sid,"start_s":10,"end_s":20,"review_status":"approved"}]
        now=time.time()
        with pilot.session() as con:
            con.execute("INSERT INTO campaigns VALUES(?,?,?,?,?,?,?)",
                 (campaign_id,1,"QA campaign","QA Brand","awareness",json.dumps(scenes),now))
            con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
                 (sid,"source.mp4","video/mp4",4096,"done",
                  json.dumps({"scenes":[{"timestamp_start":0,"timestamp_end":10},
                                         {"timestamp_start":10,"timestamp_end":20}]}),now,now))
            con.execute("INSERT INTO renders VALUES(?,?,?,?,?,?,?,?,?)",
                 (old_id,campaign_id,1,"f"*64,"interrupted",20,None,now,now))
        with patch.object(pilot.EXEC,"submit") as submit:
            code,result=self.api("/api/pilot/renders/"+old_id+"/retry",method="POST")
            self.assertEqual(code,409)
            self.assertEqual(result["code"],"approval_required")
            submit.assert_not_called()
    def test_real_spoken_transcript_admission_is_source_scoped(self):
        sid="f"*32
        now=time.time()
        with pilot.session() as con:
            con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",(
                sid,"food.mp4","video/mp4",4096,"done",
                json.dumps({"duration_s":120,"scenes":[]}),now,now))
        transcript=[{"start":i*5,"end":i*5+4,"text":f"Review line {i}"} for i in range(20)]
        code,out=self.api("/api/pilot/sources/"+sid+"/transcript",method="POST",body={"segments":transcript})
        self.assertEqual(code,200,out)
        self.assertGreater(out["count"],1)
        with pilot.session() as con:
            stored=json.loads(pilot.row(con,"sources",sid)["result_json"])
        self.assertGreater(len(stored["spoken_scenes"]),1)
        self.assertEqual(stored["scenes"],[])
        code,out=self.api("/api/pilot/sources/"+sid+"/transcript",method="POST",body={"segments":[{"start":0,"end":999,"text":"forged"}]})
        self.assertEqual(code,400)
        code,out=self.api("/api/pilot/sources/"+sid+"/transcript",method="POST",body={"segments":transcript},origin="https://evil.example")
        self.assertEqual(code,403)

    def test_cleanup_is_explicit_and_scoped_to_test_files(self):
        sid="c"*32
        with pilot.session() as db:
            db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",(
                sid,"test.mp4","video/mp4",4500,"done",None,
                time.time(),time.time()))
        uploaded=pilot.BASE/"files"/(sid+".mp4")
        uploaded.write_bytes(b"x"*4500)
        sibling=pilot.BASE/"files"/"NEVER_DELETE_ME.txt"
        sibling.write_text("outside registry")
        status,_=self.api("/api/pilot/reset",method="POST",body={"confirmation":"yes"})
        self.assertEqual(status,400)
        self.assertTrue(uploaded.exists())
        status,result=self.api("/api/pilot/reset",method="POST",
                               body={"confirmation":"DELETE LOCAL TESTS"})
        self.assertEqual(status,200)
        self.assertEqual(result["deleted_sources"],1)
        self.assertFalse(uploaded.exists())
        self.assertTrue(sibling.exists())
    def test_upload_storage_budget_fail_closed(self):
        from unittest.mock import patch
        with patch.object(pilot,"MAX_TOTAL_STORAGE",100):
            status,result=self.api("/api/pilot/uploads",method="POST",
                body={"x":"a"*3000},content_type="video/mp4")
        self.assertEqual(status,507)
        self.assertEqual(result["code"],"local_storage_limit")
if __name__=="__main__":unittest.main()

class MarketingPrivacyResetTests(LocalPilotTests):
 def test_reset_removes_registered_website_photos_and_campaign_packs_not_unrelated_files(self):
  import business_marketing_drafts as drafts
  from tests.test_business_marketing_drafts import document
  from business_website_media import import_photo
  from PIL import Image
  from io import BytesIO
  did='d'*32;url='https://example.org/roof-photo.jpg';kit='e'*32
  with pilot.session() as con:
   doc=document();doc['websiteImages']=[{'url':url,'alt':'Image found on site'}]
   drafts.save_draft(con,{'id':did,'mutationId':'b'*32,'expectedRevision':0,'document':doc})
   raw=BytesIO();Image.new('RGB',(800,600),'#72949a').save(raw,'JPEG')
   photo=import_photo(con,did,url,pilot.BASE,owner_confirmed=True,fetch=lambda *a:(raw.getvalue(),'image/jpeg'),
    resolve=lambda *a,**k:[(None,None,None,None,('93.184.215.14',443))])
   con.execute("INSERT INTO marketing_pack_jobs VALUES(?,?,?,?,?,?,?,?)",
    (kit,did,1,'f'*64,'done',None,time.time(),time.time()))
  photo_path=pilot.BASE/'website_photos'/did/(photo['id']+'.jpg')
  pack_folder=pilot.BASE/'marketing_packs'/kit;pack_folder.mkdir(parents=True)
  pack=(pack_folder/'campaign-kit.zip');pack.write_bytes(b'demo local pack')
  sibling=pack_folder/'KEEP_UNREGISTERED.txt';sibling.write_text('do not delete unrelated files')
  code,body=self.api('/api/pilot/reset',method='POST',body={'confirmation':'DELETE LOCAL TESTS'})
  self.assertEqual(code,200,body)
  self.assertFalse(photo_path.exists());self.assertFalse(pack.exists());self.assertTrue(sibling.exists())
  with pilot.session() as con:
   self.assertEqual(con.execute('SELECT COUNT(*) FROM marketing_website_media').fetchone()[0],0)
   self.assertEqual(con.execute('SELECT COUNT(*) FROM marketing_pack_jobs').fetchone()[0],0)
 def test_reset_also_preserves_paid_runway_video_jobs(self):
  import business_runway_video as video
  import time
  with pilot.session() as con:
   video.initialise(con)
   con.execute("INSERT INTO runway_video_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
     'e'*32,'a'*32,1,'f'*64,'completed',None,'d'*64,'{}',25,25,'{}',None,time.time(),time.time()))
  code,answer=self.api('/api/pilot/reset',method='POST',body={'confirmation':'DELETE LOCAL TESTS'})
  self.assertEqual(code,409,answer)
  self.assertEqual(answer['code'],'generation_audit_preserved')
 def test_reset_refuses_if_a_paid_runway_job_exists(self):
  with pilot.session() as con:
   con.execute("INSERT INTO runway_image_jobs(id,draft_id,creative_id,fingerprint,status,request_json,reserved_credits,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
    ('f'*32,'a'*32,'creative-1','a'*64,'completed','{}',20,time.time(),time.time()))
  code,body=self.api('/api/pilot/reset',method='POST',body={'confirmation':'DELETE LOCAL TESTS'})
  self.assertEqual(code,409,body)
  self.assertEqual(body.get('code'),'generation_audit_preserved')

class UnknownCinematicResetTests(LocalPilotTests):
 def test_pending_cinematic_submission_must_survive_reset(self):
  import business_cinematic_video as cinema
  with pilot.session() as con:
   cinema.initialise(con)
   con.execute('''INSERT INTO runway_cinematic_shots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
    'f'*32,'a'*32,1,'concierge_arrival','f'*64,'submission_unknown',None,
    '{}',96,None,None,'provider_connection_error',time.time(),time.time()))
  status,result=self.api('/api/pilot/reset',method='POST',body={'confirmation':'DELETE LOCAL TESTS'})
  self.assertEqual(status,409,result)
  self.assertEqual(result['code'],'generation_audit_preserved')
