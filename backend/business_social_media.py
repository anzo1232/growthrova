"""Integrity checked ordered carousel bytes from an immutable local review ZIP."""
import hashlib
import io
import zipfile


def carousel_files(content, manifest):
    # Archives come only from the server renderer. Still bound reads and reject
    # compression, duplicate names and order/hash mismatches before any dispatch.
    slides = manifest.get('slides', [])
    if not 2 <= len(slides) <= 5 or len(content) > 20 * 1024 * 1024 + 128 * 1024:
        raise ValueError('Invalid retained carousel')
    files = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate carousel entries')
        for i, slide in enumerate(slides, 1):
            name = f'slide-{i:02d}.png'
            info = archive.getinfo(name)
            if (slide['file'] != name or info.compress_type != zipfile.ZIP_STORED
                    or info.file_size != slide['bytes'] or not 8 <= info.file_size <= 20 * 1024 * 1024):
                raise ValueError('Retained carousel changed')
            pixels = archive.read(name)
            if not pixels.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(pixels).hexdigest() != slide['sha256']:
                raise ValueError('Retained slide changed')
            files.append(pixels)
    return tuple(files)
