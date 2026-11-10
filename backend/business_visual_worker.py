"""Standalone Clippr Business visual scanner (staging first, OFF by default).

Operates only on already-confirmed user-owned R2 keys; never issues Stripe
events or uploads derivatives. Start with CLIPPR_BUSINESS_VISUAL_WORKER=1.
"""
from __future__ import annotations
import os
import shutil
import signal
import socket
import sqlite3
from pathlib import Path
from threading import Event
from business_visual_jobs import claim_next_visual,scan_job,_db,DEFAULT_DB
from business_sources import _db as sources_db,REGISTRY_PATH as SOURCES_DB

POLL_SECONDS=3

class WorkerUnavailable(RuntimeError):pass

class R2Storage:
    def __init__(self,env=None,client=None):
        env=os.environ if env is None else env
        self.r2_bucket=env.get("R2_BUCKET","")
        if not self.r2_bucket or "/" in self.r2_bucket:
            raise WorkerUnavailable("Configured R2 bucket is invalid")
        if client is None:
            for k in ("R2_ENDPOINT","R2_ACCESS_KEY_ID","R2_SECRET_ACCESS_KEY"):
                if not env.get(k):raise WorkerUnavailable("R2 worker credentials incomplete")
            import boto3
            from botocore.config import Config
            self.client=boto3.client(
                "s3",endpoint_url=env["R2_ENDPOINT"],
                aws_access_key_id=env["R2_ACCESS_KEY_ID"],
                aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
                region_name="auto",config=Config(connect_timeout=6,
                    read_timeout=90,retries={"max_attempts":0}))
        else:self.client=client
    def get_r2(self):return self.client

def readiness(storage,*,visual_path=None,source_path=None,min_free_mb=1500):
    for tool in ("ffmpeg","ffprobe"):
        if not shutil.which(tool):raise WorkerUnavailable(tool+" unavailable")
    visual_path=visual_path or os.environ.get("CLIPPR_BUSINESS_VISUAL_DB",DEFAULT_DB)
    source_path=source_path or os.environ.get("CLIPPR_BUSINESS_SOURCES_DB",SOURCES_DB)
    try:
        v=_db(visual_path);v.close()
        s=sources_db(source_path);s.close()
        free=shutil.disk_usage(Path(visual_path).parent).free
    except (OSError,sqlite3.Error) as exc:
        raise WorkerUnavailable("Visual job or source registry database unavailable") from exc
    if free<min_free_mb*1024*1024:
        raise WorkerUnavailable("Insufficient disk for visual-scanning download")
    try:storage.get_r2().head_bucket(Bucket=storage.r2_bucket)
    except Exception as exc:
        raise WorkerUnavailable("R2 bucket unavailable") from exc
    return True

def once(storage,worker_id,*,visual_path=None,source_path=None,now=None):
    """Claim one durable scan. No duplicate work after API restart."""
    path=visual_path or os.environ.get("CLIPPR_BUSINESS_VISUAL_DB",DEFAULT_DB)
    src=source_path or os.environ.get("CLIPPR_BUSINESS_SOURCES_DB",SOURCES_DB)
    item=claim_next_visual(worker_id,path=path,now=now)
    if item is None:return None
    scan_job(storage,item["job_id"],item["owner"],item["source_key"],
             path=path,lease_token=item["lease_token"],source_path=src)
    return item["job_id"]

def run_forever(*,stop=None,storage=None,worker_id=None):
    if os.environ.get("CLIPPR_BUSINESS_VISUAL_WORKER")!="1":
        raise WorkerUnavailable("Business visual worker flag is OFF")
    stop=stop or Event()
    storage=storage or R2Storage()
    readiness(storage)
    worker_id=worker_id or socket.gethostname()+":"+str(os.getpid())
    while not stop.is_set():
        try:
            if once(storage,worker_id) is None:stop.wait(POLL_SECONDS)
        except Exception as exc:
            print("[business-visual-worker] failure="+type(exc).__name__,flush=True)
            stop.wait(POLL_SECONDS)

def main():
    import sys
    if "--check-config" in sys.argv:
        readiness(R2Storage())
        print("BUSINESS_VISUAL_WORKER_READINESS=PASS",flush=True)
        return
    stop=Event()
    def shutdown(*_):stop.set()
    signal.signal(signal.SIGTERM,shutdown)
    signal.signal(signal.SIGINT,shutdown)
    run_forever(stop=stop)

if __name__=="__main__":main()
