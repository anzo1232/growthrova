"""Lossless whole-panel evidence using the unchanged native Chromium viewport.

Only evidence capture scrolls here; customer interactions and assertions stay
in the journey. Never expand the compositor to a far-off document rectangle.
"""
import base64
import io
import math
from pathlib import Path

from PIL import Image


_GEOMETRY = '''async element => {
    await document.fonts.ready;
    const r = element.getBoundingClientRect();
    const root = element === document.documentElement;
    // Full-page pixels follow the integer scroll area, not a fractional root
    // box whose ceiling can exceed that area by one pixel.
    return {x:root ? 0 : r.x + scrollX, y:root ? 0 : r.y + scrollY,
        width:root ? document.documentElement.scrollWidth : r.width,
        height:root ? document.documentElement.scrollHeight : r.height,
        scale:devicePixelRatio, scrollX, scrollY,
        viewportWidth:innerWidth, viewportHeight:innerHeight,
        documentWidth:document.documentElement.scrollWidth,
        documentHeight:document.documentElement.scrollHeight};
}'''
_SCROLL = '''async position => {
    window.scrollTo({left:position.x, top:position.y, behavior:'instant'});
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return {x:scrollX, y:scrollY};
}'''


def capture_page(page, session, *, path, full_page):
    """Keep full-document evidence without a full-document compositor surface."""
    if full_page:
        capture_panel(page.locator('html'), session, path=path)
    else:
        page.screenshot(path=str(path), full_page=False)


def capture_panel_with_native_parity(panel, session, *, path, native_path):
    """Require exact independent pixels, allowing bounded paint convergence.

    Chromium's native radio animation can outlive checked-state assertions.
    Retain every pair; never mask controls, resize, tolerate different pixels,
    or retry a broken capture. Persistent mismatches still fail the journey.
    """
    path, native_path = Path(path), Path(native_path)
    for attempt in range(1, 4):
        fast_frame = path.with_stem(f'{path.stem}-attempt-{attempt}')
        native_frame = native_path.with_stem(f'{native_path.stem}-attempt-{attempt}')
        capture_panel(panel, session, path=fast_frame)
        panel.screenshot(path=str(native_frame))
        with Image.open(fast_frame) as fast, Image.open(native_frame) as native:
            matches = (fast.size == native.size
                       and fast.convert('RGB').tobytes() == native.convert('RGB').tobytes())
        if matches:
            path.write_bytes(fast_frame.read_bytes())
            native_path.write_bytes(native_frame.read_bytes())
            return
    raise AssertionError('Native screenshot pixel parity failed after 3 capture pairs; see attempt PNGs')


def capture_panel(panel, session, *, path):
    panel.scroll_into_view_if_needed()
    box = panel.evaluate(_GEOMETRY)
    keys = ('x', 'y', 'width', 'height', 'viewportWidth', 'viewportHeight',
            'documentWidth', 'documentHeight', 'scrollX', 'scrollY')
    if (box['scale'] != 1 or any(not math.isfinite(box[k]) for k in keys)
            or box['width'] <= 0 or box['height'] <= 0):
        raise ValueError('Panel evidence requires a visible native-scale rectangle')
    x, y = math.floor(box['x']), math.floor(box['y'])
    width = math.ceil(box['x'] + box['width']) - x
    height = math.ceil(box['y'] + box['height']) - y
    viewport_width, viewport_height = math.floor(box['viewportWidth']), math.floor(box['viewportHeight'])
    if (x < 0 or y < 0 or width * height > 25_000_000
            or width > viewport_width or viewport_height < 1
            or x + width > box['documentWidth'] or y + height > box['documentHeight']):
        raise ValueError('Panel evidence rectangle exceeds native capture bounds')
    combined = None
    single_pixels = None
    try:
        for top in range(0, height, viewport_height):
            rows = min(viewport_height, height - top)
            # Preserve the initial viewport whenever this tile already fits.
            # Unnecessary scrolling moves controls under a stationary pointer,
            # changing native hover pixels before the independent screenshot.
            position = dict(
                x=min(max(box['scrollX'], x + width - viewport_width), x,
                      max(0, box['documentWidth'] - viewport_width)),
                y=min(max(box['scrollY'], y + top + rows - viewport_height), y + top,
                      max(0, box['documentHeight'] - viewport_height)))
            actual = panel.page.evaluate(_SCROLL, position)
            if (actual != position or not actual['x'] <= x <= actual['x'] + viewport_width - width
                    or not actual['y'] <= y + top <= actual['y'] + viewport_height - rows):
                raise ValueError('Panel evidence tile is outside the native viewport')
            current = panel.evaluate(_GEOMETRY)
            if any(current[k] != box[k] for k in ('x', 'y', 'width', 'height', 'scale',
                                                  'viewportWidth', 'viewportHeight',
                                                  'documentWidth', 'documentHeight')):
                raise ValueError('Panel layout changed during evidence capture')
            # Read the visible browser view, not its expensive compositor surface.
            # Real complex-page captures previously cost seconds per tile;
            # native pixel-parity checks and complete row coverage stay required.
            # No document-space clip: capture only the native viewport.
            # Crop locally so deep history never expands the compositor surface.
            response = session.send('Page.captureScreenshot', dict(format='png',
                optimizeForSpeed=True, captureBeyondViewport=False, fromSurface=False))
            pixels = base64.b64decode(response['data'], validate=True)
            with Image.open(io.BytesIO(pixels)) as image:
                if image.format != 'PNG' or image.size != (viewport_width, viewport_height):
                    raise ValueError('Panel evidence was clipped or returned an unexpected format')
                image.load()
                tile = image.crop((x - actual['x'], y + top - actual['y'],
                                   x - actual['x'] + width, y + top - actual['y'] + rows))
                if height <= viewport_height:
                    output = io.BytesIO()
                    tile.save(output, format='PNG', compress_level=1)
                    single_pixels = output.getvalue()
                else:
                    if combined is None:
                        combined = Image.new('RGBA', (width, height))
                    combined.paste(tile.convert('RGBA'), (0, top))
    finally:
        restored = panel.page.evaluate(_SCROLL, dict(x=box['scrollX'], y=box['scrollY']))
        if restored != dict(x=box['scrollX'], y=box['scrollY']):
            raise ValueError('Could not restore scroll position after evidence capture')
    # Write only after every native-scale row and scroll restoration succeeds.
    if single_pixels is not None:
        Path(path).write_bytes(single_pixels)
    else:
        combined.save(path, format='PNG', compress_level=1)
