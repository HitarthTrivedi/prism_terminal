"""Local client-footage editor used by Prism Reel / Studio.

This deliberately starts as a dependable edit lane, not a pretend NLE: it
normalises phone footage to a vertical master, cross-fades clips, burns timed
captions, and can mix a separately generated voice-over. FFmpeg honours MOV
rotation metadata while decoding, which is essential for iPhone footage
recorded sideways at 4K.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile

from . import ffmpeg, reel


VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm")
AUDIO_SUFFIXES = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
TRANSITION_SECONDS = 0.22
DEFAULT_TRANSITION_SECONDS = 0.22
DEFAULT_SHOT_SECONDS = 3.4
MAX_SHOT_SECONDS = 4.6
MIN_SHOT_SECONDS = 1.8

# Client footage needs editing that feels intentional, not a slideshow of
# effects. Keep the transition vocabulary dynamic and cinematic so the story remains
# in the camera action and captions.
SUPPORTED_TRANSITIONS = {
    "fade", "smoothleft", "smoothright", "zoomin", "wipeleft", "wiperight",
    "hblur", "dissolve", "fadeblack", "fadefast", "circleopen", "circlecrop",
    "slideleft", "slideright", "slideup", "slidedown",
}
TRANSITIONS_ROTATION = [
    "smoothleft",
    "zoomin",
    "wipeleft",
    "hblur",
    "dissolve",
]


def is_video(path: str) -> bool:
    return str(path).lower().endswith(VIDEO_SUFFIXES)


def _seconds(value, default: float = 0.0) -> float:
    """Read a model-written scene duration without making the edit brittle.

    Writers commonly emit ``"0-4"`` or ``"0–4 seconds"`` for a scene's
    timeline even when asked for a number.  That means a four-second window,
    not an exception that throws away the client's render.  Plain numbers and
    ``MM:SS`` values remain supported; malformed values use the caller's
    intentional default.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, float(value))
    text = " ".join(str(value or "").strip().lower().split())
    if not text:
        return default
    try:
        return max(0.0, float(text))
    except (TypeError, ValueError):
        pass
    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?", text):
        try:
            units = [float(unit) for unit in text.split(":")]
            return units[-1] + 60 * units[-2] + (3600 * units[-3]
                                                   if len(units) == 3 else 0)
        except ValueError:
            return default
    values = [float(number) for number in re.findall(r"\d+(?:\.\d+)?", text)]
    if not values:
        return default
    if len(values) >= 2 and re.search(r"\d\s*(?:-|–|—|to)\s*\d", text):
        # Timeline bounds, e.g. 3–5, describe their span rather than a
        # five-second hold.  Fall back to the final number if reversed.
        return max(0.0, values[-1] - values[0]) or values[-1]
    return values[0]


def probe(path: str) -> dict:
    """Return only the duration needed to construct a deterministic edit."""
    exe = reel.ffmpeg_path()
    cmd = [exe, "-v", "error", "-show_entries",
           "format=duration:format_tags=creation_time",
           "-of", "json", "-i", path]
    # ffprobe is not bundled separately on every platform. ffmpeg itself
    # cannot emit this tiny JSON report, so use the system ffprobe when it is
    # present and make the fallback duration conservative.
    import shutil
    probe_exe = shutil.which("ffprobe")
    if probe_exe:
        cmd[0] = probe_exe
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT,
                                          text=True, timeout=20)
            fmt = json.loads(out).get("format") or {}
            duration = float(fmt.get("duration") or 0)
            if duration > 0:
                return {"path": path, "duration": duration,
                        "created": (fmt.get("tags") or {}).get(
                            "creation_time", "")}
        except Exception:
            pass
    return {"path": path, "duration": 8.0, "created": ""}


def edit_plan(paths: list[str], audio_path: str = "",
              captions: list[dict] | None = None,
              transition_seconds: float = DEFAULT_TRANSITION_SECONDS) -> list[dict]:
    """Choose an ordered, balanced select from each phone recording.

    Attachment pickers often return filename order, not filming order. iPhone
    MOV creation timestamps preserve the actual shoot, which gives a natural
    setup → action → result sequence. Long takes are selects, not permission
    for one angle to occupy half the finished reel.

    When scene captions or voiceover timings are provided, cuts dynamically align
    with the scene pacing and audio duration so speech is never cut short.
    """
    probed = []
    for index, path in enumerate(paths):
        item = probe(path)
        item["index"] = index
        probed.append(item)
    if probed and all(item.get("created") for item in probed):
        probed.sort(key=lambda item: (item["created"], item["index"]))

    if not probed:
        return []

    voice_seconds = 0.0
    if audio_path and os.path.isfile(audio_path):
        voice_seconds = float(probe(audio_path).get("duration") or 0)

    clean_captions = [c for c in (captions or []) if isinstance(c, dict) and c.get("seconds")]
    planned_caption_seconds = sum(_seconds(c.get("seconds"), 0.0)
                                  for c in clean_captions)
    target_total = voice_seconds if voice_seconds > 0 else planned_caption_seconds

    # If scenes or target duration require more cuts than unique clips available,
    # expand the shot list by cycling source clips so footage plays continuously.
    needed_shots = len(probed)
    if target_total > 0:
        max_clip_dur = max(float(item.get("duration") or 1.0) for item in probed)
        # Determine number of shots so each shot has comfortable pacing (~3.0-4.5s)
        shot_cadence = min(4.2, max(MIN_SHOT_SECONDS, max_clip_dur))
        calc_shots = int(math.ceil((target_total + transition_seconds * max(0, len(probed) - 1)) / shot_cadence))
        needed_shots = max(needed_shots, calc_shots)
    if clean_captions:
        needed_shots = max(needed_shots, len(clean_captions))

    if needed_shots > len(probed):
        extended = [dict(probed[i % len(probed)]) for i in range(needed_shots)]
    else:
        extended = [dict(item) for item in probed]

    if target_total > 0:
        desired = ((target_total + transition_seconds * max(0, len(extended) - 1))
                   / len(extended))
        desired = max(MIN_SHOT_SECONDS, desired)
    else:
        desired = DEFAULT_SHOT_SECONDS
        desired = min(MAX_SHOT_SECONDS, max(2.2, desired))

    has_scene_timings = bool(clean_captions and len(clean_captions) == len(extended))

    # Track usage offsets for clips used multiple times so they reveal different action
    offsets: dict[str, float] = {}

    for idx, item in enumerate(extended):
        source_seconds = max(1.0, float(item.get("duration") or 1.0))
        if has_scene_timings:
            scene_sec = _seconds(clean_captions[idx].get("seconds"), desired)
            if idx < len(extended) - 1:
                scene_sec += transition_seconds
            shot_desired = max(MIN_SHOT_SECONDS, scene_sec)
        else:
            shot_desired = desired

        selected = min(source_seconds, shot_desired)
        spare = max(0.0, source_seconds - selected)
        # If clip is reused, step into next segment of the footage; on first usage,
        # clear the camera settling moment on long takes.
        p = item.get("path") or str(idx)
        if p in offsets:
            curr_offset = offsets[p]
            if curr_offset + selected <= source_seconds:
                start = curr_offset
                offsets[p] = curr_offset + max(0.8, selected * 0.65)
            else:
                start = 0.0
                offsets[p] = selected * 0.5
        else:
            start = min(spare * 0.35, max(0.0, spare - 0.35))
            offsets[p] = start + max(0.8, selected * 0.65)

        item["start"] = round(start, 3)
        item["selected"] = round(selected, 3)
    return extended


def storyboard_sheet(paths: list[str]) -> str:
    """Make a labelled, low-resolution visual index for the script writer.

    The full client videos remain local.  Each labelled shot contains an
    opening and later-action frame, so the writer can see what changes inside
    the take rather than inventing a disconnected generic story from one
    freeze-frame.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    plan = edit_plan([os.path.abspath(path) for path in paths])
    if not plan:
        return ""
    thumbs = []
    try:
        for index, item in enumerate(plan, 1):
            fd, frame_path = tempfile.mkstemp(
                prefix=f"prism-shot-{index}-", suffix=".jpg")
            os.close(fd)
            # One frame shows the setup; the later frame gives the writer a
            # reliable cue for the actual action/result of this clip.
            start = float(item["start"])
            selected = float(item["selected"])
            later_at = start + min(max(0.45, selected * 0.72),
                                   max(0.45, selected - 0.12))
            later_path = frame_path[:-4] + "-later.jpg"

            def extract(at: float, target: str) -> bool:
                command = [reel.ffmpeg_path(), "-y", "-hide_banner", "-loglevel",
                           "error", "-ss", f"{at:.3f}", "-i", item["path"],
                           "-frames:v", "1", "-vf",
                           "scale=360:640:force_original_aspect_ratio=increase,"
                           "crop=360:640", "-q:v", "3", target]
                result = subprocess.run(command, capture_output=True, text=True,
                                        timeout=45)
                return not result.returncode and os.path.isfile(target)

            if not extract(start + min(0.18, selected * 0.1), frame_path) or not extract(later_at, later_path):
                try:
                    os.unlink(frame_path)
                except OSError:
                    pass
                try:
                    os.unlink(later_path)
                except OSError:
                    pass
                continue
            thumbs.append((index, item, frame_path, later_path))
        if not thumbs:
            return ""

        columns, cell_w, cell_h = 3, 360, 640
        rows = (len(thumbs) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#111111")
        try:
            font = ImageFont.truetype(_font_path(), 30)
            meta_font = ImageFont.truetype(_font_path(), 20)
        except OSError:
            font = meta_font = ImageFont.load_default()
        for slot, (number, item, frame_path, later_path) in enumerate(thumbs):
            with Image.open(frame_path) as source:
                opening = ImageOps.fit(source.convert("RGB"), (174, 560),
                                       method=Image.Resampling.LANCZOS)
            with Image.open(later_path) as source:
                later = ImageOps.fit(source.convert("RGB"), (174, 560),
                                     method=Image.Resampling.LANCZOS)
            x, y = (slot % columns) * cell_w, (slot // columns) * cell_h
            sheet.paste(opening, (x, y + 80))
            sheet.paste(later, (x + 186, y + 80))
            draw = ImageDraw.Draw(sheet, "RGBA")
            draw.rectangle((x, y, x + cell_w, y + 80), fill=(10, 14, 19, 255))
            draw.rounded_rectangle((x + 18, y + 16, x + 176, y + 64),
                                   radius=14, fill=(0, 0, 0, 178))
            draw.text((x + 32, y + 23), f"CLIP {number}", font=font,
                      fill="white")
            draw.text((x + 20, y + 91), "OPEN", font=meta_font, fill="white")
            draw.text((x + 205, y + 91), "ACTION", font=meta_font, fill="white")
            name = os.path.basename(item["path"])
            draw.rectangle((x, y + cell_h - 48, x + cell_w, y + cell_h),
                           fill=(0, 0, 0, 145))
            draw.text((x + 18, y + cell_h - 38),
                      f"{name[:22]}  ·  {item['selected']:.1f}s",
                      font=meta_font, fill="white")
        fd, out = tempfile.mkstemp(prefix="prism-footage-storyboard-",
                                   suffix=".jpg")
        os.close(fd)
        sheet.save(out, quality=88, optimize=True)
        return out
    finally:
        for _number, _item, frame_path, later_path in thumbs:
            for path in (frame_path, later_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass


def is_valid_audio(audio_path: str) -> bool:
    """True if audio_path exists, is not empty, is not an HTML error page,
    and carries valid audio headers/streams."""
    try:
        if not audio_path or not os.path.isfile(audio_path):
            return False
        if os.path.getsize(audio_path) < 128:
            return False
        with open(audio_path, "rb") as f:
            head = f.read(512)
        if head.lstrip().startswith((b"<!DOCTYPE", b"<html", b"<?xml", b"<head", b"<body")):
            return False
        if head.startswith((b"ID3", b"RIFF", b"OggS", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")) or b"ftyp" in head[:16]:
            return True
        import shutil
        probe_exe = shutil.which("ffprobe")
        if probe_exe:
            cmd = [probe_exe, "-v", "error", "-show_entries", "stream=codec_type",
                   "-of", "csv=p=0", audio_path]
            out = subprocess.check_output(cmd, text=True, timeout=10)
            return "audio" in out
        return True
    except Exception:
        return False


def mix_audio(video_path: str, audio_path: str) -> str:
    """Replace a local render's soundtrack with a finished voice track.

    The video stream is copied, not re-rendered, so adding ElevenLabs after a
    multi-minute Studio film takes seconds and cannot reduce picture quality.
    A temporary sibling is atomically moved over the silent working render
    only after FFmpeg succeeds.
    """
    video_path = os.path.abspath(video_path)
    audio_path = os.path.abspath(audio_path)
    if not os.path.isfile(video_path):
        raise FileNotFoundError(video_path)
    if not (audio_path.lower().endswith(AUDIO_SUFFIXES)
            and os.path.isfile(audio_path)):
        raise ValueError("The generated voice-over is not a supported audio file.")
    if not is_valid_audio(audio_path):
        raise ValueError(f"The audio file {os.path.basename(audio_path)} is invalid or corrupt (unreadable audio header/packets).")
    video_dur = float(probe(video_path).get("duration") or 0)
    audio_dur = float(probe(audio_path).get("duration") or 0)
    if video_dur <= 0 and audio_dur <= 0:
        raise RuntimeError("Could not measure the media for audio mixing.")
    total_dur = max(video_dur, audio_dur)
    folder = os.path.dirname(video_path)
    fd, temp_path = tempfile.mkstemp(prefix="prism-audio-", suffix=".mp4",
                                     dir=folder)
    os.close(fd)
    fade_out_st = max(0.0, total_dur - 0.4)
    try:
        if audio_dur > video_dur + 0.1:
            # When speech is longer than video, clone-pad the final frame so the
            # whole narration is preserved and heard without truncation.
            cmd = [reel.ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
                   "-i", video_path, "-i", audio_path,
                   "-filter_complex",
                   "[0:v]tpad=stop_mode=clone:stop=-1[v];"
                   f"[1:a]loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.1,afade=t=out:st={fade_out_st:.3f}:d=0.4[a]",
                   "-map", "[v]", "-map", "[a]",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                   "-c:a", "aac", "-b:a", "192k",
                   "-t", f"{total_dur:.3f}", "-movflags", "+faststart", temp_path]
        else:
            # Video is longer or equal: copy video stream directly for instant mixing
            cmd = [reel.ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
                   "-i", video_path, "-i", audio_path,
                   "-map", "0:v:0", "-map", "1:a:0", "-map_metadata", "-1", "-c:v", "copy",
                   "-c:a", "aac", "-b:a", "192k",
                   "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.1,afade=t=out:st={fade_out_st:.3f}:d=0.4",
                   "-t", f"{total_dur:.3f}", "-movflags", "+faststart", temp_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or
                               "FFmpeg could not add the generated voice-over.")
        os.replace(temp_path, video_path)
        return video_path
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _has_audio_stream(path: str) -> bool:
    """Check whether a media file has a valid audio stream."""
    if not (path and os.path.isfile(path)):
        return False
    try:
        exe = reel.ffmpeg_path()
        out = subprocess.run([exe, "-hide_banner", "-i", path],
                             capture_output=True, text=True, timeout=10)
        return "Audio:" in out.stderr
    except Exception:
        return False


def _font_path(font_path: str = "") -> str:
    if font_path and os.path.isfile(font_path):
        return font_path
    bundled = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "assets", "fonts",
        "Barlow-Bold.ttf"))
    return bundled if os.path.isfile(bundled) else ""


def _font_condensed_path() -> str:
    bundled = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "assets", "fonts",
        "BarlowCondensed-SemiBold.ttf"))
    return bundled if os.path.isfile(bundled) else _font_path()


def _font_serif_bold_path() -> str:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSerifDisplay-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return _font_path()


def _font_serif_italic_path() -> str:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSerifDisplay-Italic.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerif-Italic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return _font_path()


def _render_motion_caption_card(
    text: str,
    font_path: str = "",
    kicker: str = "",
    highlight: str = "",
    scene_index: int = 1,
    style: str = "",
    sub: str = "",
) -> str:
    """Render transparent kinetic editorial typography (PNG).

    Supports three distinct visual archetypes inspired by studio creator references:
    - 'creator': Bold condensed sunshine yellow with fiery 3D extrusion shadow,
      paired with an expressive italic serif subline (Inspo 2 - 'Boring subtitles').
    - 'editorial': High-contrast luxury documentary serif — delicate light italic
      top line paired with a massive bold display serif (Inspo 3 - 'But if you do / the math').
    - 'neon': Sleek modern sans with glowing vertical cursor scan beam and radial bloom
      (Inspo 1 - 'What do|').
    """
    import string
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    safe = " ".join(str(text).split())[:120]
    safe_sub = " ".join(str(sub).split())[:120] if sub else ""

    # Split lines if 2-line structure is indicated via sub, slash, or newline
    if safe_sub:
        line1, line2 = safe, safe_sub
    elif "\n" in str(text):
        parts = [p.strip() for p in str(text).split("\n", 1)]
        line1, line2 = parts[0], parts[1]
    elif " / " in safe:
        parts = [p.strip() for p in safe.split(" / ", 1)]
        line1, line2 = parts[0], parts[1]
    else:
        words = safe.split()
        if len(words) > 3 and not kicker:
            mid = len(words) // 2
            line1, line2 = " ".join(words[:mid]), " ".join(words[mid:])
        else:
            line1, line2 = safe, ""

    # Rotate styles if not explicitly set
    style_key = (style or "").lower().strip()
    if style_key not in ("creator", "editorial", "neon"):
        # Distinct rotation order: Scene 1 = creator, Scene 2 = editorial, Scene 3 = creator, Scene 4 = neon, Scene 5 = editorial
        cycle = ["creator", "editorial", "creator", "neon", "editorial"]
        style_key = cycle[(scene_index - 1) % len(cycle)]

    bold_font_file = _font_path(font_path)
    cond_font_file = _font_condensed_path()
    serif_bold_file = _font_serif_bold_path()
    serif_italic_file = _font_serif_italic_path()

    card_w, card_h = 1040, 480
    measure = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    d_m = ImageDraw.Draw(measure)

    # ──────────────────────────────────────────────────────────────────────────
    # ARCHETYPE 1: CREATOR (Inspo 2 - "Boring subtitles")
    # ──────────────────────────────────────────────────────────────────────────
    if style_key == "creator":
        sz1 = 86
        while sz1 > 40:
            f_top = ImageFont.truetype(cond_font_file, sz1) if cond_font_file else ImageFont.load_default()
            b1 = d_m.textbbox((0, 0), line1, font=f_top) if line1 else (0, 0, 0, 0)
            if (b1[2] - b1[0]) <= 920:
                break
            sz1 -= 4

        sz2 = 78
        while sz2 > 36:
            f_bot = ImageFont.truetype(serif_italic_file, sz2) if serif_italic_file else ImageFont.load_default()
            b2 = d_m.textbbox((0, 0), line2, font=f_bot) if line2 else (0, 0, 0, 0)
            if (b2[2] - b2[0]) <= 920:
                break
            sz2 -= 4

        f_kicker = ImageFont.truetype(cond_font_file, 24) if cond_font_file else ImageFont.load_default()

        b_k = d_m.textbbox((0, 0), kicker.upper(), font=f_kicker) if kicker else (0, 0, 0, 0)
        b1 = d_m.textbbox((0, 0), line1, font=f_top) if line1 else (0, 0, 0, 0)
        b2 = d_m.textbbox((0, 0), line2, font=f_bot) if line2 else (0, 0, 0, 0)

        w1 = b1[2] - b1[0]
        w2 = b2[2] - b2[0]
        wk = b_k[2] - b_k[0]

        content_w = max(w1, w2, wk, 200)
        box_w = min(1000, content_w + 80)
        line1_h = b1[3] - b1[1] + 16 if line1 else 0
        line2_h = b2[3] - b2[1] + 16 if line2 else 0
        kicker_h = 36 if kicker else 0
        box_h = kicker_h + line1_h + line2_h + 30

        img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        y = 0
        if kicker:
            draw.text((10, y), kicker.upper(), font=f_kicker, fill=(255, 220, 100, 230))
            y += kicker_h

        # Top line: 3D extruded yellow with fiery red-orange drop shadow
        if line1:
            x = 10
            extrusion = [
                (1, 1, (255, 90, 40, 255)),
                (2, 2, (255, 65, 30, 255)),
                (3, 3, (240, 50, 20, 255)),
                (4, 4, (210, 35, 15, 255)),
                (5, 5, (170, 25, 10, 240)),
                (6, 6, (30, 10, 5, 200)),
                (7, 7, (15, 5, 0, 180)),
            ]
            for dx, dy, col in extrusion:
                draw.text((x + dx, y + dy), line1, font=f_top, fill=col)
            draw.text((x, y), line1, font=f_top, fill=(255, 230, 0, 255))
            y += line1_h

        # Bottom line: contrasting italic serif in warm cream with soft shadow
        if line2:
            x = 18
            for dx, dy in [(2, 2), (3, 3), (4, 4)]:
                draw.text((x + dx, y + dy), line2, font=f_bot, fill=(15, 8, 4, 180))
            draw.text((x, y), line2, font=f_bot, fill=(255, 253, 230, 255))

    # ──────────────────────────────────────────────────────────────────────────
    # ARCHETYPE 2: EDITORIAL (Inspo 3 - "But if you do / the math")
    # ──────────────────────────────────────────────────────────────────────────
    elif style_key == "editorial":
        sz1 = 48
        while sz1 > 28:
            f_top = ImageFont.truetype(serif_italic_file, sz1) if serif_italic_file else ImageFont.load_default()
            b1 = d_m.textbbox((0, 0), line1, font=f_top) if line1 else (0, 0, 0, 0)
            if (b1[2] - b1[0]) <= 920:
                break
            sz1 -= 4

        sz2 = 96
        while sz2 > 40:
            f_bot = ImageFont.truetype(serif_bold_file, sz2) if serif_bold_file else ImageFont.load_default()
            b2 = d_m.textbbox((0, 0), line2, font=f_bot) if line2 else (0, 0, 0, 0)
            if (b2[2] - b2[0]) <= 920:
                break
            sz2 -= 4

        f_kicker = ImageFont.truetype(cond_font_file, 22) if cond_font_file else ImageFont.load_default()

        b_k = d_m.textbbox((0, 0), kicker.upper(), font=f_kicker) if kicker else (0, 0, 0, 0)
        b1 = d_m.textbbox((0, 0), line1, font=f_top) if line1 else (0, 0, 0, 0)
        b2 = d_m.textbbox((0, 0), line2, font=f_bot) if line2 else (0, 0, 0, 0)

        w1 = b1[2] - b1[0]
        w2 = b2[2] - b2[0]
        wk = b_k[2] - b_k[0]

        content_w = max(w1, w2, wk, 240)
        box_w = min(1020, content_w + 90)
        line1_h = b1[3] - b1[1] + 18 if line1 else 0
        line2_h = b2[3] - b2[1] + 20 if line2 else 0
        kicker_h = 32 if kicker else 0
        box_h = kicker_h + line1_h + line2_h + 40

        img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(shadow)
        draw = ImageDraw.Draw(img)

        # Subtle dark glass container for guaranteed contrast on bright/white video footage
        draw.rounded_rectangle((4, 4, box_w - 4, box_h - 4), radius=18,
                               fill=(15, 18, 26, 175), outline=(255, 255, 255, 38), width=1)

        y = 12
        if kicker:
            draw.text((22, y), kicker.upper(), font=f_kicker, fill=(240, 230, 210, 220))
            y += kicker_h

        # Top line: delicate italic serif in warm off-white
        if line1:
            x = 22
            s_draw.text((x + 2, y + 3), line1, font=f_top, fill=(0, 0, 0, 220))
            draw.text((x, y), line1, font=f_top, fill=(240, 242, 246, 250))
            y += line1_h

        # Bottom line: giant high-contrast display serif in pure white
        if line2:
            x = 22
            s_draw.text((x + 3, y + 5), line2, font=f_bot, fill=(0, 0, 0, 240))
            draw.text((x, y), line2, font=f_bot, fill=(255, 255, 255, 255))

        shadow_blur = shadow.filter(ImageFilter.GaussianBlur(10))
        img = Image.alpha_composite(shadow_blur, img)

    # ──────────────────────────────────────────────────────────────────────────
    # ARCHETYPE 3: NEON CYBER (Inspo 1 - "What do|")
    # ──────────────────────────────────────────────────────────────────────────
    else:  # style_key == "neon"
        sz1 = 72
        while sz1 > 36:
            f_main = ImageFont.truetype(bold_font_file, sz1) if bold_font_file else ImageFont.load_default()
            b1 = d_m.textbbox((0, 0), line1, font=f_main) if line1 else (0, 0, 0, 0)
            if (b1[2] - b1[0]) <= 860:
                break
            sz1 -= 4

        f_sub = ImageFont.truetype(cond_font_file, max(30, int(sz1 * 0.55))) if cond_font_file else ImageFont.load_default()
        f_kicker = ImageFont.truetype(cond_font_file, 22) if cond_font_file else ImageFont.load_default()

        b_k = d_m.textbbox((0, 0), kicker.upper(), font=f_kicker) if kicker else (0, 0, 0, 0)
        b1 = d_m.textbbox((0, 0), line1, font=f_main) if line1 else (0, 0, 0, 0)
        b2 = d_m.textbbox((0, 0), line2, font=f_sub) if line2 else (0, 0, 0, 0)

        w1 = b1[2] - b1[0]
        w2 = b2[2] - b2[0] if line2 else 0
        wk = b_k[2] - b_k[0] if kicker else 0
        cursor_w = 26

        content_w = max(w1 + cursor_w + 30, w2, wk, 240)
        box_w = min(1040, content_w + 80)
        line1_h = b1[3] - b1[1] + 20 if line1 else 0
        line2_h = b2[3] - b2[1] + 16 if line2 else 0
        kicker_h = 32 if kicker else 0
        box_h = kicker_h + line1_h + line2_h + 40

        img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        glow = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        g_draw = ImageDraw.Draw(glow)
        draw = ImageDraw.Draw(img)

        y = 15
        if kicker:
            draw.text((20, y), kicker.upper(), font=f_kicker, fill=(180, 220, 255, 230))
            y += kicker_h

        x = 20
        if line1:
            draw.text((x + 2, y + 4), line1, font=f_main, fill=(10, 15, 30, 220))
            draw.text((x, y), line1, font=f_main, fill=(250, 252, 255, 255))

            # Vertical neon cursor beam and radial flare
            cur_x = x + w1 + 10
            cur_y = y + 4
            cur_h = line1_h - 8
            g_draw.ellipse((cur_x - 50, cur_y - 30, cur_x + 60, cur_y + cur_h + 30),
                           fill=(0, 180, 255, 190))
            g_draw.ellipse((cur_x - 25, cur_y - 18, cur_x + 35, cur_y + cur_h + 18),
                           fill=(140, 90, 255, 230))

            draw.rounded_rectangle((cur_x, cur_y, cur_x + 8, cur_y + cur_h), radius=4,
                                   fill=(170, 130, 255, 255), outline=(235, 245, 255, 255), width=1)

            y += line1_h + 4

        if line2:
            draw.text((x + 2, y + 2), line2, font=f_sub, fill=(10, 15, 30, 200))
            draw.text((x, y), line2, font=f_sub, fill=(200, 225, 255, 230))

        glow_blur = glow.filter(ImageFilter.GaussianBlur(18))
        img = Image.alpha_composite(glow_blur, img)

    fd, path = tempfile.mkstemp(prefix="prism-motion-title-", suffix=".png")
    os.close(fd)
    img.save(path)
    return path


def _title_overlay(text: str, font_path: str = "",
                   kicker: str = "", highlight: str = "",
                   scene_index: int = 1, style: str = "", sub: str = "") -> str:
    """Make a motion graphics caption card (backward-compatible alias)."""
    return _render_motion_caption_card(
        text, font_path=font_path, kicker=kicker,
        highlight=highlight, scene_index=scene_index,
        style=style, sub=sub,
    )


def _caption_windows(captions: list[dict], total_seconds: float,
                     shot_durations: list[float] | None = None,
                     transition_seconds: float = TRANSITION_SECONDS) -> list[dict]:
    """Turn scene durations into windows spanning the completed edit."""
    clean = []
    for idx, item in enumerate(captions or []):
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("text") or "").split())[:120]
        if not text:
            continue
        try:
            seconds = max(0.6, _seconds(item.get("seconds"), 3.0))
        except (TypeError, ValueError):
            seconds = 3.0
        clean.append({
            "text": text,
            "seconds": seconds,
            "kicker": str(item.get("kicker") or ""),
            "highlight": str(item.get("highlight") or ""),
            "transition": str(item.get("transition") or ""),
            "style": str(item.get("style") or ""),
            "position": str(item.get("position") or ""),
            "sub": str(item.get("sub") or ""),
        })
    if not clean:
        return []
    if shot_durations and len(clean) == len(shot_durations):
        starts, cursor = [], 0.0
        for index, duration in enumerate(shot_durations):
            starts.append(cursor if index == 0 else
                          cursor + transition_seconds / 2)
            cursor += float(duration)
            if index < len(shot_durations) - 1:
                cursor -= transition_seconds
        res = []
        for index, item in enumerate(clean):
            w = {
                "text": item["text"],
                "start": starts[index],
                "end": (starts[index + 1] if index + 1 < len(starts) else total_seconds),
                "kicker": item["kicker"],
                "highlight": item["highlight"],
                "transition": item["transition"],
            }
            if item.get("style"):
                w["style"] = item["style"]
            if item.get("position"):
                w["position"] = item["position"]
            if item.get("sub"):
                w["sub"] = item["sub"]
            res.append(w)
        return res

    planned = sum(item["seconds"] for item in clean)
    scale = total_seconds / planned if planned > 0 else 1.0
    cursor, out = 0.0, []
    for index, item in enumerate(clean):
        end = total_seconds if index == len(clean) - 1 else min(
            total_seconds, cursor + item["seconds"] * scale)
        entry = {
            "text": item["text"],
            "start": cursor,
            "end": end,
            "kicker": item["kicker"],
            "highlight": item["highlight"],
            "transition": item["transition"],
        }
        if item.get("style"):
            entry["style"] = item["style"]
        if item.get("position"):
            entry["position"] = item["position"]
        if item.get("sub"):
            entry["sub"] = item["sub"]
        out.append(entry)
        cursor = end
    return out


def _prepare_clips(clips: list[dict], out_path: str, on_progress=None) -> list[str]:
    """Normalize phone sources sequentially before the multi-shot edit.

    Five 4K HEVC MOV files decoded inside one xfade graph can require several
    gigabytes of frames and starve the desktop compositor (which is why VS
    Code disappeared during the last client render).  Each source is first
    turned into a short 720×1280 silent mezzanine, one process at a time.
    The final graph upscales these lightweight 30fps H.264 clips only at the
    point it needs a 1080×1920 delivery master.
    """
    folder = os.path.dirname(os.path.abspath(out_path)) or tempfile.gettempdir()
    prepared: list[str] = []
    total = len(clips)
    try:
        for index, clip in enumerate(clips, 1):
            fd, target = tempfile.mkstemp(prefix="prism-footage-source-",
                                          suffix=".mp4", dir=folder)
            os.close(fd)
            command = [
                reel.ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{float(clip['start']):.3f}", "-i", clip["path"],
                "-t", f"{float(clip['selected']):.3f}", "-an",
                "-vf", "fps=30,scale=720:1280:force_original_aspect_ratio=increase,"
                       "crop=720:1280,setsar=1,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-threads", "1", "-filter_threads", "1",
                "-movflags", "+faststart", target,
            ]
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=300)
            if result.returncode or not os.path.isfile(target) or os.path.getsize(target) < 1024:
                try:
                    os.unlink(target)
                except OSError:
                    pass
                raise RuntimeError(result.stderr.strip() or
                                   f"FFmpeg could not prepare client clip {index}.")
            prepared.append(target)
            if on_progress:
                # Preflight is deliberately a small portion of the visible
                # progress bar; final encoding supplies the precise timing.
                on_progress(index, max(total, 1) * 10)
        return prepared
    except Exception:
        for path in prepared:
            try:
                os.unlink(path)
            except OSError:
                pass
        raise


def _concat_prepared_clips(paths: list[str], out_path: str) -> tuple[str, str]:
    """Join normalized clips without opening all of them in a filter graph.

    The concat demuxer copies the compatible silent mezzanines in order.  It
    is intentionally a clean cut between shots: on resource-constrained
    machines that is vastly safer than asking xfade to hold five 4K decode
    queues at once, and reads as a deliberate documentary/editing rhythm.
    """
    folder = os.path.dirname(os.path.abspath(out_path)) or tempfile.gettempdir()
    fd, list_path = tempfile.mkstemp(prefix="prism-footage-concat-",
                                     suffix=".txt", dir=folder)
    os.close(fd)
    fd, joined_path = tempfile.mkstemp(prefix="prism-footage-joined-",
                                       suffix=".mp4", dir=folder)
    os.close(fd)
    try:
        with open(list_path, "w", encoding="utf-8") as listing:
            for path in paths:
                listing.write("file '" + path.replace("'", r"'\\''") + "'\n")
        command = [reel.ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "concat", "-safe", "0", "-i", list_path,
                   "-map", "0:v:0", "-an", "-c:v", "copy", "-movflags",
                   "+faststart", joined_path]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if result.returncode or not os.path.isfile(joined_path) or os.path.getsize(joined_path) < 1024:
            raise RuntimeError(result.stderr.strip() or
                               "FFmpeg could not join the prepared client clips.")
        return joined_path, list_path
    except Exception:
        for path in (list_path, joined_path):
            try:
                os.unlink(path)
            except OSError:
                pass
        raise


def _join_clips_with_transitions(paths: list[str], durations: list[float],
                                 transitions: list[str] | None = None,
                                 trans_dur: float = DEFAULT_TRANSITION_SECONDS,
                                 out_path: str = "") -> tuple[str, str]:
    """Join normalized clips using dynamic transitions (smoothleft, zoomin, wipeleft, hblur, dissolve).

    Because each clip is already a normalized 720×1280 silent mezzanine, xfade
    executes quickly with minimal memory footprint while delivering broadcast-quality
    visual scene shifts.
    """
    if len(paths) <= 1 or trans_dur <= 0.0:
        return _concat_prepared_clips(paths, out_path)

    folder = os.path.dirname(os.path.abspath(out_path)) or tempfile.gettempdir()
    fd, joined_path = tempfile.mkstemp(prefix="prism-footage-joined-",
                                       suffix=".mp4", dir=folder)
    os.close(fd)

    inputs: list[str] = []
    for p in paths:
        inputs += ["-i", p]

    filter_chains = []
    current_label = "0:v"
    current_offset = max(0.1, durations[0] - trans_dur)

    clean_transitions = []
    for t in (transitions or []):
        t_clean = str(t).lower().strip()
        if t_clean in SUPPORTED_TRANSITIONS:
            clean_transitions.append("fade" if t_clean == "fadefast" else t_clean)

    for i in range(1, len(paths)):
        next_label = f"xf{i}"
        if i - 1 < len(clean_transitions):
            t_type = clean_transitions[i - 1]
        else:
            t_type = TRANSITIONS_ROTATION[(i - 1) % len(TRANSITIONS_ROTATION)]

        filter_chains.append(
            f"[{current_label}][{i}:v]xfade=transition={t_type}:"
            f"duration={trans_dur:.3f}:offset={current_offset:.3f}[{next_label}]"
        )
        current_label = next_label
        if i < len(paths) - 1:
            current_offset += durations[i] - trans_dur

    total_video_seconds = max(0.1, sum(durations) - (len(durations) - 1) * trans_dur)
    command = [
        reel.ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
        *inputs,
        "-filter_complex", ";".join(filter_chains),
        "-map", f"[{current_label}]",
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-threads", "1",
        "-t", f"{total_video_seconds:.3f}",
        "-movflags", "+faststart",
        joined_path,
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if result.returncode or not os.path.isfile(joined_path) or os.path.getsize(joined_path) < 1024:
            # Fallback to clean cuts if xfade encountered any issue
            try:
                os.unlink(joined_path)
            except OSError:
                pass
            return _concat_prepared_clips(paths, out_path)
        return joined_path, ""
    except Exception:
        try:
            os.unlink(joined_path)
        except OSError:
            pass
        return _concat_prepared_clips(paths, out_path)


def render(paths: list[str], out_path: str, title: str = "",
           font_path: str = "", on_progress=None,
           captions: list[dict] | None = None, audio_path: str = "",
           bgm_path: str = "") -> str:
    """Render selected client clips as one 1080×1920 H.264 deliverable with
    curated transitions, dynamic motion graphics captions, and a clean audio
    handoff.  When narration is present it is the *only* source soundtrack.
    """
    paths = [os.path.abspath(p) for p in paths if is_video(p) and os.path.isfile(p)]
    if not paths:
        raise ValueError("Attach at least one .MOV or .MP4 client video first.")
    space = ffmpeg.check_space(out_path)
    if space:
        raise RuntimeError(space)

    # Curated transitions (smoothleft, zoomin, wipeleft, hblur, dissolve) are applied
    # across normalized 720×1280 mezzanine clips. Duration planning accounts for
    # transition overlaps so narration and picture remain tightly synchronized.
    trans_dur = DEFAULT_TRANSITION_SECONDS if len(paths) > 1 else 0.0
    clips = edit_plan(paths, audio_path=audio_path, captions=captions,
                      transition_seconds=trans_dur)
    durations = [max(1.0, float(c["selected"])) for c in clips]
    prepared_paths = _prepare_clips(clips, out_path, on_progress=on_progress)

    scene_transitions = [
        str(c.get("transition", "")).strip()
        for c in (captions or [])
        if isinstance(c, dict) and c.get("transition")
    ]
    joined_path, concat_list_path = _join_clips_with_transitions(
        prepared_paths, durations, transitions=scene_transitions,
        trans_dur=trans_dur, out_path=out_path)
    # A single joined input keeps memory bounded. The per-shot durations are
    # retained below for caption timing, even though the physical video now
    # arrives through one stream.
    paths = [joined_path]
    video_seconds = max(0.1, sum(durations) - max(0, len(durations) - 1) * trans_dur)

    inputs: list[str] = []
    for p in paths:
        inputs += ["-i", p]

    filters = []
    filters.append(
        f"[0:v]trim=duration={video_seconds:.3f},setpts=PTS-STARTPTS,"
        "scale=1080:1920:flags=fast_bilinear,format=yuv420p[v0]")
    video_label = "v0"
    voice_dur = 0.0
    if audio_path and os.path.isfile(audio_path):
        voice_dur = float(probe(audio_path).get("duration") or 0)

    total_seconds = max(video_seconds, voice_dur)
    windows = _caption_windows(captions or [], total_seconds,
                               shot_durations=durations,
                               transition_seconds=trans_dur)

    overlay_paths: list[str] = []
    current = video_label
    resolved_font = _font_path(font_path)

    # Dynamic motion graphics caption overlays
    for index, window in enumerate(windows):
        overlay_path = _render_motion_caption_card(
            window["text"],
            font_path=resolved_font,
            kicker=window.get("kicker", ""),
            highlight=window.get("highlight", ""),
            scene_index=index + 1,
            style=window.get("style", ""),
            sub=window.get("sub", ""),
        )
        overlay_paths.append(overlay_path)
        input_index = len(paths) + index
        card_label = f"card{index}"
        out_label = f"caption{index}"
        start, end = float(window["start"]), float(window["end"])
        duration = max(0.4, end - start)
        fade_in_dur = min(0.35, duration * 0.25)
        fade_out_dur = min(0.28, duration * 0.20)

        # Loop single image over total timeline and apply alpha fade in/out
        inputs += ["-loop", "1", "-t", f"{total_seconds:.3f}", "-i", overlay_path]
        filters.append(
            f"[{input_index}:v]format=yuva420p,"
            f"fade=t=in:st={start:.3f}:d={fade_in_dur:.3f}:alpha=1,"
            f"fade=t=out:st={end - fade_out_dur:.3f}:d={fade_out_dur:.3f}:alpha=1[{card_label}]"
        )
        # Dynamic positioning across focal zones (upper, center, lower)
        pos = window.get("position", "").lower().strip()
        if pos not in ("upper", "center", "lower"):
            pos_cycle = ["upper", "lower", "upper", "lower", "center"]
            pos = pos_cycle[index % len(pos_cycle)]

        if pos == "upper":
            base_y = "H*0.16"
        elif pos == "center":
            base_y = "(H-h)/2"
        else:
            base_y = "(H-h)-260"

        slide_in = f"140*pow(max(0,1-(t-{start:.3f})/{fade_in_dur:.3f}),3)"
        drift = f"18*(t-{start:.3f})/{duration:.3f}"
        slide_out = f"35*pow(max(0,(t-({end:.3f}-{fade_out_dur:.3f}))/{fade_out_dur:.3f}),2)"
        y_expr = f"'{base_y} + {slide_in} - {drift} - {slide_out}'"

        filters.append(
            f"[{current}][{card_label}]overlay=x=(W-w)/2:y={y_expr}:eval=frame:"
            f"enable='between(t,{start:.3f},{end:.3f})'[{out_label}]"
        )
        current = out_label

    # Extend only by the finite amount narration needs.  ``stop=-1`` creates
    # an endless stream; even with an output -t it can leave FFmpeg flushing
    # forever after an otherwise complete export.
    pad_seconds = max(0.0, total_seconds - video_seconds)
    if pad_seconds > 0.02:
        filters.append(
            f"[{current}]tpad=stop_mode=clone:stop_duration={pad_seconds:.3f}[outv]")
    else:
        filters.append(f"[{current}]null[outv]")

    # Narrated reels deliberately use only the generated voice-over.  A phone
    # recording often contains machine noise, room chatter or handling sounds;
    # mixing/ducking it under narration makes the result sound accidental.
    audio_path = os.path.abspath(audio_path) if audio_path else ""
    has_voiceover = bool(
        audio_path and audio_path.lower().endswith(AUDIO_SUFFIXES) and os.path.isfile(audio_path)
    )
    voice_index = len(paths) + len(overlay_paths)
    if has_voiceover:
        inputs += ["-i", audio_path]

    # Optional BGM
    bgm_path = os.path.abspath(bgm_path) if bgm_path else ""
    has_bgm = bool(
        bgm_path and bgm_path.lower().endswith(AUDIO_SUFFIXES) and os.path.isfile(bgm_path)
    )
    bgm_index = voice_index + (1 if has_voiceover else 0)
    if has_bgm:
        inputs += ["-i", bgm_path]

    final_audio_label = ""
    if has_voiceover:
        filters.append(
            f"[{voice_index}:a]aformat=channel_layouts=stereo:sample_rates=44100[a_voice_only]"
        )
        final_audio_label = "a_voice_only"
    elif has_bgm:
        # Music supplied explicitly by the client is safe to use alone. Raw
        # camera audio is never promoted into a polished reel by accident.
        filters.append(
            f"[{bgm_index}:a]volume=0.20,aformat=channel_layouts=stereo:sample_rates=44100[a_bgm_only]"
        )
        final_audio_label = "a_bgm_only"

    if final_audio_label:
        fade_out_st = max(0.0, total_seconds - 0.4)
        filters.append(
            f"[{final_audio_label}]loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"afade=t=in:d=0.1,afade=t=out:st={fade_out_st:.3f}:d=0.4[outa]"
        )

    has_output_audio = bool(final_audio_label)
    cmd = [reel.ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
           *inputs, "-filter_complex_threads", "1",
           "-filter_complex", ";".join(filters), "-map", "[outv]",
           *( ["-map", "[outa]", "-c:a", "aac", "-b:a", "192k"]
              if has_output_audio else ["-an"] ),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-threads", "1",
           "-t", f"{total_seconds:.3f}",
           "-movflags", "+faststart", "-progress", "pipe:1", "-nostats",
           out_path]
    try:
        if on_progress:
            on_progress(0, int(total_seconds * 1000))
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1)
        assert process.stdout is not None
        for raw in process.stdout:
            key, _, value = raw.strip().partition("=")
            if key not in ("out_time_us", "out_time_ms"):
                continue
            try:
                done_ms = int(int(value) / 1000)
            except (TypeError, ValueError):
                continue
            if on_progress:
                on_progress(min(done_ms, int(total_seconds * 1000)),
                            int(total_seconds * 1000))
        stderr = process.stderr.read() if process.stderr is not None else ""
        code = process.wait()
        if code:
            raise RuntimeError(stderr.strip() or
                               "FFmpeg could not render the client footage.")
        if on_progress:
            on_progress(int(total_seconds * 1000), int(total_seconds * 1000))
        return out_path
    finally:
        for overlay_path in overlay_paths:
            try:
                os.unlink(overlay_path)
            except OSError:
                pass
        for prepared_path in prepared_paths:
            try:
                os.unlink(prepared_path)
            except OSError:
                pass
        for temporary_path in (joined_path, concat_list_path):
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
