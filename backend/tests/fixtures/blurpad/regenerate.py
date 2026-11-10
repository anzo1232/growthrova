"""Regenerate visual QC fixtures from media tracked in this repository.

Run from any working directory with ffmpeg installed. The source list was
selected by visual inspection, before measuring detector results.
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

# Positive sources: actual blur-padded composites in the Clippr promo.
BAD = {
    "real_padded_table.jpg": ("promo/clippr_promo_9x16.mp4", 18),
    "real_padded_interview.jpg": ("promo/clippr_promo_9x16.mp4", 20),
    "real_padded_table_late.jpg": ("promo/clippr_promo_9x16.mp4", 24),
}

# Negative sources cover plain upper walls/ceilings, product scenes, presenter
# and talking-head footage. They remain whole frames with no padding added.
GOOD = {
    **{f"hero_two_{s}.jpg": ("public/hero_clip_2.mp4", s) for s in (2, 5, 8)},
    **{f"hero_four_{s}.jpg": ("public/hero_clip_4.mp4", s) for s in (2, 5, 8)},
    "hero_five_2.jpg": ("public/hero_clip_5.mp4", 2),
    **{f"shop_{s}.jpg": ("public/shop_ad.mp4", s) for s in (2, 8, 22)},
    **{f"hero_one_{s}.jpg": ("public/hero_clip_1.mp4", s) for s in (2, 5, 8)},
    **{f"hero_three_{s}.jpg": ("public/hero_clip_3.mp4", s) for s in (2, 5)},
    **{f"demo_{s}.jpg": ("public/demo_1.mp4", s) for s in (2, 8, 16)},
    "promo_clean_presenter.jpg": ("promo/clippr_promo_9x16.mp4", 12),
}


def main():
    for name, (source, second) in (BAD | GOOD).items():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(second), "-i", str(ROOT / source),
             "-frames:v", "1", "-q:v", "3", "-y", str(HERE / name)],
            check=True,
        )


if __name__ == "__main__":
    main()
