"""Fail-closed Business Auth/PostgREST project origin configuration.

Business routes forward the caller JWT to RLS-protected PostgREST.
A user token validated against the creator Supabase project cannot be treated
as if it was issued by an independent staging Supabase project.
"""
from urllib.parse import urlsplit
import base64
import json


def business_public_anon_key(key):
    """Configuration guard, not token verification. Never accept a service key."""
    if not isinstance(key, str):
        return False
    if key.startswith('sb_publishable_'):
        return len(key) > len('sb_publishable_')
    try:
        parts = key.split('.')
        if len(parts) != 3:
            return False
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
        return isinstance(payload, dict) and payload.get('role') == 'anon'
    except (ValueError, TypeError, UnicodeError):
        return False

def _origin(url):
    if not isinstance(url,str):
        return None
    parsed=urlsplit(url.strip())
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    try:
        port=parsed.port
    except ValueError:
        return None
    if port not in (None,443) or parsed.path not in ("","/"):
        return None
    if parsed.query or parsed.fragment:
        return None
    return parsed.hostname.lower()

def business_auth_projects_match(data_url,auth_url,anon_key):
    """Require same Supabase issuer and REST project; no live/staging JWT mix."""
    if not anon_key or not isinstance(anon_key,str):
        return False
    source=_origin(data_url)
    authority=_origin(auth_url)
    if not source or not authority or source!=authority:
        return False
    # Future custom domains need explicit security review, not guessed trust.
    return source.endswith(".supabase.co") and len(source.split("."))==3
