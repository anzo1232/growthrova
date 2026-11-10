"""Clippr Business private R2 staging probe.

Default: local validation only. --test-read performs staging bucket HEAD.
--test-write additionally performs a synthetic staged MP4 PUT, presigned GET,
ETag/content check and best-effort delete, guarded against live bucket access.

No production R2 bucket, API token, customer video or paid provider use.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import os
import sys
import tempfile
import uuid
from pathlib import Path

PREFIX="clippr-business-staging-"
OBJECT_ROOT="__clippr_business_staging_canary__/"

class StagingR2Blocked(RuntimeError):
    pass

def validate_target(bucket,production_bucket=None):
    if not isinstance(bucket,str) or not bucket.startswith(PREFIX):
        raise StagingR2Blocked("Only a dedicated Clippr Business staging bucket may be tested")
    if not bucket[len(PREFIX):] or ".." in bucket or "/" in bucket:
        raise StagingR2Blocked("Invalid staging bucket")
    if production_bucket and bucket==production_bucket:
        raise StagingR2Blocked("Staging bucket matches existing live bucket")
    return bucket

def cfg(path):
    data={}
    for line in Path(path).read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k,v=line.split("=",1);data[k]=v
    return data

def staging_client(env):
    for name in ("R2_ENDPOINT","R2_ACCESS_KEY_ID","R2_SECRET_ACCESS_KEY"):
        if not env.get(name):raise StagingR2Blocked("Missing dedicated R2 staging access settings")
    import boto3
    from botocore.config import Config
    return boto3.client("s3",endpoint_url=env["R2_ENDPOINT"],
        aws_access_key_id=env["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(connect_timeout=6,read_timeout=20,retries={"max_attempts":0}))

def check_bucket(client,bucket):
    client.head_bucket(Bucket=bucket)
    return True

def put_get_delete_canary(client,bucket,sample_bytes,*,prefix=OBJECT_ROOT):
    if not prefix==OBJECT_ROOT or not isinstance(sample_bytes,bytes):
        raise StagingR2Blocked("Only synthetic staging media is permitted")
    if not 2000<len(sample_bytes)<=2*1024*1024:
        raise StagingR2Blocked("Test clip must be between 2KB and 2MB")
    object_key=prefix+uuid.uuid4().hex+".mp4"
    sha=hashlib.sha256(sample_bytes).hexdigest()
    created=False
    try:
        created=True  # prepare cleanup even if response is lost after PUT
        client.put_object(Bucket=bucket,Key=object_key,Body=sample_bytes,
                          ContentType="video/mp4",Metadata={"test":"clippr-business-stage"})
        head=client.head_object(Bucket=bucket,Key=object_key)
        if int(head.get("ContentLength") or 0)!=len(sample_bytes) or not head.get("ETag"):
            raise StagingR2Blocked("Stored object has missing ETag or wrong size")
        url=client.generate_presigned_url("get_object",
             Params={"Bucket":bucket,"Key":object_key},ExpiresIn=90)
        # Use the signed GET to test the real download path.
        import requests
        response=requests.get(url,timeout=20)
        if response.status_code!=200 or hashlib.sha256(response.content).hexdigest()!=sha:
            raise StagingR2Blocked("Presigned download does not match uploaded media")
        return {"upload":"PASS","etag":"PASS","private_signed_get":"PASS"}
    finally:
        if created:
            # Only ever delete our unique synthetic canary object.
            client.delete_object(Bucket=bucket,Key=object_key)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--env-file",default="")
    parser.add_argument("--test-read",action="store_true")
    parser.add_argument("--test-write",action="store_true")
    args=parser.parse_args()
    env=cfg(args.env_file) if args.env_file else dict(os.environ)
    bucket=validate_target(env.get("CLIPPR_BUSINESS_STAGING_R2_BUCKET"),
                           env.get("R2_BUCKET"))
    print("R2_STAGING_BUCKET_ISOLATED=PASS")
    if not args.test_read and not args.test_write:
        print("DRY_RUN_ONLY=PASS")
        return
    client=staging_client(env)
    check_bucket(client,bucket)
    print("STAGING_R2_HEAD=PASS")
    if not args.test_write:return
    if env.get("CLIPPR_BUSINESS_STAGING_R2_WRITE_TEST")!="1":
        raise StagingR2Blocked("Explicit staging-only R2 write-test flag required")
    # Always use generated synthetic video; never pass user/customer media.
    import shutil,subprocess
    if not shutil.which("ffmpeg"):
        raise StagingR2Blocked("FFmpeg required for synthetic canary")
    with tempfile.TemporaryDirectory(prefix="business-r2-qa-") as folder:
        clip=Path(folder)/"synthetic.mp4"
        subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i",
            "testsrc2=size=192x108:rate=12:duration=3","-c:v","libx264",
            "-preset","ultrafast","-movflags","+faststart",str(clip)],
            check=True,capture_output=True,timeout=30)
        result=put_get_delete_canary(client,bucket,clip.read_bytes())
        for name,state in result.items():print("STAGING_R2_"+name.upper()+"="+state)

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("STAGING_R2_CANARY_BLOCKED: "+type(exc).__name__,file=sys.stderr)
        sys.exit(2)
