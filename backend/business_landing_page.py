"""Standalone landing-page *draft* based on observed website facts.

No deployment, live form endpoint, analytics, customer data collection, or
automatically approved generated footage. The exported preview uses no JS.
"""
from __future__ import annotations
import base64,html,io,re
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image

def clean(value,limit=300):
 text=' '.join(str(value or '').split())
 text=re.sub(r'(?i)\bon[a-z]{3,30}\s*=', '[invalid text] ',text)
 return text[:limit]

def safe(value,limit=300):
 return html.escape(clean(value,limit),quote=True)

def validated_url(value):
 if not isinstance(value,str) or len(value)>512:raise ValueError('Business website required')
 u=urlsplit(value)
 if u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment or u.port not in (None,443):
  raise ValueError('Only a safe HTTPS business website may receive enquiries')
 return html.escape(value,quote=True)

def photo_data(image):
 if image is None:return None
 file=Path(image)
 if not file.is_file() or file.is_symlink() or file.stat().st_size>20*1024*1024:
  raise ValueError('The verified visual is unavailable')
 with Image.open(file) as pic:
  if pic.format not in ('JPEG','PNG','WEBP') or min(pic.size)<256 or pic.width*pic.height>20_000_000:
   raise ValueError('Unusable visual source')
  pic.load()
  original=pic.convert('RGB')
  w,h=original.size
  # Portrait editorial still, with the full visual visible and bounded size.
  original.thumbnail((1200,1600),Image.Resampling.LANCZOS)
  tmp=io.BytesIO();original.save(tmp,'WEBP',quality=72,method=5)
  data=tmp.getvalue()
  if len(data)>1000000:raise ValueError('Landing-page image exceeds safe offline size')
 return 'data:image/webp;base64,'+base64.b64encode(data).decode('ascii')

_TEMPLATE='''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; object-src 'none'">
<title>__TITLE__</title>
<meta name="description" content="__META__">
<style>
:root{color-scheme:light;--ink:#16261d;--forest:#213a2b;--warm:#f9f6ee;--gold:#c4a77a}
*{box-sizing:border-box}body{margin:0;font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:var(--warm)}
a:focus-visible{outline:3px solid #659e72;outline-offset:4px}
.draft{padding:12px 4vw;background:#fff2cc;color:#634c1c;font-size:13px;text-align:center;font-weight:700}
nav{max-width:1190px;margin:auto;padding:26px 24px;display:flex;align-items:center;justify-content:space-between;gap:18px}
.brand{font-size:20px;letter-spacing:.06em;font-weight:700;overflow-wrap:anywhere}
nav a{font-weight:700;color:var(--forest);font-size:13px}
.hero{background:#1b2e26;color:#fff;display:grid;grid-template-columns:minmax(0,1.1fr) minmax(240px,.9fr);min-height:550px}
.copy{padding:clamp(32px,6vw,100px);display:flex;flex-direction:column;justify-content:center;max-width:780px}
.overline{font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:#c8d9ba}
h1{font-family:Georgia,"Times New Roman",serif;font-size:clamp(38px,5vw,74px);line-height:1.09;letter-spacing:-.045em;font-weight:400;overflow-wrap:anywhere}
.copy p{font-size:17px;line-height:1.75;color:#dce8dc;max-width:580px}
.cta{display:inline-block;background:#d6e9b5;color:#1f3a29;text-decoration:none;font-size:14px;font-weight:750;padding:15px 25px;border-radius:9px;margin-top:16px;align-self:start}
.hero-photo{min-height:500px;background:linear-gradient(145deg,#445b62 0%,#233f44 45%,#a58b65 100%);position:relative}
.hero-photo img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.hero-photo p{position:absolute;bottom:18px;left:22px;right:22px;z-index:1;font-size:11px;line-height:1.6;color:white;text-shadow:0 2px 6px #111;background:#122c34bf;padding:8px 12px;border-radius:7px}
.services{max-width:1120px;margin:auto;padding:70px 24px}
.services h2{font-family:Georgia,"Times New Roman",serif;font-size:clamp(28px,3vw,43px);font-weight:400;letter-spacing:-.04em}
.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:30px}
.card{background:#fff;border:1px solid #e4e8df;border-radius:12px;padding:24px;min-height:180px}
.card span{font-size:11px;color:#698070;font-weight:700;letter-spacing:.08em}
.card h3{font-size:19px;line-height:1.35;overflow-wrap:anywhere}
.card p{font-size:13px;line-height:1.7;color:#60705e}
.steps{max-width:1120px;margin:0 auto 60px;padding:35px 24px;background:#e7eee3;border-radius:14px}
.steps h2{font-family:Georgia,serif;font-weight:400;font-size:34px}
.steps p{font-size:15px;line-height:1.75}
footer{text-align:center;padding:30px 24px;background:#172820;color:#d7e3d6;font-size:12px}
footer a{color:#e2f0d9}
@media(max-width:750px){nav{padding:20px}.hero{grid-template-columns:1fr}.copy{padding:36px 25px}.hero-photo{min-height:320px}.cards{grid-template-columns:1fr}.services{padding:42px 20px}.steps{margin:0 12px 40px}h1{font-size:44px}}
</style>
</head>
<body>
<div class="draft">DRAFT PREVIEW — not a live website, not approved for publishing or collecting customer details.</div>
<nav><div class="brand">__BRAND__</div><a href="__URL__" rel="noopener noreferrer">Official website ↗</a></nav>
<main id="main">
<section class="hero" aria-label="Business introduction">
<div class="copy">
<div class="overline">Explore what is available</div>
<h1>__HERO__</h1>
<p>__DESCRIPTION__</p>
<a class="cta" href="__URL__" rel="noopener noreferrer">__CTA__ →</a>
</div>
<div class="hero-photo">__PHOTO__
<p>__DISCLOSURE__</p></div>
</section>
<section class="services">
<h2>What to find out before you decide</h2>
<div class="cards">
<article class="card"><span>01 / SERVICES</span><h3>Know what's offered</h3><p>Explore the current service details on the official website.</p></article>
<article class="card"><span>02 / DETAILS</span><h3>Ask what matters to you</h3><p>Check availability, suitability, scope and terms before committing.</p></article>
<article class="card"><span>03 / NEXT STEP</span><h3>Make a clear enquiry</h3><p>Tell the business what you're looking for so it can discuss the options.</p></article>
</div>
</section>
<section class="steps">
<h2>Ready to take the next step?</h2>
<p>We haven't connected a live enquiry form. Use the business's existing website to ask for information, a booking or a quote.</p>
<a class="cta" href="__URL__" rel="noopener noreferrer">__CTA__ →</a>
</section>
</main>
<footer>__BRAND__ · Example page produced for review. Please confirm services, imagery rights, wording and the enquiry route before publishing.
<div><a href="__URL__" rel="noopener noreferrer">Official website</a></div>
</footer>
</body>
</html>
'''

def make_preview(doc,source_image,destination,*,photo_origin="generated"):
 if not isinstance(doc,dict) or doc.get('version')!=1:raise ValueError('Saved business campaign required')
 website=validated_url(doc.get('sourceUrl'))
 brand=safe(doc.get('business'),100)
 if not brand:raise ValueError('Business name required')
 facts=doc.get('observedFacts',[])
 if not isinstance(facts,list):raise ValueError('Invalid source observations')
 info=safe(facts[1] if len(facts)>1 else '',420)
 if not info:info='Read about the current services and ask about the details that matter to you.'
 headline=safe(facts[2] if len(facts)>2 else '',110)
 if not headline:headline='Explore what '+clean(doc.get('business'),50)+' can offer'
 if len(headline)<12:headline='Discover '+brand
 cta=safe((doc.get('creatives') or [{}])[0].get('callToAction') or 'Visit the official website',85)
 image=photo_data(source_image)
 pic='<img src="'+image+'" alt="Illustrative advertising concept — not an actual customer photo or verified location">' if image else ''
 disclaimer=('Owner-selected website photo; usage rights declared but not independently verified.' if photo_origin=='owner_declared' else
  'Illustrative generated image; not a verified photograph of this business or its customer work.') if image else 'Design concept only; no customer photographs are shown.'
 body=_TEMPLATE
 for name,value in {'TITLE':brand+' — website concept','META':info,'BRAND':brand,'HERO':headline,'DESCRIPTION':info,
                    'URL':website,'CTA':cta,'PHOTO':pic,'DISCLOSURE':disclaimer}.items():
  body=body.replace('__'+name+'__',value)
 output=Path(destination)
 if output.is_symlink():raise ValueError('Unsafe export destination')
 output.parent.mkdir(parents=True,exist_ok=True)
 if output.exists():raise ValueError('Do not overwrite a previous saved export')
 output.write_text(body,encoding='utf8')
 return output
