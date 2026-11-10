"""A changed request must not silently recover an older tone's proposal."""
import unittest
import tests.test_business_growthrova_writer as fixtures

class WriterRequestConflictTests(unittest.TestCase):
    setUp = fixtures.GrowthrovaWriterTests.setUp
    create = fixtures.GrowthrovaWriterTests.create
    write = fixtures.GrowthrovaWriterTests.write
    def test_new_operation_changed_tone_conflicts_without_second_charge(self):
        initial = self.write()
        self.assertEqual(initial.status_code, 200, initial.json)
        self.assertEqual(initial.json["state"], "proposed")
        changed = self.write(operationId="c" * 32, tone="direct and practical")
        self.assertEqual(changed.status_code, 409,
            "A new operation ID must not silently return the old tone's proposal")
        self.assertEqual(len(self.provider.calls), 1,
            "The conflict must not generate a second billable request")
        reopened = self.create().test_client().get(self.url, headers=self.headers)
        self.assertEqual(reopened.json["proposals"][0], initial.json)

if __name__ == "__main__":
    unittest.main()
