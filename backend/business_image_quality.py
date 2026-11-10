"""Deterministic technical checks only. No unearned marketing quality score."""
from __future__ import annotations
import math
from PIL import Image,ImageStat,ImageFilter


def inspect_image(image, *, expected_aspect_ratio=.8, detect_sparse=False):
 if not isinstance(image,Image.Image):raise ValueError('Decoded image required')
 if (type(expected_aspect_ratio) not in (int,float) or not math.isfinite(expected_aspect_ratio)
     or expected_aspect_ratio<=0):raise ValueError('Positive finite expected aspect ratio required')
 width,height=image.size
 if type(detect_sparse) is not bool:raise ValueError('detect_sparse must be boolean')
 if width<256 or height<256 or width*height>20_000_000:
  raise ValueError('Unsupported image dimensions')
 thumb=image.convert('RGB').resize((192,192),Image.Resampling.LANCZOS)
 grey=thumb.convert('L')
 colour=ImageStat.Stat(thumb)
 contrast=ImageStat.Stat(grey).stddev[0]
 edge_image=grey.filter(ImageFilter.FIND_EDGES)
 edges=ImageStat.Stat(edge_image).stddev[0]
 edge_pixels=list(edge_image.get_flattened_data())
 edge_ratio=sum(value>22 for value in edge_pixels)/len(edge_pixels)
 palette_cells=len(set((red//16,green//16,blue//16) for red,green,blue in thumb.get_flattened_data()))
 flags=[]
 if contrast<8 or max(colour.stddev)<10 or edges<4:flags.append('low_visual_detail')
 if detect_sparse and palette_cells<80 and edge_ratio<.10:flags.append('sparse_visual_field')
 ratio=width/height
 if abs(ratio-expected_aspect_ratio)>.025:flags.append('unexpected_aspect_ratio')
 return {'resolution':[width,height],
  'qualityStatus':'technical_review_required' if flags else 'awaiting_visual_and_brand_review',
  'flags':flags,'ownerApproved':False,'claimsVerified':False,'paletteCells':palette_cells,
  'edgePixelRatio':round(edge_ratio,6),
  'limitations':'Deterministic checks can reject flat or sparse visual fields, but cannot judge realism, brand accuracy, generic creative or conversion.'}
