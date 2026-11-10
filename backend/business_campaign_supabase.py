"""RLS-backed Supabase persistence for Business drafts.

Authenticated caller JWT forwarded to PostgREST, never the service role.
Writes are compare-and-set by revision to prevent concurrent lost updates.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
import requests
from business_campaign_store import _scenes, StoreError

UUID=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",re.I)
GOALS={"awareness","enquiries","bookings","education","offers"}

class CampaignStorageUnavailable(RuntimeError):pass
class CampaignForbidden(PermissionError):pass
class DuplicateCampaign(StoreError):pass

def validate_payload(name,goal,brand,scenes,notes):
    if not isinstance(name,str) or not 2<=len(name.strip())<=100:
        raise StoreError("Campaign name must be 2-100 characters.")
    if goal not in GOALS:raise StoreError("Invalid campaign objective.")
    if brand is not None and (not isinstance(brand,str) or not UUID.fullmatch(brand)):
        raise StoreError("Invalid Brand Kit.")
    if not isinstance(notes,str) or len(notes)>1500:raise StoreError("Campaign notes too long.")
    return {"name":name.strip(),"goal":goal,"brand_id":brand,
            "scenes":_scenes(scenes),"notes":notes}

class CampaignSupabase:
    def __init__(self,base,key,bearer,*,http=requests,timeout=9):
        if not isinstance(base,str) or not base.startswith("https://") or not key or not bearer:
            raise CampaignStorageUnavailable("Staging campaign storage is not configured")
        self.url=base.rstrip("/")+"/rest/v1/business_campaign_drafts"
        self.headers={"apikey":key,"Authorization":"Bearer "+bearer,
                      "Accept":"application/json"}
        self.http=http
        self.timeout=timeout

    def _request(self,method,*,params=None,payload=None,prefer=None):
        headers=dict(self.headers)
        if payload is not None:headers["Content-Type"]="application/json"
        if prefer:headers["Prefer"]=prefer
        try:
            result=self.http.request(method,self.url,params=params,json=payload,
                                     headers=headers,timeout=self.timeout)
        except requests.RequestException as exc:
            raise CampaignStorageUnavailable("Campaign storage temporarily unavailable") from exc
        if result.status_code in (401,403):raise CampaignForbidden("Cannot access this campaign")
        if result.status_code>=400:
            if result.status_code==409:
                try:code=result.json().get("code")
                except (ValueError,AttributeError,TypeError):code=None
                if code=="23505":
                    raise DuplicateCampaign("A campaign with this save identifier already exists.")
            if result.status_code in (400,409,422):
                raise StoreError("Campaign data was rejected. Refresh and try again.")
            raise CampaignStorageUnavailable("Campaign storage temporarily unavailable")
        try:return result.json() if result.content else []
        except (ValueError,TypeError) as exc:
            raise CampaignStorageUnavailable("Campaign storage returned invalid data") from exc

    def list(self,owner,org):
        rows=self._request("GET",params={
            "owner_id":"eq."+owner,"organisation_id":"eq."+org,
            "select":"id,name,goal,brand_id,revision,updated_at",
            "order":"updated_at.desc","limit":"100"})
        if not isinstance(rows,list):
            raise CampaignStorageUnavailable("Campaign list response was invalid")
        return rows

    def get(self,owner,id):
        if not UUID.fullmatch(str(id or "")):return None
        items=self._request("GET",params={
            "id":"eq."+id,"owner_id":"eq."+owner,
            "select":"id,organisation_id,name,goal,brand_id,scenes,notes,revision,created_at,updated_at",
            "limit":"1"})
        if not isinstance(items,list):
            raise CampaignStorageUnavailable("Campaign record response was invalid")
        return items[0] if items else None

    def save(self,owner,org,name,goal,brand,scenes,notes="",*,id=None,revision=None,create_id=None):
        data=validate_payload(name,goal,brand,scenes,notes)
        if not UUID.fullmatch(str(org or "")) or not UUID.fullmatch(str(owner or "")):
            raise StoreError("Invalid account or business.")
        timestamp=datetime.now(timezone.utc).isoformat()
        if id is None:
            if not UUID.fullmatch(str(create_id or "")):
                raise StoreError("New campaign request identifier required.")
            payload={**data,"id":create_id,"owner_id":owner,"organisation_id":org}
            try:
                records=self._request("POST",payload=payload,prefer="return=representation")
            except DuplicateCampaign:
                # Uncertain previous HTTP response: unique PK prevents a second
                # draft. Recover only if every saved field matches this intent.
                existing=self.get(owner,create_id)
                if not existing or existing.get("organisation_id")!=org or any(
                    existing.get(field)!=data[field] for field in
                    ("name","goal","brand_id","scenes","notes")
                ):
                    raise StoreError("Save identifier already belongs to another campaign.")
                return {"id":existing["id"],"revision":existing["revision"],
                        "updated":existing["updated_at"],"replayed":True}
        else:
            if not UUID.fullmatch(str(id or "")):raise StoreError("Invalid campaign ID.")
            if type(revision) is not int or revision<1:
                raise StoreError("Campaign revision required.")
            records=self._request("PATCH",params={
                "id":"eq."+id,"owner_id":"eq."+owner,"organisation_id":"eq."+org,
                "revision":"eq."+str(revision),"select":"id,revision,updated_at"
            },payload={**data,"revision":revision+1,"updated_at":timestamp},
                prefer="return=representation")
            if not records:
                raise StoreError("Campaign changed or is no longer accessible. Refresh before saving.")
        if not isinstance(records,list) or len(records)!=1:
            raise CampaignStorageUnavailable("Campaign save could not be confirmed")
        r=records[0]
        if (not isinstance(r,dict) or not UUID.fullmatch(str(r.get("id") or ""))
                or type(r.get("revision")) is not int or not r.get("updated_at")):
            raise CampaignStorageUnavailable("Campaign save response was invalid")
        return {"id":r["id"],"revision":r["revision"],"updated":r["updated_at"]}

    def delete(self,owner,org,id):
        if not UUID.fullmatch(str(id or "")):return False
        rows=self._request("DELETE",params={
            "id":"eq."+id,"owner_id":"eq."+owner,"organisation_id":"eq."+org,
            "select":"id"
        },prefer="return=representation")
        if not isinstance(rows,list):
            raise CampaignStorageUnavailable("Campaign delete response was invalid")
        return len(rows)==1
