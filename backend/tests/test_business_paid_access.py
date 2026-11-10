from datetime import datetime,timezone,timedelta
import unittest
from business_paid_access import has_current_paid_access,parse_period
NOW=datetime(2026,10,17,22,30,tzinfo=timezone.utc)
def row(**kw):
    result={"tier":"pro","status":"active","provider":"stripe",
        "subscription_id":"sub_test_confirmed","whop_membership_id":None,
        "current_period_end":"2026-10-20T12:00:00"}
    result.update(kw)
    return result
class PaidEntitlementTests(unittest.TestCase):
    def check(self,**kw):
        return has_current_paid_access(row(**kw),now=NOW)
    def test_active_unexpired_paid_stripe_is_allowed(self):
        self.assertTrue(self.check())
        self.assertTrue(self.check(tier="starter"))
        self.assertTrue(self.check(tier="studio"))
        self.assertTrue(self.check(current_period_end="2026-10-20T12:00:00Z"))
    def test_paid_whop_membership_requires_reference(self):
        self.assertTrue(self.check(provider="whop",
            whop_membership_id="membership_test",subscription_id=None))
        self.assertFalse(self.check(provider="whop",whop_membership_id=None))
    def test_expired_period_is_always_denied_even_with_active_status(self):
        self.assertFalse(self.check(current_period_end="2026-10-16T12:00:00"))
        self.assertFalse(self.check(current_period_end="2026-10-17T22:30:00Z"))
        self.assertFalse(self.check(current_period_end=None))
        self.assertFalse(self.check(current_period_end="tomorrow"))
    def test_trials_and_all_unpaid_states_are_denied(self):
        for status in ["trialing","past_due","incomplete","unpaid",
                       "canceled","paused",None,""]:
            with self.subTest(status=status):
                self.assertFalse(self.check(status=status))
    def test_unrecognised_tier_or_missing_payment_reference_are_denied(self):
        for field in ({"tier":"free"},{"tier":"business-free"},
                      {"provider":"unknown"},{"subscription_id":None}):
            self.assertFalse(self.check(**field))
        self.assertFalse(has_current_paid_access(None,now=NOW))
    def test_timezone_aware_comparison_never_accepts_expired_offset(self):
        self.assertFalse(self.check(current_period_end="2026-10-18T00:00:00+03:00"))
        self.assertTrue(self.check(current_period_end="2026-10-17T23:00:00+00:00"))
if __name__=="__main__":unittest.main()
