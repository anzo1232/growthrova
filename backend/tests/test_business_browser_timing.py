"""Timeout diagnostics preserve boundaries without profiling unrelated work."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.business_browser_timing import BrowserActionTiming


class BrowserTimingTests(unittest.TestCase):
    def test_journal_reuses_one_stream_and_flushes_each_nested_boundary(self):
        # Real file reads inside the transport must see starts before it returns.
        # Reopening the journal per row adds thousands of syscalls to the gate.
        class Boundary:
            def _sync(self, work):
                return work()
        transport = Boundary()
        real_open = Path.open
        streams = []
        def tracked_open(path, *args, **kwargs):
            stream = real_open(path, *args, **kwargs)
            if path.name == 'browser-actions.jsonl' and args and args[0] in ('w', 'a'):
                streams.append(stream)
            return stream
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'browser-actions.jsonl'
            def nested():
                rows = [json.loads(line) for line in output.read_text().splitlines()]
                self.assertEqual([(r['id'], r['event']) for r in rows],
                    [(1, 'started'), (2, 'started')])
                return 17
            with patch.object(Path, 'open', tracked_open):
                with BrowserActionTiming(Path(directory), boundary=Boundary):
                    self.assertEqual(transport._sync(lambda: transport._sync(nested)), 17)
            self.assertEqual(len(streams), 1,
                'One journal stream must serve the whole journey, not reopen every row')
            self.assertTrue(streams[0].closed)
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual([(r['id'], r['event']) for r in rows],
                [(1, 'started'), (2, 'started'), (2, 'returned'), (1, 'returned')])

    def test_shared_helper_retains_the_actual_journey_call_site(self):
        class Boundary:
            def _sync(self):
                pass
        original = Boundary._sync
        with tempfile.TemporaryDirectory() as directory:
            journey = compile('def guard():\n    action()\n\nguard()\n',
                'growthrova-workspace-recovery.browser.py', 'exec')
            with BrowserActionTiming(Path(directory), boundary=Boundary):
                exec(journey, {'action': Boundary()._sync})
            rows = [json.loads(line) for line in
                    (Path(directory) / 'browser-actions.jsonl').read_text().splitlines()]
            self.assertEqual(rows[0]['journeyLine'], 4)
            self.assertIs(Boundary._sync, original)

    def test_inflight_action_is_flushed_before_failure_and_boundary_is_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'browser-actions.jsonl'
            class Boundary:
                def _sync(self, secret):
                    assert 'super-secret' not in output.read_text()
                    assert 'started' in output.read_text()
                    raise RuntimeError('original failure')
            original = Boundary._sync
            with self.assertRaisesRegex(RuntimeError, 'original failure'):
                with BrowserActionTiming(Path(directory), boundary=Boundary):
                    Boundary()._sync('super-secret')
            self.assertIs(Boundary._sync, original)
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual([row['event'] for row in rows], ['started', 'returned'])
            self.assertEqual(rows[0]['id'], rows[1]['id'])
            self.assertGreaterEqual(rows[1]['wallSeconds'], 0)
            self.assertGreaterEqual(rows[1]['cpuSeconds'], 0)
            self.assertNotIn('super-secret', output.read_text())
            self.assertNotIn('original failure', output.read_text())

    def test_unrelated_work_does_not_install_a_global_profiler(self):
        class Boundary:
            def _sync(self):
                return 42
        previous = sys.getprofile()
        calls = []
        def existing(frame, event, arg):
            if event == 'call' and frame.f_code.co_name == 'ordinary_work':
                calls.append('preserved')
        def ordinary_work():
            return sum(range(4))
        try:
            sys.setprofile(existing)
            with tempfile.TemporaryDirectory() as directory:
                with BrowserActionTiming(Path(directory), boundary=Boundary):
                    self.assertIs(sys.getprofile(), existing,
                        'Diagnostics must not profile every Python/library/renderer call')
                    ordinary_work()
                self.assertEqual((Path(directory) / 'browser-actions.jsonl').read_text(), '')
            self.assertEqual(calls, ['preserved'])
        finally:
            sys.setprofile(previous)

    def test_nested_boundaries_keep_original_results_and_separate_ids(self):
        class Boundary:
            def _sync(self, work):
                return work()
        transport = Boundary()
        with tempfile.TemporaryDirectory() as directory:
            with BrowserActionTiming(Path(directory), boundary=Boundary):
                self.assertEqual(transport._sync(lambda: transport._sync(lambda: 17)), 17)
            rows = [json.loads(line) for line in
                    (Path(directory) / 'browser-actions.jsonl').read_text().splitlines()]
            self.assertEqual([(r['id'], r['event']) for r in rows],
                [(1, 'started'), (2, 'started'), (2, 'returned'), (1, 'returned')])


if __name__ == '__main__':
    unittest.main()
