"""
Prism Motion Graphics — the reference benchmark
────────────────────────────────────────────────
Measures a Prism render against a reference film, frame by frame, and
lays both out side by side so the biggest gap is visible before it is
argued about.

The reference (`inspo.mp4`) is a phone screen recording of a story ad:
the ad itself is a 9:16 film letterboxed inside a taller frame, with the
platform's chrome (status bar, header, buttons, caption) drawn over it.
`ad_region()` finds the 9:16 area; `COMPARE_BAND` keeps to the part of
that area the chrome does not cover. A Prism render is compared inside
the same band of ITS frame.

Metrics per sampled time, on band crops scaled to the same small size:

- luminance: mean absolute luminance difference (0-255)
- colour: distance between mean RGB (0-441)
- structure: correlation of edge maps (-1..1) — is the same *kind* of
  thing where the reference has it (a band, a card, a glow)
- busyness: edge density of each — a sparse frame against a dense one

Across time: the motion profile (frame-to-frame change per step) of
each film and their correlation — do things move when the reference's do.

`score()` folds these into one 0-100 number. It is a heuristic to track
progress between iterations, not a judgement of taste; the sheet is.
Pillow only; FFmpeg pulls the frames.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import review as _review

# The part of a 9:16 story that platform chrome leaves clear, as
# fractions of the ad's own height: below the header, above the
# like/share column and the call-to-action.
COMPARE_BAND = (0.04, 0.58)
THUMB = (108, 192)      # 9:16 thumbnails for the sheet and the metrics
EDGE_SIZE = (36, 64)    # coarse edge maps for structure correlation


def ad_region(width: int, height: int) -> Tuple[int, int, int, int]:
    """(left, top, right, bottom) of the 9:16 ad inside a frame. A frame
    already at 9:16 is the ad; a taller phone recording letterboxes it."""
    want_h = int(round(width * 16 / 9))
    if height <= want_h + 2:
        return (0, 0, width, height)
    top = (height - want_h) // 2
    return (0, top, width, top + want_h)


def band_box(width: int, height: int) -> Tuple[int, int, int, int]:
    l, t, r, b = ad_region(width, height)
    h = b - t
    return (l, t + int(h * COMPARE_BAND[0]), r, t + int(h * COMPARE_BAND[1]))


def _luma(img):
    return img.convert("L")


def _mean_rgb(img) -> Tuple[float, float, float]:
    from PIL import ImageStat
    m = ImageStat.Stat(img.convert("RGB")).mean
    return (m[0], m[1], m[2])


def _edges(img):
    from PIL import ImageFilter
    return _luma(img).resize(EDGE_SIZE).filter(ImageFilter.FIND_EDGES)


def _correlation(a, b) -> float:
    pa, pb = list(a.getdata()), list(b.getdata())
    n = len(pa)
    ma, mb = sum(pa) / n, sum(pb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(pa, pb))
    va = math.sqrt(sum((x - ma) ** 2 for x in pa)) or 1e-9
    vb = math.sqrt(sum((y - mb) ** 2 for y in pb)) or 1e-9
    return cov / (va * vb)


def _density(edges) -> float:
    data = list(edges.getdata())
    return sum(1 for v in data if v > 40) / max(1, len(data))


def frame_metrics(ref, cand) -> Dict[str, float]:
    """Metrics for one pair of band crops (any size; both are resized)."""
    from PIL import ImageChops, ImageStat
    a = ref.convert("RGB").resize(THUMB)
    b = cand.convert("RGB").resize(THUMB)
    lum = ImageStat.Stat(ImageChops.difference(_luma(a), _luma(b))).mean[0]
    ra, rb = _mean_rgb(a), _mean_rgb(b)
    colour = math.sqrt(sum((x - y) ** 2 for x, y in zip(ra, rb)))
    ea, eb = _edges(a), _edges(b)
    return {
        "luminance": round(lum, 2),
        "colour": round(colour, 2),
        "structure": round(_correlation(ea, eb), 3),
        "busy_ref": round(_density(ea), 3),
        "busy_cand": round(_density(eb), 3),
        "ref_rgb": [round(v) for v in ra],
        "cand_rgb": [round(v) for v in rb],
    }


def score(frames: Sequence[Dict[str, float]], motion_corr: float) -> float:
    """0-100. Equal thirds: how alike each sampled frame looks (light,
    colour, structure, busyness), and whether motion happens together."""
    if not frames:
        return 0.0
    per = []
    for f in frames:
        lum = 1 - min(1.0, f["luminance"] / 96.0)
        col = 1 - min(1.0, f["colour"] / 160.0)
        struct = max(0.0, (f["structure"] + 0.2) / 1.2)
        busy = 1 - min(1.0, abs(f["busy_ref"] - f["busy_cand"]) / 0.25)
        per.append(0.3 * lum + 0.25 * col + 0.25 * struct + 0.2 * busy)
    look = sum(per) / len(per)
    move = max(0.0, (motion_corr + 0.3) / 1.3)
    return round(100 * (0.7 * look + 0.3 * move), 1)


def _motion_profile(frames: List) -> List[float]:
    return [_review.frame_difference(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]


def compare(reference: str, candidate: str, out_dir: str, step: float = 0.5,
            duration: Optional[float] = None, ff: Optional[str] = None) -> Dict[str, Any]:
    """Sample both films every `step` seconds, measure, draw the sheet
    (reference row over candidate row, times and per-frame metrics
    underneath), write benchmark.json, return the report."""
    from PIL import Image, ImageDraw
    os.makedirs(out_dir, exist_ok=True)
    ff = _review._ffmpeg(ff)
    ref_info = _review.probe(reference, ff)
    cand_info = _review.probe(candidate, ff)
    total = min(ref_info.get("duration", 0.0), cand_info.get("duration", 0.0))
    if duration:
        total = min(total, duration)
    times = [round(i * step, 3) for i in range(int(total / step) + 1) if i * step < total - 0.02]
    scratch = os.path.join(out_dir, "_frames")
    os.makedirs(scratch, exist_ok=True)

    ref_frames, cand_frames, rows = [], [], []
    for t in times:
        r = _review._frame_image(reference, t, ff, scratch, f"ref_{int(t * 1000)}",
                                 int(round(ref_info.get("fps") or 60)))
        c = _review._frame_image(candidate, t, ff, scratch, f"cand_{int(t * 1000)}",
                                 int(round(cand_info.get("fps") or 60)))
        rb = r.crop(band_box(*r.size)).resize(THUMB)
        cb = c.crop(band_box(*c.size)).resize(THUMB)
        ref_frames.append(rb)
        cand_frames.append(cb)
        m = frame_metrics(rb, cb)
        m["time"] = t
        rows.append(m)

    mp_ref, mp_cand = _motion_profile(ref_frames), _motion_profile(cand_frames)
    if len(mp_ref) > 2:
        motion_corr = _correlation(_list_img(mp_ref), _list_img(mp_cand))
    else:
        motion_corr = 0.0
    total_score = score(rows, motion_corr)

    # the sheet: two rows of thumbnails, metrics under each column
    pad, head, foot = 6, 22, 58
    cols = max(1, len(times))
    w = pad + cols * (THUMB[0] + pad)
    h = pad + head + THUMB[1] + pad + THUMB[1] + foot + pad
    sheet = Image.new("RGB", (w, h), (14, 16, 22))
    draw = ImageDraw.Draw(sheet)
    draw.text((pad, pad), f"reference (top) vs Prism (bottom)   score {total_score}   "
                          f"motion corr {motion_corr:.2f}", fill=(235, 240, 250))
    for i, (t, r, c, m) in enumerate(zip(times, ref_frames, cand_frames, rows)):
        x = pad + i * (THUMB[0] + pad)
        y0 = pad + head
        sheet.paste(r, (x, y0))
        sheet.paste(c, (x, y0 + THUMB[1] + pad))
        y = y0 + 2 * THUMB[1] + 2 * pad
        draw.text((x, y), f"{t:.1f}s", fill=(255, 216, 168))
        draw.text((x, y + 13), f"L{m['luminance']:.0f} C{m['colour']:.0f}", fill=(180, 190, 210))
        draw.text((x, y + 26), f"S{m['structure']:+.2f}", fill=(180, 190, 210))
        draw.text((x, y + 39), f"b{m['busy_ref']:.2f}/{m['busy_cand']:.2f}", fill=(180, 190, 210))
    sheet_path = os.path.join(out_dir, "benchmark_sheet.png")
    sheet.save(sheet_path)

    worst = sorted(rows, key=lambda m: (m["luminance"] / 96 + m["colour"] / 160
                                         + (1 - m["structure"]) / 2), reverse=True)[:5]
    report = {
        "reference": reference, "candidate": candidate,
        "reference_info": ref_info, "candidate_info": cand_info,
        "step": step, "compared_seconds": total, "score": total_score,
        "motion_correlation": round(motion_corr, 3),
        "mean": {
            "luminance": round(sum(m["luminance"] for m in rows) / max(1, len(rows)), 2),
            "colour": round(sum(m["colour"] for m in rows) / max(1, len(rows)), 2),
            "structure": round(sum(m["structure"] for m in rows) / max(1, len(rows)), 3),
        },
        "worst_times": [m["time"] for m in worst],
        "frames": rows, "sheet": sheet_path,
    }
    with open(os.path.join(out_dir, "benchmark.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    return report


def _list_img(values: Sequence[float]):
    """A 1-row image so _correlation() can be reused for two profiles."""
    from PIL import Image
    img = Image.new("L", (len(values), 1))
    hi = max(values) or 1.0
    img.putdata([int(min(255, v / hi * 255)) for v in values])
    return img
