"""Offline same-host shared spend ledger for a trusted Clippr Business authority.

This is a foundation, NOT a production-connected provider spending gate. All
workers must use the ONE durable ledger path and server-issued account/period
identities; separate files or hosts are not coordinated. A reservation is a
conservative unresolved debit, never generation or publishing permission.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import re
import sqlite3
import time


class SharedLedgerError(ValueError):
    def __init__(self, message, code="shared_credit_invalid"):
        super().__init__(message)
        self.code = code


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise SharedLedgerError("A verifiable SHA-256 reference is required")
    return value


def _account(value):
    if not isinstance(value, str) or not re.fullmatch(r"acct_[0-9a-f]{16,64}", value):
        raise SharedLedgerError("Trusted server-account identity required")
    return value


def _period(value):
    if not isinstance(value, str) or not re.fullmatch(r"20[0-9]{2}-(0[1-9]|1[0-2])", value):
        raise SharedLedgerError("Trusted YYYY-MM budget period required")
    return value


def _name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{2,100}", value):
        raise SharedLedgerError("Invalid " + label)
    return value


def _amount(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 100000:
        raise SharedLedgerError("Non-negative bounded integer credits are required")
    return value


def _path(path):
    if (not isinstance(path, str) or not os.path.isabs(path)
            or not path.endswith(".sqlite3") or os.path.normpath(path) != path):
        raise SharedLedgerError("An explicit absolute shared SQLite file path is required", "shared_ledger_path_required")
    resolved = os.path.realpath(path)
    if not os.path.isdir(os.path.dirname(resolved)):
        raise SharedLedgerError("Shared ledger directory is absent", "shared_ledger_unavailable")
    return resolved


def _connect(path, *, create=False):
    name = _path(path)
    if not create and not os.path.isfile(name):
        raise SharedLedgerError("Shared budget authority is missing", "shared_authority_missing")
    try:
        connection = sqlite3.connect(name, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        if create:
            connection.execute("PRAGMA journal_mode=WAL")
        return connection
    except sqlite3.Error as exc:
        raise SharedLedgerError("Shared ledger unavailable", "shared_ledger_unavailable") from exc


@contextmanager
def _transaction(path, *, create=False, write=True):
    con = _connect(path, create=create)
    try:
        con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield con
        if write:
            con.commit()
        else:
            con.rollback()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def _budget_payload(account, period, limit, authority, history, reconciliation):
    return {
        "account_id": account, "period_id": period, "maximum_credits": limit,
        "authority_sha256": authority, "historical_credits": history,
        "reconciliation_sha256": reconciliation,
    }


def _budget(con, account, period):
    try:
        row = con.execute(
            "SELECT * FROM business_global_budgets WHERE account_id=? AND period_id=?",
            (account, period),
        ).fetchone()
    except sqlite3.Error as exc:
        raise SharedLedgerError("Shared budget authority unavailable", "shared_authority_missing") from exc
    if row is None:
        raise SharedLedgerError("Shared budget authority is missing", "shared_authority_missing")
    expected = _budget_payload(row["account_id"], row["period_id"], row["maximum_credits"],
                               row["authority_sha256"], row["historical_credits"],
                               row["reconciliation_sha256"])
    if _digest(expected) != row["fingerprint"]:
        raise SharedLedgerError("Shared authority record changed", "shared_ledger_integrity_error")
    return row


def open_budget(path, *, account_id, period_id, maximum_credits, authority_sha256,
                reconciled_legacy_credits, reconciliation_sha256):
    """Idempotently register an already-approved and legacy-reconciled budget.

    Caller must validate authority and derive account/period from a trusted
    source; accepting self-declared owner/account identity is unsafe.
    """
    account = _account(account_id)
    period = _period(period_id)
    limit = _amount(maximum_credits)
    history = _amount(reconciled_legacy_credits, zero=True)
    if history > limit:
        raise SharedLedgerError("Historical charges exceed authorised cap")
    authority = _sha(authority_sha256)
    reconciliation = _sha(reconciliation_sha256)
    payload = _budget_payload(account, period, limit, authority, history, reconciliation)
    fingerprint = _digest(payload)
    with _transaction(path, create=True) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS business_global_budgets (
          account_id TEXT NOT NULL, period_id TEXT NOT NULL, maximum_credits INTEGER NOT NULL,
          authority_sha256 TEXT NOT NULL, historical_credits INTEGER NOT NULL,
          reconciliation_sha256 TEXT NOT NULL, fingerprint TEXT NOT NULL,
          created_at REAL NOT NULL, PRIMARY KEY(account_id,period_id))""")
        con.execute("""CREATE TABLE IF NOT EXISTS business_global_reservations (
          account_id TEXT NOT NULL, period_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
          job_id TEXT NOT NULL, scene_fingerprint TEXT NOT NULL, request_sha256 TEXT NOT NULL,
          credits INTEGER NOT NULL, created_at REAL NOT NULL, fingerprint TEXT NOT NULL,
          PRIMARY KEY(account_id,period_id,scene_fingerprint),
          UNIQUE(account_id,period_id,job_id))""")
        old = con.execute("SELECT * FROM business_global_budgets WHERE account_id=? AND period_id=?",
                          (account, period)).fetchone()
        if old:
            if old["fingerprint"] != fingerprint or _budget(con, account, period)["fingerprint"] != fingerprint:
                raise SharedLedgerError("Budget cannot be reset, topped up or re-reconciled",
                                        "immutable_authority_conflict")
        else:
            con.execute("INSERT INTO business_global_budgets VALUES(?,?,?,?,?,?,?,?)",
                        (account, period, limit, authority, history, reconciliation,
                         fingerprint, time.time()))
    return {"accountId": account, "periodId": period, "maximumCredits": limit,
            "historicalCredits": history, "authorizesGeneration": False}


def _receipt_payload(row):
    return {key: row[key] for key in (
        "account_id", "period_id", "workspace_id", "job_id", "scene_fingerprint",
        "request_sha256", "credits", "created_at",
    )}


def _receipt(row):
    payload = _receipt_payload(row)
    if _digest(payload) != row["fingerprint"]:
        raise SharedLedgerError("Shared reservation record changed", "shared_ledger_integrity_error")
    return {"jobId": row["job_id"], "sceneFingerprint": row["scene_fingerprint"],
            "reservedCredits": row["credits"], "receiptSha256": row["fingerprint"],
            "reconciliationStatus": "unresolved", "authorizesGeneration": False,
            "approvesCreative": False}


def reserve(path, *, account_id, period_id, workspace_id, job_id,
            scene_fingerprint, request_sha256, credits):
    """Conservatively reserve once across same-host workers; never auto-refund.

    In actual integration this should happen BEFORE provider submission.
    If the local job transaction later fails, the global debit stays held for
    explicit reconciliation. No automatic provider retry is permitted.
    """
    account = _account(account_id)
    period = _period(period_id)
    workspace = _name(workspace_id, "workspace")
    job = _name(job_id, "job")
    scene = _sha(scene_fingerprint)
    request = _sha(request_sha256)
    amount = _amount(credits)
    with _transaction(path) as con:
        budget = _budget(con, account, period)
        try:
            previous = con.execute(
                """SELECT * FROM business_global_reservations
                   WHERE account_id=? AND period_id=?
                     AND (scene_fingerprint=? OR job_id=?)""",
                (account, period, scene, job),
            ).fetchall()
        except sqlite3.Error as exc:
            raise SharedLedgerError("Shared reservations unavailable", "shared_ledger_unavailable") from exc
        if previous:
            if (len(previous) == 1 and previous[0]["workspace_id"] == workspace
                    and previous[0]["job_id"] == job and previous[0]["scene_fingerprint"] == scene
                    and previous[0]["request_sha256"] == request
                    and previous[0]["credits"] == amount):
                return _receipt(previous[0])
            code = "reservation_identity_changed" if any(row["job_id"] == job for row in previous) else "duplicate_scene_attempt"
            raise SharedLedgerError("Existing shared reservation cannot be repurposed", code)
        used = con.execute(
            "SELECT COALESCE(SUM(credits),0) FROM business_global_reservations WHERE account_id=? AND period_id=?",
            (account, period),
        ).fetchone()[0]
        if used + budget["historical_credits"] + amount > budget["maximum_credits"]:
            raise SharedLedgerError("Shared budget would be exceeded", "shared_budget_exceeded")
        payload = {"account_id": account, "period_id": period, "workspace_id": workspace,
                   "job_id": job, "scene_fingerprint": scene, "request_sha256": request,
                   "credits": amount, "created_at": time.time()}
        fingerprint = _digest(payload)
        con.execute("INSERT INTO business_global_reservations VALUES(?,?,?,?,?,?,?,?,?)",
                    tuple(payload[key] for key in payload) + (fingerprint,))
        return {"jobId": job, "sceneFingerprint": scene, "reservedCredits": amount,
                "receiptSha256": fingerprint, "reconciliationStatus": "unresolved",
                "authorizesGeneration": False, "approvesCreative": False}


def snapshot(path, *, account_id, period_id):
    account = _account(account_id)
    period = _period(period_id)
    with _transaction(path, write=False) as con:
        budget = _budget(con, account, period)
        try:
            rows = con.execute(
                "SELECT * FROM business_global_reservations WHERE account_id=? AND period_id=?",
                (account, period),
            ).fetchall()
        except sqlite3.Error as exc:
            raise SharedLedgerError("Shared reservations unavailable", "shared_ledger_unavailable") from exc
        for row in rows:
            _receipt(row)
        used = sum(row["credits"] for row in rows)
        remaining = budget["maximum_credits"] - budget["historical_credits"] - used
        if remaining < 0:
            raise SharedLedgerError("Shared debits exceed authority", "shared_ledger_integrity_error")
        return {"accountId": account, "periodId": period,
                "maximumCredits": budget["maximum_credits"],
                "historicalCredits": budget["historical_credits"],
                "reservedCredits": used, "remainingCredits": remaining,
                "unresolvedReservations": len(rows), "authorizesGeneration": False,
                "approvesCreative": False}
