"""Real FFmpeg montage worker, mocked R2, no live credits or user data."""
import io,os,shutil,subprocess,tempfile,types,unittest,sys
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from unittest.mock import patch
with patch.dict(sys.modules,{"flask":types.SimpleNamespace(request=None,jsonify=lambda x:x)}):
    import business_montage_routes as ROUTES
_worker=ROUTES._worker
from business_montage_ledger import claim,lookup

ORG="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER="test-owner"
SOURCE="b"*32
KEY=f"business/sources/{ORG}/{SOURCE}.mp4"
BRAND={"name":"Example Business","primary_color":"#141414",
       "secondary_color":"#FFFFFF","font_style":"modern","default_cta":"Contact us"}
class Storage:
    def __init__(self,p):self.objects={KEY:Path(p).read_bytes()};self.uploads=0
    def head_object(self,Bucket,Key):
        return {"ContentLength":len(self.objects[Key])}
    def download_file(self,bucket,key,path):
        Path(path).write_bytes(self.objects[key])
class WorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):raise unittest.SkipTest("FFmpeg not installed")
        cls.temp=tempfile.TemporaryDirectory(prefix="biz-montage-worker-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.video=Path(cls.temp.name)/"raw.mp4"
        subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                        "-f","lavfi","-i","testsrc2=size=320x568:rate=12:duration=14",
                        "-c:v","libx264","-preset","ultrafast",str(cls.video)],
                       timeout=40,check=True,capture_output=True)
    def setUp(self):
        self.db=str(Path(self.temp.name)/("ledger-"+os.urandom(4).hex()+".db"))
        self.env=patch.dict(os.environ,{"CLIPPR_BUSINESS_MONTAGE_DB":self.db})
        self.env.start();self.addCleanup(self.env.stop)
        self.r2=Storage(self.video)
        def upload(p,key,filename):
            self.r2.objects[key]=Path(p).read_bytes()
            self.r2.uploads+=1
            return key
        self.deps=types.SimpleNamespace(get_r2=lambda:self.r2,
            r2_bucket="test",upload_to_r2=upload)
        self.segments=[
            {"source_id":SOURCE,"key":KEY,"start_s":0,"end_s":6},
            {"source_id":SOURCE,"key":KEY,"start_s":7,"end_s":13}]
    def test_complete_real_montage_has_private_owner_scoped_key(self):
        job=claim(OWNER,ORG,"brand",self.segments,path=self.db)
        _worker(self.deps,OWNER,job["id"],self.segments,BRAND,"brand",ORG)
        row=lookup(OWNER,job["id"],path=self.db)
        self.assertEqual(row["status"],"done")
        self.assertEqual(row["output_key"],f"business/montages/{OWNER}/{job['id']}.mp4")
        self.assertGreater(len(self.r2.objects[row["output_key"]]),1500)
        self.assertEqual(self.r2.uploads,1)
        self.assertIsNone(lookup("attacker",job["id"],path=self.db))
    def test_slow_source_download_is_heartbeated_and_phase_visible(self):
        import time
        routes=ROUTES
        real=routes.heartbeat
        observed=[]
        def tracking(owner,jid,phase,**kw):
            observed.append(phase)
            return real(owner,jid,phase,**kw)
        original=self.r2.download_file
        def slow(bucket,key,path):
            time.sleep(.08)
            return original(bucket,key,path)
        self.r2.download_file=slow
        job=claim(OWNER,ORG,"brand",self.segments,path=self.db)
        with patch.object(routes,"HEARTBEAT_SECONDS",.01),patch.object(routes,"heartbeat",side_effect=tracking):
            _worker(self.deps,OWNER,job["id"],self.segments,BRAND,"brand",ORG)
        self.assertEqual(lookup(OWNER,job["id"],path=self.db)["status"],"done")
        self.assertIn("downloading",observed)
        self.assertIn("rendering",observed)
        self.assertIn("uploading",observed)
        self.assertGreaterEqual(len(observed),4)
        self.assertEqual(self.r2.uploads,1)

    def test_interrupted_prior_to_start_never_downloads_or_uploads(self):
        from business_montage_ledger import update
        job=claim(OWNER,ORG,"brand",self.segments,path=self.db)
        self.assertTrue(update(OWNER,job["id"],"interrupted",path=self.db))
        self.r2.download_file=lambda *_:self.fail("stale job must not download")
        _worker(self.deps,OWNER,job["id"],self.segments,BRAND,"brand",ORG)
        self.assertEqual(lookup(OWNER,job["id"],path=self.db)["status"],"interrupted")
        self.assertEqual(self.r2.uploads,0)

    def test_inactive_job_cannot_upload_after_loss_of_lease(self):
        routes=ROUTES
        job=claim(OWNER,ORG,"brand",self.segments,path=self.db)
        original=routes.heartbeat
        called=[0]
        def lost_at_render(owner,jid,phase,**kw):
            called[0]+=1
            if phase=="rendering":
                from business_montage_ledger import update
                update(owner,jid,"interrupted",path=self.db)
                return False
            return original(owner,jid,phase,**kw)
        with patch.object(routes,"heartbeat",side_effect=lost_at_render):
            _worker(self.deps,OWNER,job["id"],self.segments,BRAND,"brand",ORG)
        self.assertEqual(lookup(OWNER,job["id"],path=self.db)["status"],"interrupted")
        self.assertEqual(self.r2.uploads,0)
        self.assertGreater(called[0],0)

    def test_partial_source_download_fails_safely(self):
        job=claim(OWNER,ORG,"brand",self.segments,path=self.db)
        def corrupted(bucket,key,path):
            Path(path).write_bytes(b"truncated")
        self.r2.download_file=corrupted
        _worker(self.deps,OWNER,job["id"],self.segments,BRAND,"brand",ORG)
        self.assertEqual(lookup(OWNER,job["id"],path=self.db)["status"],"error")
        self.assertEqual(self.r2.uploads,0)
if __name__=="__main__":unittest.main()
