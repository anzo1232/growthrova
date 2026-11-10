"""Offline, synthetic, cross-workspace shared-credit accounting regression cases.

These tests do not authorise generation, contact providers or use customer data.
"""
import concurrent.futures
from contextlib import closing
import importlib
import importlib.util
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

ACCOUNT = "acct_0123456789abcdef"
PERIOD = "2026-10"
AUTHORITY = "a" * 64
REQUEST = "b" * 64
SCENE = "c" * 64


class SharedCreditLedgerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("business_shared_credit_ledger"))
        self.api = importlib.import_module("business_shared_credit_ledger")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "single-shared-authority.sqlite3")

    def open(self, *, limit=10, history=0, account=ACCOUNT, period=PERIOD, authority=AUTHORITY):
        return self.api.open_budget(
            self.path, account_id=account, period_id=period,
            maximum_credits=limit, authority_sha256=authority,
            reconciled_legacy_credits=history, reconciliation_sha256="d" * 64,
        )

    def reserve(self, *, workspace="workspace-A", job="job-one", scene=SCENE,
                request=REQUEST, credits=4, account=ACCOUNT, period=PERIOD):
        return self.api.reserve(
            self.path, account_id=account, period_id=period,
            workspace_id=workspace, job_id=job, scene_fingerprint=scene,
            request_sha256=request, credits=credits,
        )

    def test_two_workspaces_share_one_cap_with_historical_usage(self):
        self.open(limit=10, history=3)
        a = self.reserve(credits=4)
        b = self.reserve(workspace="workspace-B", job="job-two", scene="e" * 64, credits=3)
        self.assertEqual(a["reservedCredits"], 4)
        self.assertEqual(b["reservedCredits"], 3)
        snapshot = self.api.snapshot(self.path, account_id=ACCOUNT, period_id=PERIOD)
        self.assertEqual((snapshot["historicalCredits"], snapshot["reservedCredits"],
                          snapshot["remainingCredits"]), (3, 7, 0))
        self.assertFalse(snapshot["authorizesGeneration"])
        with self.assertRaises(self.api.SharedLedgerError) as raised:
            self.reserve(workspace="workspace-C", job="job-three", scene="f" * 64, credits=1)
        self.assertEqual(raised.exception.code, "shared_budget_exceeded")

    def test_same_attempt_exact_replay_is_idempotent_and_sticky(self):
        self.open()
        initial = self.reserve()
        replay = self.reserve()
        self.assertEqual(replay, initial)
        self.assertEqual(self.api.snapshot(self.path, account_id=ACCOUNT, period_id=PERIOD)["reservedCredits"], 4)
        self.assertFalse(replay["authorizesGeneration"])
        self.assertFalse(replay["approvesCreative"])
        self.assertEqual(replay["reconciliationStatus"], "unresolved")

    def test_duplicate_scene_across_workspaces_cannot_get_new_job(self):
        self.open()
        self.reserve()
        with self.assertRaises(self.api.SharedLedgerError) as raised:
            self.reserve(workspace="workspace-B", job="job-two")
        self.assertEqual(raised.exception.code, "duplicate_scene_attempt")

    def test_job_id_reuse_with_changed_request_is_rejected(self):
        self.open()
        self.reserve()
        with self.assertRaises(self.api.SharedLedgerError) as raised:
            self.reserve(request="f" * 64)
        self.assertEqual(raised.exception.code, "reservation_identity_changed")

    def test_opening_same_budget_is_idempotent_but_never_resets_it(self):
        self.open(limit=8, history=1)
        self.reserve(credits=4)
        self.assertEqual(self.open(limit=8, history=1)["maximumCredits"], 8)
        for kwargs in ({"limit": 9}, {"history": 0}, {"authority": "e" * 64}):
            with self.subTest(kwargs=kwargs), self.assertRaises(self.api.SharedLedgerError) as raised:
                self.open(**{"limit": 8, "history": 1, **kwargs})
            self.assertEqual(raised.exception.code, "immutable_authority_conflict")
        self.assertEqual(self.api.snapshot(self.path, account_id=ACCOUNT, period_id=PERIOD)["remainingCredits"], 3)

    def test_independent_account_budget_cannot_borrow_anothers_cap(self):
        other = "acct_fedcba9876543210"
        self.open(limit=4)
        self.open(limit=7, account=other)
        self.reserve(credits=4)
        self.reserve(account=other, workspace="workspace-C", job="job-two", scene="e" * 64, credits=7)
        self.assertEqual(self.api.snapshot(self.path, account_id=other, period_id=PERIOD)["remainingCredits"], 0)
        with self.assertRaises(self.api.SharedLedgerError):
            self.reserve(workspace="workspace-D", job="job-three", scene="f" * 64, credits=1)

    def test_without_reconciled_authority_reservation_fails_closed(self):
        with self.assertRaises(self.api.SharedLedgerError) as raised:
            self.reserve()
        self.assertEqual(raised.exception.code, "shared_authority_missing")

    def test_reject_untrusted_identity_amounts_and_storage_paths(self):
        with self.assertRaises(self.api.SharedLedgerError):
            self.api.open_budget(":memory:", account_id=ACCOUNT, period_id=PERIOD,
                                 maximum_credits=5, authority_sha256=AUTHORITY,
                                 reconciled_legacy_credits=0, reconciliation_sha256="d" * 64)
        for amount in (True, 1.5, 0, -1):
            with self.subTest(amount=amount), self.assertRaises(self.api.SharedLedgerError):
                self.open(limit=amount)
        for account in ("", "example.com", "../foo", "acct_different"):
            with self.subTest(account=account), self.assertRaises(self.api.SharedLedgerError):
                self.open(account=account)
        with self.assertRaises(self.api.SharedLedgerError):
            self.open(authority="unverified")

    def test_concurrent_workspaces_compete_under_one_atomic_cap(self):
        self.open(limit=5)
        barrier = threading.Barrier(2)

        def attempt(i):
            barrier.wait(timeout=5)
            try:
                return self.reserve(workspace=f"workspace-{i}", job=f"job-{i}",
                                    scene=(("e" if i == 1 else "f") * 64), credits=4)
            except self.api.SharedLedgerError as exc:
                return exc.code

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, i) for i in (1, 2)]
            outcomes = [f.result(timeout=8) for f in futures]
        self.assertEqual(sum(isinstance(x, dict) for x in outcomes), 1)
        self.assertIn("shared_budget_exceeded", outcomes)
        self.assertEqual(self.api.snapshot(self.path, account_id=ACCOUNT, period_id=PERIOD)["reservedCredits"], 4)

    def test_reservation_survives_reopen_without_credit_release(self):
        self.open(limit=5)
        first = self.reserve()
        self.assertEqual(first["reservedCredits"], 4)
        self.assertEqual(self.api.snapshot(self.path, account_id=ACCOUNT, period_id=PERIOD)["remainingCredits"], 1)
        with self.assertRaises(self.api.SharedLedgerError):
            self.reserve(job="job-two", scene="e" * 64, credits=2)
        self.assertEqual(self.api.snapshot(self.path, account_id=ACCOUNT, period_id=PERIOD)["reservedCredits"], 4)

    def test_corrupt_or_missing_budget_cannot_look_like_zero_usage(self):
        self.open()
        Path(self.path).unlink()
        with self.assertRaises(self.api.SharedLedgerError) as raised:
            self.api.snapshot(self.path, account_id=ACCOUNT, period_id=PERIOD)
        self.assertEqual(raised.exception.code, "shared_authority_missing")

    def test_changed_budget_or_reservation_rows_are_not_trusted(self):
        self.open(limit=10)
        self.reserve()
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE business_global_reservations SET credits=1")
        with self.assertRaises(self.api.SharedLedgerError) as raised:
            self.api.snapshot(self.path, account_id=ACCOUNT, period_id=PERIOD)
        self.assertEqual(raised.exception.code, "shared_ledger_integrity_error")
        with closing(sqlite3.connect(self.path)) as con, con:
            con.execute("UPDATE business_global_budgets SET maximum_credits=1000")
        with self.assertRaises(self.api.SharedLedgerError) as raised:
            self.reserve(workspace="workspace-B", job="job-two", scene="f" * 64)
        self.assertEqual(raised.exception.code, "shared_ledger_integrity_error")


if __name__ == "__main__":
    unittest.main()
