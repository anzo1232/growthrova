"""Actual synthetic-video checks; these fixtures are not client creative approvals."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageStat

import business_reel_caption_render as renderer


def run(args):
    return subprocess.run(args, check=True, capture_output=True, timeout=30).stdout


def frame(path, at):
    return Image.open(io.BytesIO(run(['ffmpeg', '-nostdin', '-v', 'error', '-ss', str(at),
        '-i', str(path), '-frames:v', '1', '-f', 'image2pipe', '-c:v', 'png', '-']))).convert('RGB')


def audio_packets(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_packets',
        '-show_entries', 'packet=data_hash', '-show_data_hash', 'sha256', '-of', 'json', str(path)]))['packets']


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Local FFmpeg required')
class CaptionRenderVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='clippr-caption-synthetic-qa-')
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / 'synthetic-original.mp4'
        run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
             'color=c=0x28445D:s=720x1280:r=24:d=3', '-f', 'lavfi', '-i',
             'sine=frequency=440:sample_rate=48000:duration=3', '-map', '0:v', '-map', '1:a',
             '-c:v', 'libx264', '-threads', '2', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-b:a', '128k', '-shortest', str(cls.source)])
        cls.original = cls.source.read_bytes()
        cls.brand = {'locked': True, 'primary': '#18352B', 'accent': '#D8B37A', 'style': 'editorial'}
        cls.style = {'typeface': 'editorial', 'weight': 'bold', 'placement': 'bottom_safe'}
        cls.text = '{caption} <tag> & "quoted" £25'
        cls.cues = [{'start': .5, 'end': 1.5, 'text': cls.text}]
        cls.output = cls.root / 'synthetic-captioned.mp4'
        cls.result = renderer.render(cls.source, cls.output, cues=cls.cues, style=cls.style,
                                     brand=cls.brand, expected_duration=3)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_mp4_has_timed_caption_pixels_and_keeps_other_frames_clear(self):
        before = frame(self.output, .25)
        during = frame(self.output, 1)
        after = frame(self.output, 2)
        original = frame(self.source, 1)
        for plain in (before, after):
            difference = ImageStat.Stat(ImageChops.difference(plain, original))
            self.assertLess(max(difference.mean), 2)
        box = self.result['layout'][0]
        rect = (box['x'], box['y'], box['x'] + box['width'], box['y'] + box['height'])
        change = ImageStat.Stat(ImageChops.difference(during.crop(rect), original.crop(rect)))
        self.assertGreater(max(change.mean), 12)
        # Top-of-frame content is not covered by captions or a full-screen plate.
        untouched = ImageStat.Stat(ImageChops.difference(during.crop((0, 0, 720, 500)), original.crop((0, 0, 720, 500))))
        self.assertLess(max(untouched.mean), 2)

    def test_source_unchanged_audio_packets_copied_and_timing_preserved(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(audio_packets(self.source), audio_packets(self.output))
        self.assertEqual((self.result['width'], self.result['height']), (720, 1280))
        self.assertAlmostEqual(self.result['duration'], 3, delta=.05)
        self.assertTrue(self.result['audioCopied'])
        self.assertEqual(self.result['sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(self.result['bytes'], self.output.stat().st_size)
        self.assertFalse(list(self.root.glob('.caption-render-*')))

    def test_literal_markup_and_punctuation_stay_text_and_layout_is_safe(self):
        layout = self.result['layout'][0]
        self.assertEqual(layout['text'], self.text)
        self.assertEqual(' '.join(layout['lines']), self.text)
        self.assertGreaterEqual(layout['x'], 72)
        self.assertLessEqual(layout['x'] + layout['width'], 648)
        self.assertGreaterEqual(layout['y'], 192)
        self.assertLessEqual(layout['y'] + layout['height'], 1049)
        self.assertEqual(self.result['accent'], '#D8B37A')

    def test_middle_placement_and_wrapping_fit_long_saved_caption(self):
        style = {**self.style, 'placement': 'middle_safe'}
        text = 'A longer verified caption wraps inside the portrait without losing its words.'
        font = renderer._font_path(style['typeface'], style['weight'])
        image, layout = renderer._plate(text, style, self.brand, (720, 1280), font)
        self.assertEqual(' '.join(layout['lines']), text)
        self.assertGreater(len(layout['lines']), 1)
        self.assertLessEqual(len(layout['lines']), 3)
        self.assertAlmostEqual(layout['y'] + image.height / 2, 640, delta=1)
        self.assertLessEqual(image.width, 562)

    def test_invalid_cues_and_unavailable_glyphs_fail_before_rendering(self):
        cases = [
            [{'start': True, 'end': 1, 'text': 'Bad timestamp'}],
            [{'start': float('nan'), 'end': 1, 'text': 'Bad timestamp'}],
            [{'start': 0, 'end': 4, 'text': 'Beyond video'}],
            [{'start': 0, 'end': 1, 'text': 'First'}, {'start': .5, 'end': 2, 'text': 'Overlap'}],
            [{'start': 0, 'end': 1, 'text': 'Line\nBreak'}],
            [{'start': 0, 'end': 1, 'text': 'Hidden\u200bmark'}],
            [{'start': 0, 'end': 1, 'text': 'Unrenderable \U0010fffd'}],
        ]
        for index, cues in enumerate(cases):
            target = self.root / f'rejected-{index}.mp4'
            with self.subTest(index=index), self.assertRaises(renderer.CaptionRenderError):
                renderer.render(self.source, target, cues=cues, style=self.style, brand=self.brand, expected_duration=3)
            self.assertFalse(target.exists())

    def test_existing_outputs_and_symlink_destinations_are_never_overwritten(self):
        digest = self.result['sha256']
        with self.assertRaises(renderer.CaptionRenderError):
            renderer.render(self.source, self.output, cues=self.cues, style=self.style, brand=self.brand, expected_duration=3)
        self.assertEqual(hashlib.sha256(self.output.read_bytes()).hexdigest(), digest)
        link = self.root / 'unsafe-link.mp4'
        link.symlink_to(self.source)
        with self.assertRaises(renderer.CaptionRenderError):
            renderer.render(self.source, link, cues=self.cues, style=self.style, brand=self.brand, expected_duration=3)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_timeout_cleans_attempt_files_and_preserves_original(self):
        target = self.root / 'timeout.mp4'
        original_run = renderer.subprocess.run
        def fail_render(command, *args, **kwargs):
            if command[0] == 'ffmpeg' and str(command[-1]).endswith('.mp4'):
                Path(command[-1]).write_bytes(b'partial failed render')
                raise subprocess.TimeoutExpired(command[0], 85)
            return original_run(command, *args, **kwargs)
        with patch.object(renderer.subprocess, 'run', side_effect=fail_render):
            with self.assertRaises(renderer.CaptionRenderError):
                renderer.render(self.source, target, cues=self.cues, style=self.style, brand=self.brand, expected_duration=3)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.caption-render-*')))
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_source_mutation_during_render_rejects_result(self):
        source = self.root / 'mutation-source.mp4'
        source.write_bytes(self.original)
        target = self.root / 'mutation-result.mp4'
        original_run = renderer.subprocess.run
        def mutate(command, *args, **kwargs):
            result = original_run(command, *args, **kwargs)
            if command[0] == 'ffmpeg' and str(command[-1]).endswith('.mp4'):
                source.write_bytes(self.original + b'changed while rendering')
            return result
        with patch.object(renderer.subprocess, 'run', side_effect=mutate):
            with self.assertRaises(renderer.CaptionRenderError) as error:
                renderer.render(source, target, cues=self.cues, style=self.style, brand=self.brand, expected_duration=3)
        self.assertEqual(error.exception.code, 'changed_source')
        self.assertFalse(target.exists())

    def test_damaged_camera_packet_cannot_be_hidden_by_successful_ffmpeg_exit(self):
        source = self.root / 'synthetic-camera-damaged.mp4'
        run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
             'testsrc2=s=720x1280:r=24:d=4', '-f', 'lavfi', '-i',
             'sine=frequency=440:sample_rate=48000:duration=4', '-map', '0:v', '-map', '1:a',
             '-c:v', 'libx264', '-threads', '2', '-preset', 'ultrafast', '-g', '24',
             '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(source)])
        packets = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v',
             '-show_packets', '-show_entries', 'packet=pos,size', '-of', 'json', str(source)]))['packets']
        # Damage an interior compressed video packet without changing the MP4
        # header, declared duration, stream count or file size. FFmpeg can conceal
        # this error, emit a full-length frozen/dropped frame and still exit 0.
        packet = packets[49]
        pos, size = int(packet['pos']), int(packet['size'])
        damaged = bytearray(source.read_bytes())
        damaged[pos:pos + size] = b'\x00' * size
        source.write_bytes(damaged)
        self.assertAlmostEqual(renderer._probe(source)['duration'], 4, delta=.05)
        check = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(source),
                                '-f', 'null', '-'], capture_output=True, timeout=30)
        self.assertTrue(check.stderr.strip(), 'The fixture must contain an actual decoding failure')
        target = self.root / 'damaged-captioned.mp4'
        with self.assertRaises(renderer.CaptionRenderError) as error:
            renderer.render(source, target,
                cues=[{'start': .3, 'end': 2.8, 'text': 'Actual damaged packet regression'}],
                style=self.style, brand=self.brand, expected_duration=4)
        self.assertIn(error.exception.code, ('source_decode_failed', 'caption_render_failed'))
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.caption-render-*')))
        self.assertEqual(source.read_bytes(), bytes(damaged))

    def test_corrupt_aac_packets_are_rejected_even_when_stream_metadata_is_valid(self):
        source = self.root / 'synthetic-damaged-audio.mp4'
        packets = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'a',
             '-show_packets', '-show_entries', 'packet=pos,size', '-of', 'json', str(self.source)]))['packets']
        packet = packets[80]
        pos, size = int(packet['pos']), int(packet['size'])
        damaged = bytearray(self.original)
        damaged[pos:pos + size] = b'\x00' * size
        source.write_bytes(damaged)
        self.assertTrue(renderer._probe(source)['audioPresent'])
        target = self.root / 'damaged-audio-captioned.mp4'
        with self.assertRaises(renderer.CaptionRenderError) as error:
            renderer.render(source, target, cues=self.cues, style=self.style,
                            brand=self.brand, expected_duration=3)
        self.assertEqual(error.exception.code, 'audio_decode_failed')
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.caption-render-*')))
        self.assertEqual(source.read_bytes(), bytes(damaged))

    def test_silent_prepared_preview_renders_without_inventing_audio(self):
        source = self.root / 'silent-preview.mp4'
        run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(self.source),
             '-map', '0:v:0', '-c:v', 'copy', '-an', str(source)])
        output = self.root / 'silent-captioned.mp4'
        result = renderer.render(source, output, cues=self.cues, style=self.style,
                                 brand=self.brand, expected_duration=3)
        self.assertFalse(result['audioPresent'])
        self.assertFalse(result['audioCopied'])
        self.assertTrue(output.is_file())


if __name__ == '__main__':
    unittest.main()
