"""Real staging Auth/PostgREST RLS two-session canary.

Read-only preflight is the default. Live writes require --run-writes and a
staging-only project allowlist. QA credentials stay in a private local file
and are never printed, committed or copied to the live creator backend.

Real use: python tests/business_staging_auth_live.py
Run writes after test accounts exist:
  python tests/business_staging_auth_live.py --run-writes
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import uuid
from pathlib import Path
import requests

STAGING="zbncuxizmjinexifcshe"
LIVE="uxfvagyhnstwncbclgaf"
URL="https://"+STAGING+".supabase.co"
DEFAULT_ENV="/tmp/clippr-business-staging-20261017.env"
DEFAULT_USERS="/tmp/clippr-staging-qa-users-20261017.json"

def config(path):
    lines=Path(path).read_text().splitlines()
    return dict(line.split("=",1) for line in lines if "=" in line and not line.startswith("#"))

def check_target(base):
    if base.rstrip("/")!=URL or LIVE in base:
        raise ValueError("Refusing any non-staging Supabase URL")

def response_json(response):
    try:return response.json()
    except ValueError:raise RuntimeError("Unexpected Supabase response type") from None

def req(method,base,path,key,token=None,*,body=None,params=None,prefer=None):
    headers={"apikey":key,"Accept":"application/json"}
    if token:headers["Authorization"]="Bearer "+token
    if body is not None:headers["Content-Type"]="application/json"
    if prefer:headers["Prefer"]=prefer
    return requests.request(method,base+path,headers=headers,json=body,params=params,timeout=12)

def login(base,key,email,password):
    result=req("POST",base,"/auth/v1/token?grant_type=password",key,
               body={"email":email,"password":password})
    if result.status_code!=200:
        # Never disclose the account, password, JWT or provider response body.
        raise RuntimeError("Staging Auth login rejected QA credentials (HTTP "+str(result.status_code)+")")
    payload=response_json(result)
    if not payload.get("access_token") or not payload.get("user",{}).get("id"):
        raise RuntimeError("Staging Auth did not return a valid session")
    identity=req("GET",base,"/auth/v1/user",key,token=payload["access_token"])
    if identity.status_code!=200 or response_json(identity).get("id")!=payload["user"]["id"]:
        raise RuntimeError("Auth access token failed server-side identity confirmation")
    return {"id":payload["user"]["id"],"token":payload["access_token"]}

def api(method,base,key,user,table,*,payload=None,params=None):
    out=req(method,base,"/rest/v1/"+table,key,token=user["token"],
            body=payload,params=params,prefer="return=representation")
    if out.status_code>=400:
        raise RuntimeError("Staging "+table+" rejected request: HTTP "+str(out.status_code))
    return response_json(out) if out.content else []

def write_canary(base,key,users):
    if users[0]["id"]==users[1]["id"]:
        raise RuntimeError("Two genuinely distinct staging sessions required")
    orgs=[str(uuid.uuid4()) for _ in users]
    brands=[str(uuid.uuid4()) for _ in users]
    drafts=[str(uuid.uuid4()) for _ in users]
    created=[set(),set()]
    try:
        for i,u in enumerate(users):
            # Mark cleanup responsibility BEFORE submitting a POST: a lost
            # acknowledgement may mean the server already committed the row.
            created[i].add("org")
            api("POST",base,key,u,"business_organisations",payload={
                "id":orgs[i],"owner_id":u["id"],"name":"QA Temporary Business",
                "industry":"hospitality","primary_goal":"awareness"})
            created[i].add("brand")
            api("POST",base,key,u,"business_brand_kits",payload={
                "id":brands[i],"organisation_id":orgs[i],
                "name":"QA temporary brand","primary_color":"#121212",
                "secondary_color":"#FFFFFF"})
            created[i].add("draft")
            api("POST",base,key,u,"business_campaign_drafts",payload={
                "id":drafts[i],"owner_id":u["id"],"organisation_id":orgs[i],
                "brand_id":brands[i],"name":"QA synthetic content",
                "goal":"awareness","scenes":[],"notes":"QA only"})
        for i,u in enumerate(users):
            j=1-i
            for table,record in (("business_organisations",orgs[j]),
                                 ("business_brand_kits",brands[j]),
                                 ("business_campaign_drafts",drafts[j])):
                seen=api("GET",base,key,u,table,params={"id":"eq."+record,"select":"id"})
                if seen:
                    raise RuntimeError("CROSS TENANT DATA LEAK: "+table)
            seen=api("GET",base,key,u,"business_organisations",
                     params={"id":"eq."+orgs[i],"select":"id"})
            if len(seen)!=1:raise RuntimeError("QA session cannot see own organisation")
            deleted=api("DELETE",base,key,u,"business_campaign_drafts",
                        params={"id":"eq."+drafts[j],"select":"id"})
            if deleted:raise RuntimeError("CROSS TENANT DELETE: draft")
            mutated=api("PATCH",base,key,u,"business_brand_kits",
                        payload={"name":"QA attempted cross-tenant mutation"},
                        params={"id":"eq."+brands[j],"select":"id"})
            if mutated:raise RuntimeError("CROSS TENANT UPDATE: brand")
        print("STAGING_TWO_REAL_JWT_SESSIONS=PASS")
        print("STAGING_ORG_BRAND_DRAFT_RLS=PASS")
    finally:
        for i,u in enumerate(users):
            for table,item,label in (
                ("business_campaign_drafts",drafts[i],"draft"),
                ("business_brand_kits",brands[i],"brand"),
                ("business_organisations",orgs[i],"org")):
                if label not in created[i]:continue
                try:
                    before=api("GET",base,key,u,table,params={"id":"eq."+item,"select":"id"})
                    if before:
                        out=api("DELETE",base,key,u,table,params={"id":"eq."+item,"select":"id"})
                        if not isinstance(out,list) or len(out)!=1 or out[0].get("id")!=item:
                            raise RuntimeError("QA deletion could not be verified")
                    after=api("GET",base,key,u,table,params={"id":"eq."+item,"select":"id"})
                    if after:
                        raise RuntimeError("QA record still exists after deletion")
                    print("STAGING_QA_CLEANUP_"+label.upper()+"_USER"+str(i+1)+"=PASS")
                except Exception:
                    print("STAGING_QA_CLEANUP_"+label.upper()+"_USER"+str(i+1)+"=FAILED")
                    raise

def validate_qa_accounts(accounts, *, expected_domain="gmail.com"):
    """Reject stale/ambiguous local fixtures before any Auth requests."""
    if not isinstance(accounts,list) or len(accounts)!=2:
        raise RuntimeError("Two QA account credentials are required")
    emails=set()
    ids=set()
    for record in accounts:
        if not isinstance(record,dict):
            raise RuntimeError("Invalid staging QA fixture")
        email=record.get("email")
        if not isinstance(email,str) or not email.strip() or "@" not in email:
            raise RuntimeError("Staging QA email missing")
        if not isinstance(record.get("password"),str) or not record["password"]:
            raise RuntimeError("Staging QA password missing")
        identity=record.get("id")
        if identity:
            try:identity=str(uuid.UUID(identity))
            except (ValueError,AttributeError,TypeError):
                raise RuntimeError("Staging QA identity is invalid") from None
            if identity in ids:raise RuntimeError("Two distinct staging QA identities required")
            ids.add(identity)
        address=email.strip().lower()
        if address in emails:raise RuntimeError("Two distinct staging QA emails required")
        emails.add(address)
    return True

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--env-file",default=DEFAULT_ENV)
    parser.add_argument("--users-file",default=DEFAULT_USERS)
    parser.add_argument("--run-writes",action="store_true")
    args=parser.parse_args()
    env=config(args.env_file)
    base=env.get("VITE_SUPABASE_URL","")
    check_target(base)
    key=env.get("VITE_SUPABASE_ANON_KEY")
    if not key:raise RuntimeError("Staging publishable key missing")
    print("STAGING_PROJECT_ISOLATION=PASS")
    ping=req("GET",base,"/auth/v1/health",key)
    if ping.status_code!=200:
        raise RuntimeError("Staging Auth health endpoint returned HTTP "+str(ping.status_code))
    print("STAGING_AUTH_SERVICE=PASS")
    accounts=json.loads(Path(args.users_file).read_text())
    validate_qa_accounts(accounts)
    people=[]
    for idx,record in enumerate(accounts):
        if not record.get("email") or not record.get("password"):
            raise RuntimeError("Missing QA account credentials")
        person=login(base,key,record["email"],record["password"])
        if record.get("id") and record["id"]!=person["id"]:
            raise RuntimeError("Staging QA identity changed unexpectedly")
        people.append(person)
        print("STAGING_LOGIN_USER"+str(idx+1)+"=PASS")
    if not args.run_writes:
        print("STAGING_CREDENTIALS_VERIFIED=PASS; no database writes performed")
        return
    if env.get("CLIPPR_BUSINESS_STAGING_AUTH_WRITE_TEST")!="1":
        raise RuntimeError("Explicit staging-only Auth write-test flag required")
    write_canary(base,key,people)

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("STAGING_AUTH_CANARY_BLOCKED: "+str(exc),file=sys.stderr)
        sys.exit(2)
