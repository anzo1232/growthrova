"""Evidence captures must retain whole panels and fail closed on bad pixels."""
import base64
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image


class BrowserCaptureTests(unittest.TestCase):
    def test_page_capture_keeps_full_document_coverage_and_native_viewport_choice(self):
        from tests.business_browser_capture import capture_page
        root = object()
        page = SimpleNamespace(locator=lambda selector: root if selector == 'html' else None,
                               screenshot=unittest.mock.Mock())
        with patch('tests.business_browser_capture.capture_panel') as tiled:
            capture_page(page, 'session', path='whole.png', full_page=True)
            tiled.assert_called_once_with(root, 'session', path='whole.png')
            page.screenshot.assert_not_called()
            capture_page(page, 'session', path='viewport.png', full_page=False)
            page.screenshot.assert_called_once_with(path='viewport.png', full_page=False)

    def test_deep_capture_never_submits_document_offset_to_compositor(self):
        """Native viewport pixels are cropped locally, even 30000px down."""
        from tests.business_browser_capture import capture_panel
        state = dict(x=0, y=30000)
        viewport = Image.new('RGB', (390, 844), '#123456')
        viewport.paste('#abcdef', (20, 100, 370, 700))

        class Panel:
            page = SimpleNamespace(evaluate=lambda script, position: state.update(position) or dict(state))
            def scroll_into_view_if_needed(self):
                pass
            def evaluate(self, script):
                return dict(x=20, y=30100, width=350, height=600, scale=1,
                            viewportWidth=390, viewportHeight=844,
                            documentWidth=390, documentHeight=40000,
                            scrollX=state['x'], scrollY=state['y'])

        class Session:
            def send(self, method, params):
                self_test.assertNotIn('clip', params,
                    'Document-offset clips still ask Chromium to raster deep coordinates')
                # Real creative journey: fromSurface=True repeatedly stalled
                # while visible-view capture retained identical native pixels.
                if params.get('fromSurface', True):
                    raise TimeoutError('Compositor surface readback exhausted the journey budget')
                output = io.BytesIO()
                viewport.save(output, 'PNG')
                return dict(data=base64.b64encode(output.getvalue()).decode())

        self_test = self
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'deep.png'
            try:
                capture_panel(Panel(), Session(), path=path)
            except TimeoutError as exc:
                self.fail('Whole-panel evidence must complete without expensive compositor readback: '+str(exc))
            with Image.open(path) as actual:
                self.assertEqual(actual.size, (350, 600))
                self.assertEqual(actual.tobytes(), viewport.crop((20,100,370,700)).tobytes())
        self.assertEqual(state, dict(x=0, y=30000))

    def test_visible_panel_parity_preserves_viewport_and_native_hover_pixels(self):
        """Scrolling a fitted panel moves native controls away from the pointer."""
        from tests.business_browser_capture import capture_panel_with_native_parity
        state = dict(x=0, y=29800)
        original = dict(state)
        captures = []

        def pixels():
            # Native radio hover is tied to viewport pointer coordinates.
            return Image.new('RGB', (346, 462),
                             '#005cc8' if state == original else '#0075ff')

        class Page:
            def evaluate(self, script, position):
                state.update(position)
                return dict(state)

        class Panel:
            page = Page()

            def scroll_into_view_if_needed(self):
                pass  # Already completely visible, as in the failed journey.

            def evaluate(self, script):
                return dict(x=20, y=30000, width=346, height=462, scale=1,
                            viewportWidth=390, viewportHeight=844,
                            documentWidth=390, documentHeight=40000,
                            scrollX=state['x'], scrollY=state['y'])

            def screenshot(self, *, path):
                pixels().save(path)

        class Session:
            def send(self, method, params):
                captures.append(dict(state))
                output = io.BytesIO()
                viewport = Image.new('RGB', (390,844))
                viewport.paste(pixels(), (20,200))
                viewport.save(output, 'PNG')
                return dict(data=base64.b64encode(output.getvalue()).decode())

        with tempfile.TemporaryDirectory() as directory:
            path, native = Path(directory)/'fast.png', Path(directory)/'native.png'
            capture_panel_with_native_parity(Panel(), Session(), path=path, native_path=native)
            self.assertEqual(captures, [original], 'A fitted panel needs no viewport movement')
            self.assertEqual(state, original)
            with Image.open(path) as fast, Image.open(native) as reference:
                self.assertEqual(fast.tobytes(), reference.tobytes())

    def test_native_parity_converges_after_control_animation_but_keeps_first_frames(self):
        from tests.business_browser_capture import capture_panel_with_native_parity
        frames = iter(['#125577', '#225577'])
        with tempfile.TemporaryDirectory() as directory:
            path, native = Path(directory)/'fast.png', Path(directory)/'native.png'
            panel = SimpleNamespace(screenshot=lambda *, path: Image.new('RGB', (20, 20), '#225577').save(path))

            def capture(panel, session, *, path):
                Image.new('RGB', (20, 20), next(frames)).save(path)

            with patch('tests.business_browser_capture.capture_panel', side_effect=capture) as fast:
                capture_panel_with_native_parity(panel, object(), path=path, native_path=native)
            self.assertEqual(fast.call_count, 2)
            with Image.open(path) as a, Image.open(native) as b:
                self.assertEqual(a.tobytes(), b.tobytes())
            with Image.open(Path(directory)/'fast-attempt-1.png') as first:
                self.assertEqual(first.getpixel((0, 0)), (18, 85, 119))
            self.assertTrue((Path(directory)/'native-attempt-1.png').is_file())

    def test_persistent_capture_mismatch_never_passes_parity_or_writes_final_evidence(self):
        from tests.business_browser_capture import capture_panel_with_native_parity
        for fault in ('pixels', 'dimensions', 'corrupt'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                path, native = Path(directory)/'fast.png', Path(directory)/'native.png'
                panel = SimpleNamespace(screenshot=lambda *, path: Image.new('RGB', (20, 20), '#225577').save(path))

                def capture(panel, session, *, path):
                    if fault == 'corrupt':
                        Path(path).write_bytes(b'not PNG')
                    else:
                        Image.new('RGB', (19 if fault == 'dimensions' else 20, 20), '#125577').save(path)

                with patch('tests.business_browser_capture.capture_panel', side_effect=capture) as fast:
                    with self.assertRaises((AssertionError, OSError)):
                        capture_panel_with_native_parity(panel, object(), path=path, native_path=native)
                self.assertEqual(fast.call_count, 1 if fault == 'corrupt' else 3)
                self.assertFalse(path.exists())
                self.assertFalse(native.exists())

    def test_deep_panel_capture_uses_native_viewport_and_restores_scroll(self):
        """Offscreen evidence must not expand Chromium's capture surface."""
        from tests.business_browser_capture import capture_panel
        width, height = 350, 10746
        original = Image.new('RGB', (width, height))
        for row in range(height):
            original.paste((row % 256, row // 256, 97), (0, row, width, row + 1))
        state = dict(x=0, y=40)
        clips = []

        class Page:
            def evaluate(self, script, position):
                state.update(x=position['x'], y=position['y'])
                return dict(state)

        class Panel:
            page = Page()

            def scroll_into_view_if_needed(self):
                pass

            def evaluate(self, script):
                return dict(x=20, y=30000, width=width, height=height, scale=1,
                            viewportWidth=390, viewportHeight=844,
                            documentWidth=390, documentHeight=40746,
                            scrollX=state['x'], scrollY=state['y'])

        class Session:
            def send(self, method, params):
                if params['captureBeyondViewport']:
                    raise AssertionError('Offscreen capture expands raster beyond native viewport')
                self_test.assertNotIn('clip', params)
                top = state['y'] - 30000
                clips.append(dict(height=min(844, height-max(0,top))))
                viewport = Image.new('RGB', (390,844))
                viewport.paste(original, (20, -top))
                output = io.BytesIO()
                viewport.save(output, 'PNG')
                return dict(data=base64.b64encode(output.getvalue()).decode())

        self_test = self
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'deep-panel.png'
            capture_panel(Panel(), Session(), path=path)
            with Image.open(path) as actual:
                self.assertEqual(actual.size, original.size)
                self.assertEqual(actual.convert('RGB').tobytes(), original.tobytes())
        self.assertEqual(state, dict(x=0, y=40))
        self.assertEqual(len(clips), (height+843)//844)

    def capture(self, *, size=(349, 592), hidden=False, scale=1, corrupt=False):
        from tests.business_browser_capture import capture_panel
        calls = []
        output = io.BytesIO()
        Image.new('RGB', (390,844) if size == (349,592) else size, '#225577').save(output, 'PNG')

        class Panel:
            page = SimpleNamespace(evaluate=lambda script, position: position)

            def scroll_into_view_if_needed(self):
                calls.append('scroll')
                if hidden:
                    raise TimeoutError('Panel is hidden')

            def evaluate(self, script):
                calls.append('geometry')
                return dict(x=12.25, y=1000.5, width=348.5, height=591.25, scale=scale,
                            viewportWidth=390, viewportHeight=844, documentWidth=390,
                            documentHeight=20000, scrollX=0, scrollY=1000)

        class Session:
            def send(self, method, params):
                calls.append((method, params))
                return dict(data='invalid!' if corrupt else base64.b64encode(output.getvalue()).decode())

        panel = Panel()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'whole-panel.png'
            capture_panel(panel, Session(), path=path)
            with Image.open(path) as image:
                self.assertEqual(image.size, size)
            with Image.open(path) as image, Image.open(io.BytesIO(output.getvalue())) as viewport:
                self.assertEqual(image.convert('RGB').tobytes(), viewport.crop((12,0,361,592)).tobytes())
        return calls

    def test_full_scrolled_panel_uses_lossless_fast_png_without_changing_pixels(self):
        calls = self.capture()
        self.assertEqual(calls[:2], ['scroll', 'geometry'])
        method, params = next(call for call in calls if isinstance(call, tuple))
        self.assertEqual(method, 'Page.captureScreenshot')
        self.assertEqual(params, dict(format='png', optimizeForSpeed=True,
            captureBeyondViewport=False, fromSurface=False))

    def test_tall_panel_is_captured_in_bounded_tiles_without_missing_pixels(self):
        """A long saved-posting history must not require one giant raster."""
        from tests.business_browser_capture import capture_panel
        width, height = 350, 10746
        original = Image.new('RGB', (width, height))
        # Distinct rows catch missing, repeated or reordered tile boundaries.
        for y in range(height):
            original.paste((y % 256, (y // 256) % 256, 97), (0, y, width, y+1))
        clips = []
        state = dict(x=0,y=1000)

        class Panel:
            page = SimpleNamespace(evaluate=lambda script, position: state.update(position) or dict(state))

            def scroll_into_view_if_needed(self):
                pass

            def evaluate(self, script):
                return dict(x=12, y=1000, width=width, height=height, scale=1,
                            viewportWidth=390, viewportHeight=844, documentWidth=390,
                            documentHeight=20000, scrollX=state['x'], scrollY=state['y'])

        class Session:
            def send(self, method, params):
                self_test.assertNotIn('clip', params)
                clips.append(dict(state))
                viewport = Image.new('RGB', (390,844))
                viewport.paste(original, (12, 1000-state['y']))
                output = io.BytesIO()
                viewport.save(output, 'PNG')
                return dict(data=base64.b64encode(output.getvalue()).decode())

        self_test = self
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'history.png'
            capture_panel(Panel(), Session(), path=path)
            with Image.open(path) as result:
                self.assertEqual(result.size, original.size)
                self.assertEqual(result.convert('RGB').tobytes(), original.tobytes())
        self.assertGreater(len(clips), 1)
        self.assertEqual(len(clips), (height+843)//844)
        self.assertTrue(all(clip['x'] == 0 for clip in clips))

    def test_bad_later_tile_does_not_write_a_partial_capture(self):
        from tests.business_browser_capture import capture_panel

        state = dict(x=0,y=0)
        class Panel:
            page = SimpleNamespace(evaluate=lambda script, position: state.update(position) or dict(state))

            def scroll_into_view_if_needed(self):
                pass

            def evaluate(self, script):
                return dict(x=0, y=0, width=20, height=5092, scale=1,
                            viewportWidth=390, viewportHeight=844, documentWidth=390,
                            documentHeight=20000, scrollX=state['x'], scrollY=state['y'])

        for fault in ('dimensions', 'corrupt', 'timeout'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                state.update(x=0,y=0)
                class Session:
                    def send(self, method, params):
                        later = state['y'] > 0
                        if later and fault == 'timeout':
                            raise TimeoutError('Capture interrupted')
                        if later and fault == 'corrupt':
                            return dict(data='invalid!')
                        height = 844 - (1 if later and fault == 'dimensions' else 0)
                        output = io.BytesIO()
                        Image.new('RGBA', (390, height), (11, 22, 33, 44)).save(output, 'PNG')
                        return dict(data=base64.b64encode(output.getvalue()).decode())

                path = Path(directory)/'incomplete.png'
                with self.assertRaises((ValueError, TimeoutError)):
                    capture_panel(Panel(), Session(), path=path)
                self.assertFalse(path.exists(), 'Failed tile must not masquerade as whole-panel evidence')

    def test_capture_failure_layout_shift_or_scroll_failure_withholds_evidence(self):
        from tests.business_browser_capture import capture_panel
        for fault in ('capture', 'layout', 'scroll', 'restore'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                state = dict(x=0, y=30)
                scrolls = []

                class Page:
                    def evaluate(self, script, position):
                        scrolls.append(position)
                        state.update(position)
                        if fault == 'scroll' and position['y'] != 30:
                            state['y'] = 0
                        if fault == 'restore' and position['y'] == 30:
                            state['y'] = 0
                        return dict(state)

                class Panel:
                    page = Page()

                    def scroll_into_view_if_needed(self):
                        pass

                    def evaluate(self, script):
                        return dict(x=10, y=10000, width=20,
                                    height=1001 if fault == 'layout' and scrolls else 1000,
                                    scale=1, viewportWidth=390, viewportHeight=844,
                                    documentWidth=390, documentHeight=20000,
                                    scrollX=state['x'], scrollY=state['y'])

                class Session:
                    def send(self, method, params):
                        if fault == 'capture':
                            raise TimeoutError('Interrupted capture')
                        output = io.BytesIO()
                        Image.new('RGB', (390,844)).save(output, 'PNG')
                        return dict(data=base64.b64encode(output.getvalue()).decode())

                path = Path(directory) / 'held.png'
                with self.assertRaises((ValueError, TimeoutError)):
                    capture_panel(Panel(), Session(), path=path)
                self.assertFalse(path.exists())
                self.assertEqual(scrolls[-1], dict(x=0, y=30))
                if fault != 'restore':
                    self.assertEqual(state, dict(x=0, y=30))

    def test_hidden_wrong_dimensions_corrupt_and_non_native_scale_are_errors(self):
        for arguments in (dict(hidden=True), dict(size=(348, 844)), dict(corrupt=True), dict(scale=2)):
            with self.subTest(arguments=arguments), self.assertRaises((ValueError, TimeoutError)):
                self.capture(**arguments)


if __name__ == '__main__':
    unittest.main()
