"""Independent durable Clippr Business montage worker (staging-first).

Run: CLIPPR_BUSINESS_MONTAGE_WORKER=1 python business_montage_worker.py

Never imports the creator server, never handles HTTP, and never repeats failed
render jobs. Source credentials are read ONLY in this separate worker process.
"""
from __future__ import annotations
import os
import importlib
import sqlite3
import shutil
import signal
import socket
import time
from pathlib import Path
from threading import Event

from business_montage_ledger import claim_next,_db,DB_PATH
from business_montage_routes import _worker
from business_brand_render import FONT_REL

SLEEP_SECONDS=3

class WorkerConfigurationError(RuntimeError):pass

class Storage:
    def __init__(self,env=None,client=None):
        env=os.environ if env is None else env
        self.r2_bucket=env.get("R2_BUCKET","clippr")
        if client is None:
            required=("R2_ENDPOINT","R2_ACCESS_KEY_ID","R2_SECRET_ACCESS_KEY")
            if any(not env.get(k) for k in required):
                raise WorkerConfigurationError("R2 worker credentials not configured")
            import boto3
            from botocore.config import Config
            self.client=boto3.client(
                "s3",endpoint_url=env["R2_ENDPOINT"],
                aws_access_key_id=env["R2_ACCESS_KEY_ID"],
                aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
                region_name="auto",
                config=Config(connect_timeout=6,read_timeout=90,
                              retries={"max_attempts":0}),
            )
        else:
            self.client=client
        if not self.r2_bucket or "/" in self.r2_bucket:
            raise WorkerConfigurationError("Invalid R2 bucket")

    def get_r2(self):return self.client

    def upload_to_r2(self,source,key,filename=None):
        if (not isinstance(key,str) or not key.startswith("business/montages/")
                or not key.endswith(".mp4") or key.count("/")!=3):
            raise ValueError("Only scoped Business montage outputs may be uploaded")
        file=Path(source)
        if not file.is_file() or file.stat().st_size<1500:
            raise ValueError("Montage output missing")
        self.client.upload_file(str(file),self.r2_bucket,key,
                ExtraArgs={"ContentType":"video/mp4",
                           "ContentDisposition":'attachment; filename="clippr-business-montage.mp4"'})
        # Unknown upload response or verification outage MUST NOT silently mark
        # an unverified object as delivered to the customer.
        head=self.client.head_object(Bucket=self.r2_bucket,Key=key)
        if int(head.get("ContentLength") or 0)!=file.stat().st_size:
            raise ValueError("Uploaded montage size mismatch")
        return key

def once(deps,worker_id,*,path=None,now=None):
    """One bounded claim. None means no queued work. Exactly-once admission."""
    item=claim_next(worker_id,path=path,now=now)
    if item is None:return None
    body=item["payload"]
    # No user/request JWT in the worker: the API already verified every
    # source and the approved draft before persisting these immutable inputs.
    _worker(deps,item["owner"],item["id"],body["scenes"],body["brand"],
            body["brand_id"],item["organisation"],lease_token=item["lease_token"])
    return item["id"]

def check_worker_readiness(storage, *, ledger_path=None, min_free_mb=2500):
    """Read-only R2 access and local execution readiness; never touches user media."""
    for binary in ("ffmpeg","ffprobe"):
        if not shutil.which(binary):
            raise WorkerConfigurationError(binary+" is not installed")
    try:
        pillow=importlib.import_module("PIL.Image")
        font=importlib.import_module("PIL.ImageFont")
        if not callable(getattr(pillow,"new",None)) or not callable(getattr(font,"truetype",None)):
            raise ImportError("Incomplete Pillow installation")
    except (ImportError,AttributeError) as exc:
        raise WorkerConfigurationError("Pillow image renderer is unavailable") from exc
    if not FONT_REL.is_file():
        raise WorkerConfigurationError("Brand rendering font is unavailable")
    db_path=Path(ledger_path or os.environ.get("CLIPPR_BUSINESS_MONTAGE_DB",DB_PATH))
    try:
        db=_db(str(db_path))
        db.close()
        free=shutil.disk_usage(db_path.parent).free
    except (OSError,ValueError,sqlite3.Error) as exc:
        raise WorkerConfigurationError("Worker ledger or disk unavailable") from exc
    if free < max(0,min_free_mb)*1024*1024:
        raise WorkerConfigurationError("Insufficient free disk for bounded source downloads")
    try:
        storage.get_r2().head_bucket(Bucket=storage.r2_bucket)
    except Exception as exc:
        raise WorkerConfigurationError("R2 bucket cannot be verified") from exc
    return {"ready":True,"ledger_write":True,
            "r2_head":True,"ffmpeg":True,"ffprobe":True}


def run_forever(*,stop=None,storage=None,worker_id=None):
    if os.environ.get("CLIPPR_BUSINESS_MONTAGE_WORKER")!="1":
        raise WorkerConfigurationError("Montage worker feature flag is OFF")
    stop=stop or Event()
    deps=storage or Storage()
    check_worker_readiness(deps)
    worker_id=worker_id or (socket.gethostname()+":"+str(os.getpid()))
    while not stop.is_set():
        try:
            result=once(deps,worker_id)
        except Exception as error:
            print("[business-montage-worker] loop error="+type(error).__name__,flush=True)
            stop.wait(SLEEP_SECONDS)
            continue
        if result is None:
            stop.wait(SLEEP_SECONDS)

def main():
    import sys
    if "--check-config" in sys.argv:
        # Dry readiness command. Never starts the worker or processes a job.
        ready=check_worker_readiness(Storage())
        print("BUSINESS_MONTAGE_WORKER_READINESS="+("OK" if ready["ready"] else "FAIL"),
              flush=True)
        return
    stop=Event()
    def shut_down(*_):stop.set()
    signal.signal(signal.SIGTERM,shut_down)
    signal.signal(signal.SIGINT,shut_down)
    run_forever(stop=stop)

if __name__=="__main__":
    main()
