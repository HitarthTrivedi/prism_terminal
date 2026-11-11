"""
Prism Motion Graphics — the film's rhythm, measured
────────────────────────────────────────────────────
A film that never rests reads as noise and one that never moves reads as a
slide. The polished reference this was compared against (11-12 Nov 2026)
holds still for about a third of its frames, in a few long stretches, and
spends its motion in short bursts; Prism's model-written films moved
continuously (12 % still frames, no hold over 0.7 s) and its Reel never moved.

This renders the resolved spec at low resolution, 10 frames a second,
through the same runtime that will draw it, and measures what a viewer feels:
the share of still frames, the longest holds, how much of the motion falls in
the busiest tenth of the seconds, and the mean brightness. Deterministic, no
model call. `faults()` turns the numbers into sentences a writer can act on.

Method and thresholds are those used on the reference at 10 fps and 192 px
wide: a frame is "still" when it differs from the last by under 0.3 grey
levels on average.
"""
from __future__ import annotations

import os
import pathlib
from io import BytesIO
from typing import Any

STILL = 0.3          # mean grey-level change below which a frame is still
SAMPLE_FPS = 10
ANALYSIS_WIDTH = 192


def probe(spec: dict[str, Any], fps: int = SAMPLE_FPS) -> dict[str, Any] | None:
    """The rhythm profile of `spec`, or None when there is no browser."""
    from .render import _playwright_available
    if not _playwright_available():
        return None
    import numpy as np
    from PIL import Image
    from .resolver import resolve_motion_spec
    from .schema import validate_motion_spec
    resolved = resolve_motion_spec(validate_motion_spec(spec))
    project = resolved["project"]
    width, height = int(project["width"]), int(project["height"])
    src_fps = int(project.get("fps", 30) or 30)
    duration = float(project.get("duration") or sum(float(s.get("duration", 0) or 0) for s in resolved["scenes"]))
    scale = min(1.0, ANALYSIS_WIDTH / width)

    from playwright.sync_api import sync_playwright
    from .. import browser as _browser
    index = pathlib.Path(os.path.dirname(__file__), "runtime", "index.html")
    frames = []
    with sync_playwright() as pw:
        chromium = _browser.launch_chromium(
            pw, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        try:
            page = chromium.new_page(viewport={"width": width, "height": height}, device_scale_factor=scale)
            page.goto(index.as_uri(), wait_until="domcontentloaded")
            page.wait_for_function("typeof window.__loadSpec === 'function'", timeout=15_000)
            page.evaluate("s => window.__loadSpec(s)", resolved)
            try:
                page.wait_for_function("document.fonts.ready.then(() => true)", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            n = int(duration * fps)
            for i in range(n):
                page.evaluate(f"window.__seek({int(round(i / fps * src_fps))})")
                im = Image.open(BytesIO(page.screenshot(type="png"))).convert("L")
                frames.append(np.asarray(im, dtype=np.float32))
        finally:
            chromium.close()
    return profile_from_frames(frames, fps)


def profile_from_frames(frames, fps: int = SAMPLE_FPS) -> dict[str, Any]:
    """The rhythm profile of a list of grayscale frames (2-D float arrays)
    sampled at `fps`. The one place the numbers are made, so a film measured from
    its spec (probe) and one measured from its video file (probe_video) are
    measured identically."""
    import numpy as np
    if len(frames) < 3:
        return {"seconds": 0.0, "static_pct": 0.0, "per_second": [], "holds": [], "top10_share": 0.0,
                "luminance": [0.0, 0.0], "mean_motion": 0.0, "longest_hold": 0.0, "holds_ge_1s": 0}
    diffs = np.abs(np.diff(np.stack(frames), axis=0)).mean(axis=(1, 2))
    per_second = [float(diffs[i * fps:(i + 1) * fps].mean()) for i in range(len(diffs) // fps)]
    holds, run = [], 0
    for d in diffs:
        if d < STILL:
            run += 1
        else:
            if run:
                holds.append(run / fps)
            run = 0
    if run:
        holds.append(run / fps)
    ordered = sorted(per_second, reverse=True)
    top = max(1, len(ordered) // 10)
    total = sum(ordered) or 1.0
    lum = [float(f.mean()) for f in frames]
    return {
        "seconds": round(len(frames) / fps, 2),
        "static_pct": round(float((diffs < STILL).mean() * 100), 1),
        "mean_motion": round(float(diffs.mean()), 2),
        "per_second": [round(v, 2) for v in per_second],
        "holds": [round(h, 1) for h in holds],
        "longest_hold": round(max(holds), 1) if holds else 0.0,
        "holds_ge_1s": sum(1 for h in holds if h >= 1.0),
        "top10_share": round(sum(ordered[:top]) / total * 100, 0),
        "luminance": [round(min(lum), 0), round(max(lum), 0)],
    }


def probe_video(path: str, fps: int = SAMPLE_FPS) -> dict[str, Any] | None:
    """The rhythm profile of a finished video FILE — a Motion film, a Studio reel,
    a Reel, a reference — with FFmpeg only, no browser. Same maths, same
    thresholds. None when FFmpeg cannot read it."""
    import json as _json
    import subprocess
    import numpy as np
    from .. import ffmpeg
    ff = ffmpeg.locate()
    if not ff or not os.path.exists(path):
        return None
    ffprobe = os.path.join(os.path.dirname(ff), "ffprobe")
    try:
        j = _json.loads(subprocess.run(
            [ffprobe if os.path.exists(ffprobe) else "ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", path],
            capture_output=True, text=True).stdout)["streams"][0]
        w0, h0 = int(j["width"]), int(j["height"])
    except Exception:  # noqa: BLE001
        return None
    w = ANALYSIS_WIDTH
    h = max(2, round(w * h0 / w0) // 2 * 2)
    raw = subprocess.run([ff, "-v", "error", "-i", path, "-vf", f"fps={fps},scale={w}:{h},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    n = len(raw) // (w * h)
    if n < 3:
        return None
    arr = np.frombuffer(raw[:n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
    return profile_from_frames(list(arr), fps)


def faults(profile: dict[str, Any] | None, static_range: tuple[float, float] = (15.0, 45.0)) -> list[str]:
    """What is wrong with the rhythm, as sentences. [] when it is fine or when
    there is no profile. Ranges are wide on purpose: the reference sits at
    28-33 % still frames; anything from 15 to 45 % is a film that breathes."""
    if not profile or profile.get("seconds", 0) < 4:
        return []
    out: list[str] = []
    lo, hi = static_range
    still = profile["static_pct"]
    if still < lo:
        out.append(f"The film never rests: {still:.0f}% of frames are still (it should be about "
                   f"{lo:.0f}-{hi:.0f}%) and its longest hold is {profile['longest_hold']:g}s. Give "
                   "one or two scenes a real hold of 1.5s or more — nothing drifting, nothing "
                   "entering — right after the line that must be read.")
    elif still > hi:
        # the longest run of consecutive quiet seconds, so the writer knows WHERE
        best, run_start, best_span = 0, None, None
        for i, v in enumerate(list(profile["per_second"]) + [99.0]):
            if v < 0.5 and run_start is None:
                run_start = i
            elif v >= 0.5 and run_start is not None:
                if i - run_start > best:
                    best, best_span = i - run_start, (run_start, i)
                run_start = None
        span = f" (the quiet stretch is seconds {best_span[0]}-{best_span[1]})" if best_span else ""
        out.append(f"The film is mostly still: {still:.0f}% of frames do not change (it should be "
                   f"about {lo:.0f}-{hi:.0f}%){span}. Put a camera move, a cursor, a typed line or "
                   "an entering element in the quiet stretch.")
    if profile["holds_ge_1s"] == 0 and still >= lo:
        out.append("There is no hold of a second or more: nothing is ever given time to be read.")
    if profile["top10_share"] < 20 and still >= lo:
        out.append(f"The motion is spread evenly (only {profile['top10_share']:.0f}% of it falls in "
                   "the busiest tenth of the seconds; a film with a payoff has 30-45%). Hold, then "
                   "spend one decisive change.")
    return out
