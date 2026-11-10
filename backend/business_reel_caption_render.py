"""Local, immutable MP4 caption rendering. No provider calls or inferred speech."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata

from PIL import Image, ImageDraw, ImageFont

RENDERER_VERSION = 'pillow-cue-plates-1'
MAX_BYTES = 160 * 1024 * 1024


class CaptionRenderError(ValueError):
    def __init__(self, message, code='caption_render_failed', status=422):
        super().__init__(message)
        self.code = code
        self.status = status


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _probe(path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
            capture_output=True, text=True, check=True, timeout=8)
        info = json.loads(result.stdout)
        videos = [s for s in info['streams'] if s.get('codec_type') == 'video']
        audios = [s for s in info['streams'] if s.get('codec_type') == 'audio']
        if len(videos) != 1 or len(audios) > 1:
            raise ValueError('Only one video and at most one audio stream are supported')
        v = videos[0]
        width, height = int(v['width']), int(v['height'])
        duration = float(v.get('duration') or info['format']['duration'])
        ratio = v.get('avg_frame_rate', '24/1').split('/')
        fps = float(ratio[0]) / float(ratio[1])
        rotated = float(v.get('tags', {}).get('rotate', 0))
        rotated = rotated or any(float(s.get('rotation', 0)) for s in v.get('side_data_list', []))
        if (width < 360 or width > 1080 or width * 16 != height * 9 or
                width % 2 or height % 2 or not math.isfinite(duration) or not 0 < duration <= 60 or
                not math.isfinite(fps) or not 1 <= fps <= 60 or rotated):
            raise ValueError('Use a prepared portrait Reel, at most 1080 x 1920 and 60 seconds')
        if audios and audios[0].get('codec_name') != 'aac':
            raise ValueError('The prepared Reel must use AAC audio for lossless audio copying')
        return {'width': width, 'height': height, 'duration': duration, 'fps': fps,
                'audioPresent': bool(audios), 'audioCodec': audios[0]['codec_name'] if audios else None}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        raise CaptionRenderError('The prepared portrait Reel could not be verified', 'invalid_video') from exc


def _validate(cues, style, brand, duration):
    if not isinstance(style, dict) or set(style) != {'typeface', 'weight', 'placement'}:
        raise CaptionRenderError('Use the saved caption appearance', 'invalid_caption_style', 400)
    if (style['typeface'] not in ('editorial', 'modern', 'sans') or
            style['weight'] not in ('bold', 'regular') or
            style['placement'] not in ('bottom_safe', 'middle_safe')):
        raise CaptionRenderError('Caption appearance is not supported', 'invalid_caption_style', 400)
    if not isinstance(brand, dict) or brand.get('locked') is not True:
        raise CaptionRenderError('Lock genuine business branding before rendering captions', 'brand_not_locked', 409)
    if any(not isinstance(brand.get(k), str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', brand[k])
           for k in ('primary', 'accent')):
        raise CaptionRenderError('Saved brand colours are invalid', 'invalid_brand', 400)
    if not isinstance(cues, list) or not 1 <= len(cues) <= 50:
        raise CaptionRenderError('Save between one and fifty verified cues', 'invalid_captions', 400)
    previous = 0
    for cue in cues:
        if not isinstance(cue, dict) or set(cue) != {'start', 'end', 'text'}:
            raise CaptionRenderError('Each cue needs start, end and exact text', 'invalid_captions', 400)
        start, end, text = cue['start'], cue['end'], cue['text']
        if (type(start) not in (int, float) or type(end) not in (int, float) or
                not math.isfinite(start) or not math.isfinite(end) or start < 0 or
                end <= start + .22 or start < previous - .001 or end > duration + .05):
            raise CaptionRenderError('Caption times overlap or exceed this Reel', 'invalid_captions', 400)
        if (not isinstance(text, str) or not 1 <= len(text) <= 80 or text != text.strip() or
                any(unicodedata.category(c).startswith('C') for c in text)):
            raise CaptionRenderError('Keep each verified cue to 1–80 visible characters', 'invalid_captions', 400)
        previous = end


def _verify_audio_decodes(path):
    # Stream-copy preserves the original AAC packets, including a damaged one.
    # Decode once for integrity before copying: loudness and stream metadata do
    # not prove that every packet can play. This check adds at most 10 seconds
    # to the 85-second render and two 8-second probes (111 seconds total).
    try:
        result = subprocess.run(
            ['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
             '-vn', '-map', '0:a:0', '-f', 'null', '-'],
            capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CaptionRenderError('The soundtrack could not be decoded safely', 'audio_decode_failed', 422) from exc
    if result.returncode or result.stderr.strip():
        raise CaptionRenderError('The soundtrack contains a decoding error. Replace the damaged audio before export.',
                                 'audio_decode_failed', 422)


def _font_path(typeface, weight):
    serif = typeface == 'editorial'
    bold = weight == 'bold'
    names = ([f'Georgia{" Bold" if bold else ""}.ttf'] if serif else
             [f'Arial{" Bold" if bold else ""}.ttf'])
    candidates = [Path('/System/Library/Fonts/Supplemental') / n for n in names]
    candidates += [Path('/usr/share/fonts/truetype/dejavu') /
                   f'DejaVu{"Serif" if serif else "Sans"}{"-Bold" if bold else ""}.ttf']
    for path in candidates:
        if path.is_file() and not path.is_symlink():
            return path
    raise CaptionRenderError('The approved caption font is unavailable', 'font_unavailable', 409)


def _glyph_check(text, font):
    # FreeType uses its .notdef glyph for missing characters. Do not silently
    # export replacement squares in place of the owner's supplied wording.
    absent = font.getmask(chr(0x10ffff))
    signature = (absent.size, bytes(absent))
    for character in set(text):
        if character.isspace():
            continue
        glyph = font.getmask(character)
        if (glyph.size, bytes(glyph)) == signature:
            raise CaptionRenderError('The saved font cannot render every caption character',
                                     'unsupported_caption_character', 400)


def _wrap(text, draw, font, max_width):
    words = text.split(' ')
    lines, line = [], ''
    for word in words:
        candidate = line + (' ' if line else '') + word
        if draw.textlength(candidate, font=font) <= max_width:
            line = candidate
        else:
            if not line or draw.textlength(word, font=font) > max_width:
                return None
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines if 1 <= len(lines) <= 3 else None


def _plate(text, style, brand, size, font_path):
    width, height = size
    scale = width / 720
    max_width = round(width * .78)
    padding_x, padding_y = round(20 * scale), round(16 * scale)
    image = Image.new('RGBA', (max_width, round(height * .22)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    layout = None
    for font_size in range(round(42 * scale), max(17, round(28 * scale)) - 1, -1):
        font = ImageFont.truetype(str(font_path), font_size)
        _glyph_check(text, font)
        lines = _wrap(text, draw, font, max_width - padding_x * 2)
        if not lines:
            continue
        boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        line_height = max(box[3] - box[1] for box in boxes)
        gap = round(7 * scale)
        panel_height = line_height * len(lines) + gap * (len(lines) - 1) + padding_y * 2 + round(3 * scale)
        if panel_height <= image.height:
            layout = (font, font_size, lines, boxes, line_height, gap, panel_height)
            break
    if layout is None:
        raise CaptionRenderError('This caption cannot fit safely; shorten the saved wording', 'caption_too_wide', 400)
    font, font_size, lines, boxes, line_height, gap, panel_height = layout
    panel_width = min(max_width, math.ceil(max(draw.textlength(line, font=font) for line in lines)) + padding_x * 2)
    image = Image.new('RGBA', (panel_width, panel_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, panel_width - 1, panel_height - 1), radius=round(9 * scale), fill=(12, 14, 17, 224))
    accent = tuple(int(brand['accent'][i:i + 2], 16) for i in (1, 3, 5))
    stripe = max(2, round(3 * scale))
    draw.rectangle((round(12 * scale), panel_height - stripe, panel_width - round(12 * scale), panel_height - 1), fill=accent + (255,))
    for i, (line, box) in enumerate(zip(lines, boxes)):
        x = (panel_width - (box[2] - box[0])) / 2 - box[0]
        y = padding_y + i * (line_height + gap) - box[1]
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
    x = (width - panel_width) // 2
    y = round(height * (.75 if style['placement'] == 'bottom_safe' else .5)) - panel_height // 2
    if x < width * .1 or x + panel_width > width * .9 or y < height * .15 or y + panel_height > height * .82:
        raise CaptionRenderError('Caption placement exceeds the safe region', 'caption_unsafe', 400)
    return image, {'x': x, 'y': y, 'width': panel_width, 'height': panel_height,
                   'fontSize': font_size, 'lines': lines, 'text': text}


def render(video_path, output_path, *, cues, style, brand, expected_duration):
    """Burn verified text into a NEW portrait MP4 while copying AAC unchanged.

    Inputs must be immutable prepared local assets. The caller owns approvals,
    persistent receipts and the final recheck against current campaign state.
    """
    source, output = Path(video_path), Path(output_path)
    if (source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_BYTES or
            output.exists() or output.is_symlink() or not output.parent.is_dir() or
            output.parent.is_symlink() or source.resolve() == output.resolve()):
        raise CaptionRenderError('Preserve the original and use a new private MP4 path', 'unsafe_path', 409)
    if output.suffix.lower() != '.mp4':
        raise CaptionRenderError('Caption exports must be MP4 files', 'invalid_output', 400)
    if type(expected_duration) not in (int, float) or not math.isfinite(expected_duration) or not 0 < expected_duration <= 60:
        raise CaptionRenderError('A finite expected Reel duration is required', 'invalid_duration', 400)
    before_hash = _digest(source)
    probe = _probe(source)
    if abs(probe['duration'] - expected_duration) > .16:
        raise CaptionRenderError('The saved timing no longer matches this Reel', 'changed_source', 409)
    _validate(cues, style, brand, probe['duration'])
    if probe['audioPresent']:
        _verify_audio_decodes(source)
    font_path = _font_path(style['typeface'], style['weight'])
    font_hash = _digest(font_path)
    created = False
    try:
        with tempfile.TemporaryDirectory(prefix='.caption-render-', dir=output.parent) as temp:
            folder = Path(temp)
            target = folder / 'captioned.mp4'
            inputs, chains, positions = [], ['[0:v]setpts=PTS-STARTPTS[captionbase]'], []
            prior = 'captionbase'
            for i, cue in enumerate(cues, 1):
                plate, position = _plate(cue['text'], style, brand, (probe['width'], probe['height']), font_path)
                file = folder / f'cue-{i}.png'
                plate.save(file)
                inputs += ['-i', str(file)]
                current = f'caption{i}'
                enable = f"gte(t,{cue['start']:.3f})*lt(t,{cue['end']:.3f})"
                chains.append(f"[{prior}][{i}:v]overlay={position['x']}:{position['y']}:eof_action=repeat:shortest=0:enable='{enable}'[{current}]")
                prior = current
                positions.append({**position, 'start': cue['start'], 'end': cue['end']})
            chains.append(f'[{prior}]format=yuv420p[out]')
            command = ['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(source), *inputs,
                       '-filter_complex_threads', '1', '-filter_complex', ';'.join(chains),
                       '-map', '[out]', '-map', '0:a:0?', '-map_metadata', '-1',
                       '-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast', '-crf', '18',
                       '-c:a', 'copy', '-movflags', '+faststart', '-t', f"{probe['duration']:.6f}", str(target)]
            result = subprocess.run(command, check=True, capture_output=True, timeout=85)
            # FFmpeg can conceal damaged frames and still return exit 0. At
            # loglevel=error, any diagnostic is a decoding/processing failure,
            # not proof of a clean captioned rendition. Preserve the source and
            # reject the new output rather than accepting a frozen/missing shot.
            if result.stderr.strip():
                raise CaptionRenderError('The source contains a decoding error. Replace the damaged recording before export.',
                                         'source_decode_failed', 422)
            if not target.is_file() or not 0 < target.stat().st_size <= MAX_BYTES:
                raise CaptionRenderError('Caption render produced no usable private video')
            verified = _probe(target)
            if (verified['width'] != probe['width'] or verified['height'] != probe['height'] or
                    abs(verified['duration'] - probe['duration']) > .12 or
                    verified['audioPresent'] != probe['audioPresent'] or
                    verified['audioCodec'] != probe['audioCodec']):
                raise CaptionRenderError('Caption render did not preserve video timing and audio')
            if source.is_symlink() or _digest(source) != before_hash or _digest(font_path) != font_hash:
                raise CaptionRenderError('A caption input changed during rendering', 'changed_source', 409)
            os.chmod(target, 0o600)
            # Link rather than replace: a racing render cannot overwrite a prior file.
            os.link(target, output)
            created = True
            return {'width': verified['width'], 'height': verified['height'],
                    'duration': verified['duration'], 'sha256': _digest(output), 'bytes': output.stat().st_size,
                    'rendererVersion': RENDERER_VERSION, 'fontName': font_path.name,
                    'fontSha256': font_hash, 'sourceSha256': before_hash,
                    'audioPresent': verified['audioPresent'], 'audioCopied': verified['audioPresent'],
                    'bakedIntoVideo': True, 'cueCount': len(cues), 'layout': positions,
                    'style': dict(style), 'accent': brand['accent'], 'primary': brand['primary']}
    except CaptionRenderError:
        if created:
            output.unlink(missing_ok=True)
        raise
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        if created:
            output.unlink(missing_ok=True)
        raise CaptionRenderError('Local caption rendering failed safely; the original is preserved') from exc
