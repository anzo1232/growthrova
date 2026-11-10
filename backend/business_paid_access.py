"""Fail-closed Business paid entitlement against existing Stripe/Whop state.

No admin bypass, trial bypass or one-free-clip fallback. A Business montage
requires a verified paid plan whose subscription coverage ends in the future.
"""
from __future__ import annotations
from datetime import datetime,timezone

PAID_TIERS=frozenset(("starter","pro","studio"))
VALID_PROVIDERS=frozenset(("stripe","whop"))

def parse_period(value):
    if isinstance(value,datetime):
        dt=value
    elif isinstance(value,str) and value.strip():
        try:dt=datetime.fromisoformat(value.strip().replace("Z","+00:00"))
        except ValueError:return None
    else:return None
    if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def has_current_paid_access(row,*,now=None):
    if not row:return False
    try:
        status=(row["status"] or "").strip().lower()
        tier=(row["tier"] or "").strip().lower()
        provider=(row["provider"] or "").strip().lower()
        current_end=row["current_period_end"]
    except (KeyError,TypeError,AttributeError):return False
    if status!="active" or tier not in PAID_TIERS or provider not in VALID_PROVIDERS:
        return False
    try:
        reference=(row["subscription_id"] if provider=="stripe"
                   else row["whop_membership_id"])
    except (KeyError,TypeError,AttributeError):
        return False
    if not isinstance(reference,str) or not reference.strip():return False
    expiry=parse_period(current_end)
    if expiry is None:return False
    if now is None:now=datetime.now(timezone.utc)
    elif now.tzinfo is None:now=now.replace(tzinfo=timezone.utc)
    return expiry>now.astimezone(timezone.utc)
