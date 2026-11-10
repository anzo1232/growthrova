"""Clippr Business branded video compositor.

Render typography and brand assets into a transparent PNG using Pillow, then
overlay that artwork via FFmpeg. This avoids FFmpeg drawtext/libfreetype build
differences and keeps user-provided brand text out of filter expressions.

This private function must only receive logo paths AFTER an organisation
ownership check; no public HTTP route exposes arbitrary source paths.
"""
from __future__ import annotations

from pathlib import Path
import json
import re
import subprocess
import tempfile

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
TEMPLATES = {"modern", "classic", "bold", "minimal"}
STATIC_EXPORT_DIMENSIONS = {"portrait": (1080, 1350), "square": (1080, 1080), "story": (1080, 1920)}
# Shared with complete-advert planning; exact logos are applied locally.
EXACT_LOGO_REGION_PERCENT = dict(left=72, top=8, width=20, height=12)
FONT_REL = Path(__file__).resolve().parent / "fonts" / "DejaVuSans-Bold.ttf"


class BrandRenderError(ValueError):
    pass


def _valid_colour(value):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise BrandRenderError("Invalid brand colour")
    return value.upper()


def _luminance(value):
    c = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return c[0] * 0.2126 + c[1] * 0.7152 + c[2] * 0.0722


def contrast_ratio(colour_a, colour_b):
    x, y = _luminance(_valid_colour(colour_a)), _luminance(_valid_colour(colour_b))
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def _text(value, maximum):
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value.strip().replace("\n", " ") if c.isprintable())[:maximum]


def validate_brand(brand):
    if not isinstance(brand, dict):
        raise BrandRenderError("Brand settings are required")
    style = brand.get("font_style") or "modern"
    if style not in TEMPLATES:
        raise BrandRenderError("Unsupported creative direction")
    primary = _valid_colour(brand.get("primary_color"))
    secondary = _valid_colour(brand.get("secondary_color"))
    if contrast_ratio(primary, secondary) < 4.5:
        raise BrandRenderError("Brand palette has insufficient text contrast")
    name = _text(brand.get("name"), 38)
    if len(name) < 2:
        raise BrandRenderError("Brand name is too short")
    return {
        "name": name, "font_style": style,
        "primary_color": primary, "secondary_color": secondary,
        "default_cta": _text(brand.get("default_cta"), 66),
    }


def _probe(path):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12,
        check=False
    )
    if proc.returncode:
        raise BrandRenderError("Source video cannot be inspected")
    try:
        row = json.loads(proc.stdout)["streams"][0]
        w, h = int(row["width"]), int(row["height"])
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        raise BrandRenderError("Source video has invalid dimensions") from exc
    if not (160 <= w <= 7680 and 160 <= h <= 7680):
        raise BrandRenderError("Unsupported video dimensions")
    return w, h


def _approved_logo(logo_path, logo_root):
    if not logo_path:
        return None
    if not logo_root:
        raise BrandRenderError("Logo asset root must be authorised")
    root = Path(logo_root).resolve()
    path = Path(logo_path).resolve(strict=True)
    if not path.is_file() or not path.is_relative_to(root):
        raise BrandRenderError("Logo is outside the approved brand asset directory")
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise BrandRenderError("Unsupported logo type")
    if path.stat().st_size > 5_000_000:
        raise BrandRenderError("Logo exceeds maximum allowed size")
    return path


def _colour(hex_string, alpha=255):
    return tuple(int(hex_string[i:i+2], 16) for i in (1, 3, 5)) + (alpha,)


def _fit_text(draw, text, font_path, max_width, preferred_px, minimum_px=12):
    from PIL import ImageFont
    size = max(minimum_px, preferred_px)
    for px in range(size, minimum_px-1, -1):
        font = ImageFont.truetype(str(font_path), size=px)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return text, font
    font = ImageFont.truetype(str(font_path), size=minimum_px)
    while text and draw.textbbox((0, 0), text + "…", font=font)[2] > max_width:
        text = text[:-1]
    return text + "…" if text else "", font


def compose_brand_overlay(width, height, brand, *, logo_path=None, logo_root=None):
    """Return an RGBA Pillow image; central 70% stays transparent."""
    from PIL import Image, ImageDraw
    b = validate_brand(brand)
    logo = _approved_logo(logo_path, logo_root)
    if not FONT_REL.exists():
        raise BrandRenderError("Brand rendering font is unavailable")
    if width < 160 or height < 160 or width > 7680 or height > 7680:
        raise BrandRenderError("Unsupported branding dimensions")
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    primary, secondary = b["primary_color"], b["secondary_color"]
    pc = _colour(primary)
    white = _colour(secondary)
    style = b["font_style"]
    pad = max(10, int(width * 0.045))
    header_h = max(46, int(height * (0.11 if style=="bold" else 0.085)))
    bottom_h = max(42, int(height * (0.085 if style in ("bold","classic") else 0.075)))
    base_size = max(15, min(63, int(height*(0.047 if style=="bold" else 0.033))))
    if style == "bold":
        draw.rectangle((0, 0, width, header_h), fill=_colour(primary, 242))
        draw.rectangle((0, header_h-4, width, header_h), fill=_colour(secondary, 240))
    elif style == "minimal":
        draw.rounded_rectangle((pad-5, 8, width-pad+5, header_h-5),
                               radius=max(8,int(header_h*0.12)), fill=_colour(primary,200))
    elif style == "classic":
        draw.rectangle((0, 0, width, header_h), fill=_colour(primary, 226))
        draw.rectangle((pad, header_h-5, width-pad, header_h-3), fill=white)
    else:
        draw.rectangle((0, 0, width, header_h), fill=_colour(primary, 219))
        draw.rectangle((0, header_h-4, max(35,int(width*0.3)), header_h), fill=white)

    available = width - pad*2
    if logo:
        try:
            with Image.open(logo) as source_logo:
                source_logo.load()
                source_logo = source_logo.convert("RGBA")
                logo_size = (max(36, int(width*0.14)), max(24,int(header_h*0.8)))
                source_logo.thumbnail(logo_size, Image.Resampling.LANCZOS)
                pos=(width-pad-source_logo.width, max(3,(header_h-source_logo.height)//2))
                canvas.alpha_composite(source_logo, pos)
                available -= logo_size[0]+pad
        except Exception as exc:
            raise BrandRenderError("Unable to decode the approved brand logo") from exc

    title = b["name"].upper() if style == "bold" else b["name"]
    title, font = _fit_text(draw, title, FONT_REL, available, base_size)
    if title:
        box = draw.textbbox((0,0), title, font=font)
        text_h=box[3]-box[1]
        draw.text((pad, (header_h-text_h)//2-box[1]), title, font=font, fill=white)

    if b["default_cta"]:
        y1=height-bottom_h
        if style=="minimal":
            draw.rounded_rectangle((pad,y1,width-pad,height-6),radius=10,
                                   fill=_colour(primary,206))
        else:
            draw.rectangle((0,y1,width,height),fill=_colour(primary,224))
        cta_size=max(12,min(38,int(height*.023)))
        caption,capfont=_fit_text(draw,b["default_cta"],FONT_REL,width-pad*2,
                                  cta_size)
        if caption:
            tbox=draw.textbbox((0,0),caption,font=capfont)
            text_h=tbox[3]-tbox[1]
            draw.text((pad,y1+(bottom_h-text_h)//2-tbox[1]),
                      caption,font=capfont,fill=white)
    return canvas


def render_branded_clip(video_path, output_path, brand, *, logo_path=None,
                        logo_root=None, timeout=180):
    video = Path(video_path).resolve(strict=True)
    output = Path(output_path)
    if not video.is_file():
        raise BrandRenderError("Video was not found")
    if output.resolve() == video:
        raise BrandRenderError("Source video must never be overwritten")
    b = validate_brand(brand)
    w, h = _probe(video)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clippr-brand-") as scratch:
        overlay = Path(scratch) / "overlay.png"
        compose_brand_overlay(w,h,b,logo_path=logo_path,logo_root=logo_root).save(overlay)
        args=["ffmpeg","-hide_banner","-nostdin","-loglevel","error",
              "-y","-i",str(video),"-loop","1","-i",str(overlay),
              "-filter_complex","[0:v][1:v]overlay=0:0:shortest=1:format=auto[v]",
              "-map","[v]","-map","0:a?","-c:v","libx264","-preset","veryfast",
              "-crf","19","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k",
              "-movflags","+faststart",str(output)]
        result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              text=True,timeout=timeout,check=False)
        if result.returncode or not output.exists() or output.stat().st_size < 1500:
            try: output.unlink(missing_ok=True)
            except OSError: pass
            raise BrandRenderError("Brand export failed; the original clip is unchanged")
    return {"path":str(output),"width":w,"height":h,"style":b["font_style"]}


def _static_text_block(draw, value, box, *, preferred_px, colour, paint=True, font_path=None, align='left'):
    """Wrap complete words, fail rather than ellipsize or make mobile text tiny."""
    from PIL import ImageFont
    if (not isinstance(value, str) or not value.strip() or len(value) > 4000 or
            any(not c.isprintable() and c != '\n' for c in value)):
        raise BrandRenderError('Save complete, printable post words and a call to action first')
    left, top, right, bottom = box
    for size in range(preferred_px, 47, -2):
        font = ImageFont.truetype(str(font_path or FONT_REL), size=size)
        lines = []
        fits = True
        for paragraph in value.split('\n'):
            line = ''
            for word in paragraph.split():
                if draw.textlength(word, font=font) > right-left:
                    fits = False
                    break
                candidate = (line+' '+word).lstrip()
                if draw.textlength(candidate, font=font) > right-left:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line)
            if not fits:
                break
        step = round(size*1.3)
        if fits and len(lines)*step <= bottom-top:
            if paint:
                for index, line in enumerate(lines):
                    x = left if align == 'left' else left + (right-left-draw.textlength(line, font=font))/2
                    draw.text((x, top+index*step), line, font=font, fill=colour, anchor='lt')
            return dict(fontSize=size, top=top, bottom=top+len(lines)*step, limit=bottom)
    raise BrandRenderError('Saved words do not fit this static layout readably. Choose shorter graphic words or CTA in the campaign editor; nothing has been changed')


def compose_static_post(photo, brand, copy, call_to_action, *, logo=None, frame='portrait', layout='standard'):
    """Review draft from authorised pixels, using existing brand rules.

    No logo is inferred. No crop, text truncation, rights grant or approval.
    Caller chooses graphic words separately from the retained social caption.
    """
    from PIL import Image, ImageDraw, ImageOps
    if layout == 'logo-only':
        if frame != 'original' or logo is None:
            raise BrandRenderError('Select a whole original logo and preserve the original advert frame')
        # A deliberate alternative export, never a replacement of provider art.
        # No typography, resizing, crop, colour panel or generated logo.
        transparent = 'A' in photo.getbands() or 'transparency' in photo.info
        canvas = photo.convert('RGBA' if transparent else 'RGB')
        with ImageOps.exif_transpose(logo) as oriented:
            fitted = oriented.convert('RGBA')
        try:
            region = EXACT_LOGO_REGION_PERCENT
            fitted.thumbnail((max(1, round(canvas.width*region['width']/100)),
                              max(1, round(canvas.height*region['height']/100))), Image.Resampling.LANCZOS)
            x = canvas.width-round(canvas.width*(100-region['left']-region['width'])/100)-fitted.width
            y = round(canvas.height*region['top']/100)
            if transparent:
                canvas.alpha_composite(fitted, (x, y))
            else:
                canvas.paste(fitted, (x, y), fitted)
            return canvas, dict(copy=copy, callToAction=call_to_action, layout=layout,
                logoIncluded=True, logoBox=[x,y,fitted.width,fitted.height], frameFit='original',
                textBlocks=[], photoBox=[0,0,canvas.width,canvas.height])
        finally:
            fitted.close()
    if not isinstance(frame, str) or frame not in STATIC_EXPORT_DIMENSIONS:
        raise BrandRenderError('Choose a portrait, square or story static export')
    if layout not in ('standard', 'image-led'):
        raise BrandRenderError('Choose a supported static layout')
    height = STATIC_EXPORT_DIMENSIONS[frame][1]
    # Reserve space for common story interface overlays. Exact placement varies
    # by platform, so the final artwork still requires a placement review.
    story = frame == 'story'
    header_top = 250 if story else 0
    content_bottom = height-340 if story else height
    photo_top = 420 if story else 160
    photo_height = {'square': 360, 'portrait': 530, 'story': 600}[frame]
    copy_top = {'square': 560, 'portrait': 730, 'story': 1060}[frame]
    b = validate_brand(brand)
    if b['name'] != brand.get('name'):
        raise BrandRenderError('Save an exact brand name without surrounding whitespace first')
    if not FONT_REL.is_file():
        raise BrandRenderError('Brand rendering font is unavailable')
    if layout == 'image-led' and b['font_style'] == 'classic':
        return _classic_static_post(photo, b, copy, call_to_action, logo=logo, frame=frame)
    canvas = Image.new('RGB', (1080, height), b['primary_color'])
    draw = ImageDraw.Draw(canvas)
    # Generated portrait art used to occupy only 14% of the portrait canvas.
    # Measure the complete copy first, then give the remaining space to the
    # whole image. The genuine-photo layout remains compatible by default.
    copy_size = 64
    cta_top = content_bottom-160
    if layout == 'image-led':
        copy_size = 52
        copy_height = _static_text_block(draw, copy, (64, 0, 1016, 300),
            preferred_px=copy_size, colour=b['secondary_color'], paint=False)['bottom']
        cta_height = _static_text_block(draw, call_to_action, (64, 0, 1016, 136),
            preferred_px=52, colour=b['secondary_color'], paint=False)['bottom']
        cta_top = content_bottom-48-cta_height
        copy_top = cta_top-40-copy_height
        photo_height = copy_top-32-photo_top
        if photo_height < 280:
            raise BrandRenderError('Saved words leave too little image space. Choose shorter graphic words or CTA; nothing has been changed')
    logo_box = None
    name_right = 1016
    if logo is not None:
        # The caller resolves catalogue ownership/permission, never a URL/path.
        # Preserve the complete mark, transparency and aspect ratio.
        with ImageOps.exif_transpose(logo) as oriented:
            with oriented.convert('RGBA') as rgba:
                fitted = ImageOps.contain(rgba, (240, 100), Image.Resampling.LANCZOS)
                try:
                    x, y = 1016-fitted.width, header_top+30+(100-fitted.height)//2
                    canvas.paste(fitted, (x, y), fitted)
                    logo_box = [x, y, fitted.width, fitted.height]
                finally:
                    fitted.close()
        name_right = 744
    name_box = (64, header_top+20, name_right, header_top+150) if logo is not None else (64, header_top+40, name_right, header_top+120)
    blocks = [_static_text_block(draw, b['name'], name_box,
        preferred_px=56, colour=b['secondary_color'])]
    # EXIF orientation is applied once; contain keeps every saved crop pixel.
    with ImageOps.exif_transpose(photo) as oriented:
        with oriented.convert('RGBA') as rgba:
            fitted = ImageOps.contain(rgba, (952, photo_height), Image.Resampling.LANCZOS)
            try:
                x, y = (1080-fitted.width)//2, photo_top+(photo_height-fitted.height)//2
                canvas.paste(fitted, (x, y), fitted)
                photo_box = [x, y, fitted.width, fitted.height]
            finally:
                fitted.close()
    blocks.append(_static_text_block(draw, copy, (64, copy_top, 1016, cta_top-40 if layout == 'image-led' else content_bottom-210),
        preferred_px=copy_size, colour=b['secondary_color']))
    rule_y = cta_top-20
    draw.line((64, rule_y, 1016, rule_y), fill=b['secondary_color'], width=3)
    blocks.append(_static_text_block(draw, call_to_action, (64, cta_top, 1016, content_bottom-30),
        preferred_px=52, colour=b['secondary_color']))
    return canvas, dict(copy=copy, callToAction=call_to_action, photoBox=photo_box,
        textBlocks=blocks, logoIncluded=logo is not None, logoBox=logo_box, frameFit='contain', layout=layout)


def _classic_static_post(photo, brand, copy, call_to_action, *, logo, frame):
    """Editorial classic treatment; exact source stays whole and unmodified."""
    from PIL import Image, ImageDraw, ImageOps
    serif = Path(__file__).resolve().parent / 'fonts' / 'DejaVuSerif.ttf'
    if not serif.is_file():
        raise BrandRenderError('Classic headline font is unavailable')
    height = STATIC_EXPORT_DIMENSIONS[frame][1]
    top = 250 if frame == 'story' else 0
    bottom = height-340 if frame == 'story' else height
    canvas = Image.new('RGB', (1080, height), brand['secondary_color'])
    draw = ImageDraw.Draw(canvas)
    ink = brand['primary_color']
    logo_box = None
    name_right = 1016
    if logo is not None:
        with ImageOps.exif_transpose(logo) as oriented:
            with oriented.convert('RGBA') as rgba:
                fitted = ImageOps.contain(rgba, (220, 90), Image.Resampling.LANCZOS)
                try:
                    x,y = 1016-fitted.width,top+24
                    canvas.paste(fitted,(x,y),fitted)
                    logo_box = [x,y,fitted.width,fitted.height]
                finally:
                    fitted.close()
        name_right = 744
    # Exact saved names can need two lines, especially beside an original logo.
    # Keep the short-name layout stable and move the headline only when needed.
    name = _static_text_block(draw, brand['name'], (64,top+30,name_right,top+154),
        preferred_px=48, colour=ink, align='center')
    headline_top = max(top+138, name['bottom']+26)
    headline = _static_text_block(draw, copy, (64,headline_top,1016,headline_top+240),
        preferred_px=64, colour=ink, font_path=serif, align='center')
    cta = _static_text_block(draw, call_to_action, (96,0,984,136),
        preferred_px=48, colour=ink, paint=False)
    cta_top = bottom-40-cta['bottom']
    photo_top = headline['bottom']+30
    photo_height = cta_top-58-photo_top
    if photo_height < 280:
        canvas.close()
        raise BrandRenderError('Saved words leave too little image space. Choose shorter graphic words or CTA; nothing has been changed')
    with ImageOps.exif_transpose(photo) as oriented:
        with oriented.convert('RGBA') as rgba:
            fitted = ImageOps.contain(rgba,(952,photo_height),Image.Resampling.LANCZOS)
            try:
                x,y = (1080-fitted.width)//2, photo_top+(photo_height-fitted.height)//2
                canvas.paste(fitted,(x,y),fitted)
                photo_box = [x,y,fitted.width,fitted.height]
            finally:
                fitted.close()
    draw.rectangle((64,cta_top-18,1016,bottom-22), fill=ink)
    cta = _static_text_block(draw, call_to_action, (96,cta_top,984,bottom-30),
        preferred_px=48, colour=brand['secondary_color'], align='center')
    return canvas, dict(copy=copy,callToAction=call_to_action,photoBox=photo_box,
        textBlocks=[name,headline,cta],logoIncluded=logo is not None,logoBox=logo_box,
        frameFit='contain',layout='classic-editorial',headlineFont='DejaVuSerif')
