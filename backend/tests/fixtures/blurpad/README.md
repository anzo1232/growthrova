These 22 stills come from tracked Clippr videos. `regenerate.py` records every
source path and timestamp and reproduces each still with ffmpeg. Three positive
stills are actual blurred letterbox composites in the product promo (18, 20,
24 seconds). The 19 unmodified negative stills include plain ceilings and
walls, talking heads, product scenes, and video compression. The test makes four
additional pad variants by applying its existing deterministic transform to
these project-sourced stills, retaining the original 7-positive/19-negative
matrix size and both letterbox and pillarbox cases.

The earlier scratchpad images referenced by the old test were never checked in
and are unavailable. These assets replace that lost input set; they do not
claim to reproduce the original model-generated scenes or lip-sync frames.
