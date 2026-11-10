"""Actual server Business-paid adapter, executed isolated from live server init."""
import ast
import unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parent.parent/"server.py"
BODY=ast.parse(SOURCE.read_text())
HELPER=next(x for x in BODY.body if isinstance(x,ast.FunctionDef)
            and x.name=="_business_paid_entitlement")
PROGRAM=ast.fix_missing_locations(ast.Module(body=[HELPER],type_ignores=[]))

ROW={"tier":"pro","status":"active","provider":"stripe",
     "subscription_id":"sub_test","whop_membership_id":None,
     "current_period_end":"2999-01-01T00:00:00"}

class Conn:
    def __init__(self,row,missing=False):
        self.row=row
        self.sql=None
        self.missing=missing
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,sql,params):
        self.sql=sql
        if self.missing:raise RuntimeError("database unavailable")
        return self
    def fetchone(self):return self.row

class BillingAdapterTests(unittest.TestCase):
    def call(self,row,*,explode=False):
        conn=Conn(row,missing=explode)
        namespace={"_ensure_billing_tables":lambda:None,"get_db":lambda:conn}
        exec(compile(PROGRAM,str(SOURCE),"exec"),namespace)
        return namespace["_business_paid_entitlement"]({"id":"owner-id"}),conn
    def test_only_verified_active_paid_rows_pass(self):
        paid,conn=self.call(ROW)
        self.assertTrue(paid)
        self.assertIn("current_period_end",conn.sql)
        self.assertIn("subscription_id",conn.sql)
        self.assertIn("provider",conn.sql)
    def test_trial_expired_and_missing_payment_rows_fail(self):
        for changes in (
            {"status":"trialing"},
            {"status":"past_due"},
            {"current_period_end":"2025-01-01T00:00:00"},
            {"subscription_id":None},
            {"tier":"free"},
            {"provider":"unknown"},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(self.call({**ROW,**changes})[0])
    def test_no_row_and_database_errors_fail_closed(self):
        self.assertFalse(self.call(None)[0])
        self.assertFalse(self.call(ROW,explode=True)[0])
if __name__=="__main__":unittest.main()
