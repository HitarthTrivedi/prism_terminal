"""
Prism Motion Graphics — visual review and the export gate
──────────────────────────────────────────────────────────
The settled-frame preflight (inspect.py) proves a scene is not broken
at rest. This module looks at the film as it plays:

- `review_sheet()` renders (or takes) the MP4, pulls the start, midpoint,
  settled and exit frame of every scene and the 17 / 50 / 83 % frame of
  every continuity handoff, lays them out on one labelled contact sheet,
  and runs the checks below — writing `review.json` beside the frames so
  a failed render still leaves actionable diagnostics.
- Checks: text hold time against word count, cold cuts under the cinematic
  profile, text contrast measured on the rendered settled frames, and a
  one-frame pop at any cut (a frame-to-frame jump far larger than the
  motion around it).
- `export_gate()` probes the MP4 with FFmpeg and confirms the requested
  dimensions, frame rate, duration and codec.
- `preview_matches_export()` seeks the same runtime page the Studio shows
  to golden times and compares its screenshot with the exported frame,
  within a pixel tolerance — the proof that what was previewed is what
  was filmed.

Pillow is used for the frame maths (already a Prism dependency); the
browser is only needed for the preview comparison.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import beats as _beats
from . import continuity as _continuity
from . import inspect as _inspect
from .studio import EDITS_KEY, resolved_for, review_points

# Text must hold, settled and readable, for this long: a base plus a
# per-word allowance (about 200 words a minute, with a floor for a single
# word so a one-word title is not "read" in a blink).
HOLD_BASE_S = 0.6
HOLD_PER_WORD_S = 0.28
HOLD_MIN_S = 1.0
# WCAG-style luminance contrast between ink and ground on the rendered
# frame; 3:1 is the large-text floor and a headline is always large.
MIN_CONTRAST_RATIO = 3.0
# A cut is a pop when the frame-to-frame change at the cut exceeds this
# many times the change in the frames around it AND an absolute floor
# (mean absolute pixel difference, 0-255) so a static scene cannot trip
# it with noise.
POP_RATIO = 4.0
POP_FLOOR = 12.0
# Preview/export tolerance: mean absolute pixel difference, 0-255. JPEG
# capture on both sides plus H.264 puts identical frames a few units apart.
PREVIEW_TOLERANCE = 12.0
HANDOFF_FRACTIONS = (0.17, 0.5, 0.83)


# ── static checks ─────────────────────────────────────────────────────────────

def hold_faults(spec: Dict[str, Any]) -> List[str]:
    """Text that is not on screen, settled, long enough to be read. Works on
    a scene-local or resolved spec (times are compared within the scene)."""
    faults: List[str] = []
    for idx, scene in enumerate(spec.get("scenes", []) or []):
        if not isinstance(scene, dict):
            continue
        try:
            dur = float(scene.get("duration", 0) or 0)
            start = float(scene.get("start", 0) or 0)
        except (TypeError, ValueError):
            continue
        for node in _beats._walk(scene):
            if node.get("type") != "text":
                continue
            content = str(node.get("content", "") or "")
            words = len(content.split())
            if not words:
                continue
            need = max(HOLD_MIN_S, HOLD_BASE_S + HOLD_PER_WORD_S * words)
            anim = node.get("animation") if isinstance(node.get("animation"), dict) else {}
            enter, exit_ = anim.get("enter"), anim.get("exit")
            settled = 0.0
            if isinstance(enter, dict):
                settled = (float(enter.get("time", 0) or 0) - start
                           + float(enter.get("duration", 0.6) or 0.6))
            leaves = dur
            if isinstance(exit_, dict) and exit_.get("time") is not None:
                leaves = float(exit_["time"]) - start
            hold = leaves - settled
            if hold + 1e-6 < need:
                faults.append(
                    f'text "{node.get("id", "")}" in scene {idx + 1} ({words} word'
                    f'{"s" if words != 1 else ""}) holds for {max(0.0, hold):.1f}s but '
                    f"needs {need:.1f}s to be read — enter earlier, exit later, or "
                    "give the scene more time")
    return faults


def cold_cut_faults(resolved: Dict[str, Any]) -> List[str]:
    """Under the cinematic profile every cut is a transition; a scene the
    resolver could not overlap (too short) is a cold cut."""
    if resolved.get("_motion_profile") != _continuity.CINEMATIC_PROFILE:
        return []
    faults: List[str] = []
    scenes = [s for s in resolved.get("scenes", []) or [] if isinstance(s, dict)]
    for i in range(1, len(scenes)):
        if not scenes[i].get("_transitionOverlap"):
            faults.append(f"the cut into scene {i + 1} is a cold cut — one of the two "
                          "scenes is too short to overlap; give both at least 0.5s")
    return faults


def frame_times(resolved: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every time the review looks at: four per scene, three per handoff."""
    out: List[Dict[str, Any]] = []
    for i, scene in enumerate(resolved.get("scenes", []) or []):
        pts = review_points(scene)
        for label in ("start", "mid", "settled", "exit"):
            out.append({"time": pts[label], "label": label, "scene": i, "kind": "scene"})
    for bridge in (resolved.get("_continuity_compiled") or {}).get("bridges", []) or []:
        start, end = float(bridge.get("start", 0)), float(bridge.get("end", 0))
        for frac in HANDOFF_FRACTIONS:
            out.append({"time": round(start + (end - start) * frac, 3),
                        "label": f"{int(frac * 100)}%", "scene": int(bridge.get("scene_index", 0)),
                        "kind": "handoff", "key": bridge.get("key", "")})
    return out


# ── frame maths ───────────────────────────────────────────────────────────────

def _luminance(rgb: Tuple[int, int, int]) -> float:
    def chan(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(image) -> float:
    """Ink-versus-ground contrast inside one crop, without knowing which
    pixels are letters: the ground is the median luminance (most of a text
    box is background), the ink is the brightest or darkest one percent,
    whichever stands further from the ground. Letters are sparse — a
    thin face at a small size covers well under five percent of its box —
    so the extremes, not a wide percentile, are what the eye reads."""
    grey = image.convert("L")
    hist = grey.histogram()
    total = sum(hist)
    if not total:
        return 1.0

    def percentile(p: float) -> int:
        target, acc = total * p, 0
        for level, count in enumerate(hist):
            acc += count
            if acc >= target:
                return level
        return 255
    ground = _luminance((percentile(0.5),) * 3)
    bright = _luminance((percentile(0.99),) * 3)
    dark = _luminance((percentile(0.01),) * 3)
    light_ink = (bright + 0.05) / (ground + 0.05)
    dark_ink = (ground + 0.05) / (dark + 0.05)
    return max(light_ink, dark_ink)


def frame_difference(a, b) -> float:
    """Mean absolute pixel difference (0-255) between two same-size frames."""
    from PIL import ImageChops, ImageStat
    if a.size != b.size:
        b = b.resize(a.size)
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    return sum(ImageStat.Stat(diff).mean) / 3.0


def pop_score(frames: Sequence) -> Tuple[float, float]:
    """(largest consecutive difference, median of the others) over a run
    of frames — a pop is a single step far above its neighbours."""
    diffs = [frame_difference(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    if not diffs:
        return 0.0, 0.0
    peak = max(diffs)
    rest = sorted(d for d in diffs if d != peak) or [0.0]
    return peak, rest[len(rest) // 2]


def is_pop(frames: Sequence) -> bool:
    peak, typical = pop_score(frames)
    return peak > POP_FLOOR and peak > POP_RATIO * max(typical, 1.0)


# ── FFmpeg helpers ────────────────────────────────────────────────────────────

def _ffmpeg(ff: Optional[str]) -> str:
    if ff:
        return ff
    from core import ffmpeg
    found = ffmpeg.locate()
    if not found:
        raise RuntimeError("FFmpeg executable not found.")
    return found


def seek_time(time: float, fps: Optional[int]) -> float:
    """The `-ss` that lands on the frame nearest `time`: FFmpeg returns the
    first frame whose timestamp is >= the seek, so ask for a hair before
    that frame's own timestamp (k/fps) and never a hair after it."""
    if not fps:
        return max(0.0, time)
    import math
    frame = max(0, int(round(time * fps)))
    return max(0.0, math.floor(frame / float(fps) * 10000) / 10000 - 0.0001)


def extract_frame(mp4: str, time: float, out_png: str, ff: Optional[str] = None,
                  fps: Optional[int] = None) -> str:
    subprocess.run([_ffmpeg(ff), "-y", "-loglevel", "error", "-ss", f"{seek_time(time, fps):.4f}",
                    "-i", mp4, "-frames:v", "1", out_png], check=True)
    if not os.path.isfile(out_png):
        raise RuntimeError(f"no frame at {time:.3f}s in {mp4} — past the last frame?")
    return out_png


def _clamp_times(frames: List[Dict[str, Any]], duration: float, fps: int) -> List[Dict[str, Any]]:
    """Review times snap to a frame and may not sit past the film's last
    one (a scene's exit point is 0.05s before its end, which at 12 fps is
    past the final frame)."""
    fps = max(1, int(fps))
    last_frame = max(0, int(round(duration * fps)) - 1)
    for fr in frames:
        frame = min(last_frame, max(0, int(round(float(fr["time"]) * fps))))
        fr["time"] = round(frame / float(fps), 4)
    return frames


def _frame_image(mp4: str, time: float, ff: str, scratch: str, tag: str,
                 fps: Optional[int] = None):
    from PIL import Image
    path = os.path.join(scratch, f"_probe_{tag}.png")
    extract_frame(mp4, time, path, ff, fps)
    with Image.open(path) as img:
        return img.convert("RGB").copy()


_PROBE_STREAM = re.compile(r"Stream #\d+:\d+.*?Video: (\w+).*?(\d{2,5})x(\d{2,5}).*?([\d.]+) fps", re.S)
_PROBE_DURATION = re.compile(r"Duration: (\d+):(\d+):([\d.]+)")


def parse_probe(text: str) -> Dict[str, Any]:
    """What `ffmpeg -i` says about a file: codec, size, fps, duration."""
    out: Dict[str, Any] = {}
    m = _PROBE_DURATION.search(text)
    if m:
        h, mnt, s = m.groups()
        out["duration"] = round(int(h) * 3600 + int(mnt) * 60 + float(s), 3)
    m = _PROBE_STREAM.search(text)
    if m:
        codec, w, h, fps = m.groups()
        out.update({"codec": codec, "width": int(w), "height": int(h), "fps": float(fps)})
    return out


def probe(mp4: str, ff: Optional[str] = None) -> Dict[str, Any]:
    proc = subprocess.run([_ffmpeg(ff), "-hide_banner", "-i", mp4], capture_output=True,
                          text=True, check=False)
    return parse_probe(proc.stderr or "")


def export_gate(resolved: Dict[str, Any], mp4: str, ff: Optional[str] = None,
                fps: Optional[int] = None) -> List[str]:
    """The technical acceptance criteria: the file is what was asked for."""
    project = resolved.get("project") or {}
    want_w, want_h = int(project.get("width", 1080)), int(project.get("height", 1920))
    want_fps = float(fps or project.get("fps", 30))
    want_dur = float(project.get("duration", 0) or 0)
    if not os.path.isfile(mp4):
        return [f"no file at {mp4}"]
    got = probe(mp4, ff)
    faults: List[str] = []
    if not got:
        return [f"FFmpeg could not read {mp4}"]
    if (got.get("width"), got.get("height")) != (want_w, want_h):
        faults.append(f"size is {got.get('width')}x{got.get('height')}, not {want_w}x{want_h}")
    if got.get("fps") is None or abs(got["fps"] - want_fps) > 0.02:
        faults.append(f"frame rate is {got.get('fps')} fps, not {want_fps:g}")
    if got.get("duration") is None or abs(got["duration"] - want_dur) > max(0.15, 1.5 / want_fps):
        faults.append(f"duration is {got.get('duration')}s, not {want_dur:g}s")
    if got.get("codec") not in ("h264", "hevc"):
        faults.append(f"codec is {got.get('codec')}, not H.264")
    return faults


# ── frame checks against the film ────────────────────────────────────────────

def _text_ids(resolved_scene: Dict[str, Any]) -> List[str]:
    return [str(n.get("id", "")) for n in _beats._walk(resolved_scene)
            if n.get("type") == "text" and n.get("visible", True) and n.get("id")]


def measured_text_boxes(resolved: Dict[str, Any], wanted: Dict[float, List[str]],
                        ) -> Dict[float, Dict[str, Tuple[int, int, int, int]]]:
    """Where each text node's box actually is on the frame at each time —
    read off the runtime page (camera, depth parallax and every tween
    applied) rather than computed from authored coordinates. Needs
    Playwright's Chromium; the caller decides what to do without it."""
    import pathlib as _pl
    from playwright.sync_api import sync_playwright
    from .. import browser as _browser

    index = _pl.Path(os.path.dirname(os.path.abspath(__file__))) / "runtime" / "index.html"
    project = resolved["project"]
    width, height, fps = int(project["width"]), int(project["height"]), int(project["fps"])
    out: Dict[float, Dict[str, Tuple[int, int, int, int]]] = {}
    js = """(ids) => {
      const out = {};
      for (const id of ids) {
        const host = document.querySelector('#stage [data-motion-id="' + CSS.escape(id) + '"]');
        if (!host || !host.firstElementChild) continue;
        let el = host, hidden = false;
        while (el && el !== document.body) {
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || parseFloat(cs.opacity) < 0.05) { hidden = true; break; }
          el = el.parentElement;
        }
        if (hidden) continue;
        const r = host.firstElementChild.getBoundingClientRect();
        if (r.width < 4 || r.height < 4) continue;
        out[id] = [r.left, r.top, r.right, r.bottom];
      }
      return out;
    }"""
    with sync_playwright() as pw:
        browser = _browser.launch_chromium(pw, args=["--no-sandbox", "--disable-gpu"])
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(index.as_uri(), wait_until="load")
        page.wait_for_function("window.__ready === true", timeout=15000)
        page.evaluate("spec => window.__loadSpec(spec)", resolved)
        for t, ids in wanted.items():
            page.evaluate("f => window.__seek(f)", int(round(t * fps)))
            page.wait_for_timeout(40)
            got = page.evaluate(js, ids)
            out[t] = {k: (max(0, int(v[0])), max(0, int(v[1])),
                          min(width, int(v[2])), min(height, int(v[3]))) for k, v in got.items()}
        browser.close()
    return out


def contrast_faults(frame, boxes: Dict[str, Tuple[int, int, int, int]], scene_no: int,
                    canvas_w: int, canvas_h: int) -> List[str]:
    """Text whose letters do not stand off their ground on the rendered
    settled frame. `boxes` are frame-space boxes in canvas coordinates
    (see measured_text_boxes); the frame may be smaller than the canvas."""
    faults: List[str] = []
    fw, fh = frame.size
    sx, sy = fw / float(canvas_w), fh / float(canvas_h)
    for node_id, (left, top, right, bottom) in boxes.items():
        box = (max(0, int(left * sx)), max(0, int(top * sy)),
               min(fw, int(right * sx)), min(fh, int(bottom * sy)))
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            continue
        ratio = contrast_ratio(frame.crop(box))
        if ratio < MIN_CONTRAST_RATIO:
            faults.append(
                f'text "{node_id}" in scene {scene_no + 1} measures '
                f"{ratio:.1f}:1 contrast on the settled frame (needs "
                f"{MIN_CONTRAST_RATIO:g}:1) — darken the panel's contrast_guard, "
                "move the text off the light, or change the ink")
    return faults


def pop_faults(mp4: str, resolved: Dict[str, Any], fps: int, ff: str, scratch: str) -> List[str]:
    """A single-frame jump at any cut, judged against the motion around it."""
    faults: List[str] = []
    scenes = [s for s in resolved.get("scenes", []) or [] if isinstance(s, dict)]
    step = 1.0 / float(fps)
    for i in range(1, len(scenes)):
        cut = float(scenes[i].get("start", 0) or 0)
        window = [cut + k * step for k in range(-3, 4)]
        frames = [_frame_image(mp4, max(0.0, t), ff, scratch, f"pop{i}_{k}", fps)
                  for k, t in enumerate(window)]
        if is_pop(frames):
            peak, typical = pop_score(frames)
            faults.append(
                f"the cut into scene {i + 1} pops: one frame changes by {peak:.0f} "
                f"against {typical:.0f} around it — the handoff is not continuous")
    return faults


# ── the sheet ─────────────────────────────────────────────────────────────────

def _sheet(frames: List[Dict[str, Any]], out_png: str, thumb_w: int = 200) -> str:
    from PIL import Image, ImageDraw
    rows: Dict[Tuple[str, int, str], List[Dict[str, Any]]] = {}
    for fr in frames:
        rows.setdefault((fr["kind"], fr["scene"], fr.get("key", "")), []).append(fr)
    ordered = sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0] != "scene", kv[0][2]))
    first = Image.open(frames[0]["path"])
    ratio = first.size[1] / float(first.size[0])
    thumb_h = int(thumb_w * ratio)
    cols = max(len(v) for _, v in ordered)
    pad, head = 12, 28
    width = pad + cols * (thumb_w + pad)
    height = pad + len(ordered) * (thumb_h + head + pad)
    sheet = Image.new("RGB", (width, height), (16, 20, 25))
    draw = ImageDraw.Draw(sheet)
    y = pad
    for (kind, scene_no, key), items in ordered:
        # Pillow's built-in font has no dash or curly quote; keep to ASCII.
        title = (f"Scene {scene_no + 1}" if kind == "scene"
                 else f"Handoff into scene {scene_no + 1} ({key})")
        draw.text((pad, y), title, fill=(235, 240, 250))
        for c, fr in enumerate(items):
            x = pad + c * (thumb_w + pad)
            with Image.open(fr["path"]) as img:
                thumb = img.convert("RGB").resize((thumb_w, thumb_h))
            sheet.paste(thumb, (x, y + head))
            draw.text((x + 4, y + head + thumb_h - 16), f"{fr['label']} · {fr['time']:.2f}s",
                      fill=(255, 216, 168))
        y += thumb_h + head + pad
    sheet.save(out_png)
    return out_png


def review_sheet(spec: Dict[str, Any], out_dir: str, mp4: Optional[str] = None,
                 ff: Optional[str] = None, on_progress=None) -> Dict[str, Any]:
    """Render (unless `mp4` is given), pull every review frame, lay out the
    sheet, run every check, and write review.json. Never raises for a
    failed check — the faults are the deliverable."""
    os.makedirs(out_dir, exist_ok=True)
    resolved = resolved_for(spec, spec.get(EDITS_KEY))
    project = resolved["project"]
    fps = int(project.get("fps", 30))
    ff = _ffmpeg(ff)
    if mp4 is None:
        from .render import render
        mp4 = render(spec, os.path.join(out_dir, "review.mp4"), on_progress=on_progress)

    frames = _clamp_times(frame_times(resolved), float(project.get("duration", 0) or 0), fps)
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    for fr in frames:
        name = (f"scene{fr['scene'] + 1}_{fr['label']}.png" if fr["kind"] == "scene"
                else f"handoff{fr['scene'] + 1}_{fr['label'].rstrip('%')}.png")
        fr["path"] = extract_frame(mp4, fr["time"], os.path.join(frames_dir, name), ff, fps)
    sheet = _sheet(frames, os.path.join(out_dir, "review_sheet.png"))

    faults: List[str] = []
    warnings: List[str] = []
    # inspect() reads times as scene-local (that is how a scene is written
    # and checked during generation); the resolved spec carries global
    # times, so the layout pass runs on the scene-local spec instead.
    from .schema import validate_motion_spec as _validate
    from .studio import apply_edits as _apply
    local = _validate(_apply(spec, spec.get(EDITS_KEY)))
    for i, scene in enumerate(local["scenes"]):
        faults.extend(_inspect.inspect({"project": project, "scenes": [scene]}))
    faults.extend(hold_faults(resolved))
    faults.extend(cold_cut_faults(resolved))
    compiled = resolved.get("_continuity_compiled") or {}
    faults.extend(e["message"] for e in compiled.get("errors", []))
    warnings.extend(w["message"] for w in compiled.get("warnings", []))
    from PIL import Image
    canvas_w, canvas_h = int(project["width"]), int(project["height"])
    settled = [fr for fr in frames if fr["kind"] == "scene" and fr["label"] == "settled"]
    wanted = {fr["time"]: _text_ids(resolved["scenes"][fr["scene"]]) for fr in settled}
    try:
        boxes = measured_text_boxes(resolved, wanted)
    except Exception as e:                                # noqa: BLE001
        boxes = None
        warnings.append(f"contrast not measured — the runtime page could not be opened ({e})")
    if boxes:
        for fr in settled:
            with Image.open(fr["path"]) as img:
                faults.extend(contrast_faults(img.convert("RGB"), boxes.get(fr["time"], {}),
                                              fr["scene"], canvas_w, canvas_h))
    faults.extend(pop_faults(mp4, resolved, fps, ff, frames_dir))
    faults.extend("export: " + f for f in export_gate(resolved, mp4, ff, fps))
    grid = _beats.timing_grid(resolved)
    off = [m for m in grid["markers"] if m["kind"] == "cut" and not m["on_beat"]]
    for m in off:
        warnings.append(f"{m['label']} at {m['time']:.2f}s sits {abs(m['drift']) * 1000:.0f}ms "
                        f"off the {grid['bpm']:g} bpm grid")

    report = {
        "mp4": mp4, "sheet": sheet, "frames": frames, "faults": faults, "warnings": warnings,
        "beats": {k: grid[k] for k in ("bpm", "offset", "source", "on_beat", "off_beat")},
        "project": {"width": canvas_w, "height": canvas_h, "fps": fps,
                    "duration": project.get("duration")},
    }
    with open(os.path.join(out_dir, "review.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    return report


# ── preview vs export ─────────────────────────────────────────────────────────

def preview_matches_export(resolved: Dict[str, Any], mp4: str, times: Sequence[float],
                           tolerance: float = PREVIEW_TOLERANCE, ff: Optional[str] = None,
                           scratch: Optional[str] = None) -> List[str]:
    """Seek the runtime page (what the Studio previews) to each time and
    compare with the exported frame. Needs Playwright's Chromium."""
    import pathlib
    import tempfile
    from playwright.sync_api import sync_playwright
    from PIL import Image
    from io import BytesIO
    from .. import browser as _browser

    ff = _ffmpeg(ff)
    scratch = scratch or tempfile.mkdtemp(prefix="prism-review-")
    index = pathlib.Path(os.path.dirname(os.path.abspath(__file__))) / "runtime" / "index.html"
    project = resolved["project"]
    width, height, fps = int(project["width"]), int(project["height"]), int(project["fps"])
    faults: List[str] = []
    with sync_playwright() as pw:
        browser = _browser.launch_chromium(pw, args=["--no-sandbox", "--disable-gpu"])
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(index.as_uri(), wait_until="load")
        page.wait_for_function("window.__ready === true", timeout=15000)
        page.evaluate("spec => window.__loadSpec(spec)", resolved)
        for t in times:
            page.evaluate("f => window.__seek(f)", int(round(t * fps)))
            page.wait_for_timeout(60)
            shot = Image.open(BytesIO(page.screenshot(type="jpeg", quality=92))).convert("RGB")
            exported = _frame_image(mp4, t, ff, scratch, f"pv_{int(t * 1000)}", fps)
            diff = frame_difference(shot, exported)
            if diff > tolerance:
                faults.append(f"preview and export differ at {t:.2f}s by {diff:.1f} "
                              f"(tolerance {tolerance:g})")
        browser.close()
    return faults
